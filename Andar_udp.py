from UI.Ui_Radar_UDP import Ui_MainWindow
import sys, socket, threading
import os
from PySide6.QtCore import QObject, Signal, Qt
import time
from PySide6 import QtCore
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox,  QTableWidget, QTableWidgetItem, QHeaderView, QDockWidget
from PySide6.QtGui import QPixmap, QIcon, QAction
import numpy as np
from data_processing import *
import motorController
import scipy.io
import warnings
from udp_handler import *
from display_pg import PgDisplay
import csv


# ================== Qt 信号总线 ==================
class Bus(QObject):
    log         = Signal(str)     # log日志重定向
    frame_ready = Signal(bytes, int, int, int)# frame, sample_point, chirp_num, txrx


# ================== 接收线程（Python threading + socket） ==================
class UdpRxThread(threading.Thread):
    def __init__(self, ip: str, port: int, bus: Bus):
        super().__init__(daemon=True)
        self.ip, self.port = ip, port
        self.bus = bus
        self._stop_evt = threading.Event()
        self._sock = None
        self._asm  = DataAssembler(bus)

    def run(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self.ip, self.port))      # 0.0.0.0:8888
            self._sock.settimeout(0.5)                 # 短超时便于退出
            self.bus.log.emit(f"[OK] 监听 {self.ip}:{self.port} ...")
        except Exception as e:
            self.bus.log.emit(f"[ERR] 绑定失败: {e!r}")
            return

        while not self._stop_evt.is_set():
            try:
                data, (sip, sport) = self._sock.recvfrom(PKT_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break
            if sip != PEER_IP:
                continue
            res = self._asm.process(data)
            if res is not None:
                frame, sample, chirp, txrx = res
                self.bus.frame_ready.emit(frame, sample, chirp, txrx)
        try:
            if self._sock:
                self._sock.close()
        finally:
            self._sock = None
            self.bus.log.emit("[OK] 接收线程已退出")

    def stop(self):
        self._stop_evt.set()
        # 唤醒一次阻塞的 recvfrom，加速退出
        try:
            tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            tmp.sendto(b"", ("127.0.0.1", self.port))
            tmp.close()
        except Exception:
            pass

# ================== 主窗口初始化 ==================
class MyMainForm(QMainWindow, Ui_MainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("Radar UDP Interface ")
        self.setWindowIcon(QIcon(r'icon/Radar_UDP_icon.png'))
        #self.resize(1800, 1400)
        self.load_styles()
        self.setup_distance_table()
        self.setupInitialUIState()

        options = ["CPP", "Python"]
        self.comboBox_MatFrom.addItems(options)
        self.comboBox_MatFrom.setCurrentIndex(1)
        # UDP网络读取相关变量
        self.rx_thread = None
        self.tx_sock   = None
        # mat文件存读相关变量
        self.save_filename = None
        self.buffer = [] # 大缓存：暂存未保存的帧
        self.frame_all_data = None
        self.frame_data_list = []
        self.current_index = 0
        # 实时处理相关变量
        self.fft_results_1D = None
        self.fft_results_2D = None
        # 校准相关变量
        self.zij_vector_list = []
        self.warmup_count = 0
        self.warmup_avg = None
        self.alpha_matrix = None
        self.phi_matrix = None
        # display 控件相关变量 GUI显示界面绑定实例化
        self.last_display_time = time.time()# 记录最后显示的时间
        self.display_interval = 0.5
        self.setup_display_widgets()
        self.display = PgDisplay(
            adc_placeholders=self.adc_placeholders,
            fft1d_placeholders=self.fft1d_placeholders,
            fft2d_placeholders=self.fft2d_placeholders,
            point_cloud_placeholders=self.point_cloud_placeholders,
            DirectWave_placeholders=self.DirectWave_placeholders,
            constellation_placeholders=self.constellation_placeholders,
            amp_phase_placeholders=self.amp_phase_placeholders,
            frequency_placeholders=self.frequency_placeholders
        )
        # 信号总线连接
        self.bus = Bus()
        self.bus.log.connect(self._log)
        self.bus.frame_ready.connect(self.on_frame_ready)

        # 创建菜单
        self.create_menus()
        self.upgrade_to_dockwidgets()
        index = self.tabWidget_Display.indexOf(self.tab_Placeholder)
        if index != -1:
            self.tabWidget_Display.setTabVisible(index, False)


        # 转台电机实例化
        self.CH375motor = motorController.MotorController()

# ================== 初始化相关函数 ==================
    def setup_display_widgets(self):
        """初始化所有 widget 映射字典"""
        adc4_keys  = ['tx0rx0', 'tx0rx1', 'tx1rx0', 'tx1rx1']
        fft1d_keys = ['1DFFTtx0rx0', '1DFFTtx0rx1', '1DFFTtx1rx0', '1DFFTtx1rx1']
        fft2d_keys = ['2DFFTtx0rx0', '2DFFTtx0rx1', '2DFFTtx1rx0', '2DFFTtx1rx1']
        point_cloud_keys = ['PointCloud']
        DirectWave_keys = ['DWtx0rx0', 'DWtx0rx1', 'DWtx1rx0', 'DWtx1rx1']
        ConstellationDiagram_keys = ['CDtx0rx0', 'CDtx0rx1', 'CDtx1rx0', 'CDtx1rx1']
        amp_phase_keys = ['APtx0rx0', 'APtx0rx1', 'APtx1rx0', 'APtx1rx1']
        frequency_keys = ['frequency']

        self.adc_placeholders = {k: getattr(self, f'widget_{k}') for k in adc4_keys}
        self.fft1d_placeholders = {k: getattr(self, f'widget_{k}') for k in fft1d_keys}
        self.fft2d_placeholders = {k: getattr(self, f'widget_{k}') for k in fft2d_keys}
        self.point_cloud_placeholders = {k: getattr(self, f'widget_{k}') for k in point_cloud_keys}
        self.DirectWave_placeholders = {k: getattr(self, f'widget_{k}') for k in DirectWave_keys}
        self.constellation_placeholders = {k: getattr(self, f'widget_{k}') for k in ConstellationDiagram_keys}
        self.amp_phase_placeholders = {k: getattr(self, f'widget_{k}') for k in amp_phase_keys}
        self.frequency_placeholders = {k: getattr(self, f'widget_{k}') for k in frequency_keys}

    def setup_distance_table(self):
        self.tableWidget_distance.setColumnCount(10)
        header_labels = ['index','Angel','FFT','FFT-fre', 'Macleod', 'Macleod-fre',
                         'CTZ', 'CTZ-fre', 'MCTZ', 'MCTZ-fre']
        self.tableWidget_distance.setHorizontalHeaderLabels(header_labels)
        self.tableWidget_distance.setEditTriggers(QTableWidget.NoEditTriggers)
        # QHeaderView.Stretch 模式会使所有列等宽拉伸，填充可用空间。
        self.tableWidget_distance.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tableWidget_distance.verticalHeader().setVisible(False)

        self.checkBox_CalibrationMode.stateChanged.connect(self.CalibrationModeMessage)
        self.checkBox_IsSave.stateChanged.connect(self.SaveMatChange)

    def setupInitialUIState(self):
        self.tabWidget_Display.setMovable(True)
        self.pushButton_Disconnect.setEnabled(False)
        self.pushButton_MotorDisconnect.setEnabled(False)
        self.pushButton_MoveAngel.setEnabled(False)
        self.pushButton_Next.setEnabled(False)
        self.pushButton_SaveTable.setEnabled(False)
        self.pushButton_CloseFile.setEnabled(False)

    def generate_unique_time(self):
        """生成一个唯一的time时间戳字符串"""
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        return timestamp

    def load_styles(self):
        """加载UI样式"""
        try:
            with open('style.qss', 'r', encoding='utf-8') as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"加载样式失败: {e}")


    def upgrade_to_dockwidgets(self):
        """
        升级 UI：将 tabWidget_Display 的 index=0 作为 centralWidget，
        其余 Tabs 转为左侧堆叠 Dock，配置和消息区转为右侧 Dock。
        """
        tab_widget = self.tabWidget_Display
        tab_data = []

        # === 1. 提取所有 Tab 内容 ===
        for i in range(tab_widget.count()):
            widget = tab_widget.widget(i)
            title = tab_widget.tabText(i)
            tab_data.append((widget, title))

        # 清空并隐藏原 TabWidget
        while tab_widget.count() > 0:
            tab_widget.removeTab(0)
        tab_widget.hide()

        # === 2. 设置索引 0 的 Tab 为 centralWidget ===
        if len(tab_data) > 0:
            central_widget, _ = tab_data[0]
            self.setCentralWidget(central_widget)

        # === 3. 将其他 Display Tabs 转为 Dock 并堆叠在左侧 ===
        docks_display = []
        for i, (widget, title) in enumerate(tab_data):
            if i == 0:  # 跳过主视图
                continue
            dock = QDockWidget(title, self)
            dock.setWidget(widget)
            dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            docks_display.append(dock)
            setattr(self, f'dock_display_{i}', dock)

        # 堆叠左侧 Dock（从第一个开始）
        if docks_display:
            first_dock = docks_display[0]
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, first_dock)
            for dock in docks_display[1:]:
                self.tabifyDockWidget(first_dock, dock)
            first_dock.raise_()  # 默认显示第一个

        # === 4. 创建 控制面板 Dock ===
        dock_control = QDockWidget("dock_control", self)
        dock_control.setObjectName("dock_control")  # 方便调试
        dock_control.setWidget(self.groupBox_Config)
        dock_control.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_control)

        # === 5. 创建 消息与数据 Dock ===
        dock_message = QDockWidget("dock_message", self)
        dock_message.setObjectName("dock_message")
        dock_message.setWidget(self.tabWidget_Message)
        dock_message.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)

        # 将消息与数据 Dock 放在底部
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock_message)

        # === 6. 添加到“视图”菜单 ===
        view_menu = self.menuBar().addMenu("View")
        for dock in docks_display:
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addAction(dock_control.toggleViewAction())
        view_menu.addAction(dock_message.toggleViewAction())

        dock_control.setMaximumWidth(300)
        dock_control.setMinimumWidth(200)
        dock_control.setMaximumHeight(700)
        dock_control.setMinimumHeight(300)

    def create_menus(self):
        """
        创建完整的菜单栏：File, Edit, View, Help
        About 对话框直接在此函数中实现。
        """
        menu_bar = self.menuBar()
        # === File 菜单 ===
        file_menu = menu_bar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        # === Edit 菜单（预留功能，灰色显示）===
        edit_menu = menu_bar.addMenu("Edit")
        # === Help 菜单 ===
        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(
            lambda: QMessageBox.about(
                self,
                "About",
                "<h3>FMCW Radar GUI</h3>"
                "<p><b>Version:</b> 4.0.1</p>"
                "<p>a Python-based desktop application for real-time acquisition , " \
                "processing, and visualization of FMCW radar data</p>"
                "<p>© China Jiliang University.</p>"
            )
        )
        help_menu.addAction(about_action)

    # ---- checkbox Connect function ----
    def CalibrationModeMessage(self):
        """校准模式启用提示"""
        if self.checkBox_CalibrationMode.isChecked():
            QMessageBox.information(self,"校准模式","已启用校准模式。\n"
                                    "请确保雷达正对自反靶进行校准。\n"
                                    "前20帧用于预热并计算参考平均值，后50帧用于计算校准矩阵。\n"
                                    "校准结束后程序会自动断开连接，并关闭所有文件。")
        else:
            QMessageBox.information(self, "校准模式", "已关闭校准模式。")

    def SaveMatChange(self):
        """启用或关闭保存 .mat 文件功能"""
        if self.checkBox_IsSave.isChecked():
            self.buffer = []  # 清空缓存
            if not self.save_filename:
                self.save_filename = f"{self.generate_unique_time()}_raw_data_py.mat"
            self.bus.log.emit("[OK]已启用原始数据保存功能。\n"
                              f"保存文件：{self.save_filename}\n"
                              "每100帧数据自动保存一次，程序关闭时会保存剩余缓存。")
        else:
            self.save_buffer_to_mat()  # 保存剩余缓存
            self.buffer = []  # 清空缓存
            self.save_filename = None
            self.bus.log.emit("[OK]已关闭原始数据保存功能。")

    # ---- 重定向日志到 textEdit_log ----
    def _log(self, s: str):
        try:
            self.textEdit_log.append(s)
        except Exception:
            print(s)


# ================== 初始化相关函数 ==================

    # ---- 连接：开接收 + 备发送 ----
    def UDP_connect(self):
        if self.checkBox_IsSave.isChecked() and not self.save_filename:
            self.save_filename = f"{self.generate_unique_time()}_raw_data_py.mat"
        self.UDP_disconnect()  # 防止重复
        self.rx_thread = UdpRxThread(LISTEN_IP, LISTEN_PORT, self.bus)
        self.rx_thread.start()
        try:
            self.tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.bus.log.emit(f"[OK] 发送目标 {PEER_IP}:{PEER_PORT}")
            self.pushButton_Connect.setEnabled(False)
            self.pushButton_Disconnect.setEnabled(True)
        except Exception as e:
            self.bus.log.emit(f"[ERR] 创建发送 socket 失败: {e!r}")
            self.tx_sock = None

    # ---- 断开：停线程 + 关socket ----
    def UDP_disconnect(self):
        if self.rx_thread:
            self.rx_thread.stop()
            self.rx_thread.join(timeout=2.0)
            self.rx_thread = None
        if self.tx_sock:
            try: self.tx_sock.close()
            except Exception: pass
            self.tx_sock = None
        self.bus.log.emit("[OK] 已断开")
        self.pushButton_Connect.setEnabled(True)
        self.pushButton_Disconnect.setEnabled(False)
        if self.checkBox_IsSave.isChecked():
            self.save_buffer_to_mat()  # 保存剩余缓存

    # ---- 整帧到达回调函数 ----
    def on_frame_ready(self, frame: bytes, sample: int, chirp: int, txrx: int):
        """
        数据格式正确,接收到一帧数据后回调函数
        """
         # 保存到 .mat 文件
        if self.checkBox_IsSave.isChecked():
            self.save_to_buffer(frame,sample,chirp)

        current_time = time.time()
        if self.checkBox_HammingWindow.isChecked():
            my_window = np.hamming(sample)
        else:
            my_window = None
        iq = reorder_frame(frame, chirp, sample, window=my_window)

        self.fft_results_1D = Perform1D_FFT(iq)
        self.fft_results_2D = Perform2D_FFT(self.fft_results_1D)
        self.display.update_direct_wave_phase(self.fft_results_1D,index=1)
        R_fft, R_macleod, R_czt_fftpeak, R_czt_macleod,diag = calculate_distance_from_iq(iq,r_bins=0.5,M=16,use_window=None,coherent=True)
        self.display.update_frequency(iq,diag)
        if self.checkBox_CalibrationMode.isChecked():
            #得到2DFFT的峰值索引 对应的zij向量
            peak_idx = np.unravel_index(np.argmax(np.abs(self.fft_results_2D[0])), self.fft_results_2D[0].shape)
            zij_vector = self.fft_results_2D[:, peak_idx[0], peak_idx[1]]
            self.calibrate_on_demand(zij_vector)

        # 根据2dfft结果 将TX和RX 进行分开幅相校准
        if self.checkBox_channel_calibration.isChecked() and self.alpha_matrix is not None and self.phi_matrix is not None:
            iq = apply_channel_calibration(iq, self.alpha_matrix, self.phi_matrix)
            self.fft_results_1D = Perform1D_FFT(iq)
            self.fft_results_2D = Perform2D_FFT(self.fft_results_1D)

        # 判断是否满足显示间隔
        if current_time - self.last_display_time > self.display_interval:
            self.display.update_adc4(iq, chirp, sample)
            self.display.update_constellations(iq, remove_dc=True, max_points=3000, show_fit=True)
            self.display.update_amp_phase(iq, chirp=0, decimate=1, unwrap_phase=False)
            self.display.update_fft1d(self.fft_results_1D, sample)
            self.display.update_fft2d(self.fft_results_2D, sample, chirp)
            self.last_display_time = current_time
        else:
            pass
        az, el, idx, info = estimate_az_el_from_fft2d(self.fft_results_2D)
        self.display.update_point_cloud_polar("PointCloud", R_macleod, 90.0-az, size=10.0, color='g')

        # 更新表格显示距离、角度计算结果
        # row_data = [f"{self.current_index}",f"{az:.4f}",f"{R_fft:.4f} m / {diag['f_fft_peak_Hz']:.4f}hz",
        #             f"{R_macleod:.4f} m / {diag['f_macleod_Hz']:.4f}hz",f"{R_czt_fftpeak:.4f} m / {diag['f_czt_only_Hz']:.4f}hz",
        #             f"{R_czt_macleod:.4f} m / {diag['f_combo_Hz']:.4f}hz"]
        row_data = [f"{self.current_index}",f"{az:.2f}",f"{R_fft:.4f}",f"{diag['f_fft_peak_Hz']:.4f}",
                    f"{R_macleod:.4f}",f"{diag['f_macleod_Hz']:.4f}",f"{R_czt_fftpeak:.4f}",f"{diag['f_czt_only_Hz']:.4f}",
                    f"{R_czt_macleod:.4f}",f"{diag['f_combo_Hz']:.4f}"]
        row_count = self.tableWidget_distance.rowCount()
        self.tableWidget_distance.insertRow(row_count)
        for i, value in enumerate(row_data):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)# 设置单元格居中对齐
            self.tableWidget_distance.setItem(row_count, i, item)
        self.tableWidget_distance.scrollToBottom()# 滚动到底部
        self.current_index += 1

# ================== 校准部分内容 ==================
    """
    基于最小二乘法进行幅相校准流程
    校准：设备与自反呈0度校准
    原始数据（IQ数据）经2D FFT得到含有噪声的测量值（Z_ij_vector_frame）
    多帧平均后得到降噪后的测量值（Z_ij_vector_avg）
    通过最小二乘模型
    得到固定的校准矩阵（alpha_matrix, phi_matrix）
    保存校准矩阵到NumPy或者npz
    加载校准矩阵到程序
    对实时数据进行校准
    前20帧用于预热并计算参考平均值，后50帧用于计算校准矩阵。
    """
    def calibrate_on_demand(self, zij_vector: np.ndarray):
        if zij_vector.shape != (4,):
            raise ValueError("zij_vector 必须是包含4个元素的向量。")

        # --- 阶段一：雷达预热与基准计算 ---
        if self.warmup_count < 20:
            self.zij_vector_list.append(zij_vector)
            self.warmup_count += 1
            if self.warmup_count == 20:
                # 预热阶段结束，计算基准平均值
                warmup_vectors = np.array(self.zij_vector_list)
                # 计算每个通道的平均幅值
                self.warmup_avg = np.mean(np.abs(warmup_vectors), axis=0)
                # 清空列表，为下一阶段做准备
                self.zij_vector_list.clear()
            return

        # --- 阶段二：正式校准与数据过滤 ---
        if len(self.zij_vector_list) < 50:
            # 计算当前帧的幅值
            current_amplitudes = np.abs(zij_vector)

            # 检查幅值是否在预热平均值2倍的范围内
            # 这里使用 all() 确保所有4个通道都符合条件
            is_valid = np.all(current_amplitudes <= 2 * self.warmup_avg)

            if is_valid:
                self.zij_vector_list.append(zij_vector)

        current_count = len(self.zij_vector_list)

        if current_count >= 50:
            # 1. 计算平均值
            zij_vectors_to_calibrate = np.array(self.zij_vector_list)
            zij_vector_avg = np.mean(zij_vectors_to_calibrate, axis=0)

            # 2. 调用校准函数
            alpha_matrix = amplitude_calibration(zij_vector_avg)
            phi_matrix = phase_calibration(zij_vector_avg)

            # 3. 保存
            filename = f"{self.generate_unique_time()} calibration_matrix"
            np.savez(filename, alpha=alpha_matrix, phi=phi_matrix)

            # 4. 清空列表并重置状态，为下一次校准做准备
            self.zij_vector_list.clear()
            self.warmup_count = 0
            self.warmup_avg = None

            # 5. 断开连接并提示
            self.CloseFile()
            self.UDP_disconnect()
            QMessageBox.information(self, "校准完成", f"校准矩阵保存到：\n{filename}。")

    def LoadCalibratioMode(self):
        """
        打开文件对话框，选择 .npz 文件并读取数据
        """
        file_dialog = QFileDialog(self, "Load Calibration Mode File")
        file_dialog.setNameFilter("Mode files (*.npz)")
        if file_dialog.exec():
            file_path = file_dialog.selectedFiles()[0]
            cal_data = np.load(file_path)
            self.bus.log.emit(f"已加载校准模型文件：{file_path}")
            file_name = os.path.basename(file_path)
            self.lineEdit_ModeName.setText(file_name)
            self.alpha_matrix = cal_data['alpha']
            self.phi_matrix = cal_data['phi']
            self.bus.log.emit(f"幅度校准矩阵：\n{self.alpha_matrix}")
            self.bus.log.emit(f"相位校准矩阵：\n{self.phi_matrix}")


# ================== 文件读取部分内容 ==================
    def save_to_buffer(self, frame_data, sample_number, chirp_number):
        """
        每次接收到新的一帧数据，将数据放入大缓存中
        """
        try:
            # 获取当前时间戳，确保每一帧有唯一的变量名
            timestamp_with_ms = datetime.now().strftime("%Y_%m_%d_%H_%M_%S_%f")

            # 计算预期的数据大小：4通道，I/Q每个16bit，每个数据点2字节
            num_antennas = 4  # 4通道
            num_iq = 2        # I/Q 每个16bit = 2字节
            expected_size = sample_number * chirp_number * num_antennas * num_iq * np.dtype(np.int16).itemsize

            # 检查数据的大小
            if len(frame_data) != expected_size:
                print(f"Error: Unexpected buffer size! Expected: {expected_size}, Actual: {len(frame_data)}")
                return False

            # 转换为 int16 数组
            raw_iq = np.frombuffer(frame_data, dtype=np.int16)

            # 每帧有 2048 个数据点，且每帧是 32 行，每行 2048 列
            num_rows = 32
            num_cols = 2048
            total_frames = len(raw_iq) // (num_rows * num_cols)  # 计算帧数

            # 将数据重塑为每帧 32x2048 的 2D 数组
            reshaped_data = raw_iq[:total_frames * num_rows * num_cols].reshape((total_frames, num_rows, num_cols))

            # 将当前帧的数据添加到缓存中
            for i in range(total_frames):
                frame_timestamp = f"frame_{timestamp_with_ms}_{i}"  # 为每一帧生成唯一的变量名
                self.buffer.append({frame_timestamp: reshaped_data[i]})

            # 如果缓存达到最大大小，自动保存到文件
            if len(self.buffer) >= 100:
                #print("缓存已满，开始保存数据...")
                self.save_buffer_to_mat()

            return True
        except Exception as e:
            print(f"保存数据时出错: {e}")
            return False

    def save_buffer_to_mat(self):
        """将缓存数据写入 .mat 文件"""
        if not self.buffer:
            return  # 如果没有设置文件名或缓存为空，直接返回
        try:
            # 加载现有的 .mat 文件，如果文件不存在，则创建一个新文件
            try:
                existing_data = scipy.io.loadmat(self.save_filename)
            except FileNotFoundError:
                existing_data = {}

            # 将缓存中的所有数据添加到现有数据字典中
            for frame_data in self.buffer:
                existing_data.update(frame_data)

            # 清空缓存
            self.buffer = []

            # 保存到 .mat 文件
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=UserWarning)  # 消除对于“__header__”的警告
                try:
                    from scipy.io.matlab.mio import MatWriteWarning
                    warnings.simplefilter("ignore", category=MatWriteWarning)
                except ImportError:
                    pass
                scipy.io.savemat(self.save_filename, existing_data)
                self.bus.log.emit(f"[OK] 数据成功保存到 {self.save_filename}，包含 {len(existing_data)} 帧数据")

        except Exception as e:
            print(f"写入文件时出错: {e}")

    def ReadFile(self):
        """
        打开文件对话框，选择 .mat 文件并读取数据
        """
        file_dialog = QFileDialog(self, "Open MAT File")
        file_dialog.setNameFilter("MAT files (*.mat)")
        if file_dialog.exec():
            file_path = file_dialog.selectedFiles()[0]
            self.read_mat_file(file_path)
            self.pushButton_Next.setEnabled(True)
            self.pushButton_SaveTable.setEnabled(True)
            self.pushButton_CloseFile.setEnabled(True)


    def read_mat_file(self, filename):
        """
        读取 MAT 文件中的数据
        """
        try:
            data = scipy.io.loadmat(filename) # 读取 .mat 文件
            self.frame_all_data = data

            self.bus.log.emit(f"读取文件：{filename}")# 打印文件中包含的变量

            # 获取所有包含帧数据的变量（以 "frame" 开头的变量名）
            self.frame_data_list = [key for key in data.keys() if key.startswith('frame')]
            #self.bus.log.emit(f"找到 {len(self.frame_data_list)} 帧数据变量")
            self.current_index = 0  # 初始化为第一帧
            # 获取第一帧的数据
            frame_data = self.frame_all_data[self.frame_data_list[self.current_index]]
            self.show_matrix(frame_data)
        except Exception as e:
            print(f"读取文件时出错: {e}")
            QMessageBox.warning(self, "读取失败", f"读取文件失败：{e}")

    def show_matrix(self, frame_data):
        """
        显示当前帧的数据
        """
        #print(f"显示当前帧数据：{frame_data}")
        #print(f"帧数据形状：{frame_data.shape}")
        #self.bus.log.emit(f"{self.frame_data_list[self.current_index]} 数据已加载")
        selected_label = self.comboBox_MatFrom.currentText()
        if selected_label == "CPP":  # C++ 数据
            frame_data = frame_data.T  # 转置数据，确保行优先
            sample = frame_data.shape[0] // 8  # 4 虚拟天线，每个天线 2 个通道（I/Q）
            chirp = frame_data.shape[1]
            frame_data_flat = frame_data.flatten()
        elif selected_label == "Python":  # Python 数据
            sample = frame_data.shape[1] // 8  # 4 虚拟天线，每个天线 2 个通道（I/Q）
            chirp = frame_data.shape[0]
            frame_data_flat = frame_data.flatten()
        if self.checkBox_HammingWindow.isChecked():
            my_window = np.hamming(sample)
        else:
            my_window = None
        iq = reorder_frame(frame_data_flat, chirp, sample,window=my_window)
        # omegas = learn_calibration_parameters(iq)
        # #omegas =[0,95314.90114739, -257064.23834787,-27406.54915671]
        # print(f"学习到的补偿频率：{omegas}")
        # if self.checkBox_directwave.isChecked():
        #     #直接应用已学得的参数
        #     iq = apply_calibration_online(iq, omegas)

        #compute_psl_isl_correct(iq)
        #距离计算函数，CZT采用时域变换
        R_fft, R_macleod, R_czt_fftpeak, R_czt_macleod,diag = calculate_distance_from_iq(iq,r_bins=0.5,M=16,use_window=None,coherent=True)
        self.display.update_frequency(iq,diag)
        self.fft_results_1D = Perform1D_FFT(iq)
        self.fft_results_2D  = Perform2D_FFT(self.fft_results_1D)
        if self.checkBox_CalibrationMode.isChecked():
            #得到2DFFT的峰值索引 对应的zij向量
            peak_idx = np.unravel_index(np.argmax(np.abs(self.fft_results_2D[0])), self.fft_results_2D[0].shape)
            zij_vector = self.fft_results_2D[:, peak_idx[0], peak_idx[1]]
            self.calibrate_on_demand(zij_vector)

        # 根据2dfft结果 将TX和RX 进行分开幅相校准
        if self.checkBox_channel_calibration.isChecked() and self.alpha_matrix is not None and self.phi_matrix is not None:
            # 将校准后的IQ数据赋值给一个新的变量
            calibrated_iq = apply_channel_calibration(iq, self.alpha_matrix, self.phi_matrix)
            #对新的IQ数据 重新计算FFT
            self.fft_results_1D = Perform1D_FFT(calibrated_iq)
            self.fft_results_2D = Perform2D_FFT(self.fft_results_1D)
        else:
            # 如果不校准，则直接使用原始iq数据
            calibrated_iq = iq

        self.display.update_adc4(calibrated_iq, chirp, sample)
        self.display.update_direct_wave_phase(self.fft_results_1D,index=1)
        self.display.update_constellations(calibrated_iq, remove_dc=True, max_points=3000, show_fit=True)
        self.display.update_amp_phase(calibrated_iq, chirp=0, decimate=1, unwrap_phase=False)
        self.display.update_fft1d(self.fft_results_1D, sample)
        self.display.update_fft2d(self.fft_results_2D, sample, chirp)

        #R_fft, R_macleod, R_czt_fftpeak, R_czt_macleod = calculate_distance_from_fft2(self.fft_results_1D[0], chirp, sample)
        az, el, idx, info = estimate_az_el_from_fft2d(self.fft_results_2D)
        self.display.update_point_cloud_polar("PointCloud", R_macleod, 90.0-az, size=10.0, color='g')

        # 更新表格显示距离、角度计算结果
        # row_data = [f"{self.current_index}",f"{az:.4f}",f"{R_fft:.4f} m / {diag['f_fft_peak_Hz']:.4f}hz",
        #             f"{R_macleod:.4f} m / {diag['f_macleod_Hz']:.4f}hz",f"{R_czt_fftpeak:.4f} m / {diag['f_czt_only_Hz']:.4f}hz",
        #             f"{R_czt_macleod:.4f} m / {diag['f_combo_Hz']:.4f}hz"]
        row_data = [f"{self.current_index}",f"{az:.2f}",f"{R_fft:.4f}",f"{diag['f_fft_peak_Hz']:.4f}",
                    f"{R_macleod:.4f}",f"{diag['f_macleod_Hz']:.4f}",f"{R_czt_fftpeak:.4f}",f"{diag['f_czt_only_Hz']:.4f}",
                    f"{R_czt_macleod:.4f}",f"{diag['f_combo_Hz']:.4f}"]


        row_count = self.tableWidget_distance.rowCount()
        self.tableWidget_distance.insertRow(row_count)
        for i, value in enumerate(row_data):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)# 设置单元格居中对齐
            self.tableWidget_distance.setItem(row_count, i, item)
        self.tableWidget_distance.scrollToBottom()# 滚动到底部

    def ShowNextFrame(self):
        if self.current_index < len(self.frame_data_list) - 1:
            self.current_index += 1
            self.show_matrix(self.frame_all_data[self.frame_data_list[self.current_index]])
        else:
            QMessageBox.information(self, "没有更多数据", "已到达文件末尾！")

    def CloseFile(self):
        self.frame_all_data = None
        self.frame_data_list = []  # 清空数据
        self.current_index = 0  # 重置索引
        self.textEdit_log.clear()  # 清空日志
        self.tableWidget_distance.clearContents()  # 清空表格内容
        self.tableWidget_distance.setRowCount(0)
        self.lineEdit_ModeName.clear()
        self.alpha_matrix = None
        self.phi_matrix = None
        self.display.reset()
        self.bus.log.emit("已关闭文件，清空数据")

    def SaveTable(self):
        """
        将表格中的数据保存到CSV文件。
        """
        # 弹出文件对话框让用户选择保存路径和文件名
        filename, _ = QFileDialog.getSaveFileName(self, "保存数据", "", "CSV Files (*.csv)")
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)

                    # 获取表头并写入
                    header_labels = []
                    for col in range(self.tableWidget_distance.columnCount()):
                        header_labels.append(self.tableWidget_distance.horizontalHeaderItem(col).text())
                    writer.writerow(header_labels)

                    # 遍历所有行和列，写入数据
                    for row in range(self.tableWidget_distance.rowCount()):
                        row_data = []
                        for col in range(self.tableWidget_distance.columnCount()):
                            item = self.tableWidget_distance.item(row, col)
                            if item is not None:
                                row_data.append(item.text())
                            else:
                                row_data.append("") # 如果单元格为空，则写入空字符串
                        writer.writerow(row_data)

                QMessageBox.information(self, "保存成功", f"数据已成功保存到\n{filename}")

            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"保存文件时出错：\n{e}")


# ================== 电机控制相关内容 ==================
    def MotorConnect(self):
        if self.CH375motor.usb_initialize() and self.CH375motor.motor_initialize():
            self.pushButton_MotorDisconnect.setEnabled(True)
            self.pushButton_MoveAngel.setEnabled(True)
            self.bus.log.emit("[OK]电机连接成功")
        else:
            self.bus.log.emit("[ERR]电机连接失败，请检查连接")

    def MotorDisconnect(self):
        if self.CH375motor.motor_stop():
            self.bus.log.emit("[OK]电机断开成功")

    def AngelMove(self):
        angel_str = self.lineEdit_MoveAngel.text()
        try:
            angel = float(angel_str)
            self.CH375motor.motor_start(angel)
        except ValueError as ve:
            self.bus.log.emit(f"[ERR]无效的角度输入")

    def closeEvent(self, e):
        self.UDP_disconnect()
        super().closeEvent(e)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MyMainForm()
    win.show()
    sys.exit(app.exec())

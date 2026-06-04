from UI.Ui_Radar_UDP import Ui_MainWindow
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QInputDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDockWidget, QWidget
from PySide6.QtCore import QThread,QObject, Signal, Qt, QtMsgType, qInstallMessageHandler, QTimer
from PySide6.QtGui import QPixmap, QIcon, QAction
import sys, socket, threading
from scipy.io import loadmat
import scipy.linalg
import numpy as np
import collections
import warnings
import time
import csv
import os
import cv2
from datetime import datetime
from data_processing import *
import motorController
from udp_handler import *
from display_pg import PgDisplay
from WLS_Calibration import *
LISTEN_IP = "0.0.0.0"        # 监听所有网卡
LISTEN_PORT = 8888           # 本地接收端口
PEER_IP = "192.168.1.55"     # 雷达设备IP
PEER_PORT = 6666             # 若需主动发送，发往的端口
PKT_SIZE = 1024              # 每个UDP包固定 1024B

# ================== Qt 信号总线 ==================
class Bus(QObject):
    log         = Signal(str)     # log日志重定向

class MotorTestWorker(QThread):
    log_signal = Signal(str)     # 用于发日志给UI
    finished_signal = Signal()   # 用于通知任务结束

    def __init__(self, main_window_ref):
        super().__init__()
        self.main_ref = main_window_ref  # 获取主窗口引用(为了访问 motor 和 list)
        self.is_running = True # 停止标志位

    def run(self):
        """这里是子线程，在这里 sleep 不会卡死界面"""
        stepAngel = 1.0
        delayTime = 1.0
        num_moves = 91
        currentAngel = -46.0

        # 如果你需要每次重置 TestAngle，可以在这里初始化
        TestAngle = -100.0

        results_data = []
        csv_header = ["CommandedAngle (currentAngel)", "CalculatedAngle (TestAngle)"]

        self.log_signal.emit(f"[INFO] 线程启动: 开始执行圆周测试...")

        for i in range(num_moves):
            # 1. 安全退出机制
            if not self.is_running:
                self.log_signal.emit("[WARN] 测试被强制停止。")
                return
            # 2. 调用电机移动 (调用主窗口对象的方法)
            try:
                success = self.main_ref.CH375motor.motor_start(stepAngel)
            except Exception as e:
                self.log_signal.emit(f"⛔ 电机调用异常: {e}")
                success = False
            if success:
                currentAngel += stepAngel
                time.sleep(delayTime)  # 等待电机稳定
                # --- 安全访问主线程的数据 ---
                try:
                    if self.main_ref.AZangelList:
                        TestAngle = self.main_ref.AZangelList[-1]
                    else:
                        TestAngle = 0.0
                except:
                    TestAngle = 0.0
                self.log_signal.emit(f"[INFO] 当前角度={currentAngel:.1f}, 测得角度={TestAngle:.2f}")
            else:
                self.log_signal.emit(f"⛔ 第 {i+1} 次移动失败")
                TestAngle = float('nan')
            results_data.append([currentAngel, TestAngle])
        # --- 循环结束，保存文件 ---
        self.log_signal.emit(f"[INFO] 采集完毕，正在保存 CSV...")
        self.save_csv(results_data, csv_header)
        # 发送结束信号
        self.finished_signal.emit()

    def save_csv(self, data, header):
        try:
            # 生成时间戳 (你需要确保 generate_unique_time 可以在这里调用，或者直接用 time 库)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"motor_test_log_{timestamp}.csv"

            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(data)

            self.log_signal.emit(f"✅ 文件保存成功: {filename}")
        except Exception as e:
            self.log_signal.emit(f"⛔ 保存 CSV 失败: {e}")

    def stop(self):
        self.is_running = False

# ================== 接收线程（Python threading + socket） ==================
class UdpReceiver(threading.Thread):
    """(生产者) 只负责监听UDP端口，将原始包放入 raw_queue"""
    def __init__(self, ip: str, port: int, raw_queue: queue.Queue):
        super().__init__(daemon=True)
        self.ip, self.port = ip, port
        self.raw_queue = raw_queue
        self._stop_evt = threading.Event()
        self._sock = None
        self.peer_ip = PEER_IP

    def run(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self.ip, self.port))
            self._sock.settimeout(0.5)
            print(f"[UdpReceiver] 监听 {self.ip}:{self.port} ...")
        except Exception as e:
            print(f"[UdpReceiver] 绑定失败: {e!r}")
            self.raw_queue.put(('__recv_error__', f"绑定失败: {e!r}"))
            return

        while not self._stop_evt.is_set():
            try:
                data, (sip, sport) = self._sock.recvfrom(PKT_SIZE * 2) # 缓冲区稍大
                if sip != self.peer_ip:
                    continue
                # 将原始包放入队列，由 RobustFrameAssembler 处理
                self.raw_queue.put((time.time(), data))
            except socket.timeout:
                continue
            except OSError:
                break
        if self._sock:
            self._sock.close()
        print("[UdpReceiver] 接收线程已退出")

    def stop(self):
        self._stop_evt.set()

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
        self.tabWidget_Display.setMovable(True) #把widgets_tab设置为可移动转为dock

        # UDP网络读取相关变量
        self.raw_queue = None
        self.frame_queue = None
        self.receiver_thread = None
        self.assembler_thread = None
        self.tx_sock = None
        self.frame_consumer_timer = QTimer(self)
        self.frame_consumer_timer.timeout.connect(self.check_frame_queue)
        # mat文件存读相关变量
        self.save_filename = None
        self.buffer = [] # 大缓存：暂存未保存的帧
        self.frame_all_data = None
        self.frame_data_list = []
        self.current_index = 0
        # mat文件自动播放
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.ShowNextFrame) # 定时器的timeout连接到显示下一帧的函数
        self.playback_speed_ms = 100 # 每帧播放间隔（毫秒）
        self.is_playing = False # 播放状态标志
        # 实时处理相关变量
        self.fft_results_1D = None
        self.fft_results_2D = None
        # 校准相关变量
        self.calibration_list_FFTpeak = []
        self.calibration_list_LS= []
        self.calibration_list_WLS = []
        self.warmup_count = 0
        self.warmup_avg = None
        self.alpha_matrix = None
        self.phi_matrix = None
        self.v_calibration = None #ILS校准向量
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
            frequency_placeholders=self.frequency_placeholders,
            MUSICspectrum_placeholders=self.MUSICspectrum_placeholders,
            MUSIC2dSpectrum_placeholders=self.MUSIC2dSpectrum_placeholders,
            video_placeholders=self.video_placeholders
        )
        # 转台电机实例化
        self.AZangelList = collections.deque(maxlen=5)
        self.CH375motor = motorController.MotorController()
        # 信号总线连接
        self.bus = Bus()
        self.bus.log.connect(self._log)

        # 创建菜单
        self.create_menus()
        self.upgrade_to_dockwidgets()
        index = self.tabWidget_Display.indexOf(self.tab_Placeholder)
        if index != -1:
            self.tabWidget_Display.setTabVisible(index, False)

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
        MUSICspectrum_keys = ['MUSICspectrum']
        MUSICspectrum2d_keys = ['MUSIC2dSpectrum']
        video_keys = ['video']

        self.adc_placeholders = {k: getattr(self, f'widget_{k}') for k in adc4_keys}
        self.fft1d_placeholders = {k: getattr(self, f'widget_{k}') for k in fft1d_keys}
        self.fft2d_placeholders = {k: getattr(self, f'widget_{k}') for k in fft2d_keys}
        self.point_cloud_placeholders = {k: getattr(self, f'widget_{k}') for k in point_cloud_keys}
        self.DirectWave_placeholders = {k: getattr(self, f'widget_{k}') for k in DirectWave_keys}
        self.constellation_placeholders = {k: getattr(self, f'widget_{k}') for k in ConstellationDiagram_keys}
        self.amp_phase_placeholders = {k: getattr(self, f'widget_{k}') for k in amp_phase_keys}
        self.frequency_placeholders = {k: getattr(self, f'widget_{k}') for k in frequency_keys}
        self.MUSICspectrum_placeholders = {k: getattr(self, f'widget_{k}') for k in MUSICspectrum_keys}
        self.MUSIC2dSpectrum_placeholders = {k: getattr(self, f'widget_{k}') for k in MUSICspectrum2d_keys}
        self.video_placeholders = {k: getattr(self, f'widget_{k}') for k in video_keys}

    def setup_distance_table(self):
        self.tableWidget_distance.setColumnCount(11)
        header_labels = ['index','FFT','FFT-fre', 'Macleod', 'Macleod-fre',
                          'Rife', 'Rife-fre', 'CTZ', 'CTZ-fre', 'MCTZ', 'MCTZ-fre']
        self.tableWidget_distance.setHorizontalHeaderLabels(header_labels)
        self.tableWidget_distance.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tableWidget_distance.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tableWidget_distance.verticalHeader().setVisible(False)

        self.tableWidget_point.setColumnCount(5)
        point_header_labels = ['index','distance', 'angle', 'x', 'y']
        self.tableWidget_point.setHorizontalHeaderLabels(point_header_labels)
        self.tableWidget_point.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tableWidget_point.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tableWidget_point.verticalHeader().setVisible(False)

    def setupInitialUIState(self):
        self.checkBox_CalibrationMode.stateChanged.connect(self.CalibrationModeMessage)
        self.checkBox_IsSave.stateChanged.connect(self.SaveMatChange)

        self.pushButton_Disconnect.setEnabled(False)
        self.pushButton_MotorDisconnect.setEnabled(False)
        self.pushButton_MoveAngel.setEnabled(False)
        self.pushButton_Next.setEnabled(False)
        self.pushButton_SaveTable.setEnabled(False)
        self.pushButton_Play.setEnabled(False)
        self.pushButton_video_close.setEnabled(False)
        #self.pushButton_CloseFile.setEnabled(False)

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
        dock_control = QDockWidget("dock_Config", self)
        dock_control.setObjectName("dock_control")  # 方便调试
        dock_control.setWidget(self.groupBox_Config)
        dock_control.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock_control)
        dock_control.setFeatures(QDockWidget.NoDockWidgetFeatures)

        # === 5. 创建 消息与数据 Dock ===
        dock_message = QDockWidget("dock_Message", self)
        dock_message.setObjectName("dock_message")
        dock_message.setWidget(self.tabWidget_Message)
        dock_message.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock_message)

        # === 6. 创建 额外功能 Dock（隐藏）为了让整个GUI四分布局===
        dock_extra = QDockWidget("dock_copyR", self)
        dock_extra.setObjectName("dock_extra")
        dock_extra.setWidget(self.widget_extra)
        dock_extra.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock_extra.setTitleBarWidget(QWidget())
        self.splitDockWidget(dock_control, dock_extra, Qt.Orientation.Vertical)
        #dock_extra.hide()

        # === 6. 添加到“视图”菜单 ===
        view_menu = self.menuBar().addMenu("View")
        for dock in docks_display:
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addAction(dock_control.toggleViewAction())
        view_menu.addAction(dock_message.toggleViewAction())

        dock_extra.setMinimumHeight(200)
        dock_extra.setMaximumWidth(300)
        dock_message.setMinimumHeight(200)

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
                "<p><b>Version:</b> 5.0.1</p>"
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
            self.bus.log.emit("⚠️已启用校准模式。\n"
                                "请确保雷达正对自反靶进行校准。\n"
                                "默认校准模式为加权最小二乘法（WLS）。\n"
                                "前20帧用于预热并计算参考平均值，后50帧用于计算校准矩阵。\n"
                                "校准结束后程序会自动断开连接，并关闭所有文件。")
            self.radioButton_WLS.setChecked(True)
        else:
            self.bus.log.emit("⚠️已关闭校准模式。")

    def SaveMatChange(self):
        """启用或关闭保存 .mat 文件功能"""
        if self.checkBox_IsSave.isChecked():
            self.buffer = []  # 清空缓存
            if not self.save_filename:
                self.save_filename = f"{self.generate_unique_time()}_raw_data_py.mat"
            self.bus.log.emit("✅已启用原始数据保存功能。\n"
                              f"保存文件：{self.save_filename}\n"
                              "每100帧数据自动保存一次，程序关闭时会保存剩余缓存。")
        else:
            self.save_buffer_to_mat()  # 保存剩余缓存
            self.buffer = []  # 清空缓存
            self.save_filename = None
            self.bus.log.emit("✅已关闭原始数据保存功能。")

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
        self.UDP_disconnect()  # 先执行断开，确保清理干净
        try:
            # 1. 创建队列
            self.raw_queue = queue.Queue(maxsize=1024)
            self.frame_queue = queue.Queue(maxsize=32)
            # 2. 启动生产者 (UdpReceiver)
            self.receiver_thread = UdpReceiver(LISTEN_IP, LISTEN_PORT, self.raw_queue)
            self.receiver_thread.start()
            # 3. 启动消费者 (RobustFrameAssembler)
            self.assembler_thread = RobustFrameAssembler(self.raw_queue, self.frame_queue, timeout=1.0)
            self.assembler_thread.start()
            # 4. 启动 QTimer 来从 frame_queue 消费
            self.frame_consumer_timer.start(10) # 每 10ms 检查一次
            # 5. 准备发送用的 Socket
            self.tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.bus.log.emit(f"✅ 发送目标 {PEER_IP}:{PEER_PORT}")

            self.pushButton_Connect.setEnabled(False)
            self.pushButton_Disconnect.setEnabled(True)
            self.bus.log.emit("✅ 已连接")

        except Exception as e:
            self.bus.log.emit(f"⛔ 连接失败: {e!r}")
            self.UDP_disconnect() # 出错时回滚

    # ---- 断开：停止Timer + 两个线程 + 关socket ----
    def UDP_disconnect(self):
        # 1. 停止 QTimer
        self.frame_consumer_timer.stop()
        # 2. 停止消费者线程 (assembler)
        if self.assembler_thread:
            self.assembler_thread.stop()
            self.assembler_thread.join(timeout=1.0)
            self.assembler_thread = None
        # 3. 停止生产者线程 (receiver)
        if self.receiver_thread:
            self.receiver_thread.stop()
            self.receiver_thread.join(timeout=1.0) # join() 等待线程真正退出
            self.receiver_thread = None
        # 4. 关闭发送 socket
        if self.tx_sock:
            try: self.tx_sock.close()
            except Exception: pass
            self.tx_sock = None
        # 5. 清理队列
        self.raw_queue = None
        self.frame_queue = None
        self.bus.log.emit("✅ 已断开")
        self.pushButton_Connect.setEnabled(True)
        self.pushButton_Disconnect.setEnabled(False)

        if self.checkBox_IsSave.isChecked():
            self.save_buffer_to_mat()  # 保存剩余缓存

    # ---- 整帧到达回调函数 ----
    def check_frame_queue(self):
        """
        (主线程) 由 QTimer 调用
        """
        if not self.frame_queue:
            return # 尚未连接
        try:
            # 1. 从队列中非阻塞地获取一个项目
            item = self.frame_queue.get_nowait()
        except queue.Empty:
            return
        # 2. 检查是否是错误/日志消息
        if isinstance(item, tuple) and item and item[0] == '__error__':
            self.bus.log.emit(f"{item[1]}") # 将线程中的日志转发到GUI
            return
        # 3. 解包数据 (这现在匹配了 on_frame_ready 的参数)
        fid, frame, sample, chirp, txrx = item
        # 4. --- 数据处理 ---
        try:
            # 保存到 .mat 文件
            if self.checkBox_IsSave.isChecked():
                self.save_to_buffer(frame,sample,chirp)

            current_time = time.time()
            if self.checkBox_HammingWindow.isChecked():
                my_window = np.hamming(sample)
            else:
                my_window = None

            iq = reorder_frame_TDMMIMO(frame, chirp, sample, txrx, window=my_window)

            # iq = reorder_frame_TDMMIMO2(frame, chirp, sample, txrx, window=my_window)
            self.fft_results_1D = Perform1D_FFT(iq)
            self.fft_results_2D = Perform2D_FFT(self.fft_results_1D)
            self.display.update_direct_wave_phase(self.fft_results_1D,index=1)
            R_fft, R_macleod, R_Rife, R_czt_fftpeak, R_czt_macleod,diag = calculate_distance_from_iq(iq,r_bins=0.5,M=16,use_window=None,coherent=True)
            self.display.update_frequency(iq,diag)

            if self.checkBox_CalibrationMode.isChecked():
                #得到2DFFT的峰值索引 对应的zij向量
                peak_idx = np.unravel_index(np.argmax(np.abs(self.fft_results_2D[0])), self.fft_results_2D[0].shape)
                zij_vector = self.fft_results_2D[:, peak_idx[0], peak_idx[1]]
                if self.radioButton_WLS.isChecked():
                    self.calibrate_on_demand_WLS(zij_vector, self.fft_results_2D, peak_idx)
                elif self.radioButton_FFT.isChecked():
                    self.calibrate_on_demand_FFT(iq)
                elif self.radioButton_LS.isChecked():
                    self.calibrate_on_demand_LS(zij_vector)

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

            az_grid, el_grid, spectrum_dB, peak_az, peak_el = music_2d_spectrum_auto(self.fft_results_1D)
            self.AZangelList.append(peak_az)
            self.display.update_Azimuth_Spectrum(spectrum_dB,az_grid,el_grid,peak_az,peak_el)
            self.display.update_MUSIC2dSpectrum(az_grid, el_grid, spectrum_dB, peak_az, peak_el)
            if self.checkBox_channel_calibration.isChecked():
                point_dict = self.display.update_point_cloud_polar("PointCloud", R_czt_macleod, 90.0-peak_az, size=10.0, color='g')
            else:
                point_dict = self.display.update_point_cloud_polar("PointCloud", R_fft, 90.0-peak_az, size=10.0, color='g')

            # 更新表格显示距离计算结果
            row_data_distance = [f"{self.current_index}",f"{R_fft:.4f}",f"{diag['f_fft_peak_Hz']:.4f}",
                                f"{R_macleod:.4f}",f"{diag['f_macleod_Hz']:.4f}",
                                f"{R_Rife:.4f}",f"{diag['f_rife_Hz']:.4f}",
                                f"{R_czt_fftpeak:.4f}",f"{diag['f_czt_only_Hz']:.4f}",
                                f"{R_czt_macleod:.4f}",f"{diag['f_combo_Hz']:.4f}"]
            row_count = self.tableWidget_distance.rowCount()
            self.tableWidget_distance.insertRow(row_count)
            for i, value in enumerate(row_data_distance):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)# 设置单元格居中对齐
                self.tableWidget_distance.setItem(row_count, i, item)
            self.tableWidget_distance.scrollToBottom()# 滚动到底部

            #更新表格显示角度及点云计算结果
            row_data_point = [f"{self.current_index}", f"{point_dict['r']:.4f}", f"{point_dict['theta_deg']:.4f}", f"{point_dict['x']:.4f}", f"{point_dict['y']:.4f}"]
            row_count = self.tableWidget_point.rowCount()
            self.tableWidget_point.insertRow(row_count)
            for i, value in enumerate(row_data_point):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.tableWidget_point.setItem(row_count, i, item)
            self.tableWidget_point.scrollToBottom()
            self.current_index += 1

        except Exception as e:
            # (重要) 捕捉处理过程中发生的任何错误，防止GUI崩溃
            self.bus.log.emit(f"⛔ 帧 {fid} 处理失败: {e}")

# ================== video视频相关内容 ==================
    def VideoOpen(self):
        """打开电脑摄像头并在 GUI 中显示实时画面"""
        # 尝试打开摄像头
        self.video_cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if self.video_cap.isOpened():
            self.bus.log.emit(f"✅ 已打开摄像头")
        else:
            self.bus.log.emit("⛔ 无法打开任何摄像头，请检查设备连接")
            self.video_cap = None
            return

        self.video_cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.video_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self._video_grab_frame)
        self.video_timer.start(33)  # ~30 FPS

        self.pushButton_Video_open.setEnabled(False)
        self.pushButton_video_close.setEnabled(True)

    def _video_grab_frame(self):
        """(主线程) 由 video_timer 定时调用，抓取一帧并送到显示组件"""
        if self.video_cap is None or not self.video_cap.isOpened():
            return
        ret, frame = self.video_cap.read()
        if ret and frame is not None:
            self.display.update_video_frame('video', frame)

    def VideoClose(self):
        """关闭摄像头并停止视频流"""
        if hasattr(self, 'video_timer') and self.video_timer is not None:
            self.video_timer.stop()
            self.video_timer = None
        if hasattr(self, 'video_cap') and self.video_cap is not None:
            self.video_cap.release()
            self.video_cap = None
        self.pushButton_Video_open.setEnabled(True)
        self.pushButton_video_close.setEnabled(False)
        # 恢复视频占位文本
        if 'video' in self.display.pg_video_dict:
            label = self.display.pg_video_dict['video']['label']
            label.clear()
            label.setText("Camera Offline")
        self.bus.log.emit("✅ 摄像头已关闭")

# ================== 校准部分内容LS ==================
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
    def calibrate_on_demand_LS(self, zij_vector: np.ndarray):
        if zij_vector.shape != (4,):
            raise ValueError("zij_vector 必须是包含4个元素的向量。")

        # --- 阶段一：雷达预热与基准计算 ---
        if self.warmup_count < 20:
            self.calibration_list_LS.append(zij_vector)
            self.warmup_count += 1
            if self.warmup_count == 20:
                print("预热完成，将开始收集数据。")
                # 预热阶段结束，计算基准平均值
                warmup_vectors = np.array(self.calibration_list_LS)
                # 计算每个通道的平均幅值
                self.warmup_avg = np.mean(np.abs(warmup_vectors), axis=0)
                # 清空列表，为下一阶段做准备
                self.calibration_list_LS.clear()
            return

        # --- 阶段二：正式校准与数据过滤 ---
        if len(self.calibration_list_LS) < 50:
            # 计算当前帧的幅值
            current_amplitudes = np.abs(zij_vector)

            # 检查幅值是否在预热平均值2倍的范围内
            # 这里使用 all() 确保所有4个通道都符合条件
            is_valid = np.all(current_amplitudes <= 2 * self.warmup_avg)

            if is_valid:
                self.calibration_list_LS.append(zij_vector)
        current_count = len(self.calibration_list_LS)

        if current_count >= 50:
            print("已收集 50 帧，将立即执行校准...")
            # 1. 计算平均值
            zij_vectors_to_calibrate = np.array(self.calibration_list_LS)
            zij_vector_avg = np.mean(zij_vectors_to_calibrate, axis=0)

            # 2. 调用校准函数
            alpha_matrix = amplitude_calibration(zij_vector_avg)
            phi_matrix = phase_calibration(zij_vector_avg)

            # 3. 保存
            filename = f"{self.generate_unique_time()} calibration_matrix_LS"
            np.savez(filename, alpha=0.9*alpha_matrix, phi=0.9*phi_matrix) # 适当缩放

            # 4. 清空列表并重置状态，为下一次校准做准备
            self.calibration_list_LS.clear()
            self.warmup_count = 0
            self.warmup_avg = None

            # 5. 断开连接并提示
            self.CloseFile()
            self.UDP_disconnect()
            self.play_timer.stop()
            self.pushButton_Play.setText("Play")
            QMessageBox.information(self, "校准完成", f"校准矩阵保存到：\n{filename}。")

# ================== 校准部分内容WLS ==================
    def calibrate_on_demand_WLS(
        self,
        zij_vector: np.ndarray,
        z_ij_spectrum_frame: np.ndarray,  # (4, N_Doppler, N_Range)
        peak_idx: tuple                   # (c0, r0)
    ):
        """
        [WLS 真实应用版]
        基于加权最小二乘法 (WLS) 进行幅相校准流程。
        """
        if zij_vector.shape != (4,):
            raise ValueError("zij_vector 必须是包含4个元素的向量。")
        if z_ij_spectrum_frame.shape[0] != 4:
            raise ValueError("z_ij_spectrum_frame 的第一维必须为 4。")
        n_ant = 4  # 4个虚拟通道
        # ================================
        # 阶段一：雷达预热 (保持不变)
        # ================================
        if self.warmup_count < 20:
            # 统一强制转换，保证后续 shape 一致
            zij_vector = np.asarray(zij_vector).reshape(4,)
            z_ij_spectrum_frame = np.asarray(z_ij_spectrum_frame)
            self.calibration_list_WLS.append((zij_vector, z_ij_spectrum_frame))
            self.warmup_count += 1

            if self.warmup_count == 20:
                warmup_vectors = np.array([data[0] for data in self.calibration_list_WLS])
                self.warmup_avg = np.mean(np.abs(warmup_vectors), axis=0)
                self.calibration_list_WLS.clear()
                print("预热完成，将开始收集数据。")
            return
        # ================================
        # 阶段二：正式校准与数据过滤 (保持不变)
        # ================================
        if len(self.calibration_list_WLS) < 50:
            current_amplitudes = np.abs(zij_vector)
            is_valid = np.all(current_amplitudes <= 2 * self.warmup_avg)
            if is_valid:
                self.calibration_list_WLS.append((np.asarray(zij_vector).reshape(4,),
                                            np.asarray(z_ij_spectrum_frame)))
        current_count = len(self.calibration_list_WLS)
        # ================================
        # 阶段三：WLS 计算（核心加入防御）
        # ================================
        if current_count >= 50:
            print("已收集 50 帧，将立即执行校准...")
            valid_zij_list = []
            valid_spectrum_list = []
            bad_indices = []
            # ---- 防御性检查：确保每帧 shape/type 完整一致 ----
            for idx, item in enumerate(self.calibration_list_WLS):
                if not (isinstance(item, (tuple, list)) and len(item) >= 2):
                    bad_indices.append((idx, "not tuple/list or len<2"))
                    continue
                vec, spec = item
                # vec：必须能转成 ndarray 并 reshape 成 (4,)
                try:
                    vec = np.asarray(vec).reshape(4,)
                except Exception:
                    bad_indices.append((idx, f"vec shape invalid: {np.asarray(vec).shape}"))
                    continue
                # spec：必须能转成 ndarray，且第一维为 4
                try:
                    spec = np.asarray(spec)
                except Exception:
                    bad_indices.append((idx, f"spectrum convert failed"))
                    continue
                if spec.ndim < 2 or spec.shape[0] != 4:
                    bad_indices.append((idx, f"spectrum shape={spec.shape}"))
                    continue
                valid_zij_list.append(vec)
                valid_spectrum_list.append(spec)
            # ---- 输出被跳过帧的信息（用于调试） ----
            if bad_indices:
                print(f"[WLS] 跳过 {len(bad_indices)} 个非法帧，示例：{bad_indices[:5]}")

            if len(valid_zij_list) == 0:
                QMessageBox.warning(self, "校准失败", "无有效帧可用于校准（所有帧不合格）。")
                return
            # ---- 拼接为 ndarray（保证不会再报 ValueError） ----
            zij_vectors_to_calibrate = np.stack(valid_zij_list, axis=0)       # (N_valid, 4)
            spectrums_to_calibrate   = np.stack(valid_spectrum_list, axis=0) # (N_valid, 4, N_Doppler, N_Range)
            current_count = zij_vectors_to_calibrate.shape[0]  # 更新有效数量
            # ================================
            #  后续保持不变：计算平均、噪声、权重、WLS
            # ================================
            zij_vector_avg = np.mean(zij_vectors_to_calibrate, axis=0)
            noise_power_matrix_frames = np.zeros((current_count, n_ant))
            for frame_idx in range(current_count):
                for channel_idx in range(n_ant):
                    noise_power = estimate_noise_power_from_frame(
                        spectrums_to_calibrate[frame_idx, channel_idx], peak_idx
                    )
                    noise_power_matrix_frames[frame_idx, channel_idx] = noise_power
            avg_noise_power_per_channel = np.mean(noise_power_matrix_frames, axis=0)
            weights = calculate_weights(zij_vector_avg, avg_noise_power_per_channel, n_obs=current_count)
            alpha_matrix = amplitude_calibration_wals(zij_vector_avg, weights)
            phi_matrix = phase_calibration_wls(zij_vector_avg, weights)
            filename = f"{self.generate_unique_time()} calibration_matrix_WLS"
            np.savez(filename, alpha=alpha_matrix, phi=phi_matrix)
            # ----- 清理环境 -----
            self.calibration_list_WLS.clear()
            self.warmup_count = 0
            self.warmup_avg = None

            self.CloseFile()
            self.UDP_disconnect()
            self.play_timer.stop()
            self.pushButton_Play.setText("Play")
            QMessageBox.information(self, "WLS 校准完成", f"WLS 校准矩阵保存到：\n{filename}。")

# ================== 校准部分内容FFT峰值校准 ==================
    def calibrate_on_demand_FFT(self, iq_virtual_data: np.ndarray):
        """
        [V4 - 采用“忽略N, 平均M”的新逻辑]
        此函数是您的状态机，它现在正确地接收 (4, N_obs, N_samples) 的IQ数据。

        新逻辑:
        1. 忽略 (丢弃) 前 20 帧数据 (预热)。
        2. 收集接下来的 50 帧数据。
        3. 对这 50 帧数据进行平均，并执行校准。
        """
        calib_peak_bin = None  # 用于锁定峰值 Bin 的变量
        try:
            if iq_virtual_data.ndim != 3 or iq_virtual_data.shape[0] != 4:
                print(f"错误: 输入IQ数据维度必须是 (4, N_obs, N_samples), 实际为 {iq_virtual_data.shape}")
                return
            K_TX, L_RX = 2, 2
            M_virtual, N_obs, N_samples = iq_virtual_data.shape
            # (A) 执行 FFT
            range_fft_results = np.fft.fft(iq_virtual_data, axis=2)
            # (B) 自动查找峰值 Bin (仅在第一次运行时执行一次)
            if calib_peak_bin is None:
                # 仅在第一次运行时查找和锁定峰值
                fft_magnitude = np.abs(range_fft_results)
                avg_range_profile = np.mean(fft_magnitude, axis=(0, 1))
                avg_range_profile[0] = 0 # 忽略直流
                calib_peak_bin = int(np.argmax(avg_range_profile))
            # (C) 提取复数增益向量 (使用锁定的 Bin)
            peak_complex_values = range_fft_results[:, :, calib_peak_bin]
            zij_vector = np.mean(peak_complex_values, axis=1) # (4,) 向量
        except Exception as e:
            print(f"错误: 处理IQ数据失败: {e}")
            return
        # --- 阶段 0 完毕，zij_vector (4,) 已生成 ---
        self.warmup_count += 1 # 充当总帧数计数器
        # --- 阶段一：雷达预热 (忽略前 20 帧) ---
        if self.warmup_count <= 20:
            #print(f"预热中... 丢弃第 {self.warmup_count}/20 帧")
            if self.warmup_count == 20:
                print("预热完成，将开始收集数据。")
            return # 丢弃这一帧的数据，直接返回

        # --- 阶段二：收集 50 帧 ---
        if len(self.calibration_list_FFTpeak) < 50:
            self.calibration_list_FFTpeak.append(zij_vector)
            #print(f"收集中... {len(self.calibration_list_FFTpeak)}/50 帧 (总帧数: {self.warmup_count})")
            # 检查是否刚收集满50帧
            if len(self.calibration_list_FFTpeak) < 50:
                return # 还未满50帧，返回
            else:
                print("已收集 50 帧，将立即执行校准...")

        # --- 阶段三：执行校准 ---
        # 1. 计算平均值
        zij_vectors_to_calibrate = np.array(self.calibration_list_FFTpeak)
        zij_vector_avg = np.mean(zij_vectors_to_calibrate, axis=0) # shape (4,)
        # 2. [FFT峰值法逻辑]
        try:
            # ---- 正确的校准补偿因子计算（使用 TX0-RX0 作为参考） ----
            ref_val = zij_vector_avg[0]   # TX0-RX0 作为参考通道
            # 幅度补偿因子：使校准后 |zij| 与参考一致
            alpha = np.abs(ref_val) / np.abs(zij_vector_avg)
            # 相位补偿因子：使校准后相位与参考一致
            phi = np.angle(ref_val) - np.angle(zij_vector_avg)
            phi = -phi
            # 相位包装到 (-pi, pi]
            phi = (phi + np.pi) % (2 * np.pi) - np.pi
            #phi = -phi  # 取负号作为补偿
            alpha_matrix = alpha.reshape((K_TX, L_RX))
            phi_matrix   = phi.reshape((K_TX, L_RX))
            print("校准矩阵计算成功。")
        except Exception as e:
            print(f"错误: 无法重塑 (4,) 向量或计算矩阵: {e}")
            self.reset_calibration_state() # 重置状态
            QMessageBox.warning(self, "校准失败", f"校准计算失败: {e}")
            return

        # 3. 保存
        filename = f"{self.generate_unique_time()} calibration_matrix_FFTpeak"
        np.savez(filename, alpha=1.2*alpha_matrix, phi=1.2*phi_matrix)
        print(f"校准矩阵已保存到: {filename}")

        # 5. 断开连接并提示 (您的代码)
        self.calibration_list_FFTpeak.clear()
        self.warmup_count = 0
        self.warmup_avg = None
        self.CloseFile()
        self.UDP_disconnect()
        self.play_timer.stop()
        self.pushButton_Play.setText("Play")
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

            # 使用get方法获取数据，键不存在时返回None
            self.v_calibration = cal_data.get('v_calib', None)
            self.alpha_matrix = cal_data.get('alpha', None)
            self.phi_matrix = cal_data.get('phi', None)

            # 日志输出（仅在存在时打印，避免None值）
            if self.v_calibration is not None:
                self.bus.log.emit(f"ILS校准向量：\n{self.v_calibration}")

            if self.alpha_matrix is not None and self.phi_matrix is not None:
                self.bus.log.emit(f"幅度校准矩阵：\n{self.alpha_matrix}")
                self.bus.log.emit(f"相位校准矩阵：\n{self.phi_matrix}")

# ================== 文件读取部分内容 ==================
    def save_to_buffer(self, frame_data, sample_number, chirp_number):
        """
          每次接收到新的一帧数据，将数据放入大缓存中
        """
        try:
            # 1. 检查数据大小 (你的检查逻辑是正确的)
            num_antennas = 2  # 2 TX * 2 RX
            num_iq = 2        # I/Q
            expected_size = sample_number * chirp_number * num_antennas * num_iq * np.dtype(np.int16).itemsize

            if len(frame_data) != expected_size:
                print(f"Error: Unexpected buffer size! Expected: {expected_size}, Actual: {len(frame_data)}")
                self.bus.log.emit(f"⚠️ 保存失败: 数据大小不匹配")
                return False

            # 2. 转换为 int16 数组
            raw_iq = np.frombuffer(frame_data, dtype=np.int16)

            try:
                num_rows = chirp_number
                num_cols = sample_number * num_antennas * num_iq
                reshaped_data = raw_iq.reshape((num_rows, num_cols))
            except Exception as e:
                print(f"Reshape 失败: {e}. 形状: {(num_rows, num_cols)}, 总数: {raw_iq.size}")
                self.bus.log.emit(f"⚠️ 保存失败: Reshape 失败")
                return False

            # 4. 将数据和配置一起存入缓存
            timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S_%f")
            frame_name = f"frame_{timestamp}"

            frame_struct = {
                'data': reshaped_data,  # (chirp, sample*8) 数组
                'sample': sample_number,
                'chirp': chirp_number
            }

            self.buffer.append({frame_name: frame_struct}) # 保存为字典

            # 5. 如果缓存达到最大大小，自动保存到文件
            if len(self.buffer) >= 100:
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
                self.bus.log.emit(f"✅ 数据成功保存到 {self.save_filename}，包含 {len(existing_data)} 帧数据")

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
            self.pushButton_Play.setEnabled(True)
            #self.pushButton_CloseFile.setEnabled(True)

    def read_mat_file(self, filename):
        """
        读取 MAT 文件中的数据
        """
        try:
            data = loadmat(filename) # 读取 .mat 文件
            self.frame_all_data = data

            self.bus.log.emit(f"读取文件：{filename}")

            # 获取所有包含帧数据的变量（以 "frame" 开头的变量名）
            self.frame_data_list = [key for key in data.keys() if key.startswith('frame')]
            self.frame_data_list.sort() # [推荐] 按时间排序

            self.bus.log.emit(f"找到 {len(self.frame_data_list)} 帧数据")
            self.current_index = 0  # 初始化为第一帧

            # 获取第一帧的数据
            if self.frame_data_list:
                frame_struct = self.frame_all_data[self.frame_data_list[self.current_index]]
                # (注意: scipy.io.loadmat 会把字典读成一个 (1,1) 的 object array)
                frame_struct = frame_struct[0, 0]
                self.show_matrix(frame_struct)
            else:
                self.bus.log.emit("⚠️ 文件中未找到 'frame_' 变量")

        except Exception as e:
            print(f"读取文件时出错: {e}")
            QMessageBox.warning(self, "读取失败", f"读取文件失败：{e}")

    def PlayMatfile(self):
        """
        控制 MAT 文件的播放/暂停。
        如果正在播放，则停止。如果停止，则从当前帧开始播放。
        """
        if not hasattr(self, 'play_timer'):
            QMessageBox.warning(self, "错误", "未初始化播放定时器！")
            return

        if not hasattr(self, 'frame_data_list') or not self.frame_data_list:
            QMessageBox.warning(self, "播放失败", "没有加载任何帧数据！")
            return

        if self.is_playing:
            # 停止播放
            self.play_timer.stop()
            self.is_playing = False
            self.bus.log.emit("停止播放 MAT 文件。")
            self.pushButton_Play.setText("Play")
        else:
            # 开始播放
            if self.current_index >= len(self.frame_data_list) - 1:
                # 如果已经在最后一帧，则从头开始
                self.current_index = 0
                self.show_matrix(self.frame_all_data[self.frame_data_list[self.current_index]])

            # 启动定时器
            self.play_timer.start(self.playback_speed_ms) # 使用预设的间隔
            self.is_playing = True
            self.bus.log.emit(f"开始播放 MAT 文件，间隔：{self.playback_speed_ms} ms。")
            self.pushButton_Play.setText("Pause")
            # 可以更新按钮文本为“暂停”

    def show_matrix(self, frame_struct):
        """
        显示当前帧的数据
        """
        #print(f"显示当前帧数据：{frame_data}")
        #print(f"帧数据形状：{frame_data.shape}")
        #self.bus.log.emit(f"{self.frame_data_list[self.current_index]} 数据已加载")
        try:
            # 1. [修改点] 从结构体中读取数据和配置
            frame_data = frame_struct['data']
            sample = int(frame_struct['sample'][0,0])
            chirp = int(frame_struct['chirp'][0,0])

        except Exception as e:
            self.bus.log.emit(f"⛔ 读取帧结构失败: {e}。数据可能已损坏或格式陈旧。")
            return

        #  处理数据并更新显示
        frame_data_flat = frame_data.flatten()
        if self.checkBox_HammingWindow.isChecked():
            my_window = np.hamming(sample)
        else:
            my_window = None
        if self.checkBox_addnoise.isChecked():
            iq = reorder_frame_TDMMIMO_with_noise(frame_data_flat, chirp, sample, 4, window=my_window,sim_noise_ch=3,sim_noise_level=5048899)
        else:
            iq = reorder_frame_TDMMIMO(frame_data_flat, chirp, sample, 4, window=my_window)
        if self.checkBox_align_iq.isChecked():
            iq = align_iq_virtual(iq)

        #距离计算函数，CZT采用时域变换
        R_fft, R_macleod, R_Rife, R_czt_fftpeak, R_czt_macleod, diag = calculate_distance_from_iq(iq,r_bins=1,M=64,use_window=None,coherent=True)
        self.display.update_frequency(iq,diag)
        self.fft_results_1D = Perform1D_FFT(iq)
        self.fft_results_2D  = Perform2D_FFT(self.fft_results_1D)

        if self.checkBox_CalibrationMode.isChecked():
            #得到2DFFT的峰值索引 对应的zij向量
            peak_idx = np.unravel_index(np.argmax(np.abs(self.fft_results_2D[0])), self.fft_results_2D[0].shape)
            zij_vector = self.fft_results_2D[:, peak_idx[0], peak_idx[1]]
            if self.radioButton_WLS.isChecked():
                self.calibrate_on_demand_WLS(zij_vector, self.fft_results_2D, peak_idx)
            elif self.radioButton_FFT.isChecked():
                self.calibrate_on_demand_FFT(iq)
            elif self.radioButton_LS.isChecked():
                self.calibrate_on_demand_LS(zij_vector)

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

        #此时的calibrated_iq已经经过了校准（如果选中了校准），如果没有校准，则还是原始iq数据，后续显示和距离计算都使用这个数据
        self.display.update_adc4(calibrated_iq, chirp, sample)
        self.display.update_direct_wave_phase(self.fft_results_1D,index=1)
        self.display.update_constellations(calibrated_iq, remove_dc=True, max_points=3000, show_fit=True)
        self.display.update_amp_phase(calibrated_iq, chirp=0, decimate=1, unwrap_phase=False)
        self.display.update_fft1d(self.fft_results_1D, sample)
        self.display.update_fft2d(self.fft_results_2D, sample, chirp)

        az_grid, el_grid, spectrum_dB, peak_az, peak_el = music_2d_spectrum_auto(self.fft_results_2D)
        self.display.update_Azimuth_Spectrum(spectrum_dB,az_grid,el_grid,peak_az,peak_el)
        self.display.update_MUSIC2dSpectrum(az_grid, el_grid, spectrum_dB, peak_az, peak_el)
        if self.checkBox_channel_calibration.isChecked():
            point_dict = self.display.update_point_cloud_polar("PointCloud", R_macleod, 90.0-peak_az, size=10.0, color='g')
        else:
            point_dict = self.display.update_point_cloud_polar("PointCloud", R_fft, 90.0-peak_az, size=10.0, color='g')
        # 更新表格显示距离计算结果
        row_data_distance = [f"{self.current_index}",f"{R_fft:.4f}",f"{diag['f_fft_peak_Hz']:.4f}",
                            f"{R_macleod:.4f}",f"{diag['f_macleod_Hz']:.4f}",
                            f"{R_Rife:.4f}",f"{diag['f_rife_Hz']:.4f}",
                            f"{R_czt_fftpeak:.4f}",f"{diag['f_czt_only_Hz']:.4f}",
                            f"{R_czt_macleod:.4f}",f"{diag['f_combo_Hz']:.4f}"]
        row_count = self.tableWidget_distance.rowCount()
        self.tableWidget_distance.insertRow(row_count)
        for i, value in enumerate(row_data_distance):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)# 设置单元格居中对齐
            self.tableWidget_distance.setItem(row_count, i, item)
        self.tableWidget_distance.scrollToBottom()# 滚动到底部

        #更新表格显示角度及点云计算结果
        row_data_point = [f"{self.current_index}", f"{point_dict['r']:.4f}", f"{peak_az:.4f}", f"{point_dict['x']:.4f}", f"{point_dict['y']:.4f}"]
        row_count = self.tableWidget_point.rowCount()
        self.tableWidget_point.insertRow(row_count)
        for i, value in enumerate(row_data_point):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            self.tableWidget_point.setItem(row_count, i, item)
        self.tableWidget_point.scrollToBottom()

    def ShowNextFrame(self):
        """
        显示下一帧的数据，供手动和定时器调用。
        """
        if self.current_index < len(self.frame_data_list) - 1:
            self.current_index += 1
            self.bus.log.emit(f"显示帧：{self.frame_data_list[self.current_index]}")
            frame_struct = self.frame_all_data[self.frame_data_list[self.current_index]]
            frame_struct = frame_struct[0, 0] # (scipy 格式)
            self.show_matrix(frame_struct)
        else:
            # 播放结束
            if self.is_playing:
                self.PlayMatfile() # 二次调用 PlayMatfile 来停止播放
            else:
                QMessageBox.information(self, "没有更多数据", "已到达文件末尾！")

    def CloseFile(self):
        self.frame_all_data = None
        self.frame_data_list = []  # 清空数据
        self.current_index = 0  # 重置索引
        self.textEdit_log.clear()  # 清空日志
        self.tableWidget_distance.clearContents()  # 清空距离表格内容
        self.tableWidget_distance.setRowCount(0)
        self.tableWidget_point.clearContents()  # 清空点云表格内容
        self.tableWidget_point.setRowCount(0)
        self.lineEdit_ModeName.clear()
        self.alpha_matrix = None
        self.phi_matrix = None
        self.display.reset()
        self.bus.log.emit("已关闭文件，清空数据")
        self.setupInitialUIState()

    def SaveTable(self):
        """
        将表格中的数据保存到CSV文件，支持表格二选一。
        """
        tables = []
        if hasattr(self, 'tableWidget_point'):
            tables.append(("点云表格", self.tableWidget_point))
        if hasattr(self, 'tableWidget_distance'):
            tables.append(("距离表格", self.tableWidget_distance))

        if not tables:
            QMessageBox.warning(self, "警告", "没有可保存的表格")
            return

        selected = []
        if len(tables) == 1:
            selected = [0]
        else:
            items = [name for name, _ in tables]
            item, ok = QInputDialog.getItem(self, "Table Save", "请选择要保存的表格：", items, 0, False)
            if not ok:
                return
            selected = [items.index(item)]

        for idx in selected:
            name, table = tables[idx]
            filename, _ = QFileDialog.getSaveFileName(self, f"保存{name}", "", "CSV Files (*.csv)")
            if not filename:
                continue
            try:
                with open(filename, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    header_labels = []
                    for col in range(table.columnCount()):
                        header_labels.append(table.horizontalHeaderItem(col).text())
                    writer.writerow(header_labels)
                    for row in range(table.rowCount()):
                        row_data = []
                        for col in range(table.columnCount()):
                            item = table.item(row, col)
                            row_data.append(item.text() if item is not None else "")
                        writer.writerow(row_data)
                QMessageBox.information(self, "保存成功", f"{name}已成功保存到\n{filename}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"保存{name}时出错：\n{e}")

# ================== 电机控制相关内容 ==================

    def MotorConnect(self):
        if self.CH375motor.usb_initialize() and self.CH375motor.motor_initialize():
            self.pushButton_MotorDisconnect.setEnabled(True)
            self.pushButton_MoveAngel.setEnabled(True)
            self.bus.log.emit("✅电机连接成功")
        else:
            self.bus.log.emit("⛔电机连接失败，请检查连接")

    def MotorDisconnect(self):
        if self.CH375motor.motor_stop():
            self.bus.log.emit("✅电机断开成功")

    def AngelMove(self):
        angel_str = self.lineEdit_MoveAngel.text()
        try:
            angel = float(angel_str)
            self.CH375motor.motor_start(angel)
        except ValueError as ve:
            self.bus.log.emit(f"⛔无效的角度输入")

    def circleTest(self):
        """
        点击按钮时执行此函数
        """
        # 防止重复启动
        if hasattr(self, 'worker_thread') and self.worker_thread.isRunning():
            self.worker_thread.is_running = False  # 先请求停止当前线程
            self.bus.log.emit("[WARN] 测试正在进行中。")
            return

        # 1. 创建线程实例
        self.worker_thread = MotorTestWorker(self)

        # 2. 连接信号 (连接到你的日志输出函数)
        self.worker_thread.log_signal.connect(self.handle_thread_log)
        self.worker_thread.finished_signal.connect(self.handle_test_finished)

        # 3. 启动线程
        self.worker_thread.start()

    def handle_thread_log(self, message):
        """接收子线程发来的文本，转发给你的 bus.log"""
        self.bus.log.emit(message)

    def handle_test_finished(self):
        self.bus.log.emit("[INFO] 测试流程完全结束。")

    def closeEvent(self, e):
        self.UDP_disconnect()
        self.VideoClose()
        super().closeEvent(e)

def message_handler(msg_type: QtMsgType, context, msg: str):
    # 过滤掉包含"QWindowsWindow::setGeometry: Unable to set geometry"的警告
    if msg_type == QtMsgType.QtWarningMsg and "QWindowsWindow::setGeometry: Unable to set geometry" in msg:
        return  # 不输出该警告
    print(f"{msg_type}: {msg}", file=sys.stderr)

if __name__ == "__main__":
    qInstallMessageHandler(message_handler)
    app = QApplication(sys.argv)
    win = MyMainForm()
    win.show()
    sys.exit(app.exec())


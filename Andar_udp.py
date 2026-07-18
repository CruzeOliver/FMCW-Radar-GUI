from UI.Ui_Radar_UDP import Ui_MainWindow
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QInputDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDockWidget, QWidget
from PySide6.QtCore import QThread,QObject, Signal, Slot, Qt, QtMsgType, qInstallMessageHandler, QTimer
from PySide6.QtGui import QPixmap, QIcon, QAction
import sys, socket, threading, queue
from scipy.io import loadmat
import scipy
import numpy as np
import collections
import warnings
import time
import csv
import os
import cv2
from datetime import datetime
import motorController
from udp_handler import RobustFrameAssembler
from display_pg import PgDisplay
from calibration_manager import CalibrationManager
from radar_models import RadarFrame, RadarProcessingOptions
from radar_pipeline import RadarPipeline
from radar_worker import RadarWorker

# ---- YOLO OBB 可选依赖检测 ----
_YOLO_AVAILABLE = False
try:
    from ultralytics import YOLO
    from yolo_obb_inference import YoloInferenceWorker
    _YOLO_AVAILABLE = True
except ImportError:
    pass
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

        #需要每次重置 TestAngle，可以在这里初始化
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
    process_live_frame_requested = Signal(object, object, float, int)
    process_playback_frame_requested = Signal(object, int, int, object, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._setup_yolo_obb_ui()
        self.setWindowTitle("Radar UDP Interface ")
        self.setWindowIcon(QIcon(r'icon/Radar_UDP_icon.png'))
        #self.resize(1800, 1400)
        self.load_styles()
        self.setup_table()
        self.connectApplicationSignals()
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
        # 视频回放同步变量
        self.video_playback_cap = None   # cv2.VideoCapture（回放模式，非实时摄像头）
        self.total_radar_frames = 0      # mat 文件中雷达总帧数
        self.total_video_frames = 0      # 对应 .avi 文件中视频总帧数
        # 实时处理相关变量
        self.fft_results_1D = None
        self.fft_results_2D = None
        # 校准管理器（封装校准状态机、矩阵加载）
        self.calib_mgr = CalibrationManager(
            on_complete=self._on_calibration_complete,
            on_log=lambda msg: self.bus.log.emit(msg),
            on_show_info=lambda t, m: QMessageBox.information(self, t, m),
            on_show_warning=lambda t, m: QMessageBox.warning(self, t, m),
        )
        self.radar_pipeline = RadarPipeline(self.calib_mgr)
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
        # 实时雷达算法工作线程（MAT 回放仍在 GUI 主线程同步处理）
        self.radar_worker_busy = False
        self.live_session_id = 0
        self.playback_session_id = 0
        self._setup_radar_worker()
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

    def setup_table(self):
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

    def _update_basic_radar_plots(self, iq, chirp, sample):
        """更新 ADC、星座图、幅相图和 FFT 图。"""
        self.display.update_adc4(iq, chirp, sample)
        self.display.update_constellations(iq, remove_dc=True, max_points=3000, show_fit=True)
        self.display.update_amp_phase(iq, chirp=0, decimate=1, unwrap_phase=False)
        self.display.update_fft1d(self.fft_results_1D, sample)
        self.display.update_fft2d(self.fft_results_2D, sample, chirp)

    def _update_music_1d_plot(self, music_1d):
        """更新独立的 MUSIC 一维方位角谱。"""
        self.display.update_MUSIC1dSpectrum(
            music_1d.angles,
            music_1d.spectrum_db,
            music_1d.peak_az,
            music_1d.peak_value,
            music_1d.source_peak_el)

    def _update_music_2d_plot(self, music_2d):
        """更新独立的 MUSIC 二维方位角-俯仰角谱。"""
        self.display.update_MUSIC2dSpectrum(
            music_2d.az_grid,
            music_2d.el_grid,
            music_2d.spectrum_db,
            music_2d.peak_az,
            music_2d.peak_el)

    def _append_distance_result(self, index, R_fft, R_macleod, R_Rife,
                                R_czt_fftpeak, R_czt_macleod, diag):
        """按现有列顺序和格式向距离表格追加一行。"""
        row_data = [
            f"{index}",
            f"{R_fft:.4f}",
            f"{diag['f_fft_peak_Hz']:.4f}",
            f"{R_macleod:.4f}",
            f"{diag['f_macleod_Hz']:.4f}",
            f"{R_Rife:.4f}",
            f"{diag['f_rife_Hz']:.4f}",
            f"{R_czt_fftpeak:.4f}",
            f"{diag['f_czt_only_Hz']:.4f}",
            f"{R_czt_macleod:.4f}",
            f"{diag['f_combo_Hz']:.4f}",
        ]
        row_count = self.tableWidget_distance.rowCount()
        self.tableWidget_distance.insertRow(row_count)
        for column, value in enumerate(row_data):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            self.tableWidget_distance.setItem(row_count, column, item)
        self.tableWidget_distance.scrollToBottom()

    def _append_point_result(self, index, point_dict, display_angle):
        """按现有列顺序和格式向点云表格追加一行。"""
        row_data = [
            f"{index}",
            f"{point_dict['r']:.4f}",
            f"{display_angle:.4f}",
            f"{point_dict['x']:.4f}",
            f"{point_dict['y']:.4f}",
        ]
        row_count = self.tableWidget_point.rowCount()
        self.tableWidget_point.insertRow(row_count)
        for column, value in enumerate(row_data):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignCenter)
            self.tableWidget_point.setItem(row_count, column, item)
        self.tableWidget_point.scrollToBottom()

    def _build_processing_options(self):
        """读取一次 GUI 控件，生成当前帧使用的处理选项快照。"""
        if self.radioButton_WLS.isChecked():
            calibration_method = 'WLS'
        elif self.radioButton_FFT.isChecked():
            calibration_method = 'FFT'
        elif self.radioButton_LS.isChecked():
            calibration_method = 'LS'
        else:
            calibration_method = None

        return RadarProcessingOptions(
            use_hamming_window=self.checkBox_HammingWindow.isChecked(),
            add_simulated_noise=self.checkBox_addnoise.isChecked(),
            calibration_mode_enabled=self.checkBox_CalibrationMode.isChecked(),
            calibration_method=calibration_method,
            apply_channel_calibration=self.checkBox_channel_calibration.isChecked(),
        )

    def _setup_radar_worker(self):
        """创建只负责实时帧算法计算的 Qt 工作线程。"""
        self.radar_thread = QThread(self)
        self.radar_worker = RadarWorker(self.radar_pipeline)
        self.radar_worker.moveToThread(self.radar_thread)
        self.radar_thread.finished.connect(self.radar_worker.deleteLater)

        self.process_live_frame_requested.connect(
            self.radar_worker.process_live_frame)
        self.process_playback_frame_requested.connect(
            self.radar_worker.process_playback_frame)
        self.radar_worker.result_ready.connect(self._on_live_radar_result)
        self.radar_worker.processing_error.connect(self._on_live_processing_error)
        self.radar_worker.task_finished.connect(self._on_radar_processing_finished)
        self.radar_worker.calibration_complete.connect(
            self._on_live_calibration_complete)
        self.radar_worker.playback_result_ready.connect(
            self._on_playback_radar_result)
        self.radar_worker.playback_error.connect(
            self._on_playback_processing_error)
        self.radar_worker.playback_task_finished.connect(
            self._on_radar_processing_finished)
        self.radar_worker.playback_calibration_complete.connect(
            self._on_playback_calibration_complete)
        self.radar_worker.log_message.connect(self.bus.log.emit)
        self.radar_worker.show_info.connect(self._show_worker_info)
        self.radar_worker.show_warning.connect(self._show_worker_warning)

        self.radar_thread.start()

    @Slot(str, str)
    def _show_worker_info(self, title, message):
        QMessageBox.information(self, title, message)

    @Slot(str, str)
    def _show_worker_warning(self, title, message):
        QMessageBox.warning(self, title, message)

    def _display_radar_result(self, result, chirp, sample, update_basic_plots):
        """在主线程中更新实时与回放共用的雷达图形。"""
        self.fft_results_1D = result.fft1d
        self.fft_results_2D = result.fft2d
        self.display.update_direct_wave_phases(result.direct_wave_phases)
        self.display.update_frequency(
            result.raw_iq, result.distance_diagnostics)
        if update_basic_plots:
            self._update_basic_radar_plots(
                result.display_iq, chirp, sample)
        self._update_music_1d_plot(result.music_1d)
        self._update_music_2d_plot(result.music_2d)

    def _update_result_point_cloud(self, result, point_distance):
        """按给定距离和 MUSIC 方位角更新公共点云视图。"""
        return self.display.update_point_cloud_polar(
            "PointCloud",
            point_distance,
            90.0 - result.music_2d.peak_az,
            size=10.0,
            color='g',
            show_all=False)

    def _append_radar_result_tables(
        self, index, result, point_dict, point_display_angle):
        """将一帧处理结果追加到距离和点云表格。"""
        self._append_distance_result(
            index,
            result.distance_fft,
            result.distance_macleod,
            result.distance_rife,
            result.distance_czt_fftpeak,
            result.distance_czt_macleod,
            result.distance_diagnostics)
        self._append_point_result(
            index, point_dict, point_display_angle)

    @Slot(object, object, object, float, int)
    def _on_live_radar_result(
        self, result, radar_frame, options, submitted_at, session_id):
        """在 GUI 主线程中显示实时算法线程返回的结果。"""
        if session_id != self.live_session_id:
            return

        update_basic_plots = (
            submitted_at - self.last_display_time > self.display_interval)
        self._display_radar_result(
            result,
            radar_frame.chirp_count,
            radar_frame.sample_count,
            update_basic_plots)
        if update_basic_plots:
            self.last_display_time = submitted_at

        self.AZangelList.append(result.music_2d.peak_az)
        if options.apply_channel_calibration:
            point_distance = result.distance_czt_macleod
        else:
            point_distance = result.distance_fft
        point_dict = self._update_result_point_cloud(result, point_distance)
        self._append_radar_result_tables(
            self.current_index, result, point_dict, point_dict['theta_deg'])
        self.current_index += 1

    @Slot(int, str, int)
    def _on_live_processing_error(self, frame_id, message, session_id):
        if session_id != self.live_session_id:
            return
        self.bus.log.emit(f"⛔ 帧 {frame_id} 处理失败: {message}")

    @Slot(int)
    def _on_radar_processing_finished(self, session_id):
        """实时或回放任务结束后允许提交下一帧。"""
        self.radar_worker_busy = False

    @Slot(int)
    def _on_live_calibration_complete(self, session_id):
        if session_id == self.live_session_id:
            self._on_calibration_complete()

    @Slot(object, int, int, object, int, int)
    def _on_playback_radar_result(
        self, result, sample, chirp, options, playback_index, session_id):
        """在 GUI 主线程中显示 MAT 回放算法线程返回的结果。"""
        if session_id != self.playback_session_id:
            return

        self._display_radar_result(
            result, chirp, sample, update_basic_plots=True)

        if options.apply_channel_calibration:
            point_distance = result.distance_macleod
        else:
            point_distance = result.distance_fft
        point_dict = self._update_result_point_cloud(result, point_distance)
        self._append_radar_result_tables(
            playback_index, result, point_dict, result.music_2d.peak_az)
        self._update_playback_video_frame(playback_index)

    def _update_playback_video_frame(self, playback_index):
        """按当前雷达帧索引同步显示对应的视频帧。"""
        if self.video_playback_cap is None or self.total_video_frames <= 0:
            return
        target_video_frame = int(
            playback_index
            * (self.total_video_frames / max(1, self.total_radar_frames)))
        try:
            self.video_playback_cap.set(
                cv2.CAP_PROP_POS_FRAMES, target_video_frame)
            ret, frame = self.video_playback_cap.read()
            if ret and frame is not None:
                self.display.update_video_frame('video', frame)
        except Exception as error:
            print(f"[video playback] 跳帧失败: {error}")

    @Slot(int, str, int)
    def _on_playback_processing_error(
        self, playback_index, message, session_id):
        if session_id != self.playback_session_id:
            return
        self.bus.log.emit(
            f"⛔ 回放帧 {playback_index} 处理失败: {message}")

    @Slot(int)
    def _on_playback_calibration_complete(self, session_id):
        if session_id == self.playback_session_id:
            self._on_calibration_complete()

    def _shutdown_radar_worker(self):
        """等待当前雷达算法任务结束并关闭工作线程。"""
        if not hasattr(self, 'radar_thread') or not self.radar_thread:
            return
        if self.radar_thread.isRunning():
            self.radar_thread.quit()
            self.radar_thread.wait()

    def connectApplicationSignals(self):
        """连接仅需注册一次的应用信号。"""
        self.checkBox_CalibrationMode.stateChanged.connect(self.CalibrationModeMessage)
        self.checkBox_IsSave.stateChanged.connect(self.SaveMatChange)

    def setupInitialUIState(self):
        """重置可重复恢复的 UI 控件状态，不注册信号。"""
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

    def _on_calibration_complete(self):
        """校准完成后的清理（由 CalibrationManager 回调）。"""
        self._close_file_state()
        self.UDP_disconnect()
        self.play_timer.stop()
        self.pushButton_Play.setText("Play")

    # ==================================================================
    #  YOLO OBB 可选功能
    # ==================================================================

    def _setup_yolo_obb_ui(self):
        """初始化 YOLO OBB 复选框状态与连接（控件已在 .ui 中定义为 checkBox_yolo）。"""
        self.checkBox_yolo.setToolTip(
            "启用 YOLOv8 定向框检测角反射器（需要安装 ultralytics）")
        self.checkBox_yolo.setEnabled(_YOLO_AVAILABLE)
        if not _YOLO_AVAILABLE:
            self.checkBox_yolo.setText("YOLO (ultralytics 未安装)")
        self.checkBox_yolo.stateChanged.connect(self._on_yolo_obb_toggled)

        # 模型路径（与 predict_webcam_obb.py 保持一致）
        self._yolo_model_path = (r"best.pt")
        self._yolo_worker: YoloInferenceWorker | None = None

    def _on_yolo_obb_toggled(self, state: int):
        """复选框勾选/取消时的处理。"""
        if not state:
            # 取消勾选 → 停止 YOLO 推理线程
            self._stop_yolo_worker()
            return

        # 勾选 → 检测环境
        if not _YOLO_AVAILABLE:
            self.checkBox_yolo.blockSignals(True)
            self.checkBox_yolo.setChecked(False)
            self.checkBox_yolo.blockSignals(False)
            QMessageBox.warning(
                self, "YOLO 不可用",
                "ultralytics / torch 未安装，无法启用 YOLO OBB 检测。\n"
                "请执行: pip install ultralytics torch")
            return

        # 检查模型文件是否存在
        if not os.path.exists(self._yolo_model_path):
            self.checkBox_yolo.blockSignals(True)
            self.checkBox_yolo.setChecked(False)
            self.checkBox_yolo.blockSignals(False)
            QMessageBox.warning(
                self, "模型文件不存在",
                f"YOLO 模型文件未找到:\n{self._yolo_model_path}\n"
                f"请确保模型路径正确。")
            return

        # 如果摄像头已打开，启动推理线程
        if (hasattr(self, 'video_cap') and self.video_cap is not None
                and self.video_cap.isOpened()):
            self._start_yolo_worker()

    def _start_yolo_worker(self):
        """启动 YOLO 推理线程。"""
        if self._yolo_worker is not None:
            return
        try:
            self._yolo_worker = YoloInferenceWorker(
                self._yolo_model_path, conf_threshold=0.5, device=0)
            self._yolo_worker.frame_ready.connect(self._on_yolo_frame_ready)
            # 不连接 log 信号 → YOLO 内部日志不输出到 GUI
            self._yolo_worker.start()
        except Exception as e:
            self._yolo_worker = None

    def _stop_yolo_worker(self):
        """安全停止 YOLO 推理线程。"""
        if self._yolo_worker is not None:
            self._yolo_worker.requestInterruption()
            self._yolo_worker.quit()
            self._yolo_worker.wait(3000)
            self._yolo_worker = None

    def _on_yolo_frame_ready(self, frame: np.ndarray):
        """接收 YOLO 推理线程产出的标注帧，送 GUI 显示 + 写入视频。"""
        self.display.update_video_frame('video', frame)
        # 若正在录制，同步写入带 OBB 标注的帧
        if hasattr(self, 'video_writer') and self.video_writer is not None:
            try:
                self.video_writer.write(frame)
            except Exception:
                pass

    def _on_yolo_detection(self, det: dict):
        """接收检测结果并输出到日志。"""
        self.bus.log.emit(
            f"[YOLO] 角反检测: 中心=({det['cx']}, {det['cy']}), "
            f"置信度={det['conf']:.3f}")

    def SaveMatChange(self):
        """启用或关闭保存 .mat 文件功能"""
        if self.checkBox_IsSave.isChecked():
            self.buffer = []  # 清空缓存
            if not self.save_filename:
                self.save_filename = f"{self.generate_unique_time()}_raw_data_py.mat"
            self.bus.log.emit("✅已启用原始数据保存功能。\n"
                              f"保存文件：{self.save_filename}\n"
                              "每100帧数据自动保存一次，程序关闭时会保存剩余缓存。")
            # 若摄像头已打开，同步启动视频录制
            self._init_video_writer()
        else:
            self.save_buffer_to_mat()  # 保存剩余缓存
            self._finalize_video_writer()
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
        self.live_session_id += 1  # 使仍在计算的旧连接结果失效
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
        if self.radar_worker_busy:
            return # 同一时间只允许一个实时雷达算法任务
        try:
            # 1. 从队列中非阻塞地获取一个项目
            item = self.frame_queue.get_nowait()
        except queue.Empty:
            return
        # 2. 检查是否是错误/日志消息
        if isinstance(item, tuple) and item and item[0] == '__error__':
            self.bus.log.emit(f"{item[1]}") # 将线程中的日志转发到GUI
            return
        # 3. 将完整帧元组转换为带字段名的数据对象（队列格式保持不变）
        radar_frame = RadarFrame.from_queue_item(item)
        options = self._build_processing_options()
        # 4. --- 保存原始数据并提交算法线程 ---
        try:
            # 保存到 .mat 文件
            if self.checkBox_IsSave.isChecked():
                self.save_to_buffer(
                    radar_frame.payload,
                    radar_frame.sample_count,
                    radar_frame.chirp_count)

            self.radar_worker_busy = True
            self.process_live_frame_requested.emit(
                radar_frame, options, time.time(), self.live_session_id)
        except Exception as e:
            self.radar_worker_busy = False
            self.bus.log.emit(f"⛔ 帧 {radar_frame.frame_id} 处理失败: {e}")

# ================== video视频相关内容 ==================
    def VideoOpen(self):
        """打开电脑摄像头并在 GUI 中显示实时画面"""
        self.video_cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if self.video_cap.isOpened():
            self.bus.log.emit(f"✅ 已打开摄像头")
            # 若 YOLO 复选框已勾选，自动启动推理线程
            if (self.checkBox_yolo.isChecked()
                    and _YOLO_AVAILABLE
                    and os.path.exists(self._yolo_model_path)):
                self._start_yolo_worker()
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

        # 若保存复选框已勾选，则同步启动视频录制
        if self.checkBox_IsSave.isChecked():
            self._init_video_writer()

    def _video_grab_frame(self):
        """(主线程) 由 video_timer 定时调用，抓取一帧并送到显示组件"""
        if self.video_cap is None or not self.video_cap.isOpened():
            return
        ret, frame = self.video_cap.read()
        if ret and frame is not None:
            # YOLO OBB 推理线程正在运行 → 推送帧给它处理
            if self._yolo_worker is not None and self._yolo_worker.isRunning():
                self._yolo_worker.push_frame(frame)
            else:
                self.display.update_video_frame('video', frame)

            # 若正在录制，同步写入视频文件（写入原始帧）
            if hasattr(self, 'video_writer') and self.video_writer is not None:
                try:
                    self.video_writer.write(frame)
                except Exception as e:
                    print(f"[video] 写入视频帧失败: {e}")

    def VideoClose(self):
        """关闭摄像头并停止视频流"""
        self._stop_yolo_worker()
        self.checkBox_yolo.setChecked(False)
        self._finalize_video_writer()
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

    def _init_video_writer(self):
        """根据 self.save_filename 创建 cv2.VideoWriter"""
        # 仅当摄像头已打开时才启动录制
        if not hasattr(self, 'video_cap') or self.video_cap is None:
            return
        if not self.video_cap.isOpened():
            return
        try:
            w = int(self.video_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self.video_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self.video_cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0 or fps > 120:
                fps = 30.0
        except Exception:
            w, h = 640, 480
            fps = 30.0

        # 视频文件名与 .mat 文件同名，后缀改为 .avi
        if self.save_filename.endswith('.mat'):
            self.video_filename = self.save_filename[:-4] + '.avi'
        else:
            self.video_filename = self.save_filename + '.avi'

        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        self.video_writer = cv2.VideoWriter(self.video_filename, fourcc, fps, (w, h))
        if not self.video_writer.isOpened():
            self.bus.log.emit(f"⛔ 无法创建视频文件: {self.video_filename}")
            self.video_writer = None
            self.video_filename = None
        else:
            self.bus.log.emit(f"🔴 开始录制视频: {self.video_filename}")

    def _finalize_video_writer(self):
        """释放 VideoWriter 并记录日志"""
        if hasattr(self, 'video_writer') and self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
            if hasattr(self, 'video_filename') and self.video_filename:
                self.bus.log.emit(f"✅ 视频已保存: {self.video_filename}")
                self.video_filename = None

# ================== 校准矩阵文件读取 ==================
    def LoadCalibratioMode(self):
        """
        打开文件对话框，选择 .npz 文件并读取数据
        """
        if self.radar_worker_busy:
            QMessageBox.information(
                self, "请稍候", "当前雷达帧仍在处理中，请稍后再加载校准文件。")
            return
        file_dialog = QFileDialog(self, "Load Calibration Mode File")
        file_dialog.setNameFilter("Mode files (*.npz)")
        if file_dialog.exec():
            file_path = file_dialog.selectedFiles()[0]
            result = self.calib_mgr.load_calibration_file(file_path)
            self.bus.log.emit(f"已加载校准模型文件：{file_path}")
            file_name = os.path.basename(file_path)
            self.lineEdit_ModeName.setText(file_name)

            # 日志输出（仅在存在时打印，避免None值）
            if result['v_calib'] is not None:
                self.bus.log.emit(f"ILS校准向量：\n{result['v_calib']}")

            if result['alpha'] is not None and result['phi'] is not None:
                self.bus.log.emit(f"幅度校准矩阵：\n{result['alpha']}")
                self.bus.log.emit(f"相位校准矩阵：\n{result['phi']}")

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
        if self.radar_worker_busy:
            QMessageBox.information(
                self, "请稍候", "当前雷达帧仍在处理中，请稍后再打开文件。")
            return
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
        读取 MAT 文件中的数据，并自动挂载同目录下同名的 .avi 视频文件。
        若视频文件不存在或无法解码，仅记录日志提示，不影响 mat 数据加载。
        """
        self.playback_session_id += 1
        try:
            data = loadmat(filename) # 读取 .mat 文件
            self.frame_all_data = data

            self.bus.log.emit(f"读取文件：{filename}")

            # 获取所有包含帧数据的变量（以 "frame" 开头的变量名）
            self.frame_data_list = [key for key in data.keys() if key.startswith('frame')]
            self.frame_data_list.sort()  # 帧名包含时间戳，排序后按采集顺序回放
            self.total_radar_frames = len(self.frame_data_list)

            self.bus.log.emit(f"✅ 已挂载雷达数据: {self.total_radar_frames} 帧")
            self.progressBar_file.setMaximum(self.total_radar_frames)
            self.current_index = 0  # 初始化为第一帧

            # ---------- 视频文件自动挂载（可选） ----------
            # 释放上一次回放可能残留的视频句柄
            if self.video_playback_cap is not None:
                self.video_playback_cap.release()
                self.video_playback_cap = None
            self.total_video_frames = 0

            # 在同目录下查找同名 .avi 文件
            if filename.lower().endswith('.mat'):
                video_path = filename[:-4] + '.avi'
            else:
                video_path = filename + '.avi'

            if not os.path.isfile(video_path):
                self.bus.log.emit(f"⚠️ 未找到同名视频文件，仅加载雷达数据")
            else:
                self.video_playback_cap = cv2.VideoCapture(video_path)
                if not self.video_playback_cap.isOpened():
                    self.bus.log.emit(
                        f"⚠️ 视频文件存在但无法解码，仅加载雷达数据:\n"
                        f"  {video_path}"
                    )
                    self._release_video_playback()
                else:
                    self.total_video_frames = int(
                        self.video_playback_cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    )
                    if self.total_video_frames <= 0:
                        self.bus.log.emit(
                            f"⚠️ 视频文件总帧数为 0，仅加载雷达数据:\n"
                            f"  {video_path}"
                        )
                        self._release_video_playback()
                    else:
                        self.bus.log.emit(
                            f"✅ 已挂载视频: {os.path.basename(video_path)}"
                            f"  ({self.total_video_frames} 帧)"
                        )
            # ----------------------------------------

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
            self._release_video_playback()
            QMessageBox.warning(self, "读取失败", f"读取文件失败：{e}")

    def _release_video_playback(self):
        """释放回放模式下的视频句柄（不影响实时摄像头 self.video_cap）"""
        if self.video_playback_cap is not None:
            self.video_playback_cap.release()
            self.video_playback_cap = None
        self.total_video_frames = 0

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
                frame_struct = self.frame_all_data[
                    self.frame_data_list[self.current_index]][0, 0]
                self.show_matrix(frame_struct)

            # 启动定时器
            self.play_timer.start(self.playback_speed_ms) # 使用预设的间隔
            self.is_playing = True
            self.bus.log.emit(f"开始播放 MAT 文件，间隔：{self.playback_speed_ms} ms。")
            self.pushButton_Play.setText("Pause")
            # 可以更新按钮文本为“暂停”

    def show_matrix(self, frame_struct):
        """
        解析当前 MAT 帧并提交到雷达算法工作线程。
        """
        if self.radar_worker_busy:
            return False
        #print(f"显示当前帧数据：{frame_data}")
        #print(f"帧数据形状：{frame_data.shape}")
        #self.bus.log.emit(f"{self.frame_data_list[self.current_index]} 数据已加载")
        try:
            # 从现有 MAT 帧结构中读取原始数据与雷达配置
            frame_data = frame_struct['data']
            sample = int(frame_struct['sample'][0,0])
            chirp = int(frame_struct['chirp'][0,0])

        except Exception as e:
            self.bus.log.emit(f"⛔ 读取帧结构失败: {e}。数据可能已损坏或格式陈旧。")
            return False

        options = self._build_processing_options()
        frame_data_flat = frame_data.flatten()
        self.radar_worker_busy = True
        try:
            self.process_playback_frame_requested.emit(
                frame_data_flat,
                sample,
                chirp,
                options,
                self.current_index,
                self.playback_session_id)
            return True
        except Exception as error:
            self.radar_worker_busy = False
            self.bus.log.emit(
                f"⛔ 回放帧 {self.current_index} 提交失败: {error}")
            return False

    def ShowNextFrame(self):
        """
        显示下一帧的数据，供手动和定时器调用。
        """
        if self.radar_worker_busy:
            return
        if self.current_index < len(self.frame_data_list) - 1:
            self.current_index += 1
            self.progressBar_file.setValue(self.current_index+1)
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
        if self.radar_worker_busy:
            QMessageBox.information(
                self, "请稍候", "当前雷达帧仍在处理中，请稍后再关闭文件。")
            return
        self._close_file_state()

    def _close_file_state(self):
        """清理已加载文件；校准完成时可在任务结果返回后直接调用。"""
        self.playback_session_id += 1  # 使仍在计算的旧回放结果失效
        self.play_timer.stop()
        self.is_playing = False
        self.pushButton_Play.setText("Play")
        self._release_video_playback()
        self.frame_all_data = None
        self.frame_data_list = []  # 清空数据
        self.current_index = 0  # 重置索引
        self.total_radar_frames = 0
        self.textEdit_log.clear()  # 清空日志
        self.tableWidget_distance.clearContents()  # 清空距离表格内容
        self.tableWidget_distance.setRowCount(0)
        self.tableWidget_point.clearContents()  # 清空点云表格内容
        self.tableWidget_point.setRowCount(0)
        self.lineEdit_ModeName.clear()
        self.calib_mgr.alpha_matrix = None
        self.calib_mgr.phi_matrix = None
        self.calib_mgr.reset_state()
        self.display.reset()
        self.bus.log.emit("已关闭文件，清空数据")
        self.progressBar_file.setValue(0)
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
        self.playback_session_id += 1
        self.play_timer.stop()
        self._shutdown_radar_worker()
        self.VideoClose()
        self._release_video_playback()
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


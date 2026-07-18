"""在独立 Qt 工作线程中执行实时雷达算法。"""

from PySide6.QtCore import QObject, Signal, Slot


class RadarWorker(QObject):
    """串行处理实时雷达帧，并通过信号把结果交回 GUI 主线程。"""

    result_ready = Signal(object, object, object, float, int)
    processing_error = Signal(int, str, int)
    task_finished = Signal(int)
    calibration_complete = Signal(int)
    playback_result_ready = Signal(object, int, int, object, int, int)
    playback_error = Signal(int, str, int)
    playback_task_finished = Signal(int)
    playback_calibration_complete = Signal(int)
    log_message = Signal(str)
    show_info = Signal(str, str)
    show_warning = Signal(str, str)

    def __init__(self, processor):
        super().__init__()
        self.processor = processor
        self._calibration_completed = False
        self._info_messages = []
        self._warning_messages = []

    def _mark_calibration_complete(self):
        self._calibration_completed = True

    def _collect_info(self, title, message):
        self._info_messages.append((title, message))

    def _collect_warning(self, title, message):
        self._warning_messages.append((title, message))

    @Slot(object, object, float, int)
    def process_live_frame(self, radar_frame, options, submitted_at, session_id):
        manager = self.processor.calibration_manager
        previous_callbacks = manager.set_callbacks(
            on_complete=self._mark_calibration_complete,
            on_log=self.log_message.emit,
            on_show_info=self._collect_info,
            on_show_warning=self._collect_warning,
        )
        self._calibration_completed = False
        self._info_messages = []
        self._warning_messages = []
        try:
            result = self.processor.process_live_frame(radar_frame, options)
            self.result_ready.emit(
                result, radar_frame, options, submitted_at, session_id)
            if self._calibration_completed:
                self.calibration_complete.emit(session_id)
            for title, message in self._info_messages:
                self.show_info.emit(title, message)
            for title, message in self._warning_messages:
                self.show_warning.emit(title, message)
        except Exception as error:
            self.processing_error.emit(
                radar_frame.frame_id, str(error), session_id)
        finally:
            manager.set_callbacks(**previous_callbacks)
            self.task_finished.emit(session_id)

    @Slot(object, int, int, object, int, int)
    def process_playback_frame(self, frame_data_flat, sample_count, chirp_count,
                               options, playback_index, session_id):
        manager = self.processor.calibration_manager
        previous_callbacks = manager.set_callbacks(
            on_complete=self._mark_calibration_complete,
            on_log=self.log_message.emit,
            on_show_info=self._collect_info,
            on_show_warning=self._collect_warning,
        )
        self._calibration_completed = False
        self._info_messages = []
        self._warning_messages = []
        try:
            result = self.processor.process_playback_frame(
                frame_data_flat, sample_count, chirp_count, options)
            self.playback_result_ready.emit(
                result, sample_count, chirp_count, options,
                playback_index, session_id)
            if self._calibration_completed:
                self.playback_calibration_complete.emit(session_id)
            for title, message in self._info_messages:
                self.show_info.emit(title, message)
            for title, message in self._warning_messages:
                self.show_warning.emit(title, message)
        except Exception as error:
            self.playback_error.emit(playback_index, str(error), session_id)
        finally:
            manager.set_callbacks(**previous_callbacks)
            self.playback_task_finished.emit(session_id)

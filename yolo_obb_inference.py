"""可选的 YOLO OBB 图像推理工作线程。

本文件接收摄像头图像，在独立线程中运行定向框检测，并通过 Qt 信号把标注图像
和检测结果返回主窗口，避免推理阻塞 GUI。内部使用 Queue(maxsize=1)，始终优先
处理最新图像并丢弃过期帧；未安装 ultralytics 时不影响雷达核心程序运行。
"""
import queue
import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal


class YoloInferenceWorker(QThread):
    """独立线程：从 input_queue 取帧 → YOLO OBB 推理 → 绘制标注 → 发射信号"""

    frame_ready = Signal(np.ndarray)   # 绘制了 OBB 标注后的帧
    detection  = Signal(dict)          # 单帧检测结果：{cx, cy, conf, corners}
    log        = Signal(str)           # 日志信号

    # 时域滤波参数
    STABILITY_THRESHOLD = 3

    def __init__(self, model_path: str, input_size: tuple = (640, 640),
                 conf_threshold: float = 0.5, device=0):
        super().__init__()
        self._model_path = model_path
        self._input_size = input_size
        self._conf = conf_threshold
        self._device = device
        self._input_queue = queue.Queue(maxsize=1)
        self._stability_counter = 0
        self._model = None

    # ------------------------------------------------------------------
    #  线程入口
    # ------------------------------------------------------------------

    def run(self):
        """QThread 主循环"""
        # 1. 加载模型（在线程内加载，不阻塞 GUI）
        try:
            from ultralytics import YOLO
            self._model = YOLO(self._model_path)
            self.log.emit("[YOLO] 模型加载完成，推理线程已启动")
        except Exception as e:
            self.log.emit(f"[YOLO] 模型加载失败: {e}")
            return

        # 2. 推理循环
        while not self.isInterruptionRequested():
            try:
                frame = self._input_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                results = self._model.predict(
                    source=frame, show=False, verbose=False,
                    conf=self._conf, imgsz=self._input_size[0],
                    device=self._device,
                )

                best_detection = None
                for result in results:
                    if result.obb is not None:
                        conf_list = result.obb.conf.cpu().numpy()
                        if len(conf_list) > 0:
                            best_idx = conf_list.argmax()
                            best_detection = {
                                'corners': result.obb.xyxyxyxy.cpu().numpy()[best_idx],
                                'xywhr':   result.obb.xywhr.cpu().numpy()[best_idx],
                                'conf':    float(conf_list[best_idx]),
                            }

                # 时域滤波
                if best_detection:
                    self._stability_counter = min(
                        self._stability_counter + 1, self.STABILITY_THRESHOLD * 2)
                else:
                    self._stability_counter = max(self._stability_counter - 1, 0)

                # 稳定通过后绘制标注
                if best_detection and self._stability_counter >= self.STABILITY_THRESHOLD:
                    frame = self._draw_obb(frame, best_detection)
                    det = best_detection
                    self.detection.emit({
                        'cx':   int(det['xywhr'][0]),
                        'cy':   int(det['xywhr'][1]),
                        'conf': det['conf'],
                        'corners': det['corners'],
                    })

                self.frame_ready.emit(frame)

            except Exception as e:
                self.log.emit(f"[YOLO] 推理异常: {e}")
                # 即使推理失败也回传原始帧，保证显示不中断
                self.frame_ready.emit(frame)

    # ------------------------------------------------------------------
    #  对外接口
    # ------------------------------------------------------------------

    def push_frame(self, frame: np.ndarray):
        """主线程调用：将最新一帧塞入队列。若队列满则丢弃旧帧。"""
        while True:
            try:
                self._input_queue.put_nowait(frame)
                return
            except queue.Full:
                try:
                    self._input_queue.get_nowait()  # 丢弃旧帧
                except queue.Empty:
                    pass

    # ------------------------------------------------------------------
    #  绘制（内部）
    # ------------------------------------------------------------------

    @staticmethod
    def _draw_obb(frame: np.ndarray, det: dict) -> np.ndarray:
        """在帧上绘制 OBB 框 + 中心点 + 标签（直接操作原图）"""
        corners = det['corners']
        xywhr = det['xywhr']
        conf = det['conf']
        pts = corners.astype(int)

        # 绿色 OBB 框
        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

        # 红色中心点
        cx, cy = int(xywhr[0]), int(xywhr[1])
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
        cv2.putText(frame, f"({cx}, {cy})", (cx + 10, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        # 顶部标签
        pts_y_sorted = pts[pts[:, 1].argsort()]
        top_pt = pts_y_sorted[0]
        cv2.putText(frame, f"corner_reflector {conf:.2f}",
                    (int(top_pt[0]), int(top_pt[1]) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        return frame

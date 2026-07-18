"""雷达处理流程中使用的轻量数据模型。"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RadarFrame:
    """由完整帧队列取出后，在主线程中使用的命名数据对象。"""

    frame_id: int
    payload: bytes
    sample_count: int
    chirp_count: int
    txrx_type: int

    @classmethod
    def from_queue_item(cls, item):
        frame_id, payload, sample_count, chirp_count, txrx_type = item
        return cls(
            frame_id=frame_id,
            payload=payload,
            sample_count=sample_count,
            chirp_count=chirp_count,
            txrx_type=txrx_type,
        )


@dataclass(frozen=True)
class RadarProcessingOptions:
    """单帧处理开始时从 GUI 控件读取的不可变选项快照。"""

    use_hamming_window: bool
    add_simulated_noise: bool
    calibration_mode_enabled: bool
    calibration_method: Optional[str]
    apply_channel_calibration: bool

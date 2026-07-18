"""雷达处理流程中使用的轻量数据模型。"""

from dataclasses import dataclass
from typing import Optional
import numpy as np


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


@dataclass
class Music1DResult:
    """MUSIC 一维方位角谱结果。"""

    angles: np.ndarray
    spectrum_db: np.ndarray
    peak_az: float
    peak_value: float
    source_peak_el: float


@dataclass
class Music2DResult:
    """MUSIC 二维方位角-俯仰角谱结果。"""

    az_grid: np.ndarray
    el_grid: np.ndarray
    spectrum_db: np.ndarray
    peak_az: float
    peak_el: float


@dataclass
class RadarResult:
    """单帧雷达算法处理完成后交给主窗口显示的结果。"""

    raw_iq: np.ndarray
    display_iq: np.ndarray
    fft1d: np.ndarray
    fft2d: np.ndarray
    direct_wave_phases: np.ndarray
    distance_fft: float
    distance_macleod: float
    distance_rife: float
    distance_czt_fftpeak: float
    distance_czt_macleod: float
    distance_diagnostics: dict
    music_1d: Music1DResult
    music_2d: Music2DResult

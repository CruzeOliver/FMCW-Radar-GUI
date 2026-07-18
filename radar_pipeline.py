"""雷达单帧算法流程。

该模块只组织现有算法调用，不操作 GUI、不保存文件，也不改变算法参数。
"""

import numpy as np

from data_processing import (
    Perform1D_FFT,
    Perform2D_FFT,
    calculate_distance_from_iq,
    music_2d_spectrum_auto,
)
from radar_models import (
    Music1DResult,
    Music2DResult,
    RadarFrame,
    RadarProcessingOptions,
    RadarResult,
)
from udp_handler import reorder_frame_TDMMIMO, reorder_frame_TDMMIMO_with_noise
from WLS_Calibration import apply_channel_calibration


class RadarPipeline:
    """按实时或回放模式组织一帧雷达数据的现有处理流程。"""

    DIRECT_WAVE_BIN = 1

    def __init__(self, calibration_manager):
        self.calibration_manager = calibration_manager

    def process_live_frame(
        self,
        frame: RadarFrame,
        options: RadarProcessingOptions,
    ) -> RadarResult:
        window = np.hamming(frame.sample_count) if options.use_hamming_window else None
        iq = reorder_frame_TDMMIMO(
            frame.payload,
            frame.chirp_count,
            frame.sample_count,
            frame.txrx_type,
            window=window,
        )

        fft1d = Perform1D_FFT(iq)
        fft2d = Perform2D_FFT(fft1d)
        direct_wave_phases = self._calculate_direct_wave_phases(fft1d)
        distances = calculate_distance_from_iq(
            iq, r_bins=0.5, M=16, use_window=None, coherent=True)

        display_iq, fft1d, fft2d = self._apply_calibration(
            iq, fft1d, fft2d, options)
        music_2d = self._calculate_live_music_2d(fft1d)
        music_1d = self._calculate_music_1d(music_2d)

        return self._build_result(
            iq, display_iq, fft1d, fft2d, direct_wave_phases,
            distances, music_1d, music_2d)

    def process_playback_frame(
        self,
        frame_data_flat,
        sample_count: int,
        chirp_count: int,
        options: RadarProcessingOptions,
    ) -> RadarResult:
        window = np.hamming(sample_count) if options.use_hamming_window else None
        if options.add_simulated_noise:
            iq = reorder_frame_TDMMIMO_with_noise(
                frame_data_flat,
                chirp_count,
                sample_count,
                4,
                window=window,
                sim_noise_ch=3,
                sim_noise_level=5048899,
            )
        else:
            iq = reorder_frame_TDMMIMO(
                frame_data_flat,
                chirp_count,
                sample_count,
                4,
                window=window,
            )

        distances = calculate_distance_from_iq(
            iq, r_bins=1, M=64, use_window=None, coherent=True)
        fft1d = Perform1D_FFT(iq)
        fft2d = Perform2D_FFT(fft1d)

        display_iq, fft1d, fft2d = self._apply_calibration(
            iq, fft1d, fft2d, options)
        direct_wave_phases = self._calculate_direct_wave_phases(fft1d)
        music_2d = self._calculate_playback_music_2d(fft2d)
        music_1d = self._calculate_music_1d(music_2d)

        return self._build_result(
            iq, display_iq, fft1d, fft2d, direct_wave_phases,
            distances, music_1d, music_2d)

    def _apply_calibration(self, iq, fft1d, fft2d, options):
        """执行现有校准采集与通道补偿流程。"""
        if options.calibration_mode_enabled and options.calibration_method:
            peak_idx = np.unravel_index(
                np.argmax(np.abs(fft2d[0])), fft2d[0].shape)
            zij_vector = fft2d[:, peak_idx[0], peak_idx[1]]
            self.calibration_manager.calibrate(
                options.calibration_method,
                zij_vector=zij_vector,
                fft_results_2D=fft2d,
                peak_idx=peak_idx,
                iq_data=iq,
            )

        display_iq = iq
        if (
            options.apply_channel_calibration
            and self.calibration_manager.alpha_matrix is not None
            and self.calibration_manager.phi_matrix is not None
        ):
            display_iq = apply_channel_calibration(
                iq,
                self.calibration_manager.alpha_matrix,
                self.calibration_manager.phi_matrix,
            )
            fft1d = Perform1D_FFT(display_iq)
            fft2d = Perform2D_FFT(fft1d)

        return display_iq, fft1d, fft2d

    def _calculate_direct_wave_phases(self, fft1d):
        """从指定距离单元提取四通道直达波相位。"""
        if fft1d.ndim != 3 or fft1d.shape[0] != 4:
            raise ValueError("fft1d must be shape (4, n_chirp, n_sample)")
        direct_wave = np.mean(
            fft1d[:, :, self.DIRECT_WAVE_BIN], axis=1)
        return np.angle(direct_wave)

    @staticmethod
    def _calculate_live_music_2d(fft1d):
        """实时模式二维 MUSIC 入口，保持当前使用 1D FFT 的行为。"""
        az_grid, el_grid, spectrum_2d_db, peak_az, peak_el = (
            music_2d_spectrum_auto(fft1d))
        return Music2DResult(
            az_grid=az_grid,
            el_grid=el_grid,
            spectrum_db=spectrum_2d_db,
            peak_az=peak_az,
            peak_el=peak_el,
        )

    @staticmethod
    def _calculate_playback_music_2d(fft2d):
        """回放模式二维 MUSIC 入口，保持当前使用 2D FFT 的行为。"""
        az_grid, el_grid, spectrum_2d_db, peak_az, peak_el = (
            music_2d_spectrum_auto(fft2d))
        return Music2DResult(
            az_grid=az_grid,
            el_grid=el_grid,
            spectrum_db=spectrum_2d_db,
            peak_az=peak_az,
            peak_el=peak_el,
        )

    @staticmethod
    def _calculate_music_1d(music_2d):
        """从二维结果提取当前定义的一维方位角谱，作为独立功能输出。"""
        el_angles = music_2d.el_grid[:, 0]
        peak_el_index = np.argmin(np.abs(el_angles - music_2d.peak_el))
        azimuth_angles = music_2d.az_grid[0, :]
        azimuth_spectrum_1d = music_2d.spectrum_db[peak_el_index, :]
        peak_az_index = np.argmin(
            np.abs(azimuth_angles - music_2d.peak_az))

        return Music1DResult(
            angles=azimuth_angles,
            spectrum_db=azimuth_spectrum_1d,
            peak_az=music_2d.peak_az,
            peak_value=azimuth_spectrum_1d[peak_az_index],
            source_peak_el=music_2d.peak_el,
        )

    @staticmethod
    def _build_result(
        iq,
        display_iq,
        fft1d,
        fft2d,
        direct_wave_phases,
        distances,
        music_1d,
        music_2d,
    ):
        R_fft, R_macleod, R_Rife, R_czt_fftpeak, R_czt_macleod, diag = distances
        return RadarResult(
            raw_iq=iq,
            display_iq=display_iq,
            fft1d=fft1d,
            fft2d=fft2d,
            direct_wave_phases=direct_wave_phases,
            distance_fft=R_fft,
            distance_macleod=R_macleod,
            distance_rife=R_Rife,
            distance_czt_fftpeak=R_czt_fftpeak,
            distance_czt_macleod=R_czt_macleod,
            distance_diagnostics=diag,
            music_1d=music_1d,
            music_2d=music_2d,
        )

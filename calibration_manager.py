"""雷达通道校准流程管理器。

本文件管理 LS、WLS 和 FFT 三种校准方式的状态，包括预热、有效帧收集、
校准矩阵生成、文件加载与完成通知。输入来自 RadarPipeline 提取的 IQ 或频域
特征，输出为幅度矩阵和相位矩阵。具体数学计算保留在 WLS_Calibration.py；
本模块不依赖 Qt，而是通过回调与 RadarWorker 和主窗口通信。
"""
import numpy as np
from datetime import datetime
from WLS_Calibration import (
    amplitude_calibration,
    phase_calibration,
    amplitude_calibration_wals,
    phase_calibration_wls,
    estimate_noise_power_from_frame,
    calculate_weights,
)


class CalibrationManager:
    """校准状态机：预热 → 数据收集 → 矩阵计算 → 保存 → 清理。

    Parameters
    ----------
    on_complete : callable
        校准完成后调用，用于 CloseFile / UDP_disconnect / 停止定时器 / 重置按钮等。
    on_log : callable(str)
        日志输出回调。
    on_show_info : callable(title, message)
        弹出信息对话框。
    on_show_warning : callable(title, message)
        弹出警告对话框。
    """

    def __init__(self, on_complete=None, on_log=None,
                 on_show_info=None, on_show_warning=None):
        # ---- 回调 ----
        self._on_complete = on_complete or (lambda: None)
        self._on_log = on_log or (lambda msg: None)
        self._on_show_info = on_show_info or (lambda t, m: None)
        self._on_show_warning = on_show_warning or (lambda t, m: None)

        # ---- 校准状态变量 ----
        self.calibration_list_FFTpeak: list = []
        self.calibration_list_LS: list = []
        self.calibration_list_WLS: list = []
        self.warmup_count: int = 0
        self.warmup_avg: np.ndarray | None = None

        # ---- 已加载的校准矩阵 ----
        self.alpha_matrix: np.ndarray | None = None
        self.phi_matrix: np.ndarray | None = None
        self.v_calibration: np.ndarray | None = None

    def set_callbacks(self, on_complete=None, on_log=None,
                      on_show_info=None, on_show_warning=None):
        """更新通知回调并返回旧回调，不改变校准状态或计算流程。"""
        previous = {
            'on_complete': self._on_complete,
            'on_log': self._on_log,
            'on_show_info': self._on_show_info,
            'on_show_warning': self._on_show_warning,
        }
        if on_complete is not None:
            self._on_complete = on_complete
        if on_log is not None:
            self._on_log = on_log
        if on_show_info is not None:
            self._on_show_info = on_show_info
        if on_show_warning is not None:
            self._on_show_warning = on_show_warning
        return previous

    # ==================================================================
    #  统一入口
    # ==================================================================

    def calibrate(self, mode: str,
                  zij_vector: np.ndarray | None = None,
                  fft_results_2D: np.ndarray | None = None,
                  peak_idx: tuple | None = None,
                  iq_data: np.ndarray | None = None):
        """根据模式分发到对应的校准状态机。

        Parameters
        ----------
        mode : 'LS' | 'WLS' | 'FFT'
        zij_vector : (4,) 复数向量，LS/WLS 模式需要
        fft_results_2D : (4, N_Doppler, N_Range)，WLS 模式需要
        peak_idx : (row, col)，WLS 模式需要
        iq_data : (4, N_chirp, N_samples)，FFT 模式需要
        """
        if mode == 'WLS':
            self._calibrate_wls(zij_vector, fft_results_2D, peak_idx)
        elif mode == 'FFT':
            self._calibrate_fft(iq_data)
        elif mode == 'LS':
            self._calibrate_ls(zij_vector)

    # ==================================================================
    #  加载校准文件
    # ==================================================================

    def load_calibration_file(self, file_path: str) -> dict:
        """从 .npz 文件加载校准矩阵。

        Returns
        -------
        dict : 包含 'v_calib', 'alpha', 'phi' 键，值可能为 None。
        """
        cal_data = np.load(file_path)
        self.v_calibration = cal_data.get('v_calib', None)
        self.alpha_matrix = cal_data.get('alpha', None)
        self.phi_matrix = cal_data.get('phi', None)
        return {
            'v_calib': self.v_calibration,
            'alpha': self.alpha_matrix,
            'phi': self.phi_matrix,
        }

    # ==================================================================
    #  状态管理
    # ==================================================================

    def reset_state(self):
        """重置所有校准状态（预热计数、缓存列表）。"""
        self.calibration_list_FFTpeak.clear()
        self.calibration_list_LS.clear()
        self.calibration_list_WLS.clear()
        self.warmup_count = 0
        self.warmup_avg = None

    # ==================================================================
    #  LS 最小二乘校准
    # ==================================================================

    def _calibrate_ls(self, zij_vector: np.ndarray):
        """基于最小二乘法进行幅相校准流程。"""
        if zij_vector.shape != (4,):
            raise ValueError("zij_vector 必须是包含4个元素的向量。")

        # --- 阶段一：雷达预热与基准计算 ---
        if self.warmup_count < 20:
            self.calibration_list_LS.append(zij_vector)
            self.warmup_count += 1
            if self.warmup_count == 20:
                self._on_log("预热完成，将开始收集数据。")
                warmup_vectors = np.array(self.calibration_list_LS)
                self.warmup_avg = np.mean(np.abs(warmup_vectors), axis=0)
                self.calibration_list_LS.clear()
            return

        # --- 阶段二：正式校准与数据过滤 ---
        if len(self.calibration_list_LS) < 50:
            current_amplitudes = np.abs(zij_vector)
            is_valid = np.all(current_amplitudes <= 2 * self.warmup_avg)
            if is_valid:
                self.calibration_list_LS.append(zij_vector)
        current_count = len(self.calibration_list_LS)

        if current_count >= 50:
            self._on_log("已收集 50 帧，将立即执行校准...")
            zij_vectors_to_calibrate = np.array(self.calibration_list_LS)
            zij_vector_avg = np.mean(zij_vectors_to_calibrate, axis=0)

            alpha_matrix = amplitude_calibration(zij_vector_avg)
            phi_matrix = phase_calibration(zij_vector_avg)

            ts = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
            filename = f"{ts} calibration_matrix_LS"
            np.savez(filename, alpha=0.9 * alpha_matrix, phi=0.9 * phi_matrix)

            self.calibration_list_LS.clear()
            self.warmup_count = 0
            self.warmup_avg = None

            self._on_complete()
            self._on_show_info("校准完成", f"校准矩阵保存到：\n{filename}。")

    # ==================================================================
    #  WLS 加权最小二乘校准
    # ==================================================================

    def _calibrate_wls(self,
                       zij_vector: np.ndarray,
                       z_ij_spectrum_frame: np.ndarray,
                       peak_idx: tuple):
        """基于加权最小二乘法 (WLS) 进行幅相校准流程。"""
        if zij_vector.shape != (4,):
            raise ValueError("zij_vector 必须是包含4个元素的向量。")
        if z_ij_spectrum_frame.shape[0] != 4:
            raise ValueError("z_ij_spectrum_frame 的第一维必须为 4。")
        n_ant = 4

        # --- 阶段一：雷达预热 ---
        if self.warmup_count < 20:
            zij_vector = np.asarray(zij_vector).reshape(4,)
            z_ij_spectrum_frame = np.asarray(z_ij_spectrum_frame)
            self.calibration_list_WLS.append((zij_vector, z_ij_spectrum_frame))
            self.warmup_count += 1

            if self.warmup_count == 20:
                warmup_vectors = np.array([data[0] for data in self.calibration_list_WLS])
                self.warmup_avg = np.mean(np.abs(warmup_vectors), axis=0)
                self.calibration_list_WLS.clear()
                self._on_log("预热完成，将开始收集数据。")
            return

        # --- 阶段二：正式校准与数据过滤 ---
        if len(self.calibration_list_WLS) < 50:
            current_amplitudes = np.abs(zij_vector)
            is_valid = np.all(current_amplitudes <= 2 * self.warmup_avg)
            if is_valid:
                self.calibration_list_WLS.append(
                    (np.asarray(zij_vector).reshape(4,),
                     np.asarray(z_ij_spectrum_frame)))
        current_count = len(self.calibration_list_WLS)

        # --- 阶段三：WLS 计算 ---
        if current_count >= 50:
            self._on_log("已收集 50 帧，将立即执行校准...")
            valid_zij_list = []
            valid_spectrum_list = []
            bad_indices = []

            for idx, item in enumerate(self.calibration_list_WLS):
                if not (isinstance(item, (tuple, list)) and len(item) >= 2):
                    bad_indices.append((idx, "not tuple/list or len<2"))
                    continue
                vec, spec = item
                try:
                    vec = np.asarray(vec).reshape(4,)
                except Exception:
                    bad_indices.append((idx, f"vec shape invalid: {np.asarray(vec).shape}"))
                    continue
                try:
                    spec = np.asarray(spec)
                except Exception:
                    bad_indices.append((idx, "spectrum convert failed"))
                    continue
                if spec.ndim < 2 or spec.shape[0] != 4:
                    bad_indices.append((idx, f"spectrum shape={spec.shape}"))
                    continue
                valid_zij_list.append(vec)
                valid_spectrum_list.append(spec)

            if bad_indices:
                self._on_log(
                    f"[WLS] 跳过 {len(bad_indices)} 个非法帧，示例：{bad_indices[:5]}")

            if len(valid_zij_list) == 0:
                self._on_show_warning("校准失败", "无有效帧可用于校准（所有帧不合格）。")
                return

            zij_vectors_to_calibrate = np.stack(valid_zij_list, axis=0)
            spectrums_to_calibrate = np.stack(valid_spectrum_list, axis=0)
            current_count = zij_vectors_to_calibrate.shape[0]

            zij_vector_avg = np.mean(zij_vectors_to_calibrate, axis=0)
            noise_power_matrix_frames = np.zeros((current_count, n_ant))
            for frame_idx in range(current_count):
                for channel_idx in range(n_ant):
                    noise_power = estimate_noise_power_from_frame(
                        spectrums_to_calibrate[frame_idx, channel_idx], peak_idx)
                    noise_power_matrix_frames[frame_idx, channel_idx] = noise_power
            avg_noise_power_per_channel = np.mean(noise_power_matrix_frames, axis=0)
            weights = calculate_weights(zij_vector_avg, avg_noise_power_per_channel,
                                        n_obs=current_count)
            alpha_matrix = amplitude_calibration_wals(zij_vector_avg, weights)
            phi_matrix = phase_calibration_wls(zij_vector_avg, weights)

            ts = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
            filename = f"{ts} calibration_matrix_WLS"
            np.savez(filename, alpha=alpha_matrix, phi=phi_matrix)

            self.calibration_list_WLS.clear()
            self.warmup_count = 0
            self.warmup_avg = None

            self._on_complete()
            self._on_show_info("WLS 校准完成", f"WLS 校准矩阵保存到：\n{filename}。")

    # ==================================================================
    #  FFT 峰值校准
    # ==================================================================

    def _calibrate_fft(self, iq_virtual_data: np.ndarray):
        """使用“忽略 N、平均 M”的 FFT 峰值校准流程。

        接收 (4, N_obs, N_samples) 的 IQ 数据，预热 20 帧后收集 50 帧进行校准。
        """
        calib_peak_bin = None  # 用于锁定峰值 Bin 的变量

        try:
            if iq_virtual_data.ndim != 3 or iq_virtual_data.shape[0] != 4:
                self._on_log(
                    f"错误: 输入IQ数据维度必须是 (4, N_obs, N_samples), "
                    f"实际为 {iq_virtual_data.shape}")
                return
            K_TX, L_RX = 2, 2
            M_virtual, N_obs, N_samples = iq_virtual_data.shape

            # (A) 执行 FFT
            range_fft_results = np.fft.fft(iq_virtual_data, axis=2)
            # (B) 自动查找峰值 Bin
            if calib_peak_bin is None:
                fft_magnitude = np.abs(range_fft_results)
                avg_range_profile = np.mean(fft_magnitude, axis=(0, 1))
                avg_range_profile[0] = 0  # 忽略直流
                calib_peak_bin = int(np.argmax(avg_range_profile))
            # (C) 提取复数增益向量
            peak_complex_values = range_fft_results[:, :, calib_peak_bin]
            zij_vector = np.mean(peak_complex_values, axis=1)  # (4,) 向量
        except Exception as e:
            self._on_log(f"错误: 处理IQ数据失败: {e}")
            return

        # --- 阶段 0 完毕 ---
        self.warmup_count += 1

        # --- 阶段一：雷达预热（忽略前 20 帧） ---
        if self.warmup_count <= 20:
            if self.warmup_count == 20:
                self._on_log("预热完成，将开始收集数据。")
            return

        # --- 阶段二：收集 50 帧 ---
        if len(self.calibration_list_FFTpeak) < 50:
            self.calibration_list_FFTpeak.append(zij_vector)
            if len(self.calibration_list_FFTpeak) < 50:
                return
            else:
                self._on_log("已收集 50 帧，将立即执行校准...")

        # --- 阶段三：执行校准 ---
        zij_vectors_to_calibrate = np.array(self.calibration_list_FFTpeak)
        zij_vector_avg = np.mean(zij_vectors_to_calibrate, axis=0)

        try:
            ref_val = zij_vector_avg[0]  # TX0-RX0 作为参考通道
            alpha = np.abs(ref_val) / np.abs(zij_vector_avg)
            phi = np.angle(ref_val) - np.angle(zij_vector_avg)
            phi = -phi
            phi = (phi + np.pi) % (2 * np.pi) - np.pi
            alpha_matrix = alpha.reshape((K_TX, L_RX))
            phi_matrix = phi.reshape((K_TX, L_RX))
            self._on_log("校准矩阵计算成功。")
        except Exception as e:
            self._on_log(f"错误: 无法重塑 (4,) 向量或计算矩阵: {e}")
            self.reset_state()
            self._on_show_warning("校准失败", f"校准计算失败: {e}")
            return

        ts = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        filename = f"{ts} calibration_matrix_FFTpeak"
        np.savez(filename, alpha=1.2 * alpha_matrix, phi=1.2 * phi_matrix)
        self._on_log(f"校准矩阵已保存到: {filename}")

        self.calibration_list_FFTpeak.clear()
        self.warmup_count = 0
        self.warmup_avg = None

        self._on_complete()
        self._on_show_info("校准完成", f"校准矩阵保存到：\n{filename}。")

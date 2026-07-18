"""雷达信号处理与距离、角度估计算法集合。

本文件保存项目的核心数学算法，包括一维/二维 FFT、FFT/CZT/Macleod/Rife
测距、补偿处理和 MUSIC 空间谱估计等。RadarPipeline 按实时或回放流程调用
这些函数；本模块不负责 UDP 通信、线程调度、文件存储或 GUI 绘图。
"""

import numpy as np
from datetime import datetime
from scipy.signal import czt, get_window

""""
==================================================
AOTM610LPJDH41 毫米波雷达天线布局与 TDM-MIMO 虚拟阵列说明
==================================================

一、硬件天线物理排布（根据实物）

发射天线（TX）：2 个，较大贴片，水平排列（左右）
  TX0：左侧
  TX1：右侧
  用于提供 azimuth（水平角）分辨率

接收天线（RX）：2 个，较小贴片，垂直排列（上下）
  RX0：下侧
  RX1：上侧
  用于提供 elevation（俯仰角）分辨率

坐标系定义：
  ↑ y（elevation）
  |
      ● RX1  (提供 y 轴位移)
      |
●     ● RX0  (y=0)
TX0   TX1    (y=0)
      x（azimuth）

结论：
  TX 水平 → azimuth 方向（x 轴）
  RX 垂直 → elevation 方向（y 轴）

二、TDM-MIMO 工作模式

采用时分复用（TDM）方式交替发射：
  第一个 chirp：仅 TX0 发射，RX0 和 RX1 同时接收
  第二个 chirp：仅 TX1 发射，RX0 和 RX1 同时接收

每帧包含多个 chirp 对（TX0 + TX1 为一组），形成 4 个虚拟通道：

  虚拟通道 | 物理路径       | 说明
  ---------|----------------|----------------------------
  v0       | TX0 → RX0      | 基准通道
  v1       | TX0 → RX1      | 同 TX0，不同 RX → elevation
  v2       | TX1 → RX0      | 同 RX0，不同 TX → azimuth（需补偿）
  v3       | TX1 → RX1      | 同 RX1，不同 TX → azimuth（需补偿）

- 注意：TX0 与 TX1 发射存在时间延迟（通常为 CHIRP_PERIOD ≈ 108 μs），因此在计算 azimuth 相位差时必须进行 Doppler 相位补偿。

三、虚拟阵列结构（Virtual Array）

等效虚拟天线位置（以波长 λ 为单位，d = λ/2）：

  虚拟通道 | 等效坐标 (x, y) | 方向贡献
  ---------|------------------|-------------------
  v0       | (0, 0)           | 原点
  v1       | (0, 1)           | y 方向 → elevation
  v2       | (1, 0)           | x 方向 → azimuth
  v3       | (1, 1)           | 对角

角度估计逻辑：

1. Azimuth（水平角）：
   - 来源：TX 水平间距（x 方向）
   - 使用通道对：(v2, v0) 和 (v3, v1)
   - 必须进行 Doppler 相位补偿（因 TDM 时序）
   - 公式示例：
        dphi_az = angle( mean( [v2_comp * conj(v0), v3_comp * conj(v1)] ) )

2. Elevation（俯仰角）：
   - 来源：RX 垂直间距（y 方向）
   - 使用通道对：(v1, v0) 和 (v3, v2)
   - 无需 Doppler 补偿（RX 同时接收）
   - 公式示例：
        dphi_el = angle( mean( [v1 * conj(v0), v3 * conj(v2)] ) )


==================================================
说明结束
==================================================

"""""

#============ 雷达参数配置 =================

C = 3e8  # 光速，单位 m/s
CenterFrequency = 77  # 中心频率，单位 GHz 77
wavelength = C / (CenterFrequency * 1e9)  # 波长，单位 m
ADC_SAMPLE_RATE = 7.14  # 采样率，单位 MHz
FM = 3000  # 调频带宽，单位 MHz
CHIRP_T0 = 94  # 微秒94
CHIRP_T1 = 14  # 微秒
CHIRP_T2 = 0   # 微秒
CHIRP_PERIOD = CHIRP_T0 + CHIRP_T1 + CHIRP_T2  # Chirp周期，单位微秒

virtual_positions_m = np.array([
    [0.5 * wavelength, 0.0],              # v0: TX0→RX0
    [0.5 * wavelength, 0.5 * wavelength], # v2: TX1→RX0  (交换顺序)
    [1.0 * wavelength, 0.0],              # v1: TX0→RX1
    [1.0 * wavelength, 0.5 * wavelength]  # v3: TX1→RX1
])

# 我们只关心方位角，所以取 x 坐标（水平方向），归一化为波长
virtual_x_normalized = virtual_positions_m[:, 0] / wavelength  # [0.5, 1.0, 0.5, 1.0]

""""
TDM-MIMO 模式下的天线数据重组说明
    数据重组前：
        chirp 0 (TX0 发射):
        RX0: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]
        RX1: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]

        chirp 1 (TX1 发射):
        RX0: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]
        RX1: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]

        chirp 2 (TX0 发射):
        RX0: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]
        RX1: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]

        chirp 3 (TX1 发射):
        RX0: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]
        RX1: [I₀, Q₀, I₁, Q₁, ..., I_{N-1}, Q_{N-1}]

        ...

        chirp (total_chirp - 1):
        （依 TX 交替规则）

    数据重组后：
        [虚拟天线 0][chirp 0][样点 0]
        [虚拟天线 0][chirp 0][样点 1]
        ...
        [虚拟天线 0][chirp 0][样点 N-1]
        [虚拟天线 0][chirp 1][样点 0]
        ...
        [虚拟天线 0][chirp M-1][样点 N-1]

        [虚拟天线 1][chirp 0][样点 0]
        ...
        [虚拟天线 1][chirp M-1][样点 N-1]

        [虚拟天线 2][chirp 0][样点 0]
        ...
        [虚拟天线 2][chirp M-1][样点 N-1]

        [虚拟天线 3][chirp 0][样点 0]
        ...
        [虚拟天线 3][chirp M-1][样点 N-1]

    天线映射：
        虚拟通道 0 → TX0 → RX0
        虚拟通道 1 → TX0 → RX1
        虚拟通道 2 → TX1 → RX0
        虚拟通道 3 → TX1 → RX1

    注意：
    原始数据按 IQ 排列（即 I 在前，Q 在后）
    但是文档标注为 QI，但经实测和角度稳定性验证为 IQ

    补充说明：
    用codeblock存储的MAT文件存储的时候是列优先，
    所以在用MATLAB打开mat文件校验数据的时候，其数据格式应该如下：(2048*32) 采样点 256 chirp 32

    用Python存储的mat文件是行优先，
    所以在用Python打开mat文件校验数据的时候，其数据格式应该如下：(32*2048) 采样点 256 chirp 32

"""""
#============ 雷达数据处理 =================

# def reorder_frame_TDMMIMO(frame_bytes: bytes, total_chirp: int, sample: int, window: np.ndarray | None = None):
#     """
#     重排雷达原始帧为虚拟通道格式 (4, total_chirp//2, sample)

#     要求: total_chirp 为偶数（TDM-MIMO）
#     """
#     if total_chirp % 2 != 0:
#         raise ValueError("total_chirp 必须为偶数（TDM-MIMO 模式）")

#     n_rx = 2
#     expected_bytes = total_chirp * n_rx * sample * 4  # 4 = I(2B) + Q(2B)

#     # if len(frame_bytes) != expected_bytes:
#     #     raise ValueError(f"帧字节数错误: 期望 {expected_bytes}, 实际 {len(frame_bytes)}")

#     # 解析为 int16
#     arr_i16 = np.frombuffer(frame_bytes, dtype=np.int16)

#     # 重塑为 (chirp, rx, sample, IQ)
#     arr_iq = arr_i16.reshape(total_chirp, n_rx, sample, 2)
#     #arr_iq = arr_i16.reshape(total_chirp, sample, n_rx, 2)
#     iq = arr_iq[..., 0] + 1j * arr_iq[..., 1]  # (total_chirp, 2, sample)

#     # 构建 4 个虚拟通道
#     v0 = iq[0::2, 0, :]  # TX0 → RX0
#     v1 = iq[0::2, 1, :]  # TX0 → RX1
#     v2 = iq[1::2, 0, :]  # TX1 → RX0
#     v3 = iq[1::2, 1, :]  # TX1 → RX1

#     iq_virtual = np.stack([v0, v1, v2, v3], axis=0)  # (4, total_chirp//2, sample)

#     if window is not None:
#         if len(window) != sample:
#             raise ValueError("window 长度必须等于 sample")
#         iq_virtual = iq_virtual * window[np.newaxis, np.newaxis, :]

#     return iq_virtual


def Perform1D_FFT(iq):
    """
    对每个 Chirp 数据执行 1D FFT，保留所有 Chirp。

    输入：
        iq: np.ndarray, 形状为 (n_ant, n_chirp, n_points)

    输出：
        fft1_results: np.ndarray, 形状为 (n_ant, n_chirp, n_points)
    """
    n_ant, n_chirp, n_points = iq.shape
    fft_results = np.zeros((n_ant, n_chirp, n_points), dtype=complex)

    for ant in range(n_ant):
        # 对每个天线上的所有 Chirp 进行 1D FFT
        # axis=-1 表示对最后一个轴（样本点数）做 FFT
        fft_results[ant, :, :] = np.fft.fft(iq[ant, :, :], axis=-1)

    return fft_results

def Perform2D_FFT(fft_results):
    """
    对 1D FFT 结果执行 2D FFT，以获取多普勒信息。

    输入：
        fft1_results: np.ndarray, 形状为 (n_ant, n_chirp, n_points)

    输出：
        fft2d_results: np.ndarray, 形状为 (n_ant, n_chirp, n_points)
    """
    # 对 Chirp 维度（第二个轴）执行 FFT
    # 这将生成一个形状为 (n_ant, n_chirp, n_points) 的数组
    fft2d_intermediate = np.fft.fft(fft_results, axis=1)

    # 对 FFT 结果进行移位，使多普勒零点位于中心
    # 这一步是可选的，但有助于可视化
    fft2d_results = np.fft.fftshift(fft2d_intermediate, axes=1)

    return fft2d_results


def calculate_distance_from_fft2(fft_result_in, n_chirp, n_points):
    """
    使用多种方法从ADC数据中计算距离。
    处理逻辑为：选择第0个虚拟天线的所有Chirp数据，进行平均后做FFT，传入的数据是fft_result_in。
    然后使用Macleod和Chirp-Z插值进行峰值细化。
    """
    #传入的fft_result_in是已经计算好的FFT结果
    #fft_result_in是（ant, chirp, n_points）形状的数组，现在对0号虚拟天线进行处理，求平均
    fft_result = np.mean(fft_result_in[:, :], axis=0)

    # 步骤 3: 计算幅度谱并找到FFT峰值
    fft_sum = np.abs(fft_result)
    valid_points = n_points // 2
    max_index = np.argmax(fft_sum[:valid_points])
    max_index = int(max_index)
    # 计算频率偏移
    f_fft_peak = max_index * ADC_SAMPLE_RATE * 1e6 / n_points

    # 步骤 4: Macleod 插值
    X_km1 = fft_result[max(0, max_index - 1)]
    X_k0 = fft_result[max_index]
    X_kp1 = fft_result[min(valid_points - 1, max_index + 1)]

    mag2_km1 = np.abs(X_km1)**2
    mag2_k0 = np.abs(X_k0)**2
    mag2_kp1 = np.abs(X_kp1)**2

    denom = mag2_km1 - 2 * mag2_k0 + mag2_kp1
    delta = 0.5 * (mag2_km1 - mag2_kp1) / denom if denom != 0 else 0.0
    f_macleod = (max_index + delta) * ADC_SAMPLE_RATE * 1e6 / n_points

    # 步骤 5: 基于Macleod峰值进行CZT插值
    M = 32  # CZT 点数
    B = ADC_SAMPLE_RATE * 1e6 / n_points  # 分析频宽 ≈ 1 bin
    f_start = f_macleod - B / 2
    f_step = B / M

    # 使用 NumPy 的 CZT 函数可能更快，但这里保留了你原有的循环实现
    X_czt = np.zeros(M, dtype=complex)
    for m in range(M):
        sum_czt = 0 + 0j
        for n in range(n_points):
            phase = -2 * np.pi * f_step * m * n / (ADC_SAMPLE_RATE * 1e6)
            phase0 = 2 * np.pi * f_start * n / (ADC_SAMPLE_RATE * 1e6)
            sum_czt += fft_result[n] * np.exp(1j * (phase0 + phase))
        X_czt[m] = sum_czt

    # 步骤 6: 在CZT结果上再次进行Macleod插值
    peak_idx = np.argmax(np.abs(X_czt)) # 找到CZT结果的峰值

    # 增加边界检查，防止索引越界
    if peak_idx > 0 and peak_idx < M - 1:
        mag2_czt_km1 = np.abs(X_czt[peak_idx - 1])**2
        mag2_czt_k0 = np.abs(X_czt[peak_idx])**2
        mag2_czt_kp1 = np.abs(X_czt[peak_idx + 1])**2
        denom2 = mag2_czt_km1 - 2 * mag2_czt_k0 + mag2_czt_kp1
        delta_czt = 0.5 * (mag2_czt_km1 - mag2_czt_kp1) / denom2 if denom2 != 0 else 0.0
        f_czt_macleod = f_start + (peak_idx + delta_czt) * f_step
    else:
        # 如果峰值在边界，不进行Macleod插值
        f_czt_macleod = f_start + peak_idx * f_step

    # 步骤 7: 基于FFT峰值进行CZT插值
    f_start2 = f_fft_peak - B / 2
    X_czt_fftpeak = np.zeros(M, dtype=complex)
    for m in range(M):
        sum_czt_fftpeak = 0 + 0j
        for n in range(n_points):
            phase = -2 * np.pi * f_step * m * n / ADC_SAMPLE_RATE / 1e6
            phase0 = 2 * np.pi * f_start2 * n / ADC_SAMPLE_RATE / 1e6
            sum_czt_fftpeak += fft_result[n] * np.exp(1j * (phase0 + phase))
        X_czt_fftpeak[m] = sum_czt_fftpeak

    peak_idx2 = np.argmax(np.abs(X_czt_fftpeak))
    f_czt_fftpeak = f_start2 + peak_idx2 * f_step

    # 步骤 8: 计算距离
    R_fft = (C * f_fft_peak * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)
    R_macleod = (C * f_macleod * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)
    R_czt_fftpeak = (C * f_czt_fftpeak * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)
    R_czt_macleod = (C * f_czt_macleod * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)

    # 输出结果
    # print(f"FFT Distance: {R_fft:.4f} m | Macleod: {R_macleod:.4f} m | \
    #         CZT@peak: {R_czt_fftpeak:.4f} m | CZT@Macleod: {R_czt_macleod:.4f} m")

    return R_fft, R_macleod, R_czt_fftpeak, R_czt_macleod


def calculate_distance_from_fft(fft_result_in, n_chirp, n_points):
    """
    使用多种方法从FFT结果中计算距离。

    参数:
    fft_result_in (np.ndarray): 1D FFT 结果。
    n_chirp (int): Chirp 帧的数量。
    n_points (int): 每个 Chirp 的采样点数。

    返回:
    tuple: 包含四种距离计算结果的元组 (R_fft, R_macleod, R_czt_fftpeak, R_czt_macleod)。
    """
    fft_result = np.mean(fft_result_in[:, :], axis=0)

    # 步骤 3: 计算幅度谱并找到FFT峰值
    fft_sum = np.abs(fft_result)
    valid_points = n_points // 2
    max_index = np.argmax(fft_sum[:valid_points])

    # 计算频率偏移，这是最基础的FFT距离
    f_fft_peak = max_index * ADC_SAMPLE_RATE * 1e6 / n_points

    # 步骤 4: Macleod 插值，对FFT峰值进行二次细化
    X_km1 = fft_result[max(0, max_index - 1)]
    X_k0 = fft_result[max_index]
    X_kp1 = fft_result[min(valid_points - 1, max_index + 1)]
    mag2_km1 = np.abs(X_km1)**2
    mag2_k0 = np.abs(X_k0)**2
    mag2_kp1 = np.abs(X_kp1)**2
    denom = mag2_km1 - 2 * mag2_k0 + mag2_kp1
    delta = 0.5 * (mag2_km1 - mag2_kp1) / denom if denom != 0 else 0.0
    f_macleod = (max_index + delta) * ADC_SAMPLE_RATE * 1e6 / n_points

    # 步骤 5: 基于Macleod峰值进行CZT插值
    M = 32
    fs = ADC_SAMPLE_RATE * 1e6
    # 放大分析频宽到2个FFT Bin的宽度，以确保覆盖到峰值
    B = 1.0 * fs / n_points
    f_start = f_macleod - B / 2
    f_end = f_macleod + B / 2
    f_step_czt = (f_end - f_start) / (M-1)
    w = np.exp(-1j * 2 * np.pi * f_step_czt / fs)
    a = np.exp(1j * 2 * np.pi * f_start / fs)
    X_czt = czt(fft_result, M, w, a)

    # 步骤 6: 在CZT结果上再次进行Macleod插值，进一步细化
    peak_idx = np.argmax(np.abs(X_czt))
    if peak_idx > 0 and peak_idx < M - 1:
        mag2_czt_km1 = np.abs(X_czt[peak_idx - 1])**2
        mag2_czt_k0 = np.abs(X_czt[peak_idx])**2
        mag2_czt_kp1 = np.abs(X_czt[peak_idx + 1])**2
        denom2 = mag2_czt_km1 - 2 * mag2_czt_k0 + mag2_czt_kp1
        delta_czt = 0.5 * (mag2_czt_km1 - mag2_czt_kp1) / denom2 if denom2 != 0 else 0.0
        f_czt_macleod = f_start + (peak_idx + delta_czt) * f_step_czt
    else:
        f_czt_macleod = f_start + peak_idx * f_step_czt

    # 步骤 7: 基于FFT峰值进行CZT插值
    f_start2 = f_fft_peak - B / 2
    f_end2 = f_fft_peak + B / 2
    f_step_czt2 = (f_end2 - f_start2) / (M - 1)
    w2 = np.exp(-1j * 2 * np.pi * f_step_czt2 / fs)
    a2 = np.exp(1j * 2 * np.pi * f_start2 / fs)
    X_czt_fftpeak = czt(fft_result, M, w2, a2)

    # 再次进行Macleod插值以细化CZT结果
    peak_idx2 = np.argmax(np.abs(X_czt_fftpeak))
    if peak_idx2 > 0 and peak_idx2 < M - 1:
        mag2_czt_fftpeak_km1 = np.abs(X_czt_fftpeak[peak_idx2 - 1])**2
        mag2_czt_fftpeak_k0 = np.abs(X_czt_fftpeak[peak_idx2])**2
        mag2_czt_fftpeak_kp1 = np.abs(X_czt_fftpeak[peak_idx2 + 1])**2
        denom3 = mag2_czt_fftpeak_km1 - 2 * mag2_czt_fftpeak_k0 + mag2_czt_fftpeak_kp1
        delta_czt2 = 0.5 * (mag2_czt_fftpeak_km1 - mag2_czt_fftpeak_kp1) / denom3 if denom3 != 0 else 0.0
        f_czt_fftpeak = f_start2 + (peak_idx2 + delta_czt2) * f_step_czt2
    else:
        f_czt_fftpeak = f_start2 + peak_idx2 * f_step_czt2

    # 步骤 8: 将频率转换为距离
    R_fft = (C * f_fft_peak * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)
    R_macleod = (C * f_macleod * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)
    R_czt_fftpeak = (C * f_czt_fftpeak * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)
    R_czt_macleod = (C * f_czt_macleod * CHIRP_T0 * 1e-6) / (2.0 * FM * 1e6)

    # 输出结果
    # print(f"FFT Distance: {R_fft:.4f} m | Macleod: {R_macleod:.4f} m | \
    #         CZT@peak: {R_czt_fftpeak:.4f} m | CZT@Macleod: {R_czt_macleod:.4f} m")

    return R_fft, R_macleod, R_czt_fftpeak, R_czt_macleod


#=========距离计算函数，直接利用时域iq数据进行变换=============

# ---- 工具函数 ----
def _parabolic_delta(m1, m0, p1, eps=1e-18):
    denom = (m1 - 2.0*m0 + p1)
    if np.abs(denom) < eps:
        denom = np.sign(denom) * eps if denom != 0 else eps
    return 0.5 * (m1 - p1) / denom

def _build_czt_aw(f_start, B, M, fs):
    # 夹取到 [0, fs/2 - B]
    f_start = float(max(0.0, min(f_start, fs/2 - B)))
    df = B / (M - 1)  # 覆盖完整带宽
    W = np.exp(-1j * 2 * np.pi * (df / fs))
    A = np.exp( 1j * 2 * np.pi * (f_start / fs))
    return A, W, df, f_start

def _coarse_peak_fft(x_td, fs):
    GUARD_BINS = 4   # ← 写死：剔除前 4 个 bin（直达波）

    N = x_td.shape[-1]
    X = np.fft.fft(x_td, n=N)
    X_pos = X[: N // 2 + 1]
    mag2 = np.abs(X_pos) ** 2
    # ---- 剔除直达波 bin ----
    if GUARD_BINS > 0:
        mag2[:GUARD_BINS] = 0.0
    # ---- 峰值搜索 ----
    kmax = int(np.argmax(mag2))
    # ---- Macleod（三点二次插值）----
    if GUARD_BINS < kmax < (mag2.size - 1):
        delta = _parabolic_delta(
            mag2[kmax - 1],
            mag2[kmax],
            mag2[kmax + 1]
        )
    else:
        delta = 0.0
    f_bin = fs / N
    f_fft_peak = kmax * f_bin
    f_macleod  = (kmax + delta) * f_bin

    return kmax, f_fft_peak, f_macleod

def _rife_refinement(x_td, fs):
    """Rife 算法频率修正"""
    n = x_td.size
    X = np.fft.fft(x_td)
    mag = np.abs(X[:n // 2])
    kmax = np.argmax(mag)

    # 寻找能量较大的邻近 bin 以确定修正方向
    if kmax == 0:
        r = 1
    elif kmax == (n // 2 - 1):
        r = -1
    else:
        if mag[kmax + 1] > mag[kmax - 1]:
            r = 1
        else:
            r = -1

    val_max = mag[kmax]
    val_adj = mag[kmax + r]

    # Rife 修正公式
    delta = r * (val_adj / (val_max + val_adj))
    f_rife = (kmax + delta) * fs / n
    return f_rife, delta


def calculate_distance_from_iq(
    iq,                     # ndarray, shape (n_ant, n_chirp, n_sample)
    r_bins=3.0,             # CZT 覆盖的原始 FFT bin 数
    M=128,                  # CZT 点数
    use_window='hamming',   # None/'hann'/'hamming'...
    coherent=True,          # True: 沿 chirp 复数相干；False: 选能量最大一条
    antenna_index=0,        # 使用的虚拟天线索引
    sample_slice=None       # (i0, i1) 仅用规则区样点；None=全长
):
    """
    返回: (R_fft, R_fft_macleod, R_czt_only, R_combo, diag)
      - R_fft         : 算法1  纯 FFT 测距
      - R_fft_macleod : 算法2  FFT+Macleod（在FFT谱上做3点二次插值）
      - R_czt_only    : 算法3  CZT测距（对IQ做CZT，取CZT峰bin，不做Macleod）
                         *窗口中心使用 FFT 粗峰，仅用于定位带宽，不参与最终估计*
      - R_combo       : 算法4  FFT+Macleod → CZT（以Macleod粗频为中心）→ Macleod（二次插值）
    """
    fs = float(ADC_SAMPLE_RATE) * 1e6  # Hz
    T_chirp = float(CHIRP_T0) * 1e-6   # s
    B_chirp = float(FM) * 1e6          # Hz

    # ---- 取指定天线 & 规则区 ----
    x = iq[antenna_index]              # (n_chirp, n_sample)
    if sample_slice is not None:
        i0, i1 = sample_slice
        x = x[:, i0:i1]
    n_chirp, n_sample = x.shape

    # ---- 时域聚合 & 加窗 ----
    if coherent:
        x_td = x.mean(axis=0).astype(np.complex128, copy=False)
    else:
        Xc_all = np.fft.fft(x, axis=-1)
        idx = np.argmax(np.max(np.abs(Xc_all)**2, axis=-1))
        x_td = x[idx].astype(np.complex128, copy=False)

    if use_window is not None:
        win = get_window(use_window, x_td.size, fftbins=True).astype(np.float64)
        win = win / np.sqrt((win**2).mean())  # ENBW 归一
        x_td = x_td * win

    # ---- 粗定位 + Macleod 细化（得到 f_fft_peak, f_macleod）----
    kmax, f_fft_peak, f_macleod = _coarse_peak_fft(x_td, fs)

    #  Rife 算法 (新增)
    f_rife, delta_rife = _rife_refinement(x_td, fs)

    # ---- CZT参数（带宽 B 统一，以便公平对比）----
    B = float(r_bins) * fs / n_sample

    # ===== 算法3：CZT-only（以 FFT 粗峰为中心；不做Macleod）=====
    f_start_czt_only = f_fft_peak - B/2
    A1, W1, df1, f_start_czt_only = _build_czt_aw(f_start_czt_only, B, M, fs)
    Xc1 = czt(x_td, M, W1, A1)
    pk1 = int(np.argmax(np.abs(Xc1)))
    f_czt_only = f_start_czt_only + pk1 * df1  # 不做三点二次插值

    # ===== 算法4：组合（Macleod 粗频为中心 + CZT + Macleod 二次插值）=====
    f_start_combo = f_macleod - B/2
    A2, W2, df2, f_start_combo = _build_czt_aw(f_start_combo, B, M, fs)
    Xc2 = czt(x_td, M, W2, A2)
    pk2 = int(np.argmax(np.abs(Xc2)))
    if 0 < pk2 < (M - 1):
        m1 = np.abs(Xc2[pk2-1])**2; m0 = np.abs(Xc2[pk2])**2; p1 = np.abs(Xc2[pk2+1])**2
        delta2 = _parabolic_delta(m1, m0, p1)
    else:
        delta2 = 0.0
    f_combo = f_start_combo + (pk2 + delta2) * df2

    # ---- 频率 -> 距离 ----
    fb2R = lambda fb: C * fb * T_chirp / (2.0 * B_chirp)
    R_fft         = fb2R(f_fft_peak)     # 算法1
    R_fft_macleod = fb2R(f_macleod)      # 算法2
    R_czt_only    = fb2R(f_czt_only)     # 算法3
    R_combo       = fb2R(f_combo)        # 算法4
    R_rife        = fb2R(f_rife)         # Rife算法（新增）

    diag = {
        "antenna_used": int(antenna_index),
        "n_chirp": int(n_chirp),
        "n_sample": int(n_sample),
        "fs_Hz": float(fs),
        "B_czt_Hz": float(B),
        "M": int(M),
        "r_bins": float(r_bins),
        "coherent": bool(coherent),
        "window": use_window if use_window is not None else "none",
        # 粗估
        "kmax": int(kmax),
        "f_fft_peak_Hz": float(f_fft_peak),
        "f_macleod_Hz": float(f_macleod),
        "f_rife_Hz": float(f_rife),               # Rife算法（新增）
        # CZT-only（算法3）
        "f_start_czt_only_Hz": float(f_start_czt_only),
        "df_czt_only_Hz": float(df1),
        "f_czt_only_Hz": float(f_czt_only),
        "pk_czt_only": int(pk1),
        "czt_only_spectrum": Xc1,
        # 组合（算法4）
        "f_start_combo_Hz": float(f_start_combo),
        "df_combo_Hz": float(df2),
        "f_combo_Hz": float(f_combo),
        "pk_combo": int(pk2),
        "delta_combo_bins": float(delta2),
        "czt_combo_spectrum": Xc2,
        "sample_slice": sample_slice if sample_slice else "full"
    }

    return R_fft, R_fft_macleod, R_rife, R_czt_only, R_combo, diag

###==================== 2D FFT 角度估计 ===================

def estimate_az_el_from_fft2d2(fft2d_results):
    """
    根据 2D FFT 结果估计 水平角(az) 与 俯仰角(el)
    - 硬件布局：TX0/TX1 水平（azimuth），RX0/RX1 垂直（elevation）
    - 使用全局变量: wavelength, CHIRP_PERIOD (μs)
    - 虚拟通道顺序: [v0=TX0→RX0, v1=TX0→RX1, v2=TX1→RX0, v3=TX1→RX1]
    """
    global wavelength, CHIRP_PERIOD

    d_spacing = wavelength / 2.0
    assert fft2d_results.ndim == 3 and fft2d_results.shape[0] == 4

    n_chirp = fft2d_results.shape[1]
    n_range = fft2d_results.shape[2]

    # 1) 找最强点
    power_sum = np.sum(np.abs(fft2d_results)**2, axis=0)
    k_dop, k_rng = np.unravel_index(np.argmax(power_sum), power_sum.shape)

    # 2) 取复值
    v0 = fft2d_results[0, k_dop, k_rng]  # TX0→RX0
    v1 = fft2d_results[1, k_dop, k_rng]  # TX0→RX1
    v2 = fft2d_results[2, k_dop, k_rng]  # TX1→RX0
    v3 = fft2d_results[3, k_dop, k_rng]  # TX1→RX1

    # 3) AZIMUTH: 同 RX，不同 TX → 需 Doppler 补偿（TX0/TX1 水平）
    delta_t_s = CHIRP_PERIOD * 1e-6  # 108 μs → 0.000108 s
    prf = 1.0 / delta_t_s
    doppler_freq = k_dop * (prf / n_chirp)
    if k_dop >= n_chirp // 2:
        doppler_freq -= prf
    phase_per_chirp = 2 * np.pi * doppler_freq * delta_t_s

    v2_comp = v2 * np.exp(-1j * phase_per_chirp)  # 补偿 TX1 比 TX0 晚
    v3_comp = v3 * np.exp(-1j * phase_per_chirp)

    dphi_az1 = np.angle(v2_comp * np.conj(v0))  # RX0: TX1 vs TX0 (azimuth)
    dphi_az2 = np.angle(v3_comp * np.conj(v1))  # RX1: TX1 vs TX0 (azimuth)
    dphi_az = np.angle(np.mean(np.exp(1j * np.array([dphi_az1, dphi_az2]))))

    # 4) ELEVATION: 同 TX，不同 RX → 无需补偿（RX0/RX1 垂直）
    dphi_el1 = np.angle(v1 * np.conj(v0))  # TX0: RX1 vs RX0 (elevation)
    dphi_el2 = np.angle(v3 * np.conj(v2))  # TX1: RX1 vs RX0 (elevation)
    dphi_el = np.angle(np.mean(np.exp(1j * np.array([dphi_el1, dphi_el2]))))

    # 5) 转换为角度
    coef = wavelength / (2.0 * np.pi * d_spacing)
    s_az = coef * dphi_az  # sin(az) * cos(el)
    s_el = coef * dphi_el  # sin(el)

    s_el = float(np.clip(s_el, -0.999999, 0.999999))
    el = np.arcsin(s_el)
    cos_el = np.cos(el)
    if abs(cos_el) < 1e-6:
        cos_el = 1e-6
    ratio = float(np.clip(s_az / cos_el, -0.999999, 0.999999))
    az = np.arcsin(ratio)

    az_deg = np.degrees(az)
    el_deg = np.degrees(el)

    extra = dict(
        dphi_az=float(dphi_az),
        dphi_el=float(dphi_el),
        s_az=float(s_az),
        s_el=float(s_el),
        wavelength=wavelength,
        d_spacing=d_spacing,
        chirp_period_us=CHIRP_PERIOD,
        doppler_freq=doppler_freq,
        phase_per_chirp=phase_per_chirp,
        k_dop=k_dop,
        k_rng=k_rng
    )
    return az_deg, el_deg, (int(k_dop), int(k_rng)), extra




###==================== 频率偏移校准(时域IQ数据) ===================

def extract_dphi_hw(iq_data, ref_channel=0):
    """提取4通道相对于基准的相位差（bin=1，多chirp平均）"""
    n_ant, n_chirps, n_samples = iq_data.shape
    phase_list = []
    for chirp in range(n_chirps):
        fft_data = np.fft.fft(iq_data[:, chirp, :], axis=1)
        phase_rad = np.angle(fft_data[:, 1])  # bin=1的相位（弧度）
        phase_list.append(phase_rad)
    phase_mean_rad = np.mean(phase_list, axis=0)  # 多chirp平均
    dphi_rad = phase_mean_rad - phase_mean_rad[ref_channel]  # 相对基准的相位差
    return np.rad2deg(dphi_rad).tolist()  # 转为度

def calculate_geo_dphi_correction():
    """修正几何相位差（通道2和3对调，关键修正！）"""
    lambda_carrier = 3e8 / 77e9  # 3.9mm
    d = lambda_carrier / 2  # 间距=λ/2
    # 正确的几何相位差（基于通道定义）：
    # 通道0（TX0RX0）：0°
    # 通道1（TX0RX1）：接收间距d → 180°（λ/2对应180°）
    # 通道2（TX1RX1）：发射间距d + 接收间距d = 2d → 360°→0°
    # 通道3（TX1RX0）：发射间距d → 180°
    return [0, 180, 0, 180]  # 修正后：通道2=0°，通道3=180°

def calculate_compensation_omegas(dphi_meas_deg):
    """计算频率偏移补偿量（修正通道对应关系）"""
    T_actual = 256 / 7.14e6  # 35.85μs
    dphi_geo = calculate_geo_dphi_correction()
    # 硬件相位差 = 测量值 - 几何相位差
    dphi_hw_deg = [m - g for m, g in zip(dphi_meas_deg, dphi_geo)]
    # 计算ω = Δφ(rad) / T
    omegas = [np.deg2rad(dphi) / T_actual for dphi in dphi_hw_deg]
    return omegas

def digital_if_calibration(iq_data, omegas):
    """频率平移校准（核心逻辑不变）"""
    FS_HZ = 7.14e6
    n_ant, n_chirps, n_samples = iq_data.shape
    t = np.arange(n_samples) / FS_HZ  # 时间序列
    compensation = np.ones((n_ant, n_chirps, n_samples), dtype=np.complex64)
    for i in range(n_ant):
        compensation[i, :, :] = np.exp(-1j * omegas[i] * t)  # 频率平移补偿
    return iq_data * compensation

def learn_calibration_parameters(iq_data_no_target):
    """
    输入：无目标时采集的一次数据 (4, n_chirps, 256)
    输出：保存每个通道的补偿斜率 omega (rad/s)
    """
    FS_HZ = 7.14e6
    N_SAMPLES = 256
    t = np.arange(N_SAMPLES) / FS_HZ

    calibration_omegas = []  # 存储每个通道的 omega

    print("开始学习校准参数（无目标）...")

    for ch in [0, 1, 2, 3]:
        if ch == 0:
            # 参考通道，omega = 0
            calibration_omegas.append(0.0)
            continue

        z_ref = iq_data_no_target[0, 0, :]  # Ch0 第一个 chirp
        z_ch = iq_data_no_target[ch, 0, :]  # 当前通道

        phase_diff = np.angle(z_ch * np.conj(z_ref))
        phase_diff_unwrapped = np.unwrap(phase_diff)

        slope, _ = np.polyfit(t, phase_diff_unwrapped, 1)  # rad/s
        calibration_omegas.append(slope)

        freq_shift = slope / (2 * np.pi)
        print(f"通道 {ch}: 学得 omega = {slope:.2f} rad/s ({freq_shift:+.1f} Hz)")

    # 保存为全局参数（可存入文件或全局变量）
    return np.array(calibration_omegas)  # shape: (4,)


# def music_azimuth_spectrum_auto(fft2d_results):
#     """
#     自动执行 MUSIC 角度谱估计，无需手动输入 range_bin/doppler_bin

#     参数:
#         fft2d_results: shape=(4, n_chirp, n_range)，2D-FFT 后的数据

#     返回:
#         angles: 扫描角度数组
#         spectrum_dB: MUSIC 谱 (dB)
#         peak_angle: 估计的方位角
#         range_est: 估计的距离
#         velocity_est: 估计的速度
#     """
#     n_ant, n_chirp, n_range = fft2d_results.shape

#     # -------------------------------
#     # 步骤1：生成 RD 谱图，找最强目标
#     # -------------------------------
#     # 对 4 个通道平均，得到粗略 RD 图
#     rd_map = np.mean(np.abs(fft2d_results), axis=0)  # (n_chirp, n_range)

#     # 找全局最大值位置
#     max_idx = np.unravel_index(np.argmax(rd_map), rd_map.shape)
#     doppler_bin, range_bin = max_idx  # 注意：fftshift 后 doppler_bin 是中心对称的

#     # -------------------------------
#     # 步骤2：提取快拍数据 X (4, L)
#     # -------------------------------
#     # 方法1：用 doppler_bin 附近多个单元作为快拍
#     window_size = 5
#     start = max(0, doppler_bin - window_size//2)
#     end = min(n_chirp, doppler_bin + window_size//2 + 1)
#     X = fft2d_results[:, start:end, range_bin]  # (4, L)
#     X = X.reshape(n_ant, -1)  # (4, L)

#     if X.shape[1] < 2:
#         raise ValueError("快拍数不足，无法进行 MUSIC")

#     # -------------------------------
#     # 步骤3：协方差矩阵 & 特征分解
#     # -------------------------------
#     R = X @ X.conj().T / X.shape[1]  # (4,4)

#     eigvals, eigvecs = np.linalg.eigh(R)  # 升序
#     eigvals = eigvals[::-1]
#     eigvecs = eigvecs[:, ::-1]

#     # 假设信号源数 K=1
#     K = 1
#     U_n = eigvecs[:, K:]  # 噪声子空间 (4, 3)

#     # -------------------------------
#     # 步骤4：扫描方位角，计算 MUSIC 谱
#     # -------------------------------
#     angles = np.linspace(-90, 90, 1801)  # 0.1° 步进
#     spectrum = np.zeros_like(angles)

#     for i, angle in enumerate(angles):
#         theta = np.deg2rad(angle)
#         # 导向矢量：a(θ) = exp(-j*2π * (x_i/λ) * sinθ)
#         a = np.exp(-1j * 2 * np.pi * virtual_x_normalized * np.sin(theta))  # (4,)
#         a = a.reshape(-1, 1)

#         # MUSIC 谱
#         denom = np.abs((a.conj().T @ U_n @ U_n.conj().T @ a).item())
#         spectrum[i] = 1 / (denom + 1e-12)

#     spectrum_dB = 10 * np.log10(spectrum / np.max(spectrum))

#     # 找峰值
#     peak_idx = np.argmax(spectrum)
#     peak_angle = angles[peak_idx]

#     return angles, spectrum_dB, peak_angle

def music_2d_spectrum_auto2(fft2d_results):
    """
    2D MUSIC 角度谱估计
    坐标系：
    - 方位角 az: 水平方向，0°=正前方，正值=右，负值=左
    - 俯仰角 el: 垂直方向，0°=水平，正值=向上
    阵列：垂直平面，X轴=水平，Y轴=垂直
    """
    n_ant, n_chirp, n_range = fft2d_results.shape
    if n_ant != virtual_positions_m.shape[0]:
        raise ValueError(f"通道数 {n_ant} 与虚拟天线数 {virtual_positions_m.shape[0]} 不匹配！")

    # 1. 自动检测最强目标
    rd_map = np.mean(np.abs(fft2d_results), axis=0)
    doppler_bin, range_bin = np.unravel_index(np.argmax(rd_map), rd_map.shape)

    # 2. 提取快拍数据
    window_size = 5
    start = max(0, doppler_bin - window_size // 2)
    end = min(n_chirp, doppler_bin + window_size // 2 + 1)
    X = fft2d_results[:, start:end, range_bin]
    X = X.reshape(n_ant, -1)

    if X.shape[1] < 2:
        raise ValueError("快拍数不足")

    # 3. 协方差矩阵 & 噪声子空间
    R = X @ X.conj().T / X.shape[1]
    eigvals, eigvecs = np.linalg.eigh(R)
    idx = np.argsort(eigvals)[::-1]
    eigvecs = eigvecs[:, idx]
    K = 1
    U_n = eigvecs[:, K:]

    # 4. 构建 2D 导向矢量 - 关键修改
    az_angles = np.linspace(-90, 90, 181)      # 方位角：水平方向
    el_angles = np.linspace(-45, 45, 91)       # 俯仰角：垂直方向
    AZ, EL = np.meshgrid(az_angles, el_angles)  # (91_el, 181_az)

    az_rad = np.deg2rad(AZ)
    el_rad = np.deg2rad(EL)

    # 虚拟阵列归一化坐标
    # [:, 0] = X轴 = 水平方向 → 对应方位角
    # [:, 1] = Y轴 = 垂直方向 → 对应俯仰角
    pos_norm = virtual_positions_m / wavelength

    # 修正的导向矢量公式
    # X方向（水平）对应 sin(az)
    # Y方向（垂直）对应 sin(el)
    phase = (
        pos_norm[:, 0][:, None, None] * np.sin(az_rad) +
        pos_norm[:, 1][:, None, None] * np.sin(el_rad)
    )
    A = np.exp(-1j * 2 * np.pi * phase)

    # 5. 计算 2D MUSIC 谱
    UnUnH = U_n @ U_n.conj().T
    N_el, N_az = AZ.shape
    A_flat = A.reshape(4, -1)

    proj = UnUnH @ A_flat
    denom_flat = np.real(np.sum(A_flat.conj() * proj, axis=0))
    denom = denom_flat.reshape(N_el, N_az)

    spectrum = 1.0 / (denom + 1e-12)
    spectrum_dB = 10 * np.log10(spectrum / np.max(spectrum))

    # 找峰值
    peak_i, peak_j = np.unravel_index(np.argmax(spectrum), spectrum.shape)
    peak_el = el_angles[peak_i]  # 行索引对应俯仰角
    peak_az = az_angles[peak_j]  # 列索引对应方位角

    return AZ, EL, spectrum_dB, peak_az, peak_el

def music_2d_spectrum_auto(fft_results_1D):
    """
    (v2 - 已修正)
    2D MUSIC 角度谱估计 (在 距离-Chirp 域执行)

    输入: fft_results_1D (1D FFT 的结果)
    形状: (n_ant, n_chirp, n_range) e.g., (4, 16, 256)
    """
    n_ant, n_chirp, n_range = fft_results_1D.shape

    # 检查: 确保天线数 (4) 与虚拟阵列位置匹配
    if n_ant != virtual_positions_m.shape[0]:
        raise ValueError(f"通道数 {n_ant} 与虚拟天线数 {virtual_positions_m.shape[0]} 不匹配！")

    # 检查: 快拍数 (n_chirp) 必须大于天线数
    if n_chirp < n_ant:
        raise ValueError(f"快拍数 (n_chirp={n_chirp}) 必须大于天线数 (n_ant={n_ant})")

    # --- 1. 自动检测最强目标 ---
    # 在 距离-Chirp 矩阵上求平均来找最强的距离仓
    # (我们不再关心多普勒)
    range_profile = np.mean(np.abs(fft_results_1D), axis=(0, 1)) # (n_range,)
    range_bin = np.argmax(range_profile)

    # --- 2. 提取快拍数据 ---
    # [!!! 关键修改 !!!]
    # 快拍 (Snapshots) 是 n_chirp 个 Chirp。
    # X 的形状是 (n_ant, n_chirp) e.g., (4, 16)
    X = fft_results_1D[:, :, range_bin]

    # --- 3. 协方差矩阵 & 噪声子空间 ---
    # (此步骤不变)
    R = X @ X.conj().T / n_chirp  # (4, 4)
    eigvals, eigvecs = np.linalg.eigh(R)
    idx = np.argsort(eigvals)[::-1]
    eigvecs = eigvecs[:, idx]
    K = 1  # 假设 1 个目标
    U_n = eigvecs[:, K:] # (4, 3)

    # --- 4. 构建 2D 导向矢量 ---
    # (此步骤不变)
    az_angles = np.linspace(-90, 90, 181)     # 方位角
    el_angles = np.linspace(-45, 45, 91)     # 俯仰角
    AZ, EL = np.meshgrid(az_angles, el_angles) # (91, 181)
    az_rad = np.deg2rad(AZ)
    el_rad = np.deg2rad(EL)

    pos_norm = virtual_positions_m / wavelength

    phase = (
        pos_norm[:, 0][:, None, None] * np.sin(az_rad) +
        pos_norm[:, 1][:, None, None] * np.sin(el_rad)
    )
    A = np.exp(-1j * 2 * np.pi * phase) # (4, 91, 181)

    # --- 5. 计算 2D MUSIC 谱 ---
    # (此步骤不变)
    UnUnH = U_n @ U_n.conj().T
    N_el, N_az = AZ.shape
    A_flat = A.reshape(n_ant, -1) # (4, 91*181)

    proj = UnUnH @ A_flat
    denom_flat = np.real(np.sum(A_flat.conj() * proj, axis=0))
    denom = denom_flat.reshape(N_el, N_az)

    spectrum = 1.0 / (denom + 1e-12)
    spectrum_dB = 10 * np.log10(spectrum / np.max(spectrum))

    # 找峰值
    peak_i, peak_j = np.unravel_index(np.argmax(spectrum), spectrum.shape)
    peak_el = el_angles[peak_i]  # 行索引对应俯仰角
    peak_az = az_angles[peak_j]  # 列索引对应方位角

    return AZ, EL, spectrum_dB, peak_az, peak_el

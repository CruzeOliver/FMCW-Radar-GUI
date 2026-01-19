import threading
import queue
import time
import numpy as np
import struct
from typing import Tuple, Optional, Dict, List

# ================== 协议参数 ==================
PKT_SIZE = 1024             # 每个UDP包固定 1024B
MAX_SAMPLES = 8192
MAX_CHIRPS = 8192
MAX_FRAME_BYTES = 64 * 1024 * 1024

# ================== 数据重排函数 ==================
def reorder_frame(frame_bytes: bytes, total_chirp: int, sample: int, txrx: int, window: np.ndarray | None = None) -> np.ndarray:
    """
    重排雷达原始帧。
    假设 TDM-MIMO (txrx=4) 模式下，数据已按 (chirp_half, 4_rx, sample, IQ)
    的格式交错，但维度需要转置。
    """
    data = np.frombuffer(frame_bytes, dtype=np.int16)

    chirp_num = total_chirp
    sample_point = sample
    tx_rx_type = txrx

    # --- (以下逻辑来自 方案 A 的 bytes_to_iq) ---
    if tx_rx_type == 1:
        num_rx = 1
    elif tx_rx_type == 2:
        num_rx = 2
    else:
        # TDM-MIMO (txrx=4)
        num_rx = 4
        chirp_num = chirp_num // 2

    # 期望的 int16 元素总数
    expected_length = chirp_num * sample_point * num_rx * 2 # 2 是 I/Q

    if data.size < expected_length:
        raise ValueError(f"帧字节数错误: 期望 {expected_length} (int16), 实际 {data.size}")
    data = data[:expected_length]

    try:
        iq_data = data.reshape((chirp_num, num_rx, sample_point, 2))
        iq_data = iq_data.transpose(1, 0, 2, 3)
        complex_data = iq_data[..., 0] + 1j * iq_data[..., 1]
        complex_data = complex_data.astype('complex64')

    except Exception as e:
        raise ValueError(f"Reshape/Transpose 失败: {e}. 期望形状 ({chirp_num}, {num_rx}, {sample_point}, 2)")

    # 应用窗函数 (与方案B保持一致)
    if window is not None:
        if len(window) != sample_point:
            raise ValueError(f"window 长度 {len(window)} 必须等于 sample {sample_point}")
        complex_data = complex_data * window[np.newaxis, np.newaxis, :]

    # 最终返回形状为 (4, chirp_num/2, sample_point)
    return complex_data

def reorder_frame_TDMMIMO2(frame_bytes: bytes, chirp_from_header: int, sample_from_header: int, txrx: int, window: np.ndarray | None = None) -> np.ndarray:
    """
    (最终方案 v4 - 已修正)

    根据 C 代码分析:
    - `chirp_from_header` (e.g., 32) 是正确的 `chirp_per_tx`。
    - `sample_from_header` (e.g., 256) 是指 "每个RX通道的int16数量"。
    - 真正的复数采样点 = 256 / 2 = 128。
    """

    # --- 0. 基本参数和检查 ---
    if txrx != 4:
        raise ValueError("此重排逻辑专为 TXRXTYPE == 4 (TDM-MIMO) 设计")

    data = np.frombuffer(frame_bytes, dtype=np.int16)

    chirp_per_tx = chirp_from_header      # e.g., 32
    total_chirp_tdm = chirp_per_tx * 2   # e.g., 64
    num_rx_physical = 2

    # C 循环 16 次 (32 / 2)
    num_blocks = chirp_per_tx // 2       # e.g., 16

    # 1 packet = 512 int16s. 1 block = 4 packets.
    expected_int16s = num_blocks * 4 * 512 # e.g., 16 * 2048 = 32768

    if data.size != expected_int16s:
        raise ValueError(f"帧数据大小错误: 期望 {expected_int16s} (int16), 实际 {data.size}")


    # --- 1. “解交错” (Undo C code's interleaving) ---
    try:
        # (16, 4, 512)
        data_blocks = data.reshape((num_blocks, 4, 512))
    except Exception as e:
        raise ValueError(f"Reshape 失败 (步骤1): {e}")

    # (16, 2, 512) -> (32, 512)
    # tx0_data size = 16 * 2 * 512 = 16384
    tx0_data = data_blocks[:, 0:2, :].reshape((chirp_per_tx, 512))
    tx1_data = data_blocks[:, 2:4, :].reshape((chirp_per_tx, 512))

    # --- 2. 构建 TDM 帧 (修正点) ---
    # 检查:
    # 1 chirp (512 int16s) = num_rx(2) * real_samples(128) * iq(2)
    # 512 = 2 * 128 * 2 = 512.
    # 匹配成功。

    if sample_from_header <= 0:
         raise ValueError(f"计算出的采样点为零或负数 (来自 {sample_from_header})")

    try:
        # (32, 512) -> (32, 2, 128, 2)
        tx0_iq = tx0_data.reshape((chirp_per_tx, num_rx_physical, sample_from_header, 2))
        tx1_iq = tx1_data.reshape((chirp_per_tx, num_rx_physical, sample_from_header, 2))
    except ValueError as e:
        raise ValueError(f"Reshape 失败 (步骤2): {e}. 检查 (32, 2, 128, 2) 是否匹配 16384")

    # 创建 TDM 帧 (64, 2, 128, 2)
    tdm_frame = np.zeros((total_chirp_tdm, num_rx_physical, sample_from_header, 2), dtype=np.int16)

    tdm_frame[0::2, :, :, :] = tx0_iq  # TX0 数据放入偶数 chirps
    tdm_frame[1::2, :, :, :] = tx1_iq  # TX1 数据放入奇数 chirps

    # --- 3. 创建虚拟通道 ---

    # (64, 2, 128, 2) -> (64, 2, 128)
    iq_complex = tdm_frame[..., 0] + 1j * tdm_frame[..., 1]

    v0 = iq_complex[0::2, 0, :]  # TX0 → RX0 (32, 128)
    v1 = iq_complex[0::2, 1, :]  # TX0 → RX1 (32, 128)
    v2 = iq_complex[1::2, 0, :]  # TX1 → RX0 (32, 128)
    v3 = iq_complex[1::2, 1, :]  # TX1 → RX1 (32, 128)

    # 堆叠成 (4, 32, 128)
    iq_virtual = np.stack([v0, v1, v2, v3], axis=0).astype('complex64')

    # 应用窗函数
    if window is not None:
        # 窗函数应匹配复数采样点的数量
        if len(window) != sample_from_header:
            # 如果 Hamming 窗还是 256, 会在这里出错
            raise ValueError(f"window 长度 {len(window)} 必须等于真实采样点 {sample_from_header}")
        iq_virtual = iq_virtual * window[np.newaxis, np.newaxis, :]

    # 最终返回 (4, chirp_per_tx, sample_from_header)
    return iq_virtual

def reorder_frame_TDMMIMO(frame_bytes: bytes, chirp: int, real_sample_points: int, txrx: int, window: np.ndarray | None = None) -> np.ndarray:
    """
    (最终方案 v8 - 匹配 C 内存和 UDP)

    此函数信任调用者 (check_frame_queue) 已经计算好了
    正确的 chirp_per_tx (16) 和 real_sample_points (256)。

    它正确地解开了 C 代码的 [TX0(2包), TX1(2包), ...] 交错。
    """

    # --- 0. 基本参数和检查 ---
    if txrx != 4:
        raise ValueError("此重排逻辑专为 TXRXTYPE == 4 (TDM-MIMO) 设计")

    data = np.frombuffer(frame_bytes, dtype=np.int16)

    # (传入: chirp_per_tx = 16, real_sample_points = 256)
    total_chirp_tdm = chirp    # e.g., 32
    num_rx_physical = 2

    # 1 pkt = 1024 bytes = 512 int16s
    # 1 chirp (256 samples) = 2(RX) * 256(sample) * 2(I/Q) = 1024 int16s
    # 1 chirp = 2 个包

    # C 代码的循环次数 (基于 header 32 / 2) = 16 次
    num_c_loops = (chirp ) // 2 # 16

    expected_int16s = num_c_loops * 4 * 512 # 16 * 4 * 512 = 32,768

    if data.size != expected_int16s:
        raise ValueError(f"帧数据大小错误: 期望 {expected_int16s} (int16), 实际 {data.size}")
    chirp_per_tx = chirp // 2  # tx的chirp是总的chirp的一半

    # --- 1. “解交错” (Undo C code's interleaving) ---
    try:
        # C 循环 16 次, 每次发 4 包
        # (16, 4, 512)
        data_blocks = data.reshape((num_c_loops, 4, 512))
    except Exception as e:
        raise ValueError(f"Reshape 失败 (步骤1): {e}")

    # C 发送: [TX0 Pkt 0-1] [TX1 Pkt 0-1]
    # Pkt 0 和 Pkt 1 是 *一个* chirp (1024 int16s)

    # [v8 修正点]
    # (16, 2, 512) -> (16, 1024)
    # tx0_data size = 16 * 1024 = 16384
    tx0_data = data_blocks[:, 0:2, :].reshape((chirp_per_tx, 1024))
    tx1_data = data_blocks[:, 2:4, :].reshape((chirp_per_tx, 1024))

    # --- 2. 构建 TDM 帧 ---
    try:
        # (16, 1024) -> (16, 2, 256, 2)
        tx0_iq = tx0_data.reshape((chirp_per_tx, num_rx_physical, real_sample_points, 2))
        tx1_iq = tx1_data.reshape((chirp_per_tx, num_rx_physical, real_sample_points, 2))
    except ValueError as e:
        raise ValueError(f"Reshape 失败 (步骤2): {e}. 检查 {tx0_data.size} 和 {(chirp_per_tx, num_rx_physical, real_sample_points, 2)}")

    # 创建 TDM 帧 (32, 2, 256, 2)
    tdm_frame = np.zeros((total_chirp_tdm, num_rx_physical, real_sample_points, 2), dtype=np.int16)

    # 1. TX0 对应 奇数索引 (1, 3, 5...)
    tdm_frame[1::2, :, :, :] = tx1_iq # TX0 数据放入奇数 chirps

    # 2. TX1 对应 偶数索引 (0, 2, 4...)
    tdm_frame[0::2, :, :, :] = tx0_iq # TX1 数据放入偶数 chirps

    # --- 3. 创建虚拟通道 ---

    # (32, 2, 256, 2) -> (32, 2, 256)
    #iq_complex = tdm_frame[..., 0] + 1j * tdm_frame[..., 1] # 假设 I, Q
    iq_complex = tdm_frame[..., 1] + 1j * tdm_frame[..., 0] # 将 I (索引 1) 作为实部，Q (索引 0) 作为虚部

    # v0, v1 使用奇数索引的数据 (TX0)
    v0 = iq_complex[1::2, 0, :]  # TX0 → RX0 (奇数Chirp)
    v1 = iq_complex[1::2, 1, :]  # TX0 → RX1 (奇数Chirp)

    # v2, v3 使用偶数索引的数据 (TX1)
    v2 = iq_complex[0::2, 0, :]  # TX1 → RX0 (偶数Chirp)
    v3 = iq_complex[0::2, 1, :]  # TX1 → RX1 (偶数Chirp)

    # 堆叠成 (4, 16, 256)
    iq_virtual = np.stack([v0, v1, v2, v3], axis=0).astype('complex64')

    # 应用窗函数
    if window is not None:
        if len(window) != real_sample_points:
            raise ValueError(f"window 长度 {len(window)} 必须等于真实采样点 {real_sample_points}")
        iq_virtual = iq_virtual * window[np.newaxis, np.newaxis, :]

    # 最终返回 (4, chirp_per_tx, real_sample_points)
    return iq_virtual

def reorder_frame_TDMMIMO_with_noise(frame_bytes: bytes, chirp: int, real_sample_points: int, txrx: int,
                          window: np.ndarray | None = None,
                          sim_noise_ch: int = -1,      # [新增] 指定注入噪声的虚拟通道索引 (0-3), -1表示不注入
                          sim_noise_level: float = 0.0 # [新增] 噪声标准差 (幅度), 建议 500~2000
                          ) -> np.ndarray:
    """
    (最终方案 v8 - 匹配 C 内存和 UDP) + [鲁棒性验证功能]

    sim_noise_ch:  指定要"搞坏"的通道索引 (例如 1 代表 TX0RX1)
    sim_noise_level: 噪声强度 (ADC数据通常在几千量级, 建议设置 500-3000 来模拟显著干扰)
    """

    # --- 0. 基本参数和检查 ---
    if txrx != 4:
        raise ValueError("此重排逻辑专为 TXRXTYPE == 4 (TDM-MIMO) 设计")

    data = np.frombuffer(frame_bytes, dtype=np.int16)

    total_chirp_tdm = chirp    # e.g., 32
    num_rx_physical = 2

    num_c_loops = (chirp ) // 2 # 16

    expected_int16s = num_c_loops * 4 * 512 # 16 * 4 * 512 = 32,768

    if data.size != expected_int16s:
        # [建议] 这里最好不要直接 raise, 而是打印 log 并返回 None, 增强系统鲁棒性
        print(f"[Warning] 帧数据大小错误: 期望 {expected_int16s} (int16), 实际 {data.size}")
        return None
    chirp_per_tx = chirp // 2  # tx的chirp是总的chirp的一半

    # --- 1. “解交错” (Undo C code's interleaving) ---
    try:
        # C 循环 16 次, 每次发 4 包
        # (16, 4, 512)
        data_blocks = data.reshape((num_c_loops, 4, 512))
    except Exception as e:
        raise ValueError(f"Reshape 失败 (步骤1): {e}")

    tx0_data = data_blocks[:, 0:2, :].reshape((chirp_per_tx, 1024))
    tx1_data = data_blocks[:, 2:4, :].reshape((chirp_per_tx, 1024))

    # --- 2. 构建 TDM 帧 ---
    try:
        # (16, 1024) -> (16, 2, 256, 2)
        tx0_iq = tx0_data.reshape((chirp_per_tx, num_rx_physical, real_sample_points, 2))
        tx1_iq = tx1_data.reshape((chirp_per_tx, num_rx_physical, real_sample_points, 2))
    except ValueError as e:
        raise ValueError(f"Reshape 失败 (步骤2): {e}. 检查 {tx0_data.size} 和 {(chirp_per_tx, num_rx_physical, real_sample_points, 2)}")

    # 创建 TDM 帧 (32, 2, 256, 2)
    tdm_frame = np.zeros((total_chirp_tdm, num_rx_physical, real_sample_points, 2), dtype=np.int16)
    tdm_frame[1::2, :, :, :] = tx1_iq

    # 2. TX1 对应 偶数索引 (0, 2, 4...)
    tdm_frame[0::2, :, :, :] = tx0_iq # TX1 数据放入偶数 chirps

    # --- 3. 创建虚拟通道 ---
    iq_complex = tdm_frame[..., 1] + 1j * tdm_frame[..., 0] # 将 I (索引 1) 作为实部，Q (索引 0) 作为虚部

    # v0, v1 使用奇数索引的数据 (TX0)
    v0 = iq_complex[1::2, 0, :]  # TX0 → RX0 (奇数Chirp)
    v1 = iq_complex[1::2, 1, :]  # TX0 → RX1 (奇数Chirp)

    # v2, v3 使用偶数索引的数据 (TX1)
    v2 = iq_complex[0::2, 0, :]  # TX1 → RX0 (偶数Chirp)
    v3 = iq_complex[0::2, 1, :]  # TX1 → RX1 (偶数Chirp)

    # 堆叠成 (4, 16, 256)
    iq_virtual = np.stack([v0, v1, v2, v3], axis=0).astype('complex64')

    # ==========================================================
    # --- [关键修改] 4. 注入半实物仿真噪声 (仅用于WLS验证) ---
    # ==========================================================
    if sim_noise_ch >= 0 and sim_noise_level > 0:
        # 确保索引有效 (0-3)
        if 0 <= sim_noise_ch < 4:
            # 仅在第一次调用时打印，避免刷屏 (逻辑需在外部控制，这里简单打印)
            # print(f"[Simulation Warning] 正在向虚拟通道 CH{sim_noise_ch} 注入强度为 {sim_noise_level} 的高斯噪声!")

            # 生成复高斯白噪声 (Circularly Symmetric Complex Gaussian Noise)
            # 形状匹配: (chirp_per_tx, real_sample_points)
            noise_shape = iq_virtual[sim_noise_ch].shape

            # 实部虚部独立生成，标准差为 sim_noise_level
            # 实际叠加功率会是 2 * level^2
            noise_real = np.random.normal(0, sim_noise_level, noise_shape)
            noise_imag = np.random.normal(0, sim_noise_level, noise_shape)
            complex_noise = noise_real + 1j * noise_imag

            # 叠加噪声到指定通道
            iq_virtual[sim_noise_ch] += complex_noise
        else:
            print(f"[Simulation Error] 无效的噪声通道索引: {sim_noise_ch}")
    # ==========================================================

    # 应用窗函数
    if window is not None:
        if len(window) != real_sample_points:
            raise ValueError(f"window 长度 {len(window)} 必须等于真实采样点 {real_sample_points}")
        iq_virtual = iq_virtual * window[np.newaxis, np.newaxis, :]

    # 最终返回 (4, chirp_per_tx, real_sample_points)
    return iq_virtual

def reorder_frame_TDMMIMO_adaptive_noise(frame_bytes: bytes, chirp: int, real_sample_points: int, txrx: int,
                                         window: np.ndarray | None = None,
                                         sim_noise_ch: int = -1,         # 注入噪声的通道索引 (0-3)
                                         sim_noise_level: float = 0.0,   # [手动模式] 固定噪声标准差
                                         noise_auto_scale: bool = True,  # [新增] 是否开启自适应噪声强度
                                         noise_ratio: float = 1.0        # [新增] 噪声与主峰的比例系数 (1.0 = 噪声底噪与主峰齐平)
                                         ) -> np.ndarray:
    """
    (最终方案 v9 - 自适应噪声注入)

    功能:
    1. 解析 UDP 数据并重排为 TDM-MIMO 虚拟通道格式。
    2. [鲁棒性验证]: 可根据当前帧的目标信号强度，自动注入"相当强度"的高斯白噪声。

    参数详解:
    - noise_auto_scale: True 时，忽略 sim_noise_level，自动计算噪声强度。
    - noise_ratio:      控制噪声相对于主峰的大小。
                        0.1 = 噪声底噪是主峰的 1/10 (轻微干扰)
                        1.0 = 噪声底噪与主峰持平 (目标完全被淹没，0dB SNR)
    """

    # --- 0. 基本参数和检查 ---
    if txrx != 4:
        raise ValueError("此重排逻辑专为 TXRXTYPE == 4 (TDM-MIMO) 设计")

    data = np.frombuffer(frame_bytes, dtype=np.int16)

    total_chirp_tdm = chirp
    num_rx_physical = 2
    num_c_loops = (chirp ) // 2
    expected_int16s = num_c_loops * 4 * 512

    if data.size != expected_int16s:
        print(f"[Warning] 帧数据大小错误: 期望 {expected_int16s}, 实际 {data.size}")
        return None

    chirp_per_tx = chirp // 2

    # --- 1. “解交错” (Undo C code's interleaving) ---
    try:
        data_blocks = data.reshape((num_c_loops, 4, 512))
    except Exception as e:
        raise ValueError(f"Reshape 失败 (步骤1): {e}")

    tx0_data = data_blocks[:, 0:2, :].reshape((chirp_per_tx, 1024))
    tx1_data = data_blocks[:, 2:4, :].reshape((chirp_per_tx, 1024))

    # --- 2. 构建 TDM 帧 ---
    try:
        tx0_iq = tx0_data.reshape((chirp_per_tx, num_rx_physical, real_sample_points, 2))
        tx1_iq = tx1_data.reshape((chirp_per_tx, num_rx_physical, real_sample_points, 2))
    except ValueError as e:
        raise ValueError(f"Reshape 失败 (步骤2): {e}")

    tdm_frame = np.zeros((total_chirp_tdm, num_rx_physical, real_sample_points, 2), dtype=np.int16)
    tdm_frame[1::2, :, :, :] = tx1_iq
    tdm_frame[0::2, :, :, :] = tx0_iq

    # --- 3. 创建虚拟通道 ---
    iq_complex = tdm_frame[..., 1] + 1j * tdm_frame[..., 0]

    v0 = iq_complex[1::2, 0, :]  # TX0 -> RX0
    v1 = iq_complex[1::2, 1, :]  # TX0 -> RX1
    v2 = iq_complex[0::2, 0, :]  # TX1 -> RX0
    v3 = iq_complex[0::2, 1, :]  # TX1 -> RX1

    # 堆叠成 (4, chirp_per_tx, real_sample_points)
    # 注意：此时还是纯净信号
    iq_virtual = np.stack([v0, v1, v2, v3], axis=0).astype('complex64')

    # ==========================================================
    # --- [核心修改] 4. 自适应注入半实物仿真噪声 ---
    # ==========================================================
    if sim_noise_ch >= 0:
        if 0 <= sim_noise_ch < 4:
            target_ch_data = iq_virtual[sim_noise_ch] # 获取该通道数据 (16, 256)
            current_sigma = sim_noise_level # 默认使用手动值

            # --- 自动计算噪声强度逻辑 ---
            if noise_auto_scale:
                # 1. 快速进行 1D-FFT (Range FFT) 以寻找主峰
                # 为了速度，只取第一个 chirp 或者取所有 chirp 的平均谱
                # 这里我们对所有 chirp 做 FFT 并取最大值，确保捕捉到最强目标
                fft_temp = np.fft.fft(target_ch_data, axis=1)
                fft_mag = np.abs(fft_temp)

                # 2. 找到当前帧、当前通道的最大峰值幅度 (Signal Peak)
                signal_peak_mag = np.max(fft_mag)

                # 3. 反推时域噪声标准差
                # 公式: Sigma_time = (Signal_Peak * Ratio) / sqrt(N_points)
                # 解释: FFT 处理增益为 N，但噪声是非相干叠加，幅度增益为 sqrt(N)
                current_sigma = (signal_peak_mag * noise_ratio) / np.sqrt(real_sample_points)

                # 保护措施：如果完全没有信号（全是0），防止 sigma 为 0
                if current_sigma < 1e-6:
                    current_sigma = 10.0

            # --- 生成并注入噪声 ---
            if current_sigma > 0:
                noise_shape = target_ch_data.shape
                # 生成复高斯白噪声
                noise_real = np.random.normal(0, current_sigma, noise_shape)
                noise_imag = np.random.normal(0, current_sigma, noise_shape)
                complex_noise = noise_real + 1j * noise_imag

                # 叠加噪声
                iq_virtual[sim_noise_ch] += complex_noise

                # [可选] 打印调试信息，观察自动计算出的噪声水平
                print(f"[AutoNoise] CH:{sim_noise_ch} Peak:{signal_peak_mag:.1f} -> Inject Sigma:{current_sigma:.1f} (Ratio:{noise_ratio})")
        else:
            print(f"[Simulation Error] 无效的噪声通道索引: {sim_noise_ch}")
    # ==========================================================

    # 应用窗函数 (注意：窗函数通常在加噪之后，或者加噪之前？
    # 物理上噪声是进入天线后的，所以应该先加噪再加窗，符合现在的顺序)
    if window is not None:
        if len(window) != real_sample_points:
            raise ValueError(f"window 长度不对")
        iq_virtual = iq_virtual * window[np.newaxis, np.newaxis, :]

    return iq_virtual

# ================== 组装状态类 ==================
class AsmState:
    """用于跟踪单帧组装的状态"""
    # 状态
    awaiting_cfg: bool = True     # True=等待配置包；False=收集数据包
    # 配置
    current_frame_id: int = -1
    sample_number: int = 0
    chirp_number:  int = 0
    tx_rx_type:    int = 1
    # 拼帧
    total_bytes:   int = 0
    total_pkts:    int = 0
    frame_buf:     bytearray = bytearray()
    pkg_cnt:       int = 0
    # 超时 (方案A引入)
    last_seen:     float = 0.0

# ================== 融合后的新组装器 ==================
class RobustFrameAssembler(threading.Thread):
    """
    消费UDP原始包，组装成帧 (bytes)，并转换为 IQ 数据。
    """
    def __init__(self, raw_queue: queue.Queue, frame_queue: queue.Queue, timeout: float = 1.0):
        super().__init__(daemon=True)
        self.raw_queue = raw_queue
        self.frame_queue = frame_queue
        self.timeout = timeout
        self.stop_event = threading.Event()

        self.s = AsmState()
        self.last_emitted_frame_id: Optional[int] = None

    def _log_error(self, message: str):
        """辅助函数：向GUI发送错误/日志消息"""
        try:
            self.frame_queue.put_nowait(('__error__', message))
        except queue.Full:
            pass

    def _reset_to_wait_cfg(self, log_msg: Optional[str] = None):
        """重置状态机到“等待配置包”状态"""
        if log_msg:
            self._log_error(log_msg)

        self.s.awaiting_cfg = True
        self.s.total_pkts = 0
        self.s.pkg_cnt = 0
        self.s.frame_buf = bytearray()
        self.s.current_frame_id = -1
        self.s.last_seen = 0.0

    def parse_header(self, buf: bytes) -> Tuple[Optional[int], int, Optional[int], Optional[int], Optional[int]]:
        """
        解析包头
        返回 (frame_id, packet_id, chirp_num, sample_point, tx_rx_type)
        packet_id: 0 = 配置包, -1 = 数据包
        """
        # buffer length check
        if len(buf) < 24:
            return None, -1, None, None, None

        first_number = int.from_bytes(buf[0:4], 'little')
        second_number = int.from_bytes(buf[4:8], 'little')

        if first_number == 0x11223344 and second_number == 0x44332211:
            # 这是一个配置包 (First Frame)
            frame_id = int.from_bytes(buf[8:12], 'little')
            chirp_num = int.from_bytes(buf[12:16], 'little')
            sample_point = int.from_bytes(buf[16:20], 'little')
            tx_rx_type = int.from_bytes(buf[20:24], 'little')
            return frame_id, 0, chirp_num, sample_point, tx_rx_type

        # 不是配置包，当做数据包处理
        return None, -1, None, None, None

    def check_timeout(self):
        if not self.s.awaiting_cfg and self.s.last_seen > 0:
            if (time.time() - self.s.last_seen) > self.timeout:
                self._reset_to_wait_cfg(f"⚠️ 帧 {self.s.current_frame_id} 超时，已丢弃")

    def run(self):
        while not self.stop_event.is_set():
            try:
                # 1. 从队列获取原始包
                item = self.raw_queue.get(timeout=0.1)
            except queue.Empty:
                # 2.  队列为空时，检查超时
                self.check_timeout()
                continue

            # 转发错误消息
            if isinstance(item, tuple) and item and item[0] == '__recv_error__':
                self._log_error(item[1])
                continue

            ts, buf = item
            if len(buf) != PKT_SIZE:
                continue # 忽略长度不符的包

            # 3. 解析包头
            frame_id, packet_id, chirp_num, sample_point, tx_rx_type = self.parse_header(buf)

            # 4. 逻辑处理
            if packet_id == 0:
                # --- 这是一个配置包 (方案B的 'if self.s.awaiting_cfg' 逻辑) ---

                # 如果我们正在组装上一帧，说明上一帧丢包了
                if not self.s.awaiting_cfg:
                    self._log_error(f"⚠️ 帧 {self.s.current_frame_id} 未完成 (仅收到 {self.s.pkg_cnt}/{self.s.total_pkts} 包)，被新帧 {frame_id} 覆盖")

                # 合理性校验
                if not (1 <= sample_point <= MAX_SAMPLES and 1 <= chirp_num <= MAX_CHIRPS):
                    self._reset_to_wait_cfg(f"⚠️ 帧 {frame_id} 配置越界，已丢弃")
                    continue

                # TxRxType (TDM-MIMO)
                if tx_rx_type != 4:
                    # GUI只接受 TX2RX2 (type 4)
                    self._reset_to_wait_cfg(f"⚠️ 帧 {frame_id} txrx_type={tx_rx_type} (非TDM-MIMO)，已丢弃")
                    continue

                # 4 虚拟天线 * chirp * sample * (I/Q各int16=4字节)
                # B方案的TDM重排函数 reorder_frame_TDMMIMO 假设 n_rx=2
                # 所以总字节数 = total_chirp * n_rx(2) * sample * 4
                total_bytes = chirp_num * 2 * sample_point * 4

                if total_bytes <= 0 or total_bytes > MAX_FRAME_BYTES:
                    self._reset_to_wait_cfg(f"⚠️ 帧 {frame_id} total_bytes={total_bytes} 超限，丢弃配置")
                    continue

                # 准备缓冲区
                try:
                    self.s.frame_buf = bytearray(total_bytes)
                except MemoryError:
                    self._reset_to_wait_cfg(f"⚠️ 帧 {frame_id} 申请内存 {total_bytes}B 失败")
                    continue

                # 更新状态机
                self.s.total_bytes = total_bytes
                self.s.total_pkts = (total_bytes + PKT_SIZE - 1) // PKT_SIZE
                self.s.pkg_cnt = 0
                self.s.awaiting_cfg = False
                self.s.current_frame_id = frame_id
                self.s.sample_number = sample_point
                self.s.chirp_number = chirp_num
                self.s.tx_rx_type = tx_rx_type
                self.s.last_seen = time.time()

            else:
                # --- 这是一个数据包 ---

                # 如果还在等配置包，说明这是孤儿包，丢弃
                if self.s.awaiting_cfg:
                    continue

                # 填充数据
                offset = self.s.pkg_cnt * PKT_SIZE
                if offset >= self.s.total_bytes:
                    # 缓冲区溢出，这不应该发生，重置状态机
                    self._reset_to_wait_cfg(f"⛔ 帧 {self.s.current_frame_id} 缓冲区溢出，已丢弃")
                    continue

                n = min(PKT_SIZE, self.s.total_bytes - offset)
                self.s.frame_buf[offset:offset + n] = buf[:n]
                self.s.pkg_cnt += 1
                self.s.last_seen = time.time() # (来自方案A) 更新时间戳

                # 5. 检查帧是否完成
                if self.s.pkg_cnt >= self.s.total_pkts:
                    # --- 帧组装完成 ---

                    # [关键] 获取原始bytes，而不是转换IQ
                    frame_bytes = bytes(self.s.frame_buf)

                    fid = self.s.current_frame_id

                    # [关键] 获取配置信息，准备传递给GUI线程
                    sample = self.s.sample_number
                    chirp = self.s.chirp_number
                    txrx = self.s.tx_rx_type

                    # 连续性检查
                    if self.last_emitted_frame_id is not None and fid != self.last_emitted_frame_id + 1:
                        missing = list(range(self.last_emitted_frame_id + 1, fid)) if fid > self.last_emitted_frame_id else []
                        if missing:
                            self._log_error(f"⚠️ 缺失帧: {missing}")
                    self.last_emitted_frame_id = fid

                    try:
                        if self.frame_queue.full():
                            try:
                                self.frame_queue.get_nowait() # 队列满，丢弃最旧的
                            except queue.Empty:
                                pass

                        # [关键] 放入 5 个元素
                        self.frame_queue.put_nowait((fid, frame_bytes, sample, chirp, txrx))
                    except Exception as e:
                        self._log_error(f"⛔ 帧 {fid} 推入队列失败: {e}")
                    self._reset_to_wait_cfg()

    def stop(self):
        self.stop_event.set()
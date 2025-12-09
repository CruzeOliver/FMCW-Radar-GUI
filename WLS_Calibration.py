import numpy as np
import warnings
from scipy.fft import fft, ifft, fftfreq
###==================== 时延校准 ===================

def align_iq_strong(iq_virtual: np.ndarray, ref_ch_idx: int = 0) -> np.ndarray:
    """
    [强力版] 通道对齐：应对通道间存在巨大时延的情况。

    逻辑流程：
    1. 粗对齐 (Coarse): 使用包络互相关，计算整数采样点的位移，使用 np.roll 暴力搬移。
    2. 精对齐 (Fine):   在粗对齐的基础上，使用频域相位斜率修补剩下的亚采样误差。

    Args:
        iq_virtual: (num_ch, chirps, samples) 复数数据
        ref_ch_idx: 参考通道索引

    Returns:
        aligned_iq: 对齐后的数据
    """
    num_ch, n_chirps, n_samples = iq_virtual.shape
    aligned_iq = np.zeros_like(iq_virtual, dtype=np.complex64)

    # 1. 获取参考通道的平均包络 (作为对齐的标准)
    #    取平均是为了抑制噪声，取 abs 是为了只看能量位置
    ref_data = iq_virtual[ref_ch_idx]
    ref_avg_complex = np.mean(ref_data, axis=0)
    ref_envelope = np.abs(ref_avg_complex)

    # 为了提高互相关精度，去直流 (可选，视波形情况而定)
    ref_envelope = ref_envelope - np.mean(ref_envelope)

    for ch in range(num_ch):
        # 如果是参考通道，直接拷贝
        if ch == ref_ch_idx:
            aligned_iq[ch] = iq_virtual[ch]
            continue

        cur_data = iq_virtual[ch]
        cur_avg_complex = np.mean(cur_data, axis=0)
        cur_envelope = np.abs(cur_avg_complex)
        cur_envelope = cur_envelope - np.mean(cur_envelope)

        # ======================================================
        # 步骤 A: 整数级粗对齐 (Integer Shift)
        # ======================================================
        # 使用互相关 (Cross-Correlation) 寻找两个包络的最佳重合点
        # mode='full' 会返回长度为 2*N-1 的数组
        correlation = np.correlate(ref_envelope, cur_envelope, mode='full')

        # 找到相关性最大的索引
        best_match_idx = np.argmax(correlation)

        # 计算位移量 (lags)
        # correlate 的中心点索引是 n_samples - 1
        shift_integer = best_match_idx - (n_samples - 1)

        # [核心操作] 暴力搬移数据
        # np.roll 会循环移位，对于 FMCW 雷达这种周期性信号通常是安全的
        # 如果 shift_integer > 0，说明 cur 在 ref 左边，要向右移
        iq_coarse_aligned = np.roll(cur_data, shift_integer, axis=-1)

        # 打印一下移了多少，方便您了解板子差异有多大
        print(f"CH{ch} 粗对齐: 移动了 {shift_integer} 个采样点")

        # ======================================================
        # 步骤 B: 亚采样精对齐 (Sub-sample Fine Tuning)
        # ======================================================
        # 经过步骤A，峰值误差应该在 0.5 个点以内了。
        # 现在用之前的 "相位斜率法" 修剩下的误差。

        # 1. 更新当前波形 (用粗对齐后的数据)
        cur_avg_coarse = np.mean(iq_coarse_aligned, axis=0)

        # 2. 转频域 (加窗)
        win = np.hanning(n_samples)
        fft_ref = np.fft.fftshift(np.fft.fft(ref_avg_complex * win))
        fft_cur = np.fft.fftshift(np.fft.fft(cur_avg_coarse * win))

        # 3. 插值找精确峰值位置
        def get_precise_peak_idx(fft_mag):
            k = np.argmax(fft_mag)
            if k == 0 or k == len(fft_mag)-1: return float(k)
            y0, y1, y2 = fft_mag[k-1], fft_mag[k], fft_mag[k+1]
            denom = y0 - 2*y1 + y2
            if denom == 0: return float(k)
            return k - (y2 - y0) / (2 * denom) # Parabolic interpolation

        peak_ref = get_precise_peak_idx(np.abs(fft_ref))
        peak_cur = get_precise_peak_idx(np.abs(fft_cur))

        # 4. 计算剩余的微小误差
        shift_fractional = peak_ref - peak_cur

        # 5. 应用相位斜率补偿
        # 对 "未加窗" 的粗对齐数据做 FFT
        raw_fft_frames = np.fft.fftshift(np.fft.fft(iq_coarse_aligned, axis=-1), axes=-1)

        k_vec = np.arange(n_samples) - n_samples // 2
        phase_slope = np.exp(-1j * 2 * np.pi * k_vec * shift_fractional / n_samples)

        corrected_fft = raw_fft_frames * phase_slope[np.newaxis, :]

        # 6. IFFT 还原
        aligned_iq[ch] = np.fft.ifft(np.fft.ifftshift(corrected_fft, axes=-1), axis=-1)

    return aligned_iq


def align_iq_virtual(iq_virtual: np.ndarray, ref_ch_idx: int = 0) -> np.ndarray:
    """
    修正版 TDM-MIMO 虚拟通道 IQ 时域对齐（消除前后半段翻转问题）

    Args:
        iq_virtual: (4, chirp_per_tx, samples) 复数 IQ 数据
        ref_ch_idx: 参考通道索引 (默认 0)

    Returns:
        aligned_iq: 对齐后的复数 IQ 数据，shape 与输入一致
    """
    num_ch, chirp_per_tx, num_samples = iq_virtual.shape
    aligned_iq = np.zeros_like(iq_virtual, dtype=np.complex64)

    # 1. 参考通道平均波形
    ref_wave = iq_virtual[ref_ch_idx].mean(axis=0)

    for ch in range(num_ch):
        if ch == ref_ch_idx:
            aligned_iq[ch] = iq_virtual[ch]
            continue

        # 当前通道平均波形
        cur_wave = iq_virtual[ch].mean(axis=0)

        # -------------------------
        # 2. 整数采样对齐（互相关）
        # -------------------------
        corr = np.correlate(ref_wave.real, cur_wave.real, mode='full')
        shift = corr.argmax() - (num_samples - 1)
        aligned_iq[ch] = np.roll(iq_virtual[ch], shift, axis=-1)

        # -------------------------
        # 3. 亚样补偿（频域 phase slope）
        # -------------------------
        # FFT shift 保证前后半段对称处理
        fft_ch = np.fft.fftshift(np.fft.fft(aligned_iq[ch], axis=-1), axes=-1)
        fft_ref = np.fft.fftshift(np.fft.fft(ref_wave, axis=-1))

        # 计算亚样偏移（峰值差）
        ref_peak = np.argmax(np.abs(fft_ref))
        cur_peak = np.argmax(np.abs(fft_ch))
        sub_shift = ref_peak - cur_peak
        if abs(sub_shift) > 1e-6:
            k = np.arange(num_samples) - num_samples // 2  # 对应 fftshift 后索引
            phase_slope = np.exp(-1j * 2 * np.pi * k * sub_shift / num_samples)
            fft_ch *= phase_slope

        # IFFT 回时域，并恢复顺序
        aligned_iq[ch] = np.fft.ifft(np.fft.ifftshift(fft_ch, axes=-1), axis=-1)

    return aligned_iq

###==================== 基于最小二乘法进行IQ校准(2DFFT峰值点) ===================
def amplitude_calibration(zij_vector: np.ndarray):
    """
    使用最小二乘法进行幅度校准，返回校准因子矩阵（包含归一化还原）。

    输入：
        zij_vector: 形状为 (n_ant,) 的复数向量，每个元素代表虚拟通道 (tx, rx) 的响应
    输出：
        alpha_matrix: 形状为 (n_ant, n_ant) 的幅度校准因子矩阵（绝对校准，非相对）
    """
    n_ant = zij_vector.shape[0]
    # 虚拟天线映射（假设你的映射是固定的：4个虚拟通道对应 (tx0,rx0), (tx0,rx1), (tx1,rx0), (tx1,rx1)）
    tx_map = np.array([0, 0, 1, 1])
    rx_map = np.array([0, 1, 0, 1])
    n_tx = len(np.unique(tx_map))  # 实际发射天线数（这里是2）
    n_rx = len(np.unique(rx_map))  # 实际接收天线数（这里是2）

    # 提取观测幅度（每个虚拟通道的幅度）
    y_ij = np.abs(zij_vector)

    # 初始化发射/接收幅度因子（以第0个天线为基准，初始为1）
    alpha_tx = np.ones(n_tx)
    alpha_rx = np.ones(n_rx)

    # 迭代求解最小二乘（固定一方，更新另一方）
    max_iterations = 100
    tol = 1e-6  # 收敛阈值
    for _ in range(max_iterations):
        alpha_tx_old = alpha_tx.copy()
        alpha_rx_old = alpha_rx.copy()

        # 固定发射因子，更新接收因子（每个rx对应的虚拟通道）
        for j in range(n_rx):
            # 找到所有属于第j个接收天线的虚拟通道索引
            rx_mask = (rx_map == j)
            if np.any(rx_mask):
                # 最小二乘：alpha_rx[j] 使得 sum((y_ij - alpha_tx[i] * alpha_rx[j])^2) 最小
                numerator = np.sum(y_ij[rx_mask] * alpha_tx[tx_map[rx_mask]])
                denominator = np.sum(alpha_tx[tx_map[rx_mask]] ** 2)
                if denominator > 1e-9:
                    alpha_rx[j] = numerator / denominator

        # 固定接收因子，更新发射因子（每个tx对应的虚拟通道）
        for i in range(n_tx):
            # 找到所有属于第i个发射天线的虚拟通道索引
            tx_mask = (tx_map == i)
            if np.any(tx_mask):
                # 最小二乘：alpha_tx[i] 使得 sum((y_ij - alpha_tx[i] * alpha_rx[j])^2) 最小
                numerator = np.sum(y_ij[tx_mask] * alpha_rx[rx_map[tx_mask]])
                denominator = np.sum(alpha_rx[rx_map[tx_mask]] ** 2)
                if denominator > 1e-9:
                    alpha_tx[i] = numerator / denominator

        # 检查收敛（参数变化小于阈值则停止）
        if np.max(np.abs(alpha_tx - alpha_tx_old)) < tol and np.max(np.abs(alpha_rx - alpha_rx_old)) < tol:
            break

    # 计算归一化前的“理论基准幅度”（用于还原）
    # 以参考通道（tx0, rx0）的实际幅度为基准，确保校准后不丢失原始量级
    ref_idx = np.where((tx_map == 0) & (rx_map == 0))[0][0]  # 参考虚拟通道索引
    theoretical_ref_amplitude = alpha_tx[0] * alpha_rx[0]  # 校准模型中的基准幅度
    actual_ref_amplitude = y_ij[ref_idx]  # 实际观测的基准幅度
    scale_factor = actual_ref_amplitude / theoretical_ref_amplitude  # 还原比例（消除归一化影响）

    # 应用还原比例，确保校准后的基准通道幅度与实际一致
    alpha_tx *= scale_factor
    alpha_rx *= 1  # 发射/接收因子中只需一个乘比例，避免重复放大（这里选择tx）

    # 构建幅度校准矩阵（实际发射×接收天线的矩阵）
    alpha_matrix = np.outer(alpha_tx, alpha_rx)

    return alpha_matrix

def phase_calibration(
    zij_vector: np.ndarray,
    ref_tx: int = 0,
    ref_rx: int = 0
) -> np.ndarray:
    """
    基于固定天线排布的相位校准（2发2收，虚拟通道映射固定）。
    物理模型：虚拟通道相位 = 发射天线相位 + 接收天线相位。

    输入：
        zij_vector: 形状为 (4,) 的复数向量，4个虚拟通道的峰值响应（顺序：[0,1,2,3]）
        ref_tx: 参考发射天线编号（0或1，默认0）
        ref_rx: 参考接收天线编号（0或1，默认0）
    输出：
        phi_matrix: 形状为 (2, 2) 的相位校准矩阵（发射×接收），元素为相位值（rad）
    """
    # 固定天线映射（根据你的实体与虚拟天线排布）
    # 虚拟通道索引：0→TX0RX0，1→TX0RX1，2→TX1RX0，3→TX1RX1
    tx_map = np.array([0, 0, 1, 1])  # 虚拟通道→发射天线（0:TX0，1:TX1）
    rx_map = np.array([0, 1, 0, 1])  # 虚拟通道→接收天线（0:RX0，1:RX1）

    n_virtual = zij_vector.shape[0]
    if n_virtual != 4:
        raise ValueError("zij_vector必须为4元素向量（对应4个虚拟通道）")

    # 1. 提取实体天线信息（固定2发2收）
    tx_ids = np.unique(tx_map)  # [0,1]
    rx_ids = np.unique(rx_map)  # [0,1]
    n_tx, n_rx = len(tx_ids), len(rx_ids)  # 均为2

    # 2. 相位解缠绕（消除[-π, π]跳变）
    raw_phase = np.angle(zij_vector)
    unwrapped_phase = np.unwrap(raw_phase)

    # 3. 构建线性方程组：phi_tx[t] + phi_rx[r] = 观测相位（以参考天线为基准）
    tx_idx = {t: i for i, t in enumerate(tx_ids)}  # {0:0, 1:1}
    rx_idx = {r: i for i, r in enumerate(rx_ids)}  # {0:0, 1:1}
    ref_tx_idx = tx_idx[ref_tx]
    ref_rx_idx = rx_idx[ref_rx]

    num_unknowns = (n_tx - 1) + (n_rx - 1)  # 2个未知数（非参考天线相位）
    A = np.zeros((n_virtual, num_unknowns))
    b = np.zeros(n_virtual)

    for i in range(n_virtual):
        t = tx_map[i]
        r = rx_map[i]
        t_idx = tx_idx[t]
        r_idx = rx_idx[r]

        # 方程右侧：当前相位 - 参考通道相位
        ref_mask = (tx_map == ref_tx) & (rx_map == ref_rx)
        ref_phase = unwrapped_phase[ref_mask][0] if np.any(ref_mask) else 0
        b[i] = unwrapped_phase[i] - ref_phase

        # 方程左侧：非参考天线相位系数
        if t != ref_tx:
            tx_unknown_idx = t_idx - (1 if t_idx > ref_tx_idx else 0)
            A[i, tx_unknown_idx] = 1.0
        if r != ref_rx:
            rx_unknown_idx = (n_tx - 1) + (r_idx - (1 if r_idx > ref_rx_idx else 0))
            A[i, rx_unknown_idx] = 1.0

    # 4. 最小二乘求解
    x, residuals, rank, _ = np.linalg.lstsq(A, b, rcond=None)
    if rank < num_unknowns:
        print(f"警告：相位方程组秩不足（有效方程数{rank} < 未知数{num_unknowns}）")

    # 5. 重构发射/接收相位（参考天线相位为0）
    phi_tx = np.zeros(n_tx)
    phi_rx = np.zeros(n_rx)
    tx_unknowns = x[:n_tx - 1]
    rx_unknowns = x[n_tx - 1:]

    tx_unknown_idx = 0
    for t_idx in range(n_tx):
        if t_idx != ref_tx_idx:
            phi_tx[t_idx] = tx_unknowns[tx_unknown_idx]
            tx_unknown_idx += 1

    rx_unknown_idx = 0
    for r_idx in range(n_rx):
        if r_idx != ref_rx_idx:
            phi_rx[r_idx] = rx_unknowns[rx_unknown_idx]
            rx_unknown_idx += 1

    # 6. 构建相位矩阵（发射相位 + 接收相位）
    phi_matrix = np.outer(phi_tx, np.ones(n_rx)) + np.outer(np.ones(n_tx), phi_rx)
    return phi_matrix

###==================== 基于WLS进行IQ校准(2DFFT峰值点) ===================

# [NEW] 辅助函数 1：从单帧频谱中估计噪声功率
def estimate_noise_power_from_frame(spectrum_2d, peak_idx, excl_win=3, mask_edges=True):
    # spectrum_2d: 2D complex or magnitude array (range x doppler or similar)
    # peak_idx: (r,c) or (row,col) index of detected peak
    r0, c0 = peak_idx
    mask = np.ones(spectrum_2d.shape, dtype=bool)
    # exclude a small window around peak
    mask[max(0, r0-excl_win): r0+excl_win+1,
         max(0, c0-excl_win): c0+excl_win+1] = False
    if mask_edges:
        # optionally exclude DC/zero axes (adjust depending on your layout)
        mask[0, :] = False
        mask[:, 0] = False
    bg = np.abs(spectrum_2d[mask])
    if bg.size == 0:
        return 1e-9
    # robust estimator: median power -> convert to mean approx
    median_power = np.median(bg**2)
    # convert median to mean approx for Rayleigh-like mag: mean_power ≈ k * median_power
    # But simpler: use median_power directly and floor
    return max(median_power, 1e-12)

def calculate_weights(zij_avg: np.ndarray,
                              noise_power_vec: np.ndarray,
                              n_obs: int = 1,
                              eps: float = 1e-3,
                              max_w: float = 1e4,
                              normalize: bool = True,
                              transform: str = 'linear'):
    """
    zij_avg: (M,) complex, averaged over n_obs frames (M = K*L)
    noise_power_vec: (M,) estimated noise power per virtual channel (same units as |z|^2)
    returns w: (M,) weights (non-negative)
    """
    M = zij_avg.shape[0]
    # avoid zeros
    noise_power_vec = np.maximum(noise_power_vec, 1e-12)

    # signal power after averaging
    sig_power = np.abs(zij_avg)**2  # |mean(z)|^2

    # effective noise power after averaging: sigma2 / n_obs
    noise_eff = noise_power_vec / max(1, n_obs)

    # raw SNR estimate (non-negative)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        snr_raw = np.maximum((sig_power / noise_eff) - 1.0, 0.0)

    # optional transform to compress dynamic range
    if transform == 'log':
        w = np.log1p(snr_raw)  # log(1+snr)
    elif transform == 'sqrt':
        w = np.sqrt(snr_raw)
    else:
        w = snr_raw  # identity

    # clamp and floor
    w = np.nan_to_num(w, nan=eps, posinf=max_w, neginf=eps)
    w = np.clip(w, eps, max_w)

    if normalize:
        w = w / np.max(w)

    return w


def amplitude_calibration_wals(zij_vector: np.ndarray, weights: np.ndarray):
    """
    使用 [加权 W-ALS] 进行幅度校准。
    """
    n_ant = zij_vector.shape[0]
    tx_map = np.array([0, 0, 1, 1])
    rx_map = np.array([0, 1, 0, 1])
    n_tx = 2
    n_rx = 2

    y_ij = np.abs(zij_vector)

    # [NEW] 将 (4,) 权重向量映射为 (2, 2) 矩阵
    w_ij_matrix = np.zeros((n_tx, n_rx))
    w_ij_matrix[tx_map, rx_map] = weights

    alpha_tx = np.ones(n_tx)
    alpha_rx = y_ij[[0, 1]].mean() * np.ones(n_rx) # 简单初始化

    max_iterations = 100
    tol = 1e-6
    for _ in range(max_iterations):
        alpha_tx_old = alpha_tx.copy()
        alpha_rx_old = alpha_rx.copy()

        # 1. 更新 Rx (j=0 to n_rx-1)
        for j in range(n_rx):
            w_j = w_ij_matrix[:, j] # (K,) 权重向量
            y_j = y_ij[rx_map == j] # (K,) 观测向量
            a_tx = alpha_tx[tx_map[rx_map == j]]

            # [MODIFIED] num = sum(w_ij * y_ij * a_tx_i)
            # [MODIFIED] den = sum(w_ij * a_tx_i^2)
            numerator = np.dot(w_j * y_j, a_tx)
            denominator = np.dot(w_j, a_tx**2)
            if denominator > 1e-9:
                alpha_rx[j] = numerator / denominator

        # 2. 更新 Tx (i=0 to n_tx-1)
        for i in range(n_tx):
            w_i = w_ij_matrix[i, :] # (L,) 权重向量
            y_i = y_ij[tx_map == i] # (L,) 观测向量
            a_rx = alpha_rx[rx_map[tx_map == i]]

            # [MODIFIED] num = sum(w_ij * y_ij * a_rx_j)
            # [MODIFIED] den = sum(w_ij * a_rx_j^2)
            numerator = np.dot(w_i * y_i, a_rx)
            denominator = np.dot(w_i, a_rx**2)
            if denominator > 1e-9:
                alpha_tx[i] = numerator / denominator

        if np.max(np.abs(alpha_tx - alpha_tx_old)) < tol and \
           np.max(np.abs(alpha_rx - alpha_rx_old)) < tol:
            break

    # [MODIFIED] 归一化：我们只关心相对因子
    # 以 tx0, rx0 为参考 (我们假设它们是 [0,0])
    ref_factor = alpha_tx[0] * alpha_rx[0]
    alpha_tx_est = alpha_tx / np.sqrt(ref_factor)
    alpha_rx_est = alpha_rx / np.sqrt(ref_factor)

    # 输出相对校准矩阵
    alpha_matrix = np.outer(alpha_tx_est, alpha_rx_est)

    return alpha_matrix

def phase_calibration_wls(zij_vector: np.ndarray, weights: np.ndarray, ref_tx: int = 0, ref_rx: int = 0):
    """
    使用 [加权 WLS] 进行相位校准。
    """
    tx_map = np.array([0, 0, 1, 1])
    rx_map = np.array([0, 1, 0, 1])
    n_tx, n_rx = 2, 2
    n_virtual = 4

    raw_phase = np.angle(zij_vector)
    unwrapped_phase = np.unwrap(raw_phase)

    tx_ids = np.unique(tx_map)
    rx_ids = np.unique(rx_map)
    tx_idx = {t: i for i, t in enumerate(tx_ids)}
    rx_idx = {r: i for i, r in enumerate(rx_ids)}
    ref_tx_idx = tx_idx[ref_tx]
    ref_rx_idx = rx_idx[ref_rx]

    num_unknowns = (n_tx - 1) + (n_rx - 1)

    # [MODIFIED] 我们只使用 n_virtual - 1 个方程
    num_eqs = n_virtual - 1
    A = np.zeros((num_eqs, num_unknowns))
    b = np.zeros(num_eqs)
    W_diag = np.zeros(num_eqs) # [NEW] WLS 权重

    ref_mask = (tx_map == ref_tx) & (rx_map == ref_rx)
    ref_phase = unwrapped_phase[ref_mask][0] if np.any(ref_mask) else 0

    eq_idx = 0
    for i in range(n_virtual):
        if tx_map[i] == ref_tx and rx_map[i] == ref_rx:
            continue # 跳过参考通道

        t = tx_map[i]
        r = rx_map[i]
        t_idx = tx_idx[t]
        r_idx = rx_idx[r]

        b[eq_idx] = unwrapped_phase[i] - ref_phase

        if t != ref_tx:
            tx_unknown_idx = t_idx - (1 if t_idx > ref_tx_idx else 0)
            A[eq_idx, tx_unknown_idx] = 1.0
        if r != ref_rx:
            rx_unknown_idx = (n_tx - 1) + (r_idx - (1 if r_idx > ref_rx_idx else 0))
            A[eq_idx, rx_unknown_idx] = 1.0

        # [NEW] 从权重向量中获取权重
        W_diag[eq_idx] = weights[i]
        eq_idx += 1

    # 4. [MODIFIED] 最小二乘求解 -> WLS 求解
    # x = (A^T W A)^-1 A^T W b
    W = np.diag(W_diag)
    try:
        # A.T @ W @ A
        ATWA = A.T @ W @ A
        # A.T @ W @ b
        ATWb = A.T @ W @ b
        # (A^T W A)^-1
        ATWA_inv = np.linalg.inv(ATWA)

        x = ATWA_inv @ ATWb

    except np.linalg.LinAlgError:
        print("警告：WLS 求解失败，退化为标准 LS。")
        x, _, _, _ = np.linalg.lstsq(A, b, rcond=None)

    # 5. 重构相位（与之前相同）
    phi_tx = np.zeros(n_tx)
    phi_rx = np.zeros(n_rx)
    # ... [重构逻辑与您原代码相同] ...
    tx_unknowns = x[:n_tx - 1]
    rx_unknowns = x[n_tx - 1:]
    tx_unknown_idx = 0
    for t_idx in range(n_tx):
        if t_idx != ref_tx_idx:
            phi_tx[t_idx] = tx_unknowns[tx_unknown_idx]
            tx_unknown_idx += 1
    rx_unknown_idx = 0
    for r_idx in range(n_rx):
        if r_idx != ref_rx_idx:
            phi_rx[r_idx] = rx_unknowns[rx_unknown_idx]
            rx_unknown_idx += 1

    # 6. 构建相位矩阵
    phi_matrix = np.outer(phi_tx, np.ones(n_rx)) + np.outer(np.ones(n_tx), phi_rx)
    return phi_matrix


def apply_channel_calibration(
    iq_data: np.ndarray,
    alpha_matrix: np.ndarray,
    phi_matrix: np.ndarray,
) -> np.ndarray:
    """
    应用幅度和相位校准（基于固定天线排布，无需传入映射参数）。

    输入：
        iq_data: 形状为 (4, n_chirp, n_points) 的IQ数据（4个虚拟通道）
        alpha_matrix: 形状为 (2, 2) 的幅度校准矩阵（发射×接收）
        phi_matrix: 形状为 (2, 2) 的相位校准矩阵（发射×接收）
    输出：
        calibrated_iq: 校准后的IQ数据（与输入形状一致）
    """
    # 固定虚拟通道→实体天线映射
    tx_map = np.array([0, 0, 1, 1])  # 虚拟通道0-3对应发射天线
    rx_map = np.array([0, 1, 0, 1])  # 虚拟通道0-3对应接收天线

    # 校验输入维度
    if iq_data.shape[0] != 4:
        raise ValueError("iq_data第一维度必须为4（对应4个虚拟通道）")
    if alpha_matrix.shape != (2, 2) or phi_matrix.shape != (2, 2):
        raise ValueError("alpha_matrix和phi_matrix必须为(2,2)矩阵（2发2收）")

    # 找到参考通道的绝对幅度校准因子
    # 假设 tx0, rx0 是参考通道，其在 alpha_matrix 中的索引为 [0, 0]
    ref_alpha = alpha_matrix[0, 0]

    # 将每个通道的绝对校准因子转换为相对校准因子
    # 这样，所有通道都会相对于参考通道进行校准
    relative_alpha_matrix = alpha_matrix / ref_alpha

    # 提取每个虚拟通道的相对校准因子
    alpha_vector = relative_alpha_matrix[tx_map, rx_map] # 4元素向量（每个虚拟通道的幅度因子）
    phi_vector = phi_matrix[tx_map, rx_map] # 4元素向量（每个虚拟通道的幅度因子）

    # 幅度补偿：乘以 1.0 / 相对校准因子
    # 这会使校准后的幅度都与参考通道的幅度一致
    amp_comp = 1.0 / alpha_vector[:, np.newaxis, np.newaxis]
    phase_comp = np.exp(-1j * phi_vector[:, np.newaxis, np.newaxis])

    # 应用校准
    calibrated_iq = iq_data * amp_comp * phase_comp

    return calibrated_iq
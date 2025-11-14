import numpy as np
import scipy.linalg
from numpy.linalg import norm
from typing import List, Tuple

# --- 0. 核心参数定义 (根据您的 TDM-MIMO 2Tx/2Rx 结构) ---
K = 2                      # Tx 通道数
L = 2                      # Rx 通道数
M = K * L                  # VA 通道数 = 4

# 物理和迭代参数 (需要从您的全局配置中获取并匹配)
LAMBDA_C = 3e8 / 77e9      # 77 GHz 波长
D_RX = LAMBDA_C / 2        # Rx 阵元间距 (lambda/2)
D_TX = L * D_RX            # Tx 阵元间距 (稀疏阵列)
ILS_ITERATIONS = 20        # 迭代次数
ILS_TOLERANCE = 1e-4       # 收敛阈值

# --------------------------------------------------------
# 辅助函数 1 & 2: 转向矢量 (Steering Vector)
# --------------------------------------------------------
def get_virtual_steering_vector(phi, k, l, d_tx, d_rx, lambda_c):
    """ 计算单个 (k, l) 虚拟阵元的理想转向矢量元素 """
    phase = -2j * np.pi * (k * d_tx + l * d_rx) * np.sin(phi) / lambda_c
    return np.exp(phase)

def get_full_steering_matrix(phi_array, K, L, d_tx, d_rx, lambda_c):
    """
    生成 (M x I) 的理想转向矩阵 H_ideal
    phi_array 可以是单个角度或多个角度数组 (I 维)
    """
    M = K * L
    I = len(phi_array)
    H_ideal = np.zeros((M, I), dtype=complex)
    for i in range(I):
        phi = phi_array[i]
        m = 0
        for k in range(K):
            for l in range(L):
                H_ideal[m, i] = get_virtual_steering_vector(phi, k, l, d_tx, d_rx, lambda_c)
                m += 1
    return H_ideal

# --------------------------------------------------------
# 核心函数 3: 简单角度估计 (Beamforming/FFT)
# --------------------------------------------------------
def simple_doa_estimator(kappa_snapshot: np.ndarray, K, L, d_tx, d_rx, lambda_c):
    """
    简单 Beamforming 峰值搜索 (用于单个 M x 1 快照).

    Args:
        kappa_snapshot (M, 1): 单个目标在 M 个 VA 通道的复数响应。

    Returns:
        float: 单个角度估计值 (弧度)。
    """
    M = K * L

    # 搜索网格
    angle_grid = np.linspace(-np.pi/2, np.pi/2, 361)
    spectrum = []

    for phi in angle_grid:
        # 理想转向矢量 a(phi) (M x 1)
        a_phi = get_full_steering_matrix([phi], K, L, d_tx, d_rx, lambda_c).flatten()

        # 功率 P = | a^H * kappa |^2
        power = np.abs(np.vdot(a_phi, kappa_snapshot.flatten()))**2
        spectrum.append(power)

    peak_index = np.argmax(spectrum)
    return angle_grid[peak_index]

# --------------------------------------------------------
# 核心函数 4: 估计权重 (WLS 权重)
# --------------------------------------------------------
def estimate_target_weights(Kappa_noisy: np.ndarray, phi_ils: np.ndarray, gamma_va_ils: np.ndarray):
    """
    估计每个目标 (i) 的权重，基于目标强度。
    用于 WLS，确保强目标权重更高。
    """
    M, I = Kappa_noisy.shape

    # 1. 使用当前通道误差校准数据
    Kappa_calibrated = Kappa_noisy / gamma_va_ils.reshape(-1, 1)
    weights = np.zeros(I)

    for i in range(I):
        # 2. 构建理想转向矢量 a_i
        phi = phi_ils[i]
        a_i = get_full_steering_matrix([phi], K, L, D_TX, D_RX, LAMBDA_C).flatten()

        # 3. 目标强度估计 (通过匹配滤波)
        target_strength = np.abs(np.vdot(a_i, Kappa_calibrated[:, i]))**2

        # 4. 权重设置为目标强度 (或平方根，这里使用强度)
        weights[i] = target_strength

    # 避免权重为零
    return np.clip(weights, 1e-6, np.max(weights))

# --------------------------------------------------------
# 核心函数 5: MIMO 独立校准 (WLS 求解器)
# --------------------------------------------------------
def calibrate_mimo(Kappa_noisy: np.ndarray, phi_known: np.ndarray, K, L, d_tx, d_rx, lambda_c, weights: np.ndarray | None = None, verbose=False):
    """ MIMO 独立校准 (LS/WLS 求解器) """
    I = len(phi_known)
    Kappa_reshaped = Kappa_noisy.reshape(K, L, I)

    # --- 权重处理 ---
    if weights is None:
        weights = np.ones(I)
    w_sqrt = np.sqrt(weights)

    # --- Tx 校准 (WLS) ---
    gamma_tx_est = np.ones(K, dtype=complex)
    for k in range(1, K):
        A_tx, b_tx = [], []

        for i in range(I):
            h_ki = get_virtual_steering_vector(phi_known[i], k, 0, d_tx, d_rx, lambda_c) / \
                   get_virtual_steering_vector(phi_known[i], 0, 0, d_tx, d_rx, lambda_c)

            for l in range(L):
                p_kli = Kappa_reshaped[k, l, i] / Kappa_reshaped[0, l, i]
                # 赋权给 LS 矩阵 A 和 B (WLS)
                A_tx.append(h_ki * w_sqrt[i])
                b_tx.append(p_kli * w_sqrt[i])

        gamma_k, _, _, _ = scipy.linalg.lstsq(np.array(A_tx).reshape(-1, 1), np.array(b_tx).reshape(-1, 1))
        gamma_tx_est[k] = gamma_k[0] if gamma_k.size > 0 else 1.0

    # --- Rx 校准 (WLS) ---
    gamma_rx_est = np.ones(L, dtype=complex)
    for l in range(1, L):
        A_rx, b_rx = [], []

        for i in range(I):
            h_li = get_virtual_steering_vector(phi_known[i], 0, l, d_tx, d_rx, lambda_c) / \
                   get_virtual_steering_vector(phi_known[i], 0, 0, d_tx, d_rx, lambda_c)
            for k in range(K):
                p_kli = Kappa_reshaped[k, l, i] / Kappa_reshaped[k, 0, i]

                A_rx.append(h_li * w_sqrt[i])
                b_rx.append(p_kli * w_sqrt[i])

        gamma_l, _, _, _ = scipy.linalg.lstsq(np.array(A_rx).reshape(-1, 1), np.array(b_rx).reshape(-1, 1))
        gamma_rx_est[l] = gamma_l[0] if gamma_l.size > 0 else 1.0

    return gamma_tx_est, gamma_rx_est

# --------------------------------------------------------
# 核心函数 6: 角度匹配 (简化版本)
# --------------------------------------------------------
def match_estimated_angles(phi_old: np.ndarray, phi_new_unsorted: np.ndarray) -> np.ndarray:
    """
    使用最近邻匹配法，将新估计的角度匹配到上一步的目标顺序上。
    """
    I = phi_old.size
    phi_new_matched = np.zeros_like(phi_old)
    unmatched_new = list(phi_new_unsorted)

    for i in range(I):
        old_angle = phi_old[i]

        distances = np.abs(np.array(unmatched_new) - old_angle)

        if distances.size > 0:
            best_match_index = np.argmin(distances)
            phi_new_matched[i] = unmatched_new[best_match_index]
            unmatched_new.pop(best_match_index)
        else:
            phi_new_matched[i] = old_angle # Fallback

    return phi_new_matched

# --------------------------------------------------------
# 主函数 7: CalibrateILS (ILS 主逻辑)
# --------------------------------------------------------
def CalibrateILS_SimpleDOA(K_noisy: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    执行基于 WLS 和 简单 Beamforming 的迭代最小二乘 (ILS) 通道校准。

    Args:
        K_noisy (M, I): VA 信号响应矩阵 (M=4, I=目标数)。

    Returns:
        Tuple[np.ndarray, np.ndarray]: (Tx 误差向量, Rx 误差向量)
    """
    M, I = K_noisy.shape

    if I < max(K, L):
        raise ValueError(f"观测次数 I={I} 太少，ILS 求解需要 I >= {max(K, L)}。")

    gamma_tx_ils = np.ones(K, dtype=complex)
    gamma_rx_ils = np.ones(L, dtype=complex)
    phi_ils = np.zeros(I)

    # 1. 初始化角度 (运行 Beamforming 对每个目标快照)
    phi_initial_unsorted = np.zeros(I)
    for i in range(I):
        phi_initial_unsorted[i] = simple_doa_estimator(K_noisy[:, i].reshape(-1, 1), K, L, D_TX, D_RX, LAMBDA_C)

    # 将初始估计的角度作为目标顺序的基准 (排序)
    phi_ils = np.sort(phi_initial_unsorted)

    # 2. ILS 迭代循环
    for iter_n in range(ILS_ITERATIONS):
        # A. 计算 WLS 权重 (需要用到当前通道误差)
        gamma_va_current = np.kron(gamma_tx_ils, gamma_rx_ils)
        weights = estimate_target_weights(K_noisy, phi_ils, gamma_va_current)

        # B. 估计通道 (WLS 求解)
        gamma_tx_new, gamma_rx_new = calibrate_mimo(
            K_noisy, phi_ils, K, L, D_TX, D_RX, LAMBDA_C,
            weights=weights, verbose=False
        )

        # C. 估计角度 (DoA)
        gamma_va_new = np.kron(gamma_tx_new, gamma_rx_new)
        Kappa_calibrated = K_noisy / gamma_va_new.reshape(-1, 1)

        phi_new_unsorted = np.zeros(I)
        for i in range(I):
            phi_new_unsorted[i] = simple_doa_estimator(Kappa_calibrated[:, i].reshape(-1, 1), K, L, D_TX, D_RX, LAMBDA_C)

        # D. 角度匹配
        phi_new = match_estimated_angles(phi_ils, phi_new_unsorted)

        # E. 检查收敛
        error_tx = norm(gamma_tx_new - gamma_tx_ils) / norm(gamma_tx_ils)
        error_rx = norm(gamma_rx_new - gamma_rx_ils) / norm(gamma_rx_ils)

        # F. 更新状态
        gamma_tx_ils, gamma_rx_ils, phi_ils = gamma_tx_new, gamma_rx_new, phi_new

        if (error_tx < ILS_TOLERANCE and error_rx < ILS_TOLERANCE):
            break

    return gamma_tx_ils, gamma_rx_ils
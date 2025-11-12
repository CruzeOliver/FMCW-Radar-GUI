import numpy as np
import scipy.linalg
from numpy.linalg import norm
import matplotlib.pyplot as plt
import time
import warnings

# --- 0. 抑制 DeprecationWarning (我们知道我们在做什么) ---
# 警告来自 lstsq 返回数组后我们提取 [0]
warnings.filterwarnings("ignore", category=DeprecationWarning)

# --- 1. 仿真参数设置 ---
K = 3       # K: 发射 (Tx) 天线数量
L = 4       # L: 接收 (Rx) 天线数量
M = K * L   # M: 虚拟阵元总数

# ILS 迭代参数
ILS_ITERATIONS = 15                 # ILS 算法最大迭代次数
ILS_TOLERANCE = 1e-6                # ILS 收敛阈值

# 蒙特卡洛仿真次数
N_MONTE_CARLO = 50                  # 为使曲线平滑，每个数据点运行50次取平均

# --- 2. 物理参数 ---
f_c = 77e9                          # 载频 (77 GHz)
c = 3e8                             # 光速
lambda_c = c / f_c                    # 波长
d_rx = lambda_c / 2                   # Rx 阵元间距
d_tx = L * d_rx                       # Tx 阵元间距 (稀疏阵列)

# --- 3. 辅助函数 ---

def get_virtual_steering_vector(phi, k, l, d_tx, d_rx, lambda_c):
    """ 计算单个 (k, l) 虚拟阵元的理想转向矢量元素 """
    phase = -2j * np.pi * (k * d_tx + l * d_rx) * np.sin(phi) / lambda_c
    return np.exp(phase)

def get_full_steering_matrix(phi_array, K, L, d_tx, d_rx, lambda_c):
    """ 生成 (M x I) 的理想转向矩阵 H_ideal """
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

def simple_doa_estimator(x_calibrated, M, K, L, d_tx, d_rx, lambda_c):
    """ 一个简单的基于FFT的DoA估计器 (用于ILS) """
    angle_grid = np.linspace(-np.pi/2, np.pi/2, 361)
    spectrum = []

    for phi in angle_grid:
        a_phi = get_full_steering_matrix([phi], K, L, d_tx, d_rx, lambda_c).flatten()
        spectrum.append(np.abs(np.vdot(a_phi, x_calibrated))**2)

    peak_index = np.argmax(spectrum)
    return angle_grid[peak_index]

# --- 4. CRB 计算函数 (新增) ---
def calculate_crb(K, L, I, SNR_dB):
    """
    计算 VA 和 MIMO 校准的理论 CRB
    (假设所有 I 个目标具有相同的 SNR)
    """
    M = K * L
    snr_linear = 10**(SNR_dB / 10.0)

    # 根据论文 (Eq. 7): CRB_va = (I + sum(SNR_i))^-1
    # 假设 I 个目标具有相同的 SNR
    sum_snr_term = I * snr_linear

    # (Eq. 7) 严格来说是 (h^H * Sigma^-1 * h)^-1
    # Sigma_inv = diag(SNR_i + 1)
    # h^H * Sigma_inv * h = sum(SNR_i + 1) = I + sum(SNR_i)
    crb_va_base = 1.0 / (I + sum_snr_term)

    # (Eq. 15): CRB_mimo = ((K+L)/(KL)) * CRB_va_base
    crb_mimo = ((K + L) / (K * L)) * crb_va_base

    return crb_va_base, crb_mimo

# --- 5. 核心校准算法 ---

def calibrate_va(Kappa_noisy, H_ideal_known, verbose=False):
    """ 方案 1: 传统虚拟阵列 (VA) 校准 """
    M, I = H_ideal_known.shape
    if verbose:
        print(f"  [VA] 运行中... (I={I}, M-1={M-1})")
        if I < M - 1:
            print(f"  [VA] 警告: 独立观测 I < M-1，LS问题欠定！")

    P_va = Kappa_noisy[1:, :] / Kappa_noisy[0, :]
    H_va = H_ideal_known[1:, :] / H_ideal_known[0, :]

    gamma_va_est_partial = np.zeros(M-1, dtype=complex)

    for m in range(M-1):
        p_m_vec = P_va[m, :]
        h_m_vec = H_va[m, :]
        A = h_m_vec.reshape(-1, 1)
        b = p_m_vec.reshape(-1, 1)
        # lstsq 返回 (solution_array, residuals, rank, singular_values)
        gamma_m, _, _, _ = scipy.linalg.lstsq(A, b)
        # 提取标量，处理 DeprecationWarning
        gamma_va_est_partial[m] = gamma_m[0] if gamma_m.size > 0 else 1.0

    gamma_va_est = np.hstack([1.0, gamma_va_est_partial])
    return gamma_va_est

def calibrate_mimo(Kappa_noisy, phi_known, K, L, d_tx, d_rx, lambda_c, verbose=False):
    """ 方案 2: MIMO 独立校准 """
    I = len(phi_known)
    if verbose:
        print(f"  [MIMO] 运行中... (I={I}, K={K}, L={L})")

    Kappa_reshaped = Kappa_noisy.reshape(K, L, I)

    # --- Tx 校准 ---
    gamma_tx_est = np.ones(K, dtype=complex)
    for k in range(1, K):
        A_tx, b_tx = [], []
        for i in range(I):
            phi = phi_known[i]
            h_ki = get_virtual_steering_vector(phi, k, 0, d_tx, d_rx, lambda_c) / \
                   get_virtual_steering_vector(phi, 0, 0, d_tx, d_rx, lambda_c)
            for l in range(L):
                p_kli = Kappa_reshaped[k, l, i] / Kappa_reshaped[0, l, i]
                A_tx.append(h_ki)
                b_tx.append(p_kli)

        gamma_k, _, _, _ = scipy.linalg.lstsq(np.array(A_tx).reshape(-1, 1),
                                              np.array(b_tx).reshape(-1, 1))
        gamma_tx_est[k] = gamma_k[0] if gamma_k.size > 0 else 1.0

    # --- Rx 校准 ---
    gamma_rx_est = np.ones(L, dtype=complex)
    for l in range(1, L):
        A_rx, b_rx = [], []
        for i in range(I):
            phi = phi_known[i]
            h_li = get_virtual_steering_vector(phi, 0, l, d_tx, d_rx, lambda_c) / \
                   get_virtual_steering_vector(phi, 0, 0, d_tx, d_rx, lambda_c)
            for k in range(K):
                p_kli = Kappa_reshaped[k, l, i] / Kappa_reshaped[k, 0, i]
                A_rx.append(h_li)
                b_rx.append(p_kli)

        gamma_l, _, _, _ = scipy.linalg.lstsq(np.array(A_rx).reshape(-1, 1),
                                              np.array(b_rx).reshape(-1, 1))
        gamma_rx_est[l] = gamma_l[0] if gamma_l.size > 0 else 1.0

    return gamma_tx_est, gamma_rx_est

def calibrate_ils(Kappa_noisy, K, L, d_tx, d_rx, lambda_c, verbose=False):
    """ 方案 3: ILS 自校准 MIMO (角度未知) """
    M, I = Kappa_noisy.shape

    if verbose:
        print(f"  [ILS] 运行中... (迭代次数 {ILS_ITERATIONS})")

    gamma_tx_ils = np.ones(K, dtype=complex)
    gamma_rx_ils = np.ones(L, dtype=complex)
    phi_ils = np.zeros(I)

    for i in range(I):
        phi_ils[i] = simple_doa_estimator(Kappa_noisy[:, i], M, K, L, d_tx, d_rx, lambda_c)

    for iter_n in range(ILS_ITERATIONS):
        gamma_tx_new, gamma_rx_new = calibrate_mimo(Kappa_noisy, phi_ils, K, L, d_tx, d_rx, lambda_c, verbose=False)

        gamma_va_ils = np.kron(gamma_tx_new, gamma_rx_new)
        Kappa_calibrated = Kappa_noisy / gamma_va_ils.reshape(-1, 1)

        phi_new = np.zeros(I)
        for i in range(I):
            phi_new[i] = simple_doa_estimator(Kappa_calibrated[:, i], M, K, L, d_tx, d_rx, lambda_c)

        error_tx = norm(gamma_tx_new - gamma_tx_ils) / norm(gamma_tx_ils)
        error_rx = norm(gamma_rx_new - gamma_rx_ils) / norm(gamma_rx_ils)

        gamma_tx_ils, gamma_rx_ils, phi_ils = gamma_tx_new, gamma_rx_new, phi_new

        if (error_tx < ILS_TOLERANCE and error_rx < ILS_TOLERANCE):
            break

    return gamma_tx_ils, gamma_rx_ils

# --- 6. 核心仿真封装 ---

def run_single_simulation(K, L, I, SNR_dB, error_std_dev):
    """
    运行一次完整的仿真 (生成数据 -> 运行3个算法 -> 返回MSE)
    """
    M = K * L

    # 1. 生成“真实” (Ground Truth) 数据
    gamma_tx_true = np.ones(K, dtype=complex)
    gamma_rx_true = np.ones(L, dtype=complex)

    err_tx_real = error_std_dev * np.random.randn(K-1)
    err_tx_imag = error_std_dev * np.random.randn(K-1)
    gamma_tx_true[1:] = 1.0 + err_tx_real + 1j * err_tx_imag

    err_rx_real = error_std_dev * np.random.randn(L-1)
    err_rx_imag = error_std_dev * np.random.randn(L-1)
    gamma_rx_true[1:] = 1.0 + err_rx_real + 1j * err_rx_imag

    gamma_va_true = np.kron(gamma_tx_true, gamma_rx_true)

    phi_true = np.random.uniform(-np.pi/4, np.pi/4, I)
    alpha_true = (np.random.randn(I) + 1j * np.random.randn(I)) / np.sqrt(2)
    H_ideal_true = get_full_steering_matrix(phi_true, K, L, d_tx, d_rx, lambda_c)

    # 2. 生成“测量”数据
    Kappa_clean = np.zeros((M, I), dtype=complex)
    for i in range(I):
        Kappa_clean[:, i] = alpha_true[i] * gamma_va_true * H_ideal_true[:, i]

    signal_power = np.mean(np.abs(Kappa_clean)**2)
    noise_power = signal_power / (10**(SNR_dB / 10))
    noise = (np.random.randn(M, I) + 1j * np.random.randn(M, I)) * np.sqrt(noise_power / 2)
    Kappa_noisy = Kappa_clean + noise

    # 3. 运行三种校准方案
    gamma_va_est = calibrate_va(Kappa_noisy, H_ideal_true, verbose=False)
    gamma_tx_mimo, gamma_rx_mimo = calibrate_mimo(Kappa_noisy, phi_true, K, L, d_tx, d_rx, lambda_c, verbose=False)
    gamma_va_mimo_est = np.kron(gamma_tx_mimo, gamma_rx_mimo)
    gamma_tx_ils, gamma_rx_ils = calibrate_ils(Kappa_noisy, K, L, d_tx, d_rx, lambda_c, verbose=False)
    gamma_va_ils_est = np.kron(gamma_tx_ils, gamma_rx_ils)

    # 4. 评估结果 (MSE)
    mse_va = np.mean(np.abs(gamma_va_est / gamma_va_est[0] - gamma_va_true / gamma_va_true[0])**2)
    mse_mimo = np.mean(np.abs(gamma_va_mimo_est / gamma_va_mimo_est[0] - gamma_va_true / gamma_va_true[0])**2)
    mse_ils = np.mean(np.abs(gamma_va_ils_est / gamma_va_ils_est[0] - gamma_va_true / gamma_va_true[0])**2)

    return mse_va, mse_mimo, mse_ils

# --- 7. 绘图函数 (已更新, 包含 CRB) ---

def plot_vs_snr(K, L, I_fixed, error_fixed):
    """ 图 1: MSE vs SNR """
    print(f"\n--- 正在生成 图 1 (vs SNR) ---")
    print(f"固定参数: I = {I_fixed}, Error StdDev = {error_fixed}")

    snr_range = np.linspace(0, 30, 10) # 0 to 30 dB
    # (VA, MIMO, ILS, CRB_VA, CRB_MIMO)
    results = np.zeros((len(snr_range), 5))

    start_time = time.time()
    for i, snr in enumerate(snr_range):
        mse_mc = np.zeros((N_MONTE_CARLO, 3))
        for mc in range(N_MONTE_CARLO):
            mse_mc[mc, :] = run_single_simulation(K, L, I_fixed, snr, error_fixed)
        results[i, 0:3] = np.mean(mse_mc, axis=0)

        # (新增) 计算 CRB
        crb_va, crb_mimo = calculate_crb(K, L, I_fixed, snr)
        results[i, 3] = crb_va
        results[i, 4] = crb_mimo

        print(f"  SNR = {snr:.1f} dB 完成 ({i+1}/{len(snr_range)})")

    plt.figure()
    plt.plot(snr_range, results[:, 0], 'o--', label='方案 1 (VA - 角度已知)')
    plt.plot(snr_range, results[:, 1], 's-', label='方案 2 (MIMO - 角度已知)')
    plt.plot(snr_range, results[:, 2], 'x:', label='方案 3 (ILS - 角度未知)')

    # (新增) 绘制 CRB
    plt.plot(snr_range, results[:, 3], 'k--', label='CRB (VA)')
    plt.plot(snr_range, results[:, 4], 'k-', label='CRB (MIMO)')

    plt.xlabel('信噪比 (SNR) / dB')
    plt.ylabel('通道误差 MSE (log scale)')
    plt.title(f'校准性能 vs SNR (I={I_fixed}, K={K}, L={L})')
    plt.yscale('log')
    plt.legend()
    plt.grid(True, which="both")
    plt.ylim(bottom=1e-5) # 设置 y 轴下限
    plt.savefig('mse_vs_snr_with_crb.png')
    print(f"图 1 保存为: mse_vs_snr_with_crb.png (耗时: {time.time() - start_time:.2f}s)")

def plot_vs_observations(K, L, snr_fixed, error_fixed):
    """ 图 2: MSE vs 观测次数 I """
    print(f"\n--- 正在生成 图 2 (vs 观测次数 I) ---")
    print(f"固定参数: SNR = {snr_fixed} dB, Error StdDev = {error_fixed}")
    M = K * L
    i_range = np.arange(max(K,L), M + 5) # 从 max(K,L) 到 M+4
    results = np.zeros((len(i_range), 5))

    start_time = time.time()
    for i, obs_I in enumerate(i_range):
        mse_mc = np.zeros((N_MONTE_CARLO, 3))
        for mc in range(N_MONTE_CARLO):
            mse_mc[mc, :] = run_single_simulation(K, L, obs_I, snr_fixed, error_fixed)
        results[i, 0:3] = np.mean(mse_mc, axis=0)

        # (新增) 计算 CRB
        crb_va, crb_mimo = calculate_crb(K, L, obs_I, snr_fixed)
        results[i, 3] = crb_va
        results[i, 4] = crb_mimo

        print(f"  I = {obs_I} 完成 ({i+1}/{len(i_range)})")

    plt.figure()
    plt.plot(i_range, results[:, 0], 'o--', label='方案 1 (VA - 角度已知)')
    plt.plot(i_range, results[:, 1], 's-', label='方案 2 (MIMO - 角度已知)')
    plt.plot(i_range, results[:, 2], 'x:', label='方案 3 (ILS - 角度未知)')

    # (新增) 绘制 CRB
    plt.plot(i_range, results[:, 3], 'k--', label='CRB (VA)')
    plt.plot(i_range, results[:, 4], 'k-', label='CRB (MIMO)')

    # 绘制VA欠定区域
    plt.axvline(x=M-1, color='r', linestyle='--', label=f'VA 欠定 (I < {M-1})')

    plt.xlabel('独立观测次数 (I)')
    plt.ylabel('通道误差 MSE (log scale)')
    plt.title(f'校准性能 vs 观测次数 (SNR={snr_fixed}dB)')
    plt.yscale('log')
    plt.legend()
    plt.grid(True, which="both")
    plt.ylim(bottom=1e-5) # 设置 y 轴下限
    plt.savefig('mse_vs_observations_with_crb.png')
    print(f"图 2 保存为: mse_vs_observations_with_crb.png (耗时: {time.time() - start_time:.2f}s)")

def plot_vs_error_magnitude(K, L, snr_fixed, i_fixed):
    """ 图 3: MSE vs 真实误差大小 """
    print(f"\n--- 正在生成 图 3 (vs 真实误差大小) ---")
    print(f"固定参数: SNR = {snr_fixed} dB, I = {i_fixed}")

    error_range = np.linspace(0.05, 0.5, 10) # 误差标准差
    results = np.zeros((len(error_range), 5))

    # (新增) CRB 在此图中是恒定的，因为 SNR 和 I 不变
    crb_va, crb_mimo = calculate_crb(K, L, i_fixed, snr_fixed)
    results[:, 3] = crb_va
    results[:, 4] = crb_mimo

    start_time = time.time()
    for i, err_std in enumerate(error_range):
        mse_mc = np.zeros((N_MONTE_CARLO, 3))
        for mc in range(N_MONTE_CARLO):
            mse_mc[mc, :] = run_single_simulation(K, L, i_fixed, snr_fixed, err_std)
        results[i, 0:3] = np.mean(mse_mc, axis=0)
        print(f"  Error StdDev = {err_std:.2f} 完成 ({i+1}/{len(error_range)})")

    plt.figure()
    plt.plot(error_range, results[:, 0], 'o--', label='方案 1 (VA - 角度已知)')
    plt.plot(error_range, results[:, 1], 's-', label='方案 2 (MIMO - 角度已知)')
    plt.plot(error_range, results[:, 2], 'x:', label='方案 3 (ILS - 角度未知)')

    # (新增) 绘制 CRB (恒定值)
    plt.plot(error_range, results[:, 3], 'k--', label='CRB (VA)')
    plt.plot(error_range, results[:, 4], 'k-', label='CRB (MIMO)')

    plt.xlabel('真实通道误差的标准差 (Error StdDev)')
    plt.ylabel('通道误差 MSE (log scale)')
    plt.title(f'校准性能 vs 真实误差大小 (SNR={snr_fixed}dB, I={i_fixed})')
    plt.yscale('log')
    plt.legend()
    plt.grid(True, which="both")
    plt.ylim(bottom=1e-5) # 设置 y 轴下限
    plt.savefig('mse_vs_error_magnitude_with_crb.png')
    print(f"图 3 保存为: mse_vs_error_magnitude_with_crb.png (耗时: {time.time() - start_time:.2f}s)")

# --- 8. 主函数 ---

def main_plotter():
    print("====== 开始运行校准方案对比仿真 ======")
    print(f"固定参数: K={K}, L={L}, M={M}, Monte Carlo 次数={N_MONTE_CARLO}")

    # 固定的仿真参数
    # 我们特意选择 I_fixed < M-1 来凸显MIMO方案的优势
    I_FIXED = 6         # (I < M-1 = 11)
    SNR_FIXED = 20      # 20 dB
    ERROR_FIXED = 0.2   # 真实误差的标准差

    # 运行三个绘图函数
    plot_vs_snr(K, L, I_FIXED, ERROR_FIXED)
    plot_vs_observations(K, L, SNR_FIXED, ERROR_FIXED)
    plot_vs_error_magnitude(K, L, SNR_FIXED, I_FIXED)

    print("\n====== 仿真结束 ======")

if __name__ == "__main__":
    main_plotter()
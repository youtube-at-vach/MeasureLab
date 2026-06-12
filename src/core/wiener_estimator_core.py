import logging
import numpy as np
from scipy.signal import lfilter, butter, sosfilt

logger = logging.getLogger(__name__)

def generate_schroeder_multisine(sample_rate: float, duration: float, start_freq: float, end_freq: float, amplitude_db: float) -> np.ndarray:
    """
    Generates a low crest-factor multisine signal using Schroeder phase formula.
    """
    num_samples = int(sample_rate * duration)
    # Perform FFT-based synthesis
    freq_bins = np.fft.rfftfreq(num_samples, d=1.0/sample_rate)

    # Identify bin indices in range
    bin_idx = np.where((freq_bins >= start_freq) & (freq_bins <= end_freq))[0]
    if len(bin_idx) == 0:
        # Fallback to single tone
        bin_idx = np.array([int(start_freq * num_samples / sample_rate)])

    num_tones = len(bin_idx)

    # Initialize spectrum
    spec = np.zeros(num_samples // 2 + 1, dtype=complex)

    # Schroeder phase formulation
    for i, idx in enumerate(bin_idx):
        phase = -np.pi * i * (i - 1) / num_tones
        spec[idx] = np.exp(1j * phase)

    # Transform to time domain
    signal = np.fft.irfft(spec, n=num_samples)

    # Normalize to desired peak amplitude (peak value matches target amplitude)
    peak = np.max(np.abs(signal))
    if peak > 1e-12:
        signal /= peak

    amp_linear = 10 ** (amplitude_db / 20.0)
    return signal * amp_linear

def generate_gaussian_noise(sample_rate: float, duration: float, start_freq: float, end_freq: float, amplitude_db: float) -> np.ndarray:
    """
    Generates bandpass-filtered Gaussian noise normalized to the target peak amplitude.
    """
    num_samples = int(sample_rate * duration)
    noise = np.random.normal(0.0, 1.0, num_samples)

    # Bandpass filter the noise
    nyquist = sample_rate / 2.0
    # Keep safety margins for Butterworth design
    low = max(2.0, start_freq) / nyquist
    high = min(nyquist * 0.99, end_freq) / nyquist

    try:
        sos = butter(4, [low, high], btype='bandpass', output='sos')
        filtered = sosfilt(sos, noise)
    except Exception as e:
        logger.warning(f"Failed to design Butterworth bandpass filter: {e}. Using raw noise.")
        filtered = noise

    # Scale to peak value matching target amplitude
    peak = np.max(np.abs(filtered))
    if peak > 1e-12:
        filtered /= peak

    amp_linear = 10 ** (amplitude_db / 20.0)
    return filtered * amp_linear

def identify_bussgang(u: np.ndarray, y: np.ndarray, P: int = 4, lti_len: int = 64):
    """
    Identifies the Wiener model using Bussgang theorem (cross-correlation).
    u: input signal (assumed Gaussian)
    y: output signal
    P: polynomial degree for static nonlinearity
    lti_len: length of LTI impulse response to estimate

    Returns:
        lti_impulse: np.ndarray of shape (lti_len,) (normalized)
        poly_coeffs: np.ndarray of shape (P,) for y = c1*x + c2*x^2 + ... + cP*x^P
        fit_ratio: float, fitness R^2
        y_pred: np.ndarray predicted output
        x_est: np.ndarray estimated intermediate signal
    """
    N = len(u)
    # 1. Compute cross-correlation R_yu(tau)
    # We use FFT-based convolution for speed
    U = np.fft.rfft(np.pad(u, (0, N)))
    Y = np.fft.rfft(np.pad(y, (0, N)))
    R_yu_full = np.fft.irfft(Y * np.conj(U)) / N

    # Extract positive lags
    g = R_yu_full[:lti_len]

    # Normalize LTI impulse response to have unit norm
    norm = np.linalg.norm(g)
    if norm > 1e-12:
        g = g / norm

    # 2. Reconstruct intermediate signal x_est
    x_est = lfilter(g, [1.0], u)

    # 3. Fit static polynomial nonlinearity: y = sum_{i=1}^P c_i * x^i
    # Build regression matrix
    X_reg = np.zeros((N, P))
    for i in range(1, P + 1):
        X_reg[:, i - 1] = x_est ** i

    # Solve least-squares
    try:
        c, _, _, _ = np.linalg.lstsq(X_reg, y, rcond=None)
    except np.linalg.LinAlgError:
        c = np.zeros(P)
        c[0] = 1.0 # fallback

    y_pred = X_reg @ c

    # Fit ratio (R^2 coefficient of determination)
    var_total = np.var(y)
    if var_total > 1e-12:
        fit_ratio = 1.0 - (np.var(y - y_pred) / var_total)
    else:
        fit_ratio = 0.0

    return g, c, fit_ratio, y_pred, x_est

def identify_bla_ls(u: np.ndarray, y: np.ndarray, P: int = 4, na: int = 4, nb: int = 4):
    """
    Identifies the Wiener model using Best Linear Approximation (BLA)
    via Time-Domain ARX modeling followed by LS polynomial fitting.

    u: input signal
    y: output signal
    P: polynomial order
    na: number of poles (denominator coefficients)
    nb: number of zeros (numerator coefficients)

    Returns:
        b: numerator coefficients of G(z)
        a: denominator coefficients of G(z) (normalized with a[0] = 1)
        poly_coeffs: np.ndarray of shape (P,) for y = c1*x + c2*x^2 + ... + cP*x^P
        fit_ratio: float, fitness R^2
        y_pred: np.ndarray predicted output
        x_est: np.ndarray estimated intermediate signal
    """
    N = len(u)
    max_n = max(na, nb)

    # 1. Estimate G(z) using ARX model on the raw input/output data (Best Linear Approximation)
    # y(t) + a1*y(t-1) + ... = b0*u(t) + b1*u(t-1) + ...
    # Build regression matrix
    X_arx = np.zeros((N - max_n, na + nb + 1))
    for i in range(na):
        X_arx[:, i] = -y[max_n - 1 - i : N - 1 - i]
    for i in range(nb + 1):
        X_arx[:, na + i] = u[max_n - i : N - i]

    y_arx = y[max_n:]

    try:
        theta, _, _, _ = np.linalg.lstsq(X_arx, y_arx, rcond=None)
        a_coefs = np.concatenate([[1.0], theta[:na]])
        b_coefs = theta[na:]
    except (np.linalg.LinAlgError, ValueError):
        a_coefs = np.array([1.0, 0.0])
        b_coefs = np.array([1.0, 0.0])

    # Scale G(z) norm to avoid scaling ambiguity (e.g. norm of impulse response = 1)
    # Simulate impulse response to normalize
    impulse = np.zeros(128)
    impulse[0] = 1.0
    ir = lfilter(b_coefs, a_coefs, impulse)
    ir_norm = np.linalg.norm(ir)
    if ir_norm > 1e-12:
        b_coefs = b_coefs / ir_norm

    # 2. Filter u to obtain estimated intermediate signal x_est
    x_est = lfilter(b_coefs, a_coefs, u)

    # 3. Fit static polynomial nonlinearity y = sum_{i=1}^P c_i * x^i
    X_reg = np.zeros((N, P))
    for i in range(1, P + 1):
        X_reg[:, i - 1] = x_est ** i

    try:
        c, _, _, _ = np.linalg.lstsq(X_reg, y, rcond=None)
    except np.linalg.LinAlgError:
        c = np.zeros(P)
        c[0] = 1.0

    y_pred = X_reg @ c

    var_total = np.var(y)
    if var_total > 1e-12:
        fit_ratio = 1.0 - (np.var(y - y_pred) / var_total)
    else:
        fit_ratio = 0.0

    return b_coefs, a_coefs, c, fit_ratio, y_pred, x_est

def identify_tsa_svd(u: np.ndarray, y: np.ndarray, P: int = 4, na: int = 2, nb: int = 2):
    """
    Identifies the Wiener model using Two-Stage Algorithm (TSA) and SVD.
    This assumes the inverse nonlinearity can be approximated as a polynomial:
      f^{-1}(y(t)) = y(t) + c2*y(t)^2 + ... + cP*y(t)^P = G(z) u(t)

    Where G(z) = B(z)/A(z) (IIR format).
    The expanded linear model is:
      y(t) + sum_{i=2}^P c_i y(t)^i + sum_{j=1}^na a_j y(t-j) + sum_{j=1}^na sum_{i=2}^P w_{i,j} y(t-j)^i - sum_{k=0}^nb b_k u(t-k) = 0

    We solve for:
      y(t) = - sum_{i=2}^P c_i y(t)^i - sum_{j=1}^na a_j y(t-j) - sum_{j=1}^na sum_{i=2}^P w_{i,j} y(t-j)^i + sum_{k=0}^nb b_k u(t-k)

    Then apply SVD on matrix M containing c_i, a_j, and w_{i,j} = c_i * a_j to extract c and a.

    Returns:
        b: numerator coefficients of G(z)
        a: denominator coefficients of G(z)
        poly_coeffs: np.ndarray of shape (P,) for the FORWARD polynomial y = d1*x + ... + dP*x^P
        fit_ratio: float, fitness R^2
        y_pred: np.ndarray predicted output
        x_est: np.ndarray estimated intermediate signal
    """
    N = len(u)
    max_n = max(na, nb)

    # Count variables
    num_c = P - 1
    num_a = na
    num_w = (P - 1) * na
    num_b = nb + 1
    total_params = num_c + num_a + num_w + num_b

    if N - max_n <= total_params:
        # Fallback if we don't have enough samples
        return np.array([1.0]), np.array([1.0]), np.zeros(P), 0.0, np.zeros(N), np.zeros(N)

    X_reg = np.zeros((N - max_n, total_params))

    # Fill regressor matrix
    # 1. c_i terms: -y(t)^i for i = 2...P
    for i in range(2, P + 1):
        col_idx = i - 2
        X_reg[:, col_idx] = - (y[max_n:] ** i)

    # 2. a_j terms: -y(t-j) for j = 1...na
    for j in range(1, na + 1):
        col_idx = num_c + (j - 1)
        X_reg[:, col_idx] = - y[max_n - j : N - j]

    # 3. w_{i,j} terms: -y(t-j)^i for j = 1...na, i = 2...P
    w_start = num_c + num_a
    idx = 0
    for j in range(1, na + 1):
        for i in range(2, P + 1):
            col_idx = w_start + idx
            X_reg[:, col_idx] = - (y[max_n - j : N - j] ** i)
            idx += 1

    # 4. b_k terms: u(t-k) for k = 0...nb
    b_start = num_c + num_a + num_w
    for k in range(0, nb + 1):
        col_idx = b_start + k
        X_reg[:, col_idx] = u[max_n - k : N - k]

    y_target = y[max_n:]

    try:
        theta, _, _, _ = np.linalg.lstsq(X_reg, y_target, rcond=None)
    except np.linalg.LinAlgError:
        theta = np.zeros(total_params)

    # Extract estimated parameters
    c_est = np.zeros(P)
    c_est[0] = 1.0  # c1 = 1.0 by definition
    c_est[1:] = theta[:num_c]

    a_est = np.zeros(na + 1)
    a_est[0] = 1.0  # a0 = 1.0 by definition
    a_est[1:] = theta[num_c : num_c + num_a]

    b_est = theta[b_start:]

    # SVD stage: construct matrix M of size P x (na + 1)
    M_mat = np.zeros((P, na + 1))

    # Row 0: c1 * a_j = 1 * a_j
    M_mat[0, :] = a_est
    # Col 0: c_i * a0 = c_i * 1
    M_mat[:, 0] = c_est

    # Fill remaining w terms
    w_start = num_c + num_a
    idx = 0
    for j in range(1, na + 1):
        for i in range(2, P + 1):
            M_mat[i - 1, j] = theta[w_start + idx]
            idx += 1

    # Perform SVD
    try:
        U_svd, S_svd, Vt_svd = np.linalg.svd(M_mat)

        c_svd = U_svd[:, 0]
        a_svd = Vt_svd[0, :]

        scale_c = c_svd[0] if np.abs(c_svd[0]) > 1e-9 else 1.0
        scale_a = a_svd[0] if np.abs(a_svd[0]) > 1e-9 else 1.0

        c_final = c_svd / scale_c
        a_final = a_svd / scale_a

        b_final = b_est / (scale_c * scale_a)
    except Exception as e:
        logger.warning(f"SVD failed: {e}. Falling back to LS values.")
        c_final = c_est
        a_final = a_est
        b_final = b_est

    # Scale G(z) norm to avoid scaling ambiguity
    impulse = np.zeros(128)
    impulse[0] = 1.0
    ir = lfilter(b_final, a_final, impulse)
    ir_norm = np.linalg.norm(ir)
    if ir_norm > 1e-12:
        b_final = b_final / ir_norm
        c_final = c_final * ir_norm

    # Now generate the forward polynomial.
    x_est = lfilter(b_final, a_final, u)

    X_fwd = np.zeros((N, P))
    for i in range(1, P + 1):
        X_fwd[:, i - 1] = x_est ** i

    try:
        d_coeffs, _, _, _ = np.linalg.lstsq(X_fwd, y, rcond=None)
    except np.linalg.LinAlgError:
        d_coeffs = np.zeros(P)
        d_coeffs[0] = 1.0

    y_pred = X_fwd @ d_coeffs

    var_total = np.var(y)
    if var_total > 1e-12:
        fit_ratio = 1.0 - (np.var(y - y_pred) / var_total)
    else:
        fit_ratio = 0.0

    return b_final, a_final, d_coeffs, fit_ratio, y_pred, x_est

class SimulatedWienerSystem:
    """
    A simulated physical Wiener system for loopback/offline mode.
    Simulates a 2nd-order Butterworth LPF followed by a polynomial static nonlinearity
    and optional process/measurement noise.
    """
    def __init__(self, sample_rate: float):
        self.sample_rate = sample_rate
        nyquist = sample_rate / 2.0
        fc = 800.0
        try:
            self.b, self.a = butter(2, fc / nyquist, btype='low')
        except Exception:
            self.b = np.array([0.003, 0.006, 0.003])
            self.a = np.array([1.0, -1.8, 0.82])

        self.poly_coeffs = np.array([1.0, -0.15, 0.08, -0.02])

    def process(self, u: np.ndarray, noise_std: float = 0.005) -> np.ndarray:
        x = lfilter(self.b, self.a, u)

        # Add process noise
        x_noisy = x + np.random.normal(0.0, 0.002, len(x))

        # 2. Static Non-Linearity
        y = np.zeros_like(x_noisy)
        for i, c in enumerate(self.poly_coeffs, start=1):
            y += c * (x_noisy ** i)

        # Add measurement noise
        y_noisy = y + np.random.normal(0.0, noise_std, len(y))

        return y_noisy

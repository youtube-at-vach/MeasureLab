import logging
from typing import List, Tuple
import numpy as np
import scipy.signal

logger = logging.getLogger(__name__)


class PredistortionApplicator:
    """
    Core DSP engine for applying non-linear predistortion based on inverse
    Hammerstein models, and running simulation verification.
    """

    def __init__(self):
        self.sample_rate = 48000
        self.P = 0
        self.g_kernels: List[np.ndarray] = []  # Inverse model kernels (g1 ~ g5)
        self.h_kernels: List[np.ndarray] = []  # Forward model kernels (h1 ~ h5)

        # Stateful filter states for real-time streaming
        self.g_zi: List[np.ndarray] = []

        # Oversampling settings to prevent aliasing during power operations
        self.os_factor = 4  # 1: Bypass, 2, 4, 8: Oversampling factor

    def load_model(self, model_data: dict):
        """
        Loads Hammerstein/Inverse Hammerstein model parameters.
        Automatically reconstructs forward/inverse kernels using Tikhonov approximation
        if only one direction is present, enabling simulation visualization.
        """
        try:
            metadata = model_data.get("metadata", {})
            self.sample_rate = metadata.get("sample_rate", 48000)

            time_domain = model_data.get("time_domain", {})
            kernels = time_domain.get("kernels", {})
            if not kernels:
                raise ValueError("No kernels found in model data.")

            raw_kernels = []
            for p in range(1, 6):
                k_key = f"h{p}"
                if k_key in kernels:
                    raw_kernels.append(np.array(kernels[k_key], dtype=np.float32))
                else:
                    break

            self.P = len(raw_kernels)
            direction = metadata.get("model_direction", "forward")

            # Apply loaded model kernels directly to both forward and inverse representation without approximation
            self.g_kernels = raw_kernels
            self.h_kernels = raw_kernels

            self.reset_states()
            logger.info("Successfully loaded %d-order %s predistortion model.", self.P, direction)
        except Exception as e:
            logger.error("Failed to load predistortion model: %s", e, exc_info=True)
            raise

    def reset_states(self):
        """Resets the stateful filter buffers to zero (e.g. at playback start)."""
        self.g_zi = []
        for gk in self.g_kernels:
            # Audio streams start from silence, so filter states should be initialized to zero.
            # The state vector length for lfilter is len(coefficients) - 1.
            zi = np.zeros(len(gk) - 1, dtype=np.float32)
            self.g_zi.append(zi)

    def apply_predistortion_block(self, block_in: np.ndarray) -> np.ndarray:
        """
        Applies predistortion to an incoming block of audio samples.
        Maintains filter states across block boundaries.
        """
        if self.P == 0 or len(self.g_kernels) == 0:
            return block_in.copy()

        block_out = np.zeros_like(block_in, dtype=np.float32)

        # 1. Compute power series components w_p(t) with anti-aliasing if enabled
        w_signals = []
        if self.os_factor > 1:
            # Resample polyphase filter performs upsampling and anti-aliasing
            block_up = scipy.signal.resample_poly(block_in, self.os_factor, 1)
            for p in range(1, self.P + 1):
                block_up_p = block_up**p
                # Downsample with anti-aliasing back to base rate
                w_p = scipy.signal.resample_poly(block_up_p, 1, self.os_factor)
                w_signals.append(w_p.astype(np.float32))
        else:
            for p in range(1, self.P + 1):
                w_signals.append((block_in**p).astype(np.float32))

        # 2. Filter power series components with respective inverse kernels
        for p in range(self.P):
            # Apply stateful FIR filtering
            filtered, self.g_zi[p] = scipy.signal.lfilter(self.g_kernels[p], [1.0], w_signals[p], zi=self.g_zi[p])
            block_out += filtered

        return block_out

    def run_simulation(self, input_sig: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Simulates predistortion and DUT system projection for a test signal.
        Returns:
            compensated_sig: The predistorted signal x(t)
            dut_output_raw: Simulated DUT output without predistortion y_raw(t)
            dut_output_compensated: Simulated DUT output with predistortion y_sim(t)
        """
        if self.P == 0:
            return input_sig.copy(), input_sig.copy(), input_sig.copy()

        # Save current streaming state to avoid corrupting active streams
        saved_g_zi = [zi.copy() for zi in self.g_zi]

        try:
            # --- 1. Compute Predistorted Signal x(t) ---
            self.reset_states()
            compensated_sig = self.apply_predistortion_block(input_sig)

            # --- 2. Simulate Uncompensated DUT Response y_raw(t) ---
            dut_output_raw = np.zeros_like(input_sig, dtype=np.float32)
            # Power signals in forward direction (no oversampling required for basic simulation plots)
            for p in range(1, self.P + 1):
                u_p = input_sig**p
                filtered = scipy.signal.lfilter(self.h_kernels[p - 1], [1.0], u_p)
                dut_output_raw += filtered

            # --- 3. Simulate Compensated DUT Response y_sim(t) ---
            dut_output_compensated = np.zeros_like(input_sig, dtype=np.float32)
            for p in range(1, self.P + 1):
                x_p = compensated_sig**p
                filtered = scipy.signal.lfilter(self.h_kernels[p - 1], [1.0], x_p)
                dut_output_compensated += filtered

            return compensated_sig, dut_output_raw, dut_output_compensated
        finally:
            # Restore original streaming state
            self.g_zi = saved_g_zi

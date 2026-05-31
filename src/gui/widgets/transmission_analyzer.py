import logging
import threading
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.core.transmission_logic import (
    PRBSGenerator,
    find_sequence_delay,
    extract_impulse_response,
    extract_frequency_response,
    calculate_evm,
    diagnose_bit_perfection,
    estimate_fractional_delay,
    shift_signal_fractional,
    track_jitter_fractional,
)
from src.gui.styles import MONOSPACE_FONT_FAMILY

logger = logging.getLogger(__name__)


class TransmissionAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self._lock = threading.Lock()

        # Audio buffer sizes
        self.max_buffer_len = 131072  # 2.7 sec at 48kHz
        self.rx_buffer = np.zeros(self.max_buffer_len, dtype=np.float32)
        self.rx_write_ptr = 0
        self.new_samples_count = 0

        # TX History Buffers for exact alignment
        self.tx_history_l = np.zeros(self.max_buffer_len, dtype=np.float32)
        self.tx_history_r = np.zeros(self.max_buffer_len, dtype=np.float32)
        self.tx_write_ptr = 0

        # Generator settings
        self.pattern_mode = "PRBS-15"
        self.bit_depth = 24
        self.input_channel_idx = 0  # 0 for Left, 1 for Right
        self.mode = "Digital"  # "Digital" or "Analog"

        # PRBS Engines (Distinct seeds to allow Crosstalk measurement)
        self.generator_l = PRBSGenerator(self.pattern_mode, seed=0x7FFFFFFF)
        self.generator_r = PRBSGenerator(self.pattern_mode, seed=0x12345678)

        # Reference cache for initial synchronization
        self.ref_cycle_len = self.generator_l.period
        temp_gen = PRBSGenerator(self.pattern_mode, seed=0x7FFFFFFF)
        self.ref_cycle = temp_gen.generate_reference_sequence(min(self.ref_cycle_len, 65536), self.bit_depth)

        # Sync and Lock State
        self.is_locked = False
        self.lock_offset = 0
        self.samples_processed = 0
        self.initial_fractional_delay = 0.0
        self.fractional_delay = 0.0
        self.delay_samples = 0
        self.initial_delay_samples = 0
        self.delay_slip_counter = 0

        # Accumulated stats (Digital Mode)
        self.total_test_samples = 0
        self.total_bit_errors = 0
        self.bit_hist = np.zeros(24, dtype=np.int64)

        # Analysis Outputs for Plots
        self.impulse_response = np.zeros(1024, dtype=np.float32)
        self.freq_resp_x = np.linspace(20, 20000, 513)
        self.freq_resp_y = np.zeros(513, dtype=np.float32)

        # Scrolling History Trends
        self.history_len = 150
        self.gain_trend = []
        self.ber_trend = []
        self.jitter_trend = []

        self.results = {
            "locked": False,
            "bit_perfect": False,
            "reason": tr("Waiting for signal..."),
            "gain_db": 0.0,
            "bit_depth": 0,
            "bit_errors": 0,
            "error_rate": 0.0,
            "total_samples": 0,
            "active_bits": 0,
            "evm": 0.0,
            "dsp_detected": "None",
            "jitter_samples": 0.0,
        }

        self.callback_id = None

    @property
    def name(self) -> str:
        return "Transmission Analyzer"

    @property
    def description(self) -> str:
        return tr("Analyzes transmission paths (USB, BT, Analog) using multi-pattern PRBS sequences.")

    def get_widget(self):
        return TransmissionAnalyzerWidget(self)

    def start_analysis(self):
        with self._lock:
            if self.is_running:
                return
            self.is_running = True

            # Reset buffers
            self.rx_buffer.fill(0)
            self.rx_write_ptr = 0
            self.new_samples_count = 0

            self.tx_history_l.fill(0)
            self.tx_history_r.fill(0)
            self.tx_write_ptr = 0

            # Recreate generators
            self.generator_l = PRBSGenerator(self.pattern_mode, seed=0x7FFFFFFF)
            self.generator_r = PRBSGenerator(self.pattern_mode, seed=0x12345678)
            self.ref_cycle_len = self.generator_l.period
            # Use temporary generator to keep self.generator_l at its clean reset state
            temp_gen = PRBSGenerator(self.pattern_mode, seed=0x7FFFFFFF)
            # Cap synchronization reference length at 65536 for PRBS-23 and PRBS-31
            self.ref_cycle = temp_gen.generate_reference_sequence(min(self.ref_cycle_len, 65536), self.bit_depth)

            self.is_locked = False
            self.lock_offset = 0
            self.samples_processed = 0
            self.initial_fractional_delay = 0.0
            self.fractional_delay = 0.0
            self.delay_samples = 0
            self.initial_delay_samples = 0
            self.delay_slip_counter = 0
            self.total_test_samples = 0
            self.total_bit_errors = 0
            self.bit_hist.fill(0)

            self.impulse_response.fill(0)
            self.freq_resp_y.fill(0)

            # Clear Trends
            self.gain_trend.clear()
            self.ber_trend.clear()
            self.jitter_trend.clear()

            self.results = {
                "locked": False,
                "bit_perfect": False,
                "reason": tr("Synchronizing..."),
                "gain_db": 0.0,
                "bit_depth": 0,
                "bit_errors": 0,
                "error_rate": 0.0,
                "total_samples": 0,
                "active_bits": 0,
                "evm": 0.0,
                "dsp_detected": tr("Analyzing..."),
                "jitter_samples": 0.0,
            }

        self.callback_id = self.audio_engine.register_callback(self._audio_callback)

    def stop_analysis(self):
        callback_id_to_unregister = None
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False

            if self.callback_id is not None:
                callback_id_to_unregister = self.callback_id
                self.callback_id = None

        if callback_id_to_unregister is not None:
            self.audio_engine.unregister_callback(callback_id_to_unregister)

    def _audio_callback(self, indata, outdata, frames, time, status):
        # 1. Output distinct PRBS signals on Left and Right channels
        out_ch = outdata.shape[1]

        l_samples = np.empty(frames, dtype=np.float32)
        r_samples = np.empty(frames, dtype=np.float32)

        for i in range(frames):
            l_val = self.generator_l.next_sample(self.bit_depth)
            r_val = self.generator_r.next_sample(self.bit_depth)

            l_samples[i] = l_val
            r_samples[i] = r_val

            outdata[i, 0] = l_val
            if out_ch > 1:
                outdata[i, 1] = r_val

        # Write to TX History (Ring Buffer)
        with self._lock:
            if not self.is_running:
                outdata.fill(0)
                return

            ptr = self.tx_write_ptr
            space = self.max_buffer_len - ptr
            if frames <= space:
                self.tx_history_l[ptr : ptr + frames] = l_samples
                self.tx_history_r[ptr : ptr + frames] = r_samples
                self.tx_write_ptr = (ptr + frames) % self.max_buffer_len
            else:
                self.tx_history_l[ptr:] = l_samples[:space]
                self.tx_history_l[: frames - space] = l_samples[space:]
                self.tx_history_r[ptr:] = r_samples[:space]
                self.tx_history_r[: frames - space] = r_samples[space:]
                self.tx_write_ptr = frames - space

            # 2. Record Input Signal
            n = len(indata)
            rx_ptr = self.rx_write_ptr
            rx_space = self.max_buffer_len - rx_ptr

            # Choose channel
            ch = self.input_channel_idx
            if ch >= indata.shape[1]:
                ch = 0
            ch_data = indata[:, ch]

            if n <= rx_space:
                self.rx_buffer[rx_ptr : rx_ptr + n] = ch_data
                self.rx_write_ptr = (rx_ptr + n) % self.max_buffer_len
            else:
                self.rx_buffer[rx_ptr:] = ch_data[:rx_space]
                self.rx_buffer[: n - rx_space] = ch_data[rx_space:]
                self.rx_write_ptr = n - rx_space

            self.new_samples_count = min(self.max_buffer_len, self.new_samples_count + n)

    def process_data(self) -> dict | None:
        """Processes ring buffer samples to compute all Digital & Analog diagnostics."""
        with self._lock:
            if not self.is_running or self.new_samples_count < 2048:
                return None

            # Read new samples from the ring buffer
            n = self.new_samples_count
            # Cap block-size at 2048 for live diagnostic updates
            block_size = min(n, 2048)

            rx_w = self.rx_write_ptr
            rx_r = (rx_w - block_size) % self.max_buffer_len

            if rx_r + block_size <= self.max_buffer_len:
                rx_block = self.rx_buffer[rx_r : rx_r + block_size].copy()
            else:
                part = self.max_buffer_len - rx_r
                rx_block = np.concatenate((self.rx_buffer[rx_r:], self.rx_buffer[: block_size - part]))

            self.new_samples_count = 0

            tx_w = self.tx_write_ptr

            # Determine alignment channel (which transmitter is the source of the measurement)
            # Left TX feeds Left RX, Right TX feeds Right RX under loopback.
            # We perform a .copy() inside the lock to prevent data races with the audio callback thread.
            if self.input_channel_idx == 0:
                align_tx_history = self.tx_history_l.copy()
            else:
                align_tx_history = self.tx_history_r.copy()

        # Synchronization & Lock
        if not self.is_locked:
            # Slides Pearson correlation over the reference sequence
            search_len = min(len(rx_block), 1024)
            segment = rx_block[:search_len]

            offset, corr = find_sequence_delay(segment, self.ref_cycle)

            # Lowered integer search threshold to 0.60 to account for physical analog loopback sub-sample delay
            if corr > 0.60:
                # Extract exact integer-aligned reference segment
                ref_segment = np.zeros(search_len, dtype=np.float32)
                for idx in range(search_len):
                    ref_segment[idx] = self.ref_cycle[(offset + idx) % self.ref_cycle_len]

                # Estimate sub-sample fractional delay using FFT phase
                est_delay = estimate_fractional_delay(segment, ref_segment)

                # Shift reference segment to align phases perfectly
                ref_shifted = shift_signal_fractional(ref_segment, est_delay)

                # Calculate fractional correlation
                seg_ac = segment - np.mean(segment)
                ref_s_ac = ref_shifted - np.mean(ref_shifted)
                norm_seg = np.linalg.norm(seg_ac)
                norm_ref = np.linalg.norm(ref_s_ac)

                if norm_seg > 1e-6 and norm_ref > 1e-6:
                    fractional_corr = float(np.dot(seg_ac, ref_s_ac) / (norm_seg * norm_ref))
                else:
                    fractional_corr = 0.0

                # Dynamically set threshold based on mode (Analog lines undergo inescapable frequency/phase distortions)
                lock_threshold = 0.90 if self.mode == "Digital" else 0.75

                if fractional_corr > lock_threshold:
                    self.is_locked = True
                    self.initial_fractional_delay = est_delay
                    self.fractional_delay = est_delay

                    # Calculate correct delay estimate modulo max_buffer_len to avoid wrap discrepancy
                    delay_est = (rx_w - block_size - offset) % self.max_buffer_len
                    # Prevent wrap discrepancy by keeping the delay within the PRBS period boundary.
                    # For very long periods (PRBS-23/31), we cap it at the reference cycle length to ensure
                    # the lock offset stays close to the write pointer. This prevents catastrophic boundary
                    # un-sync when the ring buffer wraps around.
                    sync_period = min(self.ref_cycle_len, len(self.ref_cycle))
                    delay_est = delay_est % sync_period

                    self.delay_samples = delay_est  # Save baseline physical loopback delay samples
                    self.initial_delay_samples = delay_est  # Save baseline for cumulative drift tracking

                    # Match to absolute tx write pointer using correct delay estimate
                    self.lock_offset = (rx_w - block_size - delay_est) % self.max_buffer_len
                    self.samples_processed = 0
                    logger.debug(
                        f"Transmission Lock Established. Offset={self.lock_offset}, Delay={self.delay_samples}, Fractional Delay={est_delay:.4f}, Correlation={fractional_corr:.4f}"
                    )
                else:
                    self.results["reason"] = tr("Waiting for sync... (Correlation: {0:.2f})").format(corr)
                    self.results["locked"] = False
                    return None
            else:
                self.results["reason"] = tr("Waiting for sync... (Correlation: {0:.2f})").format(corr)
                self.results["locked"] = False
                return None

        # Lock is active: Continuous alignment tracking (fine jitter/slip check)
        N = len(rx_block)
        offset = self.lock_offset

        # 1. Slide expected offset dynamically in sync with the audio callback's write index (tx_w)
        # This keeps the track_jitter search window [-8, +8] exactly centered around the true physical delay path.
        expected_offset = (rx_w - block_size - self.delay_samples) % self.max_buffer_len

        # 2. Track offset drift with sub-sample fractional precision using expected_offset.
        # Narrow active tracking search window to max_search=2 to drastically decrease noise false-positive locks.
        self.lock_offset, tracking_corr, self.fractional_delay = track_jitter_fractional(
            rx_block, align_tx_history, expected_offset, max_search=2
        )

        # 3. Integer Self-Correction Feedback Loop with Integrator Filter:
        # Detect if clock drift has slipped by one or more whole integer samples.
        # We use a slip integrator counter to filter out transient noise spikes:
        # We only update the delay_samples when a persistent slip in the same direction
        # is observed over multiple consecutive blocks (threshold = 3).
        drift_int = (expected_offset - self.lock_offset) % self.max_buffer_len
        if drift_int > self.max_buffer_len / 2:
            drift_int -= self.max_buffer_len

        if drift_int != 0:
            # Increment or decrement slip counter based on drift direction
            slip_dir = 1 if drift_int > 0 else -1

            # If the slip direction matches the current counter sign, accumulate it.
            # Otherwise, immediately reset to the new direction to catch up quickly on real drift.
            if (self.delay_slip_counter > 0 and slip_dir > 0) or (self.delay_slip_counter < 0 and slip_dir < 0):
                self.delay_slip_counter += slip_dir
            else:
                self.delay_slip_counter = slip_dir

            # Trigger delay correction only after 3 consecutive slip indications in the same direction
            if abs(self.delay_slip_counter) >= 3:
                self.delay_samples = (self.delay_samples + slip_dir) % self.max_buffer_len
                # Recalculate expected_offset and lock_offset to reflect the corrected baseline instantly
                expected_offset = (rx_w - block_size - self.delay_samples) % self.max_buffer_len
                self.lock_offset = (rx_w - block_size - self.delay_samples) % self.max_buffer_len
                logger.debug(
                    f"Absorption of Integer Drift (Integrator Triggered): Slipped {slip_dir:+.0f} samples. "
                    f"delay_samples corrected to {self.delay_samples}."
                )
                self.delay_slip_counter = 0
        else:
            # Decamp slip counter slowly to 0 when no slip is detected,
            # allowing high resilience to sporadic isolated slip reports.
            if self.delay_slip_counter > 0:
                self.delay_slip_counter -= 1
            elif self.delay_slip_counter < 0:
                self.delay_slip_counter += 1

        # Calculate matching aligned TX blocks (integer matched first)
        aligned_tx_int = np.zeros(N, dtype=np.float32)

        if self.lock_offset + N <= self.max_buffer_len:
            aligned_tx_int = align_tx_history[self.lock_offset : self.lock_offset + N]
        else:
            part = self.max_buffer_len - self.lock_offset
            aligned_tx_int = np.concatenate((align_tx_history[self.lock_offset :], align_tx_history[: N - part]))

        # Apply precision fractional delay shift to aligned primary signal in frequency domain.
        # This aligns the reference phases perfectly to the received block down to sub-sample scale.
        aligned_tx = shift_signal_fractional(aligned_tx_int, self.fractional_delay)

        # Check for catastrophic unlock using precision fractional correlation.
        # Threshold set dynamically to robustly handle physical analog line fluctuations.
        unlock_threshold = 0.75 if self.mode == "Digital" else 0.60
        if tracking_corr < unlock_threshold:
            # --- Robust Buffer-Skip Recovery (Warp Search) ---
            # Under high noise or heavy CoreAudio / sounddevice load, the OS/driver might bounce buffers
            # or drop blocks in perfect increments of 16384 samples, 32767 samples (PRBS period),
            # or 2048 samples (block size). Before declaring sync lost, we attempt to find the signal
            # at these known jump destinations.
            recovered = False
            jump_candidates = [16384, -16384, 32767, -32767, 2048, -2048, 4096, -4096]

            for jump in jump_candidates:
                test_expected = (expected_offset + jump) % self.max_buffer_len
                test_lock_offset, test_corr, test_frac = track_jitter_fractional(
                    rx_block, align_tx_history, test_expected, max_search=2
                )

                # If we find a highly correlated signal at the warp destination
                if test_corr > (unlock_threshold + 0.05):
                    # Warp established! Update the baseline delay instantly to absorb the jump.
                    drift_warp = (expected_offset - test_lock_offset) % self.max_buffer_len
                    if drift_warp > self.max_buffer_len / 2:
                        drift_warp -= self.max_buffer_len

                    self.delay_samples = (self.delay_samples + drift_warp) % self.max_buffer_len
                    expected_offset = (rx_w - block_size - self.delay_samples) % self.max_buffer_len
                    self.lock_offset = (rx_w - block_size - self.delay_samples) % self.max_buffer_len
                    self.fractional_delay = test_frac
                    tracking_corr = test_corr
                    self.delay_slip_counter = 0

                    logger.info(
                        f"[Warp Recovery Success] Absorbed sudden OS/buffer skip of {jump:+.0f} samples! "
                        f"Delay adjusted to {self.delay_samples}. Corr recovered to {tracking_corr:.4f}."
                    )
                    recovered = True
                    break

            if not recovered:
                rx_rms = float(np.sqrt(np.mean(rx_block**2)))
                tx_rms = float(np.sqrt(np.mean(aligned_tx**2)))
                logger.warning(
                    f"Transmission Analyzer lost lock due to low correlation!\n"
                    f"=== SYNC LOSS DETAILED DUMP ===\n"
                    f"  Mode                : {self.mode}\n"
                    f"  PRBS Pattern        : {self.pattern_mode}\n"
                    f"  Bit Depth Setting   : {self.bit_depth}-bit\n"
                    f"  Correlation         : {tracking_corr:.6f} (Threshold: {unlock_threshold:.2f})\n"
                    f"  Delay Samples (int) : {self.delay_samples}\n"
                    f"  Fractional Delay    : {self.fractional_delay:.6f}\n"
                    f"  Expected Offset     : {expected_offset}\n"
                    f"  Lock Offset         : {self.lock_offset}\n"
                    f"  Slip Counter        : {self.delay_slip_counter}\n"
                    f"  TX Write Ptr (tx_w) : {tx_w}\n"
                    f"  RX Write Ptr (rx_w) : {self.rx_write_ptr}\n"
                    f"  Block Size          : {N}\n"
                    f"  Received RMS Level  : {rx_rms:.6f}\n"
                    f"  Transmitted RMS     : {tx_rms:.6f}\n"
                    f"================================"
                )
                self.is_locked = False
                self.results["locked"] = False
                self.results["reason"] = tr("Lock lost (Low correlation).")
                return None

        self.samples_processed += N
        self.total_test_samples += N

        # Regular telemetry trace (every 10 blocks) to capture drift tendencies
        if (self.samples_processed // N) % 10 == 0:
            rx_rms_val = float(np.sqrt(np.mean(rx_block**2)))
            logger.info(
                f"[Transmission Telemetry] Block={self.samples_processed // N}, "
                f"Corr={tracking_corr:.4f}, Delay={self.delay_samples}, Frac={self.fractional_delay:.4f}, "
                f"Slip={self.delay_slip_counter}, RxRMS={rx_rms_val:.6f}"
            )

        # ---------------- 1. Digital & Analog Mode Metrics ----------------
        if self.mode == "Digital":
            diag = diagnose_bit_perfection(rx_block, aligned_tx)
            gain_db = diag["gain_db"]
            bit_depth = diag["bit_depth"]
            dsp_detected = diag["dsp_detected"]
            reason = diag["reason"]
            active_bits = diag["active_bits"]
            bit_perfect = diag["bit_perfect"]

            # Scale and compute bit errors for histogram
            gain_scalar = 10 ** (gain_db / 20.0)
            rx_scaled = rx_block / (gain_scalar + 1e-12)

            err_mask = np.abs(rx_scaled - aligned_tx) > 1e-6
            err_count = np.sum(err_mask)
            self.total_bit_errors += err_count

            if err_count > 0:
                # Map values into 24-bit integer values to verify exactly which bits flipped
                rx_int = np.round(rx_scaled[err_mask] * 8388608.0).astype(np.int32)
                ref_int = np.round(aligned_tx[err_mask] * 8388608.0).astype(np.int32)
                diff_mask = (rx_int ^ ref_int) & 0xFFFFFF

                for b in range(24):
                    bits_flipped = np.sum((diff_mask >> b) & 1)
                    self.bit_hist[b] += bits_flipped
        else:
            # Analog mode: Bypass digital bit perfect diagnostics
            dot_ref_ref = np.dot(aligned_tx, aligned_tx)
            if dot_ref_ref > 1e-12:
                K = np.dot(rx_block, aligned_tx) / dot_ref_ref
            else:
                K = 1.0
            gain_db = 20 * np.log10(abs(K) + 1e-12)
            bit_depth = 0
            dsp_detected = "N/A"
            active_bits = 0
            bit_perfect = False
            err_count = 0

        # Jitter estimation (convert offset variance into samples / ms)
        # Calculate cumulative integer buffer drift since initial sync baseline
        cumulative_drift_int = (self.delay_samples - self.initial_delay_samples) % self.max_buffer_len
        if cumulative_drift_int > self.max_buffer_len / 2:
            cumulative_drift_int -= self.max_buffer_len

        drift_frac = self.fractional_delay
        jitter_s = cumulative_drift_int + drift_frac

        # ---------------- 2. Analog Mode Metrics ----------------
        # 2a. Impulse Response (h[t])
        h = extract_impulse_response(rx_block, aligned_tx)
        # Center peak and truncate to 512 points for display
        peak_idx = np.argmax(np.abs(h))
        start_idx = max(0, peak_idx - 128)
        end_idx = min(len(h), start_idx + 512)
        self.impulse_response = h[start_idx:end_idx]

        # 2b. Frequency Response
        freqs, mag_db = extract_frequency_response(rx_block, aligned_tx, self.audio_engine.sample_rate)
        self.freq_resp_x = freqs
        self.freq_resp_y = mag_db

        # 2c. EVM calculation
        evm_val = calculate_evm(rx_block, aligned_tx)

        # Set analog-specific reason text if in Analog mode
        if self.mode == "Analog":
            if evm_val < 1.0:
                reason = tr("Excellent signal quality (EVM < 1.0%).")
            elif evm_val < 10.0:
                reason = tr("Standard analog path (EVM < 10.0%). Minimal distortion.")
            else:
                reason = tr("High signal distortion or noise (EVM >= 10.0%).")

        # Delay in samples & milliseconds
        delay_samples = self.delay_samples
        delay_ms = (delay_samples / self.audio_engine.sample_rate) * 1000.0

        # Update Trend Histories
        self.gain_trend.append(gain_db)
        self.ber_trend.append((err_count / N) * 100.0 if N > 0 else 0.0)
        self.jitter_trend.append(float(jitter_s))

        # Cap histories
        if len(self.gain_trend) > self.history_len:
            self.gain_trend.pop(0)
            self.ber_trend.pop(0)
            self.jitter_trend.pop(0)

        # Save results
        self.results = {
            "locked": True,
            "bit_perfect": bit_perfect,
            "reason": reason,
            "gain_db": gain_db,
            "bit_depth": bit_depth,
            "bit_errors": self.total_bit_errors,
            "error_rate": (self.total_bit_errors / self.total_test_samples) * 100.0
            if (self.mode == "Digital" and self.total_test_samples > 0)
            else 0.0,
            "total_samples": self.total_test_samples if self.mode == "Digital" else 0,
            "active_bits": active_bits,
            "evm": evm_val,
            "dsp_detected": dsp_detected,
            "jitter_samples": float(jitter_s),
            "delay_samples": delay_samples,
            "delay_ms": delay_ms,
        }

        return self.results


class TransmissionAnalyzerWidget(QWidget, CompactableWidgetInterface):
    def __init__(self, module: TransmissionAnalyzer):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        self.module = module

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.setInterval(200)  # 5Hz updates to reduce CPU overhead and timing drift

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ================= Left Panel: Controls =================
        self.left_panel = QWidget()
        self.left_panel.setFixedWidth(260)
        controls_layout = QVBoxLayout(self.left_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        # Test controls
        ctrl_group = QGroupBox(tr("Test Controls"))
        ctrl_layout = QVBoxLayout()
        ctrl_layout.setSpacing(6)

        self.btn_toggle = QPushButton(tr("Start Diagnostics"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setStyleSheet(
            "QPushButton { background-color: #2ecc71; color: black; font-weight: bold; height: 34px; border-radius: 4px; }"
            "QPushButton:checked { background-color: #e74c3c; color: white; }"
        )
        self.btn_toggle.clicked.connect(self.on_toggle_test)
        ctrl_layout.addWidget(self.btn_toggle)

        self.btn_clear = QPushButton(tr("Reset Statistics"))
        self.btn_clear.clicked.connect(self.on_reset_stats)
        ctrl_layout.addWidget(self.btn_clear)

        ctrl_group.setLayout(ctrl_layout)
        controls_layout.addWidget(ctrl_group)

        # Configuration Settings
        settings_group = QGroupBox(tr("Analyzer Settings"))
        form_layout = QFormLayout()
        form_layout.setVerticalSpacing(6)

        self.combo_mode = QComboBox()
        self.combo_mode.addItem(tr("Digital Integrity"), "Digital")
        self.combo_mode.addItem(tr("Analog Transmission"), "Analog")
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        form_layout.addRow(tr("Analysis Mode:"), self.combo_mode)

        self.combo_channel = QComboBox()
        self.combo_channel.addItem(tr("Left Channel (CH1)"), 0)
        self.combo_channel.addItem(tr("Right Channel (CH2)"), 1)
        self.combo_channel.currentIndexChanged.connect(self.on_channel_changed)
        form_layout.addRow(tr("Input Channel:"), self.combo_channel)

        self.combo_pattern = QComboBox()
        self.combo_pattern.addItem("PRBS-15 (Standard)", "PRBS-15")
        self.combo_pattern.addItem("PRBS-7 (Fast Sync)", "PRBS-7")
        self.combo_pattern.addItem("PRBS-9 (Low Latency)", "PRBS-9")
        self.combo_pattern.addItem("PRBS-23 (Long Sweep)", "PRBS-23")
        self.combo_pattern.addItem("PRBS-31 (High Load)", "PRBS-31")
        self.combo_pattern.currentIndexChanged.connect(self.on_settings_changed)
        form_layout.addRow(tr("PRBS Pattern:"), self.combo_pattern)

        self.combo_depth = QComboBox()
        self.combo_depth.addItem(tr("24-bit (High Precision)"), 24)
        self.combo_depth.addItem(tr("16-bit (CD Quality)"), 16)
        self.combo_depth.currentIndexChanged.connect(self.on_settings_changed)
        form_layout.addRow(tr("Bit Depth:"), self.combo_depth)

        settings_group.setLayout(form_layout)
        controls_layout.addWidget(settings_group)

        controls_layout.addStretch()
        main_layout.addWidget(self.left_panel)

        # ================= Right Panel: Visualizer Tabs =================
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)

        # 1. Dashboard Status Area
        self.card_status = QWidget()
        self.card_status.setStyleSheet("background-color: #2c3e50; border-radius: 6px;")
        self.card_status.setFixedHeight(105)
        status_layout = QVBoxLayout(self.card_status)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(2)

        self.lbl_status = QLabel(tr("IDLE"))
        self.lbl_status.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        self.lbl_status.setStyleSheet("color: #bdc3c7;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.lbl_status)

        self.lbl_reason = QLabel(tr("Start analysis to evaluate transmission characteristics."))
        self.lbl_reason.setStyleSheet("color: #ecf0f1; font-size: 12px;")
        self.lbl_reason.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self.lbl_reason)

        # Horizontal Row of Secondary Stats
        stats_row = QHBoxLayout()
        stats_row.setSpacing(15)

        self.lbl_stat_delay = QLabel(tr("Delay: -"))
        self.lbl_stat_delay.setStyleSheet("color: #ecf0f1; font-size: 11px; font-weight: bold;")
        self.lbl_stat_delay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_stat_evm = QLabel(tr("EVM: -"))
        self.lbl_stat_evm.setStyleSheet("color: #ecf0f1; font-size: 11px; font-weight: bold;")
        self.lbl_stat_evm.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stats_row.addWidget(self.lbl_stat_delay)
        stats_row.addWidget(self.lbl_stat_evm)
        status_layout.addLayout(stats_row)

        right_panel.addWidget(self.card_status)

        # 2. Tabs for Plots (To fit comfortably within size limitations)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane { border: 1px solid #7f8c8d; border-radius: 4px; padding: 4px; }")

        # Tab 1: Digital Report and Histogram
        self.tab_digital = QWidget()
        tab_dig_layout = QHBoxLayout(self.tab_digital)
        tab_dig_layout.setContentsMargins(5, 5, 5, 5)
        tab_dig_layout.setSpacing(10)

        # Report box
        self.lbl_report = QLabel(tr("Establish sync lock to generate digital report."))
        self.lbl_report.setStyleSheet(f"font-family: {MONOSPACE_FONT_FAMILY}; font-size: 11px;")
        self.lbl_report.setWordWrap(True)
        self.lbl_report.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        report_scroll = QGroupBox(tr("Diagnostic Report"))
        report_scroll_layout = QVBoxLayout(report_scroll)
        report_scroll_layout.addWidget(self.lbl_report)
        report_scroll.setLayout(report_scroll_layout)
        report_scroll.setFixedWidth(280)
        tab_dig_layout.addWidget(report_scroll)

        # Histogram Plot
        self.plot_hist = pg.PlotWidget()
        self.plot_hist.getPlotItem().getAxis("left").enableAutoSIPrefix(False)
        self.plot_hist.setLabel("bottom", tr("Bit Position (LSB 0 to MSB 23)"))
        self.plot_hist.setLabel("left", tr("Error Count"))
        self.plot_hist.showGrid(x=False, y=True, alpha=0.3)
        self.plot_hist.setXRange(-0.5, 23.5)
        self.bar_item = pg.BarGraphItem(x=np.arange(24), height=np.zeros(24), width=0.6, brush="y")
        self.plot_hist.addItem(self.bar_item)

        hist_group = QGroupBox(tr("Active Bit-Error Distribution"))
        hist_layout = QVBoxLayout(hist_group)
        hist_layout.addWidget(self.plot_hist)
        hist_group.setLayout(hist_layout)
        tab_dig_layout.addWidget(hist_group, stretch=1)

        self.tabs.addTab(self.tab_digital, tr("Digital Path"))

        # Tab 2: Impulse Response Plot
        self.tab_impulse = QWidget()
        tab_imp_layout = QVBoxLayout(self.tab_impulse)
        tab_imp_layout.setContentsMargins(5, 5, 5, 5)
        self.plot_imp = pg.PlotWidget()
        self.plot_imp.getPlotItem().getAxis("left").enableAutoSIPrefix(False)
        self.plot_imp.setLabel("bottom", tr("Time Domain Index (Samples)"))
        self.plot_imp.setLabel("left", tr("Amplitude"))
        self.plot_imp.showGrid(x=True, y=True, alpha=0.3)
        self.imp_curve = self.plot_imp.plot(pen=pg.mkPen("#2ecc71", width=2.0))
        tab_imp_layout.addWidget(self.plot_imp)
        self.tabs.addTab(self.tab_impulse, tr("Impulse Response"))

        # Tab 3: Frequency Response Plot
        self.tab_freq = QWidget()
        tab_freq_layout = QVBoxLayout(self.tab_freq)
        tab_freq_layout.setContentsMargins(5, 5, 5, 5)
        self.plot_freq = pg.PlotWidget()
        self.plot_freq.setLabel("bottom", tr("Frequency (Hz)"))
        self.plot_freq.setLabel("left", tr("Magnitude (dB)"))
        self.plot_freq.showGrid(x=True, y=True, alpha=0.3)
        self.plot_freq.setLogMode(x=True, y=False)

        # Custom Axis Ticks for Clean Decade Spacing matching the valid trace range (prevents label overlap)
        axis_freq = self.plot_freq.getPlotItem().getAxis("bottom")
        ticks = [100, 200, 500, 1000, 2000, 5000, 10000, 20000]
        ticks_log = [(np.log10(t), str(t) if t < 1000 else f"{t / 1000:.0f}k") for t in ticks]
        axis_freq.setTicks([ticks_log])

        sr = self.module.audio_engine.sample_rate
        nyquist = sr / 2.0
        self.plot_freq.setXRange(np.log10(90), np.log10(nyquist * 1.05))
        self.freq_curve = self.plot_freq.plot(pen=pg.mkPen("#e74c3c", width=2.0))
        tab_freq_layout.addWidget(self.plot_freq)
        self.tabs.addTab(self.tab_freq, tr("Transmission Response"))

        # Tab 4: Jitter & scrolling histories
        self.tab_trends = QWidget()
        tab_trend_layout = QVBoxLayout(self.tab_trends)
        tab_trend_layout.setContentsMargins(5, 5, 5, 5)
        tab_trend_layout.setSpacing(5)

        trend_ctrl_row = QHBoxLayout()
        trend_ctrl_row.addWidget(QLabel(tr("Select Trend Chart:")))
        self.combo_trend = QComboBox()
        self.combo_trend.currentIndexChanged.connect(self.on_trend_changed)
        trend_ctrl_row.addWidget(self.combo_trend)
        trend_ctrl_row.addStretch()
        tab_trend_layout.addLayout(trend_ctrl_row)

        self.plot_trend = pg.PlotWidget()
        self.plot_trend.getPlotItem().getAxis("left").enableAutoSIPrefix(False)
        self.plot_trend.setLabel("bottom", tr("History Time (Blocks)"))
        self.plot_trend.showGrid(x=True, y=True, alpha=0.3)
        self.trend_curve = self.plot_trend.plot(pen=pg.mkPen("#f1c40f", width=2.0))
        tab_trend_layout.addWidget(self.plot_trend)
        self.tabs.addTab(self.tab_trends, tr("Trends & Jitter"))

        self.update_trend_options()

        right_panel.addWidget(self.tabs, stretch=1)
        main_layout.addLayout(right_panel, stretch=1)

        self.setLayout(main_layout)

    def on_toggle_test(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.btn_toggle.setText(tr("Stop Analyzer"))
            self.lbl_status.setText(tr("WAITING FOR SYNC..."))
            self.lbl_status.setStyleSheet("color: #f39c12;")
            self.lbl_reason.setText(tr("Correlating incoming signal..."))
            self.tabs.setEnabled(True)
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.btn_toggle.setText(tr("Start Diagnostics"))
            self.lbl_status.setText(tr("IDLE"))
            self.lbl_status.setStyleSheet("color: #bdc3c7;")
            self.lbl_reason.setText(tr("Start analysis to evaluate transmission characteristics."))
            self.lbl_stat_delay.setText(tr("Delay: -"))
            self.lbl_stat_evm.setText(tr("EVM: -"))

    def on_reset_stats(self):
        with self.module._lock:
            self.module.total_test_samples = 0
            self.module.total_bit_errors = 0
            self.module.bit_hist.fill(0)
            self.bar_item.setOpts(height=np.zeros(24))
            self.module.gain_trend.clear()
            self.module.ber_trend.clear()
            self.module.jitter_trend.clear()

    def on_mode_changed(self, idx):
        mode = self.combo_mode.currentData()
        self.module.mode = mode

        # Switch tab index to highlight relevant visualizers and enable/disable digital tab
        if mode == "Digital":
            self.tabs.setTabEnabled(0, True)
            self.tabs.setCurrentIndex(0)
            self.plot_trend.setLabel("left", tr("Error Rate (%)"))
        else:
            self.tabs.setTabEnabled(0, False)
            self.tabs.setCurrentIndex(1)
            self.plot_trend.setLabel("left", tr("Jitter (samples)"))

        self.update_trend_options()

    def update_trend_options(self):
        curr_data = self.combo_trend.currentData()

        self.combo_trend.blockSignals(True)
        self.combo_trend.clear()
        self.combo_trend.addItem(tr("Clock Jitter / Buffer Drifts (samples)"), "jitter")
        self.combo_trend.addItem(tr("Gain / Volume Variations (dB)"), "gain")
        if self.module.mode == "Digital":
            self.combo_trend.addItem(tr("Bit Error Rate (BER %)"), "ber")

        idx = self.combo_trend.findData(curr_data)
        if idx >= 0:
            self.combo_trend.setCurrentIndex(idx)
        else:
            self.combo_trend.setCurrentIndex(0)
        self.combo_trend.blockSignals(False)

        self.update_trend_axes()

    def on_channel_changed(self, idx):
        self.module.input_channel_idx = idx

    def on_settings_changed(self):
        is_running = self.btn_toggle.isChecked()
        if is_running:
            self.module.stop_analysis()

        self.module.pattern_mode = self.combo_pattern.currentData()
        self.module.bit_depth = self.combo_depth.currentData()

        if is_running:
            self.module.start_analysis()

    def on_trend_changed(self):
        self.update_trend_axes()

    def update_trend_axes(self):
        trend = self.combo_trend.currentData()
        if not trend:
            return
        if trend == "jitter":
            self.plot_trend.setLabel("left", tr("Jitter / Drift (samples)"))
            self.trend_curve.setPen(pg.mkPen("#f1c40f", width=2.0))
        elif trend == "gain":
            self.plot_trend.setLabel("left", tr("Gain Deviation (dB)"))
            self.trend_curve.setPen(pg.mkPen("#3498db", width=2.0))
        elif trend == "ber":
            self.plot_trend.setLabel("left", tr("Instantaneous BER (%)"))
            self.trend_curve.setPen(pg.mkPen("#e74c3c", width=2.0))

    def update_display(self):
        res = self.module.process_data()
        if res is None:
            if not self.module.is_locked:
                self.lbl_status.setText(tr("WAITING FOR SYNC..."))
                self.lbl_status.setStyleSheet("color: #f39c12;")
                self.lbl_reason.setText(self.module.results["reason"])
            return

        # Locked and evaluating!
        # Color updates
        is_digital = self.module.mode == "Digital"

        if is_digital:
            is_perfect = res["bit_perfect"]
            if is_perfect:
                self.lbl_status.setText(tr("✔ BIT-PERFECT"))
                self.lbl_status.setStyleSheet("color: #2ecc71; font-weight: bold;")
                self.card_status.setStyleSheet("background-color: #1b4d3e; border-radius: 6px;")
            else:
                self.lbl_status.setText(tr("❌ ALTERED"))
                self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.card_status.setStyleSheet("background-color: #5c1d1d; border-radius: 6px;")
        else:
            # Analog mode color indicator (based on EVM thresholds)
            evm = res["evm"]
            if evm < 1.0:
                self.lbl_status.setText(tr("✔ HIGH FIDELITY"))
                self.lbl_status.setStyleSheet("color: #2ecc71; font-weight: bold;")
                self.card_status.setStyleSheet("background-color: #1b4d3e; border-radius: 6px;")
            elif evm < 10.0:
                self.lbl_status.setText(tr("▲ ANALOG PATH"))
                self.lbl_status.setStyleSheet("color: #f1c40f; font-weight: bold;")
                self.card_status.setStyleSheet("background-color: #4a3e1b; border-radius: 6px;")
            else:
                self.lbl_status.setText(tr("❌ HIGH DISTORTION"))
                self.lbl_status.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.card_status.setStyleSheet("background-color: #5c1d1d; border-radius: 6px;")

        self.lbl_reason.setText(res["reason"])

        # Update Secondary Header Metrics
        self.lbl_stat_delay.setText(
            tr("Delay: {0:d} samples ({1:.2f} ms)").format(res["delay_samples"], res["delay_ms"])
        )
        self.lbl_stat_evm.setText(tr("Waveform EVM: {0:.3f} %").format(res["evm"]))



        # Update Text Report (Tab 1)
        if self.module.mode == "Digital":
            report_text = (
                f"<b>{tr('Transmission Mode:')}</b> {tr(self.module.mode)}<br/>"
                f"<b>{tr('Detected Bit Depth:')}</b> {res['bit_depth'] if res['bit_depth'] > 0 else 'N/A'}-bit<br/>"
                f"<b>{tr('Volume Alteration:')}</b> {res['gain_db']:+.3f} dB<br/>"
                f"<b>{tr('Total Processed:')}</b> {res['total_samples']:,} samples<br/>"
                f"<b>{tr('Bit Errors:')}</b> {res['bit_errors']:,}<br/>"
                f"<b>{tr('Bit Error Rate (BER):')}</b> {res['error_rate']:.6f} %<br/>"
                f"<b>{tr('Intervention Heuristic:')}</b> {res['dsp_detected']}<br/>"
                f"<b>{tr('Jitter Drift:')}</b> {res['jitter_samples']:+.1f} samples"
            )
        else:
            report_text = (
                f"<b>{tr('Transmission Mode:')}</b> {tr(self.module.mode)}<br/>"
                f"<br/>"
                f"<i>{tr('Digital Path diagnostics are disabled in Analog Transmission mode.')}</i>"
            )
        self.lbl_report.setText(report_text)

        # Update Bit-Error Histogram (Tab 1)
        hist = self.module.bit_hist.copy()
        self.bar_item.setOpts(height=hist)
        max_err = np.max(hist)
        self.plot_hist.setYRange(0, max(10, max_err * 1.1))

        # Update Impulse Response plot (Tab 2)
        imp = self.module.impulse_response
        self.imp_curve.setData(imp)
        self.plot_imp.setXRange(0, len(imp))
        self.plot_imp.setYRange(np.min(imp) * 1.1 - 0.05, np.max(imp) * 1.1 + 0.05)

        # Update Frequency Response plot (Tab 3)
        freq_y = self.module.freq_resp_y
        freq_x = self.module.freq_resp_x
        # Avoid 0Hz to prevent log10(0) coordinate issues inside pyqtgraph
        valid_mask = freq_x > 0
        self.freq_curve.setData(freq_x[valid_mask], freq_y[valid_mask])
        self.plot_freq.setYRange(-80.0, 10.0)

        # Update Jitter & Trends plot (Tab 4)
        trend = self.combo_trend.currentData()
        if trend == "jitter":
            y_data = list(self.module.jitter_trend)
        elif trend == "gain":
            y_data = list(self.module.gain_trend)
        elif trend == "ber":
            y_data = list(self.module.ber_trend)
        else:
            y_data = []

        if len(y_data) > 0:
            self.trend_curve.setData(np.arange(len(y_data)), np.array(y_data))
            self.plot_trend.setXRange(0, self.module.history_len)
            min_y = np.min(y_data)
            max_y = np.max(y_data)
            max_y - min_y
            self.plot_trend.setYRange(min_y - 0.1 * abs(min_y) - 0.05, max_y + 0.1 * abs(max_y) + 0.05)

    def update_compact_layout(self):
        compact = self.is_compact_mode()
        self.left_panel.setHidden(compact)

        win = self.window()
        if win:
            from PyQt6 import sip
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(50, lambda: win.adjustSize() if not sip.isdeleted(win) else None)

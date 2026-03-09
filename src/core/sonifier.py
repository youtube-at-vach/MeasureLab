import threading
import time

import numpy as np


class PeakToneSonifier:
    """Sonifies detected peaks as a chord with smooth transitions and CPU optimizations."""

    AUDIBLE_MIN_FREQ = 220.0
    AUDIBLE_MAX_FREQ = 1760.0
    MAX_SUPPORTED_PEAKS = 5
    DEFAULT_TONE_PEAK = 0.12
    MODE_CHORD = "chord"

    # Smoothing time constants
    AMP_SMOOTH_TC = 0.05  # seconds
    FREQ_SMOOTH_TC = 0.05  # seconds

    # Safety Watchdog
    WATCHDOG_TIMEOUT = 0.5 # seconds

    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.enabled = False
        self.master_volume = 0.5
        self.output_channel = 2
        self.max_peaks = 1
        self.tone_peak = self.DEFAULT_TONE_PEAK
        self.mode = self.MODE_CHORD

        # Oscillator Bank
        # Each oscillator has: [frequency, target_frequency, amplitude, target_amplitude, phase]
        self._oscillators = np.zeros((self.MAX_SUPPORTED_PEAKS, 5), dtype=np.float64)
        # 0: current_freq
        # 1: target_freq
        # 2: current_amp
        # 3: target_amp
        # 4: phase

        self._last_update_time = 0.0
        self.lock = threading.Lock()

    def set_sample_rate(self, sr):
        with self.lock:
            self.sample_rate = sr

    def set_enabled(self, enabled):
        with self.lock:
            self.enabled = bool(enabled)
            if not self.enabled:
                self._reset_state()
            else:
                self._last_update_time = time.time()

    def set_volume(self, volume):
        with self.lock:
            self.master_volume = max(0.0, min(1.0, float(volume)))

    def set_output_channel(self, channel):
        with self.lock:
            self.output_channel = int(channel)

    def set_max_peaks(self, peaks):
        with self.lock:
            old_max = self.max_peaks
            self.max_peaks = max(1, min(self.MAX_SUPPORTED_PEAKS, int(peaks)))
            if self.max_peaks < old_max:
                # Instantly silence oscillators that are now out of range
                self._oscillators[self.max_peaks :, 3] = 0.0

    def _reset_state(self):
        self._oscillators.fill(0.0)

    def _fold_to_audible_band(self, freq_hz):
        freq = float(max(1.0, freq_hz))
        while freq < self.AUDIBLE_MIN_FREQ:
            freq *= 2.0
        while freq > self.AUDIBLE_MAX_FREQ:
            freq *= 0.5
        return freq

    def update_spectrum(self, freqs_hz, mags_db, peak_freqs_hz):
        """Update targets of the oscillator bank based on detected peaks."""
        if not self.enabled:
            return

        # Record activity for watchdog
        self._last_update_time = time.time()

        # 1. Prepare and fold new peak frequencies
        new_peaks = [self._fold_to_audible_band(f) for f in peak_freqs_hz[: self.max_peaks] if f is not None]

        with self.lock:
            # 2. Track peaks and assign to oscillators
            assigned_peaks = [False] * len(new_peaks)
            used_oscillators = [False] * self.MAX_SUPPORTED_PEAKS

            # First pass: Exact or very close match
            for i in range(self.max_peaks):
                curr_f = self._oscillators[i, 0]
                if self._oscillators[i, 2] < 1e-4: # Silent oscillator
                    continue

                best_peak_idx = -1
                best_dist = 0.2 # 20% relative distance max for "tracking"

                for j, p_f in enumerate(new_peaks):
                    if assigned_peaks[j]:
                        continue
                    dist = abs(p_f - curr_f) / max(1.0, curr_f)
                    if dist < best_dist:
                        best_dist = dist
                        best_peak_idx = j

                if best_peak_idx != -1:
                    self._oscillators[i, 1] = new_peaks[best_peak_idx]
                    self._oscillators[i, 3] = 1.0 
                    assigned_peaks[best_peak_idx] = True
                    used_oscillators[i] = True

            # Second pass: Assign remaining peaks to silent oscillators
            for j, p_f in enumerate(new_peaks):
                if assigned_peaks[j]:
                    continue

                for i in range(self.max_peaks):
                    if not used_oscillators[i] and self._oscillators[i, 2] < 1e-4:
                        if self._oscillators[i, 2] == 0.0:
                            self._oscillators[i, 0] = p_f 
                        self._oscillators[i, 1] = p_f
                        self._oscillators[i, 3] = 1.0
                        used_oscillators[i] = True
                        assigned_peaks[j] = True
                        break

            # Third pass: Set remaining active but unmatched oscillators to target 0 amplitude
            for i in range(self.MAX_SUPPORTED_PEAKS):
                if not used_oscillators[i]:
                    self._oscillators[i, 3] = 0.0

    def process(self, outdata):
        with self.lock:
            if not self.enabled:
                outdata.fill(0.0)
                return

            sr = self.sample_rate
            out_ch = self.output_channel
            master_gain = self.tone_peak * self.master_volume
            num_oscillators = self.MAX_SUPPORTED_PEAKS

            # Watchdog check: If no update for 0.5s, trigger fade out
            if time.time() - self._last_update_time > self.WATCHDOG_TIMEOUT:
                self._oscillators[:, 3] = 0.0

            state = self._oscillators.copy()

        if sr <= 0:
            outdata.fill(0.0)
            return

        frames = len(outdata)
        mixed_wave = np.zeros(frames, dtype=np.float64)

        active_mask = (state[:, 2] > 1e-5) | (state[:, 3] > 1e-5)
        active_count = np.count_nonzero(active_mask)
        if active_count == 0:
            outdata.fill(0.0)
            return

        gain_multiplier = master_gain / max(1.0, np.sqrt(float(active_count)))
        dt = 1.0 / sr
        two_pi = 2.0 * np.pi
        two_pi_dt = two_pi * dt

        # Pre-allocate time index array
        t_array = np.arange(frames, dtype=np.float64)
        progress = t_array / frames

        for i in range(num_oscillators):
            if not active_mask[i]:
                continue

            curr_f, target_f, curr_a, target_a, phase = state[i]

            buffer_time = frames * dt
            alpha_a = 1.0 - np.exp(-buffer_time / self.AMP_SMOOTH_TC)
            alpha_f = 1.0 - np.exp(-buffer_time / self.FREQ_SMOOTH_TC)

            next_a = curr_a + (target_a - curr_a) * alpha_a
            next_f = curr_f + (target_f - curr_f) * alpha_f

            # Optimization: Skip if amplitude is effectively zero
            if curr_a < 1e-6 and next_a < 1e-6:
                state[i, 0] = next_f
                state[i, 2] = 0.0
                continue

            # Optimization: Use fast phase calculation if frequency is static
            if abs(next_f - curr_f) < 1e-3:
                phases = phase + two_pi_dt * curr_f * t_array
                next_f = curr_f # Keep it exactly static
            else:
                # Linear frequency sweep: phase = 2*pi * integral( (f0 + (f1-f0)*t/T) dt )
                # = 2*pi * (f0*t + 0.5*(f1-f0)*t^2/T)
                phases = phase + (two_pi_dt) * (t_array * curr_f + (next_f - curr_f) * (t_array * (t_array - 1)) / (2.0 * frames))

            # Optimization: Skip amplitude interpolation if gain is static
            if abs(next_a - curr_a) < 1e-4:
                mixed_wave += np.sin(phases) * curr_a
            else:
                amps = curr_a + (next_a - curr_a) * progress
                mixed_wave += np.sin(phases) * amps

            # Update state
            state[i, 0] = next_f
            state[i, 2] = next_a
            state[i, 4] = (phases[-1] + two_pi_dt * next_f) % two_pi

        mixed_wave *= gain_multiplier

        channels = outdata.shape[1]
        outdata.fill(0.0)
        if out_ch == 0:
            outdata[:, 0] = mixed_wave
        elif out_ch == 1:
            if channels > 1:
                outdata[:, 1] = mixed_wave
            else:
                outdata[:, 0] = mixed_wave
        else:
            for channel in range(channels):
                outdata[:, channel] = mixed_wave

        with self.lock:
            self._oscillators = state

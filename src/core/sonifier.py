import threading

import numpy as np


class PeakToneSonifier:
    """Sonifies detected peaks as a chord with smooth transitions."""

    AUDIBLE_MIN_FREQ = 220.0
    AUDIBLE_MAX_FREQ = 1760.0
    MAX_SUPPORTED_PEAKS = 5
    DEFAULT_TONE_PEAK = 0.12
    MODE_CHORD = "chord"

    # Smoothing time constants
    AMP_SMOOTH_TC = 0.05  # seconds
    FREQ_SMOOTH_TC = 0.05  # seconds

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

        self.lock = threading.Lock()

    def set_sample_rate(self, sr):
        with self.lock:
            self.sample_rate = sr

    def set_enabled(self, enabled):
        with self.lock:
            self.enabled = bool(enabled)
            if not self.enabled:
                self._reset_state()

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

        # 1. Prepare and fold new peak frequencies
        new_peaks = [self._fold_to_audible_band(f) for f in peak_freqs_hz[: self.max_peaks] if f is not None]

        with self.lock:
            # 2. Track peaks and assign to oscillators
            # We want to match existing oscillators to new peaks to prevent jumps.
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
                    self._oscillators[i, 3] = 1.0 # Target amplitude is fully on
                    assigned_peaks[best_peak_idx] = True
                    used_oscillators[i] = True

            # Second pass: Assign remaining peaks to silent oscillators
            for j, p_f in enumerate(new_peaks):
                if assigned_peaks[j]:
                    continue

                # Find a silent oscillator
                for i in range(self.max_peaks):
                    if not used_oscillators[i] and self._oscillators[i, 2] < 1e-4:
                        if self._oscillators[i, 2] == 0.0:
                            self._oscillators[i, 0] = p_f # Start exactly at freq
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

            # Copy state to local variables for processing
            state = self._oscillators.copy()

        if sr <= 0:
            outdata.fill(0.0)
            return

        frames = len(outdata)
        mixed_wave = np.zeros(frames, dtype=np.float64)

        # We'll determine the normalizing gain based on the number of active/fading oscillators
        # but for simplicity, we use sqrt(active_count) or fixed if preferred.
        # Let's count how many oscillators have significant amplitude or target amplitude.
        active_count = np.count_nonzero((state[:, 2] > 1e-4) | (state[:, 3] > 1e-4))
        gain_multiplier = master_gain / max(1.0, np.sqrt(float(active_count)))

        # Pre-calculate sampling period
        dt = 1.0 / sr
        two_pi = 2.0 * np.pi

        for i in range(num_oscillators):
            curr_f, target_f, curr_a, target_a, phase = state[i]

            if curr_a < 1e-5 and target_a < 1e-5:
                continue

            # Simple linear ramp for frequency and amplitude across the buffer
            # This is an approximation. A true exponential smoothing would be per-sample.
            # But linear ramp across a small buffer (e.g. 10ms-50ms) is usually seamless enough.

            # Per-sample phase increment and gain
            # We use half-buffer interpolation or just linear end-to-end.

            # Calculate next state values (smoothing)
            # Using exponential smoothing logic: y = y + (target - y) * alpha
            # Alpha for a whole buffer: 1 - exp(-buffer_time / smoothing_tc)
            buffer_time = frames * dt

            alpha_a = 1.0 - np.exp(-buffer_time / self.AMP_SMOOTH_TC)
            alpha_f = 1.0 - np.exp(-buffer_time / self.FREQ_SMOOTH_TC)

            next_a = curr_a + (target_a - curr_a) * alpha_a
            next_f = curr_f + (target_f - curr_f) * alpha_f

            # Generate sample arrays for gains and frequencies
            t_array = np.arange(frames, dtype=np.float64)
            progress = t_array / frames

            # Interpolated amplitude
            amps = curr_a + (next_a - curr_a) * progress

            # Accumulated phase: phase(t) = phase(0) + sum(2*pi*f(i)*dt)
            # Since f(i) is linear, sum is based on arithmetic progression:
            # phase(n) = phase(0) + 2*pi*dt * [n*curr_f + (next_f - curr_f)/frames * sum(0..n-1)]
            # sum(0..n-1) = (n-1)*n / 2

            phases = phase + (two_pi * dt) * (t_array * curr_f + (next_f - curr_f) * (t_array * (t_array - 1)) / (2.0 * frames))

            # Oscillation
            mixed_wave += np.sin(phases) * amps

            # Update state for next block
            state[i, 0] = next_f
            state[i, 2] = next_a
            state[i, 4] = (phases[-1] + two_pi * next_f * dt) % two_pi

        mixed_wave *= gain_multiplier

        # Write to output channels
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

        # Save back the state
        with self.lock:
            self._oscillators = state

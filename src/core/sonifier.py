import threading

import numpy as np


class PeakToneSonifier:
    """
    Lightweight sonifier that plays a few detected peak frequencies
    at a fixed level. Updates happen outside the audio callback.
    """

    AUDIBLE_MIN_FREQ = 220.0
    AUDIBLE_MAX_FREQ = 1760.0
    MAX_SUPPORTED_PEAKS = 8
    DEFAULT_TONE_PEAK = 0.12

    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.enabled = False
        self.master_volume = 0.5
        self.output_channel = 2
        self.max_peaks = 1
        self.tone_peak = self.DEFAULT_TONE_PEAK

        self._active_freqs = np.zeros(0, dtype=np.float64)
        self._phase_state = np.zeros(self.MAX_SUPPORTED_PEAKS, dtype=np.float64)
        self.lock = threading.Lock()

    def set_sample_rate(self, sr):
        with self.lock:
            self.sample_rate = sr

    def set_enabled(self, enabled):
        with self.lock:
            self.enabled = bool(enabled)
            if not self.enabled:
                self._active_freqs = np.zeros(0, dtype=np.float64)

    def set_volume(self, volume):
        with self.lock:
            self.master_volume = max(0.0, min(1.0, float(volume)))

    def set_output_channel(self, channel):
        with self.lock:
            self.output_channel = int(channel)

    def set_max_peaks(self, peaks):
        with self.lock:
            self.max_peaks = max(1, min(self.MAX_SUPPORTED_PEAKS, int(peaks)))

    def _fold_to_audible_band(self, freq_hz):
        freq = float(max(1.0, freq_hz))
        while freq < self.AUDIBLE_MIN_FREQ:
            freq *= 2.0
        while freq > self.AUDIBLE_MAX_FREQ:
            freq *= 0.5
        return freq

    def update_peaks(self, peak_freqs_hz):
        if not self.enabled:
            return

        cleaned = []
        for freq in peak_freqs_hz[: self.MAX_SUPPORTED_PEAKS]:
            if freq is None:
                continue
            cleaned.append(self._fold_to_audible_band(freq))

        if cleaned:
            cleaned_arr = np.asarray(cleaned, dtype=np.float64)
        else:
            cleaned_arr = np.zeros(0, dtype=np.float64)

        with self.lock:
            limit = min(self.max_peaks, len(cleaned_arr))
            new_freqs = cleaned_arr[:limit]
            if len(new_freqs) == len(self._active_freqs) and np.array_equal(new_freqs, self._active_freqs):
                return
            self._active_freqs = new_freqs

    def process(self, outdata):
        frames = len(outdata)
        channels = outdata.shape[1]

        with self.lock:
            if not self.enabled or len(self._active_freqs) == 0:
                outdata.fill(0.0)
                return

            sr = self.sample_rate
            out_ch = self.output_channel
            freqs = self._active_freqs.copy()
            phase_state = self._phase_state.copy()
            tone_peak = self.tone_peak * self.master_volume

        if sr <= 0:
            outdata.fill(0.0)
            return

        tone_count = len(freqs)
        gain = tone_peak / max(1.0, np.sqrt(float(tone_count)))
        frame_idx = np.arange(frames, dtype=np.float64)

        if tone_count == 1:
            phase = phase_state[0] + frame_idx * ((2.0 * np.pi * freqs[0]) / sr)
            wave = np.sin(phase) * gain
            next_phase = phase[-1] + (2.0 * np.pi * freqs[0] / sr)
            updated_phases = np.array([next_phase % (2.0 * np.pi)], dtype=np.float64)
        else:
            wave = np.zeros(frames, dtype=np.float64)
            updated_phases = np.zeros(tone_count, dtype=np.float64)
            for idx, freq in enumerate(freqs):
                phase = phase_state[idx] + frame_idx * ((2.0 * np.pi * freq) / sr)
                wave += np.sin(phase)
                updated_phases[idx] = (phase[-1] + (2.0 * np.pi * freq / sr)) % (2.0 * np.pi)
            wave *= gain

        outdata.fill(0.0)
        if out_ch == 0:
            outdata[:, 0] = wave
        elif out_ch == 1:
            if channels > 1:
                outdata[:, 1] = wave
            else:
                outdata[:, 0] = wave
        else:
            for c in range(channels):
                outdata[:, c] = wave

        with self.lock:
            self._phase_state[:tone_count] = updated_phases

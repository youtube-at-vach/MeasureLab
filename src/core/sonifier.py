import threading

import numpy as np


class PeakToneSonifier:
    """
    Lightweight sonifier that plays a few detected peak frequencies
    at a fixed level. Updates happen outside the audio callback.
    """

    AUDIBLE_MIN_FREQ = 220.0
    AUDIBLE_MAX_FREQ = 1760.0
    MAX_SUPPORTED_PEAKS = 16
    DEFAULT_TONE_PEAK = 0.12
    MODE_CHORD = "chord"
    MODE_SWEEP_BEEPS = "sweep_beeps"
    QUEUE_DOT_SEC = 0.060
    QUEUE_DASH_SEC = 0.180
    QUEUE_ELEMENT_GAP_SEC = 0.060
    QUEUE_PEAK_GAP_SEC = 0.120
    QUEUE_PITCHES = np.asarray([523.25, 659.25, 783.99, 1046.50], dtype=np.float64)

    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.enabled = False
        self.master_volume = 0.5
        self.output_channel = 2
        self.max_peaks = 1
        self.tone_peak = self.DEFAULT_TONE_PEAK
        self.mode = self.MODE_CHORD

        self._active_freqs = np.zeros(0, dtype=np.float64)
        self._phase_state = np.zeros(self.MAX_SUPPORTED_PEAKS, dtype=np.float64)
        self._queue_freqs = np.zeros(0, dtype=np.float64)
        self._queue_lengths = np.zeros(0, dtype=np.int64)
        self._queue_levels = np.zeros(0, dtype=np.float64)
        self._pending_queue_freqs = np.zeros(0, dtype=np.float64)
        self._pending_queue_lengths = np.zeros(0, dtype=np.int64)
        self._pending_queue_levels = np.zeros(0, dtype=np.float64)
        self._queue_index = 0
        self._queue_remaining = 0
        self._queue_phase = 0.0
        self._queue_elapsed = 0
        self.lock = threading.Lock()

    def set_sample_rate(self, sr):
        with self.lock:
            self.sample_rate = sr

    def set_enabled(self, enabled):
        with self.lock:
            self.enabled = bool(enabled)
            if not self.enabled:
                self._active_freqs = np.zeros(0, dtype=np.float64)
                self._clear_queue_state()

    def set_volume(self, volume):
        with self.lock:
            self.master_volume = max(0.0, min(1.0, float(volume)))

    def set_output_channel(self, channel):
        with self.lock:
            self.output_channel = int(channel)

    def set_max_peaks(self, peaks):
        with self.lock:
            self.max_peaks = max(1, min(self.MAX_SUPPORTED_PEAKS, int(peaks)))

    def set_mode(self, mode):
        mode = str(mode)
        if mode not in {self.MODE_CHORD, self.MODE_SWEEP_BEEPS}:
            mode = self.MODE_CHORD

        with self.lock:
            if self.mode == mode:
                return
            self.mode = mode
            self._phase_state.fill(0.0)
            self._clear_queue_state()

    def _fold_to_audible_band(self, freq_hz):
        freq = float(max(1.0, freq_hz))
        while freq < self.AUDIBLE_MIN_FREQ:
            freq *= 2.0
        while freq > self.AUDIBLE_MAX_FREQ:
            freq *= 0.5
        return freq

    def update_peaks(self, peak_freqs_hz, spectrum_range=None):
        if not self.enabled:
            return

        raw_freqs = []
        folded_freqs = []
        for freq in peak_freqs_hz[: self.MAX_SUPPORTED_PEAKS]:
            if freq is None:
                continue
            raw_freqs.append(float(freq))
            folded_freqs.append(self._fold_to_audible_band(freq))

        if folded_freqs:
            cleaned_arr = np.asarray(folded_freqs, dtype=np.float64)
        else:
            cleaned_arr = np.zeros(0, dtype=np.float64)

        with self.lock:
            limit = min(self.max_peaks, len(cleaned_arr))
            new_freqs = cleaned_arr[:limit]
            if len(new_freqs) == len(self._active_freqs) and np.array_equal(new_freqs, self._active_freqs):
                peaks_unchanged = True
            else:
                peaks_unchanged = False
            self._active_freqs = new_freqs
            if peaks_unchanged and self.mode == self.MODE_CHORD:
                return

            if self.mode == self.MODE_SWEEP_BEEPS:
                start_freq, stop_freq = self._get_range_limits(raw_freqs[:limit], spectrum_range)

                if limit == 0:
                    self._pending_queue_freqs = np.zeros(0, dtype=np.float64)
                    self._pending_queue_lengths = np.zeros(0, dtype=np.int64)
                    self._pending_queue_levels = np.zeros(0, dtype=np.float64)
                    return

                queue_freqs, queue_lengths, queue_levels = self._build_rhythmic_queue(
                    raw_freqs[:limit],
                    start_freq,
                    stop_freq,
                )
                self._pending_queue_freqs = queue_freqs
                self._pending_queue_lengths = queue_lengths
                self._pending_queue_levels = queue_levels
                if len(self._queue_freqs) == 0:
                    self._activate_pending_queue()

    def _get_range_limits(self, peak_freqs_hz, spectrum_range):
        if spectrum_range is not None:
            try:
                low = float(spectrum_range[0])
                high = float(spectrum_range[1])
            except (TypeError, ValueError, IndexError):
                low = 0.0
                high = 0.0
        elif peak_freqs_hz:
            low = float(min(peak_freqs_hz))
            high = float(max(peak_freqs_hz))
        else:
            low = 0.0
            high = 0.0

        if high <= low:
            high = low + 1.0
        return low, high

    def _clear_queue_state(self):
        self._queue_freqs = np.zeros(0, dtype=np.float64)
        self._queue_lengths = np.zeros(0, dtype=np.int64)
        self._queue_levels = np.zeros(0, dtype=np.float64)
        self._pending_queue_freqs = np.zeros(0, dtype=np.float64)
        self._pending_queue_lengths = np.zeros(0, dtype=np.int64)
        self._pending_queue_levels = np.zeros(0, dtype=np.float64)
        self._queue_index = 0
        self._queue_remaining = 0
        self._queue_phase = 0.0
        self._queue_elapsed = 0

    def _activate_pending_queue(self):
        self._queue_freqs = self._pending_queue_freqs
        self._queue_lengths = self._pending_queue_lengths
        self._queue_levels = self._pending_queue_levels
        self._pending_queue_freqs = np.zeros(0, dtype=np.float64)
        self._pending_queue_lengths = np.zeros(0, dtype=np.int64)
        self._pending_queue_levels = np.zeros(0, dtype=np.float64)
        self._queue_index = 0
        if len(self._queue_lengths) > 0:
            self._queue_remaining = int(self._queue_lengths[0])
        else:
            self._queue_remaining = 0
        self._queue_phase = 0.0
        self._queue_elapsed = 0

    def _build_rhythmic_queue(self, peak_freqs_hz, start_freq, stop_freq):
        dot_len = max(16, int(round(self.QUEUE_DOT_SEC * self.sample_rate)))
        dash_len = max(dot_len, int(round(self.QUEUE_DASH_SEC * self.sample_rate)))
        element_gap = max(8, int(round(self.QUEUE_ELEMENT_GAP_SEC * self.sample_rate)))
        peak_gap = max(element_gap, int(round(self.QUEUE_PEAK_GAP_SEC * self.sample_rate)))

        queue_freqs = []
        queue_lengths = []
        queue_levels = []
        peak_count = max(1, len(peak_freqs_hz))

        for idx, raw_freq in enumerate(peak_freqs_hz):
            norm = (float(raw_freq) - start_freq) / max(1e-9, stop_freq - start_freq)
            norm = min(1.0, max(0.0, norm))
            pitch_idx = min(len(self.QUEUE_PITCHES) - 1, int(norm * len(self.QUEUE_PITCHES)))
            pitch = float(self.QUEUE_PITCHES[pitch_idx])
            pulse_len = dash_len if idx < max(1, peak_count // 3) else dot_len
            level = 1.0 - min(0.45, 0.10 * idx)

            queue_freqs.append(pitch)
            queue_lengths.append(pulse_len)
            queue_levels.append(level)

            queue_freqs.append(0.0)
            queue_lengths.append(element_gap)
            queue_levels.append(0.0)

            if idx < peak_count - 1:
                queue_freqs.append(0.0)
                queue_lengths.append(peak_gap)
                queue_levels.append(0.0)

        return (
            np.asarray(queue_freqs, dtype=np.float64),
            np.asarray(queue_lengths, dtype=np.int64),
            np.asarray(queue_levels, dtype=np.float64),
        )

    def _process_chord_mode(self, outdata, sr, out_ch, freqs, phase_state, tone_peak):
        frames = len(outdata)
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

        self._write_wave(outdata, out_ch, wave)

        with self.lock:
            self._phase_state[:tone_count] = updated_phases

    def _process_sweep_mode(
        self,
        outdata,
        sr,
        out_ch,
        queue_freqs,
        queue_lengths,
        queue_levels,
        queue_index,
        queue_remaining,
        queue_phase,
        queue_elapsed,
        tone_peak,
    ):
        frames = len(outdata)
        wave = np.zeros(frames, dtype=np.float64)
        offset = 0
        local_index = queue_index
        local_remaining = queue_remaining
        local_phase = queue_phase
        local_elapsed = queue_elapsed

        while offset < frames:
            if len(queue_freqs) == 0:
                break

            if local_remaining <= 0:
                local_index += 1
                if local_index >= len(queue_freqs):
                    with self.lock:
                        if len(self._pending_queue_freqs) > 0:
                            self._activate_pending_queue()
                            queue_freqs = self._queue_freqs.copy()
                            queue_lengths = self._queue_lengths.copy()
                            queue_levels = self._queue_levels.copy()
                        local_index = 0
                    if len(queue_freqs) == 0:
                        break
                local_remaining = int(queue_lengths[local_index])
                local_phase = 0.0
                local_elapsed = 0

            chunk = min(frames - offset, local_remaining)
            freq = float(queue_freqs[local_index])
            level = float(queue_levels[local_index])
            total_len = max(1, int(queue_lengths[local_index]))

            if freq > 0.0 and level > 0.0:
                sample_idx = np.arange(chunk, dtype=np.float64)
                phase = local_phase + sample_idx * ((2.0 * np.pi * freq) / sr)
                pos = (local_elapsed + sample_idx + 0.5) / float(total_len)
                envelope = np.sin(np.pi * np.clip(pos, 0.0, 1.0))
                wave[offset : offset + chunk] = np.sin(phase) * envelope * tone_peak * level
                local_phase = (phase[-1] + (2.0 * np.pi * freq / sr)) % (2.0 * np.pi)
            else:
                wave[offset : offset + chunk] = 0.0
                local_phase = 0.0

            offset += chunk
            local_remaining -= chunk
            local_elapsed += chunk

        self._write_wave(outdata, out_ch, wave)

        with self.lock:
            self._queue_index = local_index
            self._queue_remaining = local_remaining
            self._queue_phase = local_phase
            self._queue_elapsed = local_elapsed

    def _write_wave(self, outdata, out_ch, wave):
        channels = outdata.shape[1]
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

    def process(self, outdata):
        with self.lock:
            if not self.enabled:
                outdata.fill(0.0)
                return

            sr = self.sample_rate
            out_ch = self.output_channel
            mode = self.mode
            freqs = self._active_freqs.copy()
            phase_state = self._phase_state.copy()
            queue_freqs = self._queue_freqs.copy()
            queue_lengths = self._queue_lengths.copy()
            queue_levels = self._queue_levels.copy()
            queue_index = self._queue_index
            queue_remaining = self._queue_remaining
            queue_phase = self._queue_phase
            queue_elapsed = self._queue_elapsed
            tone_peak = self.tone_peak * self.master_volume

        if sr <= 0:
            outdata.fill(0.0)
            return

        if mode == self.MODE_SWEEP_BEEPS:
            if len(queue_freqs) == 0:
                outdata.fill(0.0)
                return
            self._process_sweep_mode(
                outdata,
                sr,
                out_ch,
                queue_freqs,
                queue_lengths,
                queue_levels,
                queue_index,
                queue_remaining,
                queue_phase,
                queue_elapsed,
                tone_peak,
            )
            return

        if len(freqs) == 0:
            outdata.fill(0.0)
            return

        self._process_chord_mode(outdata, sr, out_ch, freqs, phase_state, tone_peak)

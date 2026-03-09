import threading

import numpy as np


class PeakToneSonifier:
    """Sonifies detected peaks either as a chord or as differential layered cues."""

    AUDIBLE_MIN_FREQ = 220.0
    AUDIBLE_MAX_FREQ = 1760.0
    MAX_SUPPORTED_PEAKS = 16
    MAX_BELL_VOICES = 8
    DEFAULT_TONE_PEAK = 0.12
    MODE_CHORD = "chord"
    MODE_DIFF_LAYERS = "diff_layers"
    SPATIAL_DIFF_FLOOR_DB = 1.5
    BELL_DIFF_FLOOR_DB = 4.0
    CLICK_DIFF_FLOOR_DB = 2.5
    BELL_DURATION_SEC = 0.24
    CLICK_DURATION_SEC = 0.028

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

        self._spatial_freqs = np.zeros(0, dtype=np.float64)
        self._spatial_levels = np.zeros(0, dtype=np.float64)
        self._spatial_pans = np.zeros(0, dtype=np.float64)
        self._spatial_phases = np.zeros(self.MAX_SUPPORTED_PEAKS, dtype=np.float64)

        self._bell_freqs = np.zeros(self.MAX_BELL_VOICES, dtype=np.float64)
        self._bell_levels = np.zeros(self.MAX_BELL_VOICES, dtype=np.float64)
        self._bell_pans = np.zeros(self.MAX_BELL_VOICES, dtype=np.float64)
        self._bell_phases = np.zeros(self.MAX_BELL_VOICES, dtype=np.float64)
        self._bell_ages = np.zeros(self.MAX_BELL_VOICES, dtype=np.int64)

        self._click_remaining = 0
        self._click_phase = 0.0
        self._click_level = 0.0
        self._click_polarity = 1.0

        self._prev_freqs = np.zeros(0, dtype=np.float64)
        self._prev_mags = np.zeros(0, dtype=np.float64)
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
            self.max_peaks = max(1, min(self.MAX_SUPPORTED_PEAKS, int(peaks)))

    def set_mode(self, mode):
        mode = str(mode)
        if mode not in {self.MODE_CHORD, self.MODE_DIFF_LAYERS}:
            mode = self.MODE_CHORD

        with self.lock:
            if self.mode == mode:
                return
            self.mode = mode
            self._reset_state()

    def _reset_state(self):
        self._active_freqs = np.zeros(0, dtype=np.float64)
        self._phase_state.fill(0.0)
        self._spatial_freqs = np.zeros(0, dtype=np.float64)
        self._spatial_levels = np.zeros(0, dtype=np.float64)
        self._spatial_pans = np.zeros(0, dtype=np.float64)
        self._spatial_phases.fill(0.0)
        self._bell_freqs.fill(0.0)
        self._bell_levels.fill(0.0)
        self._bell_pans.fill(0.0)
        self._bell_phases.fill(0.0)
        self._bell_ages.fill(0)
        self._click_remaining = 0
        self._click_phase = 0.0
        self._click_level = 0.0
        self._prev_freqs = np.zeros(0, dtype=np.float64)
        self._prev_mags = np.zeros(0, dtype=np.float64)

    def _fold_to_audible_band(self, freq_hz):
        freq = float(max(1.0, freq_hz))
        while freq < self.AUDIBLE_MIN_FREQ:
            freq *= 2.0
        while freq > self.AUDIBLE_MAX_FREQ:
            freq *= 0.5
        return freq

    def update_spectrum(self, freqs_hz, mags_db, peak_freqs_hz):
        if not self.enabled:
            return

        freqs = np.asarray(freqs_hz, dtype=np.float64)
        mags = np.asarray(mags_db, dtype=np.float64)
        peaks = [float(freq) for freq in peak_freqs_hz[: self.MAX_SUPPORTED_PEAKS] if freq is not None]

        with self.lock:
            if self.mode == self.MODE_CHORD:
                self._update_chord_state(peaks)
                return

            self._update_diff_state(freqs, mags)

    def _update_chord_state(self, peak_freqs_hz):
        if peak_freqs_hz:
            cleaned_arr = np.asarray([self._fold_to_audible_band(freq) for freq in peak_freqs_hz], dtype=np.float64)
        else:
            cleaned_arr = np.zeros(0, dtype=np.float64)

        limit = min(self.max_peaks, len(cleaned_arr))
        new_freqs = cleaned_arr[:limit]
        self._active_freqs = new_freqs
        self._spatial_freqs = np.zeros(0, dtype=np.float64)
        self._spatial_levels = np.zeros(0, dtype=np.float64)
        self._spatial_pans = np.zeros(0, dtype=np.float64)
        self._bell_levels.fill(0.0)
        self._click_remaining = 0
        self._click_level = 0.0

    def _update_diff_state(self, freqs, mags):
        if len(freqs) == 0 or len(mags) == 0 or len(freqs) != len(mags):
            self._clear_diff_layers()
            self._prev_freqs = freqs.copy()
            self._prev_mags = mags.copy()
            return

        if len(self._prev_freqs) != len(freqs) or not np.allclose(self._prev_freqs, freqs, rtol=0.0, atol=1e-9):
            self._clear_diff_layers()
            self._prev_freqs = freqs.copy()
            self._prev_mags = mags.copy()
            return

        delta = mags - self._prev_mags
        abs_delta = np.abs(delta)
        pos_delta = np.clip(delta, 0.0, None)

        spatial_idx = self._select_diff_indices(abs_delta, self.SPATIAL_DIFF_FLOOR_DB)
        if spatial_idx:
            max_diff = max(self.SPATIAL_DIFF_FLOOR_DB, float(np.max(abs_delta[spatial_idx])))
            freq_span = max(1e-9, float(freqs[-1] - freqs[0]))
            self._spatial_freqs = np.asarray(
                [self._fold_to_audible_band(float(freqs[idx])) for idx in spatial_idx],
                dtype=np.float64,
            )
            self._spatial_levels = np.asarray(
                [min(1.0, max(0.08, float(abs_delta[idx]) / max_diff)) for idx in spatial_idx],
                dtype=np.float64,
            )
            self._spatial_pans = np.asarray(
                [((float(freqs[idx]) - float(freqs[0])) / freq_span) * 2.0 - 1.0 for idx in spatial_idx],
                dtype=np.float64,
            )
        else:
            self._spatial_freqs = np.zeros(0, dtype=np.float64)
            self._spatial_levels = np.zeros(0, dtype=np.float64)
            self._spatial_pans = np.zeros(0, dtype=np.float64)

        bell_idx = self._select_peak_bell_indices(freqs, mags, pos_delta)
        for idx in bell_idx:
            pan = 0.0
            if freqs[-1] > freqs[0]:
                pan = (((float(freqs[idx]) - float(freqs[0])) / float(freqs[-1] - freqs[0])) * 2.0) - 1.0
            level = min(1.0, max(0.2, float(pos_delta[idx]) / 12.0))
            self._trigger_bell(float(freqs[idx]), level, pan)

        click_metric = float(np.max(abs_delta)) if len(abs_delta) > 0 else 0.0
        if click_metric >= self.CLICK_DIFF_FLOOR_DB:
            self._trigger_click(click_metric)

        self._prev_freqs = freqs.copy()
        self._prev_mags = mags.copy()

    def _clear_diff_layers(self):
        self._spatial_freqs = np.zeros(0, dtype=np.float64)
        self._spatial_levels = np.zeros(0, dtype=np.float64)
        self._spatial_pans = np.zeros(0, dtype=np.float64)
        self._spatial_phases.fill(0.0)
        self._bell_levels.fill(0.0)
        self._bell_ages.fill(0)
        self._click_remaining = 0
        self._click_level = 0.0

    def _select_diff_indices(self, diff_db, floor_db):
        if len(diff_db) == 0:
            return []

        ranked = self._rank_local_maxima(diff_db)
        if not ranked:
            return []

        cutoff = max(float(floor_db), float(np.percentile(diff_db, 80)))
        selected = [idx for idx in ranked if float(diff_db[idx]) >= cutoff]
        if not selected and float(diff_db[ranked[0]]) >= floor_db:
            selected = [ranked[0]]

        return selected[: self.max_peaks]

    def _select_peak_bell_indices(self, freqs, mags, pos_delta):
        if len(freqs) == 0 or len(mags) == 0 or len(pos_delta) == 0:
            return []

        peak_candidates = []
        for idx in self._rank_local_maxima(mags):
            if float(pos_delta[idx]) >= self.BELL_DIFF_FLOOR_DB:
                peak_candidates.append(idx)

        if not peak_candidates:
            return []

        cutoff = max(self.BELL_DIFF_FLOOR_DB, float(np.percentile(pos_delta[peak_candidates], 70)))
        selected = [idx for idx in peak_candidates if float(pos_delta[idx]) >= cutoff]
        return selected[: min(self.max_peaks, self.MAX_BELL_VOICES)]

    def _rank_local_maxima(self, values):
        if len(values) == 0:
            return []
        if len(values) <= 2:
            return list(np.argsort(values)[::-1])

        maxima = []
        for idx in range(len(values)):
            left = values[idx - 1] if idx > 0 else -np.inf
            right = values[idx + 1] if idx < len(values) - 1 else -np.inf
            if values[idx] >= left and values[idx] >= right:
                maxima.append(idx)

        if not maxima:
            maxima = list(range(len(values)))
        return sorted(maxima, key=lambda idx: float(values[idx]), reverse=True)

    def _trigger_bell(self, freq_hz, level, pan):
        slot = int(np.argmin(self._bell_levels))
        self._bell_freqs[slot] = self._fold_to_audible_band(freq_hz * 2.0)
        self._bell_levels[slot] = float(level)
        self._bell_pans[slot] = float(np.clip(pan, -1.0, 1.0))
        self._bell_phases[slot] = 0.0
        self._bell_ages[slot] = 0

    def _trigger_click(self, metric):
        duration = max(8, int(round(self.CLICK_DURATION_SEC * self.sample_rate)))
        self._click_remaining = max(self._click_remaining, duration)
        self._click_level = max(self._click_level, min(1.0, max(0.2, (float(metric) - 2.0) / 10.0)))
        self._click_polarity *= -1.0

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
            for channel in range(channels):
                outdata[:, channel] = wave

    def _write_stereo_wave(self, outdata, out_ch, left, right):
        channels = outdata.shape[1]
        outdata.fill(0.0)
        if out_ch == 0:
            outdata[:, 0] = left + right
            return
        if out_ch == 1:
            if channels > 1:
                outdata[:, 1] = left + right
            else:
                outdata[:, 0] = left + right
            return

        if channels > 1:
            outdata[:, 0] = left
            outdata[:, 1] = right
        else:
            outdata[:, 0] = 0.5 * (left + right)

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

    def _process_diff_mode(
        self,
        outdata,
        sr,
        out_ch,
        spatial_freqs,
        spatial_levels,
        spatial_pans,
        spatial_phases,
        bell_freqs,
        bell_levels,
        bell_pans,
        bell_phases,
        bell_ages,
        click_remaining,
        click_phase,
        click_level,
        click_polarity,
        tone_peak,
    ):
        frames = len(outdata)
        frame_idx = np.arange(frames, dtype=np.float64)
        left = np.zeros(frames, dtype=np.float64)
        right = np.zeros(frames, dtype=np.float64)

        spatial_count = len(spatial_freqs)
        if spatial_count > 0:
            base_gain = tone_peak * 0.55 / max(1.0, np.sqrt(float(spatial_count)))
            for idx, freq in enumerate(spatial_freqs):
                phase = spatial_phases[idx] + frame_idx * ((2.0 * np.pi * freq) / sr)
                wave = np.sin(phase) * (base_gain * float(spatial_levels[idx]))
                pan = float(np.clip(spatial_pans[idx], -1.0, 1.0))
                left += wave * np.sqrt(0.5 * (1.0 - pan))
                right += wave * np.sqrt(0.5 * (1.0 + pan))
                spatial_phases[idx] = (phase[-1] + (2.0 * np.pi * freq / sr)) % (2.0 * np.pi)

        bell_duration = max(8, int(round(self.BELL_DURATION_SEC * sr)))
        for idx in range(len(bell_levels)):
            level = float(bell_levels[idx])
            if level <= 0.0:
                continue

            age0 = int(bell_ages[idx])
            remaining = bell_duration - age0
            if remaining <= 0:
                bell_levels[idx] = 0.0
                bell_ages[idx] = 0
                continue

            chunk = min(frames, remaining)
            sample_idx = np.arange(chunk, dtype=np.float64)
            age = age0 + sample_idx
            env = np.exp(-4.5 * (age / bell_duration)) * np.sin(np.pi * np.clip((age + 0.5) / bell_duration, 0.0, 1.0))
            phase = bell_phases[idx] + sample_idx * ((2.0 * np.pi * bell_freqs[idx]) / sr)
            bell = (np.sin(phase) + 0.35 * np.sin(2.4 * phase)) * env * tone_peak * 0.75 * level
            pan = float(np.clip(bell_pans[idx], -1.0, 1.0))
            left[:chunk] += bell * np.sqrt(0.5 * (1.0 - pan))
            right[:chunk] += bell * np.sqrt(0.5 * (1.0 + pan))
            bell_phases[idx] = (phase[-1] + (2.0 * np.pi * bell_freqs[idx] / sr)) % (2.0 * np.pi)
            bell_ages[idx] = age0 + chunk
            if bell_ages[idx] >= bell_duration:
                bell_levels[idx] = 0.0
                bell_ages[idx] = 0

        if click_remaining > 0 and click_level > 0.0:
            chunk = min(frames, click_remaining)
            sample_idx = np.arange(chunk, dtype=np.float64)
            total_click = max(1, int(round(self.CLICK_DURATION_SEC * sr)))
            pos = sample_idx / total_click
            env = np.exp(-9.0 * pos)
            phase = click_phase + sample_idx * ((2.0 * np.pi * 3200.0) / sr)
            click = (np.sin(phase) + 0.45 * np.sin(2.7 * phase)) * env * tone_peak * 0.9 * click_level * click_polarity
            left[:chunk] += click
            right[:chunk] += click
            click_phase = (phase[-1] + (2.0 * np.pi * 3200.0 / sr)) % (2.0 * np.pi)
            click_remaining -= chunk
            if click_remaining <= 0:
                click_remaining = 0
                click_level = 0.0
                click_phase = 0.0

        left = np.tanh(left)
        right = np.tanh(right)
        self._write_stereo_wave(outdata, out_ch, left, right)

        with self.lock:
            self._spatial_phases[: len(spatial_freqs)] = spatial_phases[: len(spatial_freqs)]
            self._bell_phases[:] = bell_phases
            self._bell_levels[:] = bell_levels
            self._bell_ages[:] = bell_ages
            self._click_remaining = click_remaining
            self._click_phase = click_phase
            self._click_level = click_level

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
            spatial_freqs = self._spatial_freqs.copy()
            spatial_levels = self._spatial_levels.copy()
            spatial_pans = self._spatial_pans.copy()
            spatial_phases = self._spatial_phases.copy()
            bell_freqs = self._bell_freqs.copy()
            bell_levels = self._bell_levels.copy()
            bell_pans = self._bell_pans.copy()
            bell_phases = self._bell_phases.copy()
            bell_ages = self._bell_ages.copy()
            click_remaining = self._click_remaining
            click_phase = self._click_phase
            click_level = self._click_level
            click_polarity = self._click_polarity
            tone_peak = self.tone_peak * self.master_volume

        if sr <= 0:
            outdata.fill(0.0)
            return

        if mode == self.MODE_DIFF_LAYERS:
            if len(spatial_freqs) == 0 and not np.any(bell_levels > 0.0) and click_remaining <= 0:
                outdata.fill(0.0)
                return
            self._process_diff_mode(
                outdata,
                sr,
                out_ch,
                spatial_freqs,
                spatial_levels,
                spatial_pans,
                spatial_phases,
                bell_freqs,
                bell_levels,
                bell_pans,
                bell_phases,
                bell_ages,
                click_remaining,
                click_phase,
                click_level,
                click_polarity,
                tone_peak,
            )
            return

        if len(freqs) == 0:
            outdata.fill(0.0)
            return

        self._process_chord_mode(outdata, sr, out_ch, freqs, phase_state, tone_peak)

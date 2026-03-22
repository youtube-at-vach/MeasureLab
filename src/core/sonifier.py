import numpy as np
import threading
import logging

logger = logging.getLogger(__name__)


class Sonifier:
    """
    Real-time sine wave synthesizer for power noise sonification.
    Implements parameter smoothing (linear interpolation for frequency and amplitude)
    to prevent audio pops and glitches.
    """

    MODE_LEVEL_MONITOR = "Level Monitor"
    MODE_FREQUENCY_MAPPING = "Frequency Mapping"
    MODE_MANUAL_TUNER = "Manual Tuner"

    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.enabled = False
        self.mode = self.MODE_LEVEL_MONITOR

        # Audio parameters
        self.master_volume_db = 0.0  # dB offset for sensitivity
        self.manual_freq = 1000.0  # Hz
        self.output_channel = 2  # 0: Left, 1: Right, 2: Both

        # Internal state for synthesis
        self.current_phase = 0.0
        self.current_freq = 800.0
        self.current_amp = 0.0

        # Target state set by the analyzer
        self.target_freq = 800.0
        self.target_amp = 0.0

        # We need a lock because update_parameters is called from the worker thread,
        # and process is called from the audio callback thread.
        self.lock = threading.Lock()

    def set_sample_rate(self, sr):
        with self.lock:
            self.sample_rate = sr

    def set_enabled(self, enabled):
        with self.lock:
            self.enabled = enabled
            if not enabled:
                self.target_amp = 0.0

    def set_mode(self, mode):
        with self.lock:
            self.mode = mode

    def set_volume(self, volume_db):
        with self.lock:
            self.master_volume_db = max(-120.0, min(80.0, volume_db))

    def set_manual_freq(self, freq):
        with self.lock:
            self.manual_freq = max(1.0, freq)

    def set_output_channel(self, channel):
        with self.lock:
            self.output_channel = channel

    def update_parameters(self, scan_freq, mag_db):
        """
        Called by the analyzer to update the sonification targets.
        mag_db is expected to be typical FFT magnitudes (e.g. -120 to 0).
        """
        if not self.enabled:
            return

        with self.lock:
            # Shift magnitude by master volume dB to allow "hearing" small signals
            effective_mag = mag_db + self.master_volume_db

            # Base it on a typical noise floor, e.g., -100 dBFS -> 0 amplitude
            # -20 dBFS -> max amplitude
            noise_floor_db = -100.0
            max_level_db = -20.0

            clamped_db = max(noise_floor_db, min(max_level_db, effective_mag))

            # Map dB to linear scale for sonification volume (0.0 to 1.0)
            normalized_amp = (clamped_db - noise_floor_db) / (max_level_db - noise_floor_db)

            # Apply non-linear curve for more natural volume perception (e.g., cubic)
            target_linear_amp = normalized_amp**3

            self.target_amp = target_linear_amp

            if self.mode == self.MODE_LEVEL_MONITOR:
                self.target_freq = 800.0
            elif self.mode == self.MODE_FREQUENCY_MAPPING:
                # Limit freq to prevent aliasing/annoying high pitches
                self.target_freq = max(20.0, min(15000.0, scan_freq))
            elif self.mode == self.MODE_MANUAL_TUNER:
                self.target_freq = self.manual_freq
                # If we are in manual tuner mode and the scan frequency is far from the
                # manual frequency, we should probably ignore the magnitude update.
                # However, this method is called per chunk. The caller should pass the mag
                # for the specific frequency we care about.
                # For simplicity, we just take whatever is given if it's close.
                pass

    def update_manual_tuner_mag(self, mag_db):
        """
        Specific update for manual tuner when we extract magnitude at exactly the manual freq.
        """
        if not self.enabled or self.mode != self.MODE_MANUAL_TUNER:
            return

        with self.lock:
            effective_mag = mag_db + self.master_volume_db
            noise_floor_db = -100.0
            max_level_db = -20.0
            clamped_db = max(noise_floor_db, min(max_level_db, effective_mag))
            normalized_amp = (clamped_db - noise_floor_db) / (max_level_db - noise_floor_db)
            target_linear_amp = normalized_amp**3
            self.target_amp = target_linear_amp
            self.target_freq = self.manual_freq

    def process(self, outdata):
        """
        Fills the given audio buffer `outdata` with the synthesized sine wave.
        outdata shape: (frames, channels)
        """
        frames = len(outdata)
        channels = outdata.shape[1]

        with self.lock:
            if not self.enabled and self.current_amp < 1e-5:
                # Ensure outdata is zeroed
                outdata.fill(0.0)
                return

            # Capture parameters to avoid holding lock during computation
            target_f = self.target_freq
            target_a = self.target_amp if self.enabled else 0.0
            start_f = self.current_freq
            start_a = self.current_amp
            start_phase = self.current_phase
            sr = self.sample_rate
            out_ch = self.output_channel

        if sr <= 0:
            outdata.fill(0.0)
            return

        # Generate ramps for frequency and amplitude to prevent clicks
        freq_ramp = np.linspace(start_f, target_f, frames, endpoint=False)
        amp_ramp = np.linspace(start_a, target_a, frames, endpoint=False)

        # Compute instantaneous phase
        # phase_inc = 2 * pi * f / sr
        phase_inc = 2.0 * np.pi * freq_ramp / sr

        # Cumulative sum of phase increments
        phase = start_phase + np.cumsum(phase_inc)

        # Generate sine wave
        wave = np.sin(phase) * amp_ramp

        # Fill output buffer
        outdata.fill(0.0)

        if out_ch == 0:  # Left
            outdata[:, 0] = wave
        elif out_ch == 1:  # Right
            if channels > 1:
                outdata[:, 1] = wave
            else:
                outdata[:, 0] = wave
        else:  # Both
            for c in range(channels):
                outdata[:, c] = wave

        # Update state for next block
        with self.lock:
            # Modulo phase to keep it small
            self.current_phase = phase[-1] % (2.0 * np.pi)
            self.current_freq = target_f
            self.current_amp = target_a

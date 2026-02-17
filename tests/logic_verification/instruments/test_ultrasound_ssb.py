import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import unittest
import numpy as np
from src.gui.widgets.ultrasound_modulator import UltrasoundModulator

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000

    def register_callback(self, cb):
        # We will capture this in the test
        return 0

    def unregister_callback(self, id):
        pass

class TestUltrasoundSSB(unittest.TestCase):
    def setUp(self):
        self.engine = MockAudioEngine()
        self.mod = UltrasoundModulator(self.engine)

    def test_ssb_suppression(self):
        # Configure for SSB USB
        self.mod.carrier_freq = 10000.0
        self.mod.modulation_mode = "USB"
        self.mod.input_mode = "L"
        self.mod.output_mode = "L"
        self.mod.input_gain = 1.0
        self.mod.output_gain = 1.0
        self.mod.bypass = False

        # Capture the callback
        callback_fn = None
        def register(cb):
            nonlocal callback_fn
            callback_fn = cb
            return 123

        self.engine.register_callback = register
        self.mod.start()

        self.assertIsNotNone(callback_fn)

        fs = 48000
        duration = 0.5 # seconds
        frames = int(fs * duration)

        # Input signal: 1kHz sine wave
        t = np.arange(frames) / fs
        input_sig = np.cos(2 * np.pi * 1000 * t)

        # Process in chunks
        chunk_size = 1024
        output_sig = []

        cursor = 0
        while cursor < frames:
            n = min(chunk_size, frames - cursor)
            indata = np.zeros((n, 2), dtype=np.float32)
            indata[:, 0] = input_sig[cursor:cursor+n]

            outdata = np.zeros((n, 2), dtype=np.float32)

            callback_fn(indata, outdata, n, None, None)

            output_sig.append(outdata[:, 0].copy())
            cursor += n

        output_sig = np.concatenate(output_sig)

        # Analyze Spectrum
        # Skip beginning to avoid filter transient
        skip = fs//4
        stable_output = output_sig[skip:]

        # FFT
        fft_out = np.abs(np.fft.rfft(stable_output))
        freqs = np.fft.rfftfreq(len(stable_output), d=1/fs)

        # Expected: Peak at Carrier + Signal = 10k + 1k = 11kHz.
        # Suppressed: Carrier - Signal = 9kHz.
        # Also Carrier might be present if we added it.

        target_idx = np.argmin(np.abs(freqs - 11000))
        image_idx = np.argmin(np.abs(freqs - 9000))
        carrier_idx = np.argmin(np.abs(freqs - 10000))

        target_amp = fft_out[target_idx]
        image_amp = fft_out[image_idx]
        carrier_amp = fft_out[carrier_idx]

        print(f"Target (11k): {target_amp}")
        print(f"Image (9k): {image_amp}")
        print(f"Carrier (10k): {carrier_amp}")

        # Check suppression
        # We expect Target >> Image
        # If image_amp is very small, ratio is huge.
        suppression_ratio = target_amp / (image_amp + 1e-9)
        print(f"Suppression Ratio: {suppression_ratio}")

        # Note: 65 taps might not give huge suppression, but should be significant.
        # 20dB = ratio 10.
        self.assertGreater(suppression_ratio, 5.0, "Sideband should be suppressed")

if __name__ == '__main__':
    unittest.main()

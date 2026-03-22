import unittest
from unittest.mock import MagicMock, patch
import sys
import numpy as np
import importlib


class TestAudioEngineDithering(unittest.TestCase):
    def setUp(self):
        # Patch sys.modules to mock sounddevice
        self.patcher = patch.dict(sys.modules, {"sounddevice": MagicMock()})
        self.patcher.start()

        # Import and reload AudioEngine to use the mock
        import src.core.audio_engine

        importlib.reload(src.core.audio_engine)
        self.AudioEngineClass = src.core.audio_engine.AudioEngine

        self.engine = self.AudioEngineClass()
        # Mock stream so register_callback doesn't try to start it
        self.engine.stream = MagicMock()
        self.engine.logger = MagicMock()

        # Prepare dummy callback for tests
        self.frames = 1024
        self.indata = np.zeros((self.frames, 2), dtype="float32")
        self.outdata = np.zeros((self.frames, 2), dtype="float32")

        # Register a callback that outputs silence (zeros)
        # This ensures that any output is purely from the dithering process
        def silence_cb(indata, outdata, frames, time, status):
            outdata.fill(0)

        self.engine.register_callback(silence_cb)

    def tearDown(self):
        self.patcher.stop()

    def test_dithering_16bit(self):
        """Verify that 16-bit TPDF dither is applied correctly."""
        self.engine.dithering_enabled = True
        self.engine.dithering_bit_depth = "16"

        # Invoke callback
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)

        # Verify output is not zero
        max_val = np.max(np.abs(self.outdata))
        self.assertGreater(max_val, 0, "Dither output should not be zero")

        # 16-bit LSB = 1 / 2^15
        lsb_16 = 1.0 / (2**15)

        # TPDF dither is sum of two uniform distributions (-LSB/2 to LSB/2), or rather:
        # Code: (rand1 - rand2) * lsb
        # rand1 is [0, 1), rand2 is [0, 1). diff is (-1, 1).
        # So range is strictly (-LSB, LSB).
        # We allow a tiny epsilon for float precision
        self.assertLess(max_val, lsb_16 * 1.01, f"Dither should be within approx 1 LSB ({lsb_16}), got {max_val}")

        # Also check it's reasonably large (not just 1e-20)
        # Random noise should cover a good portion of the range over 1024 samples
        self.assertGreater(max_val, lsb_16 * 0.1, "Dither noise seems too small for 16-bit")

    def test_dithering_24bit(self):
        """Verify that 24-bit TPDF dither is applied correctly."""
        self.engine.dithering_enabled = True
        self.engine.dithering_bit_depth = "24"

        # Invoke callback
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)

        # Verify output is not zero
        max_val = np.max(np.abs(self.outdata))
        self.assertGreater(max_val, 0, "Dither output should not be zero")

        # 24-bit LSB = 1 / 2^23
        lsb_24 = 1.0 / (2**23)

        self.assertLess(max_val, lsb_24 * 1.01, f"Dither should be within approx 1 LSB ({lsb_24}), got {max_val}")
        self.assertGreater(max_val, lsb_24 * 0.1, "Dither noise seems too small for 24-bit")

    def test_dithering_disabled(self):
        """Verify that output is zero when dithering is disabled."""
        self.engine.dithering_enabled = False

        # Invoke callback
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)

        # Verify output is exactly zero
        max_val = np.max(np.abs(self.outdata))
        self.assertEqual(max_val, 0.0, "Output should be zero when dithering is disabled")

    def test_dithering_logic_parsing(self):
        """Verify string parsing for bit depth selection."""
        self.engine.dithering_enabled = True

        # Test "16-bit" string
        self.engine.dithering_bit_depth = "16-bit"
        self.outdata.fill(0)  # Reset buffer
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)
        max_val_16 = np.max(np.abs(self.outdata))

        lsb_16 = 1.0 / (2**15)
        # Should be roughly 16-bit level
        self.assertGreater(max_val_16, lsb_16 * 0.1, "Should detect 16-bit mode")

        # Test "32-bit float" (should fallback to 24-bit logic as per code)
        self.engine.dithering_bit_depth = "32-bit float"
        self.outdata.fill(0)  # Reset buffer
        self.engine._master_callback(self.indata, self.outdata, self.frames, None, 0)
        max_val_32 = np.max(np.abs(self.outdata))

        lsb_24 = 1.0 / (2**23)
        # Should be roughly 24-bit level (much smaller than 16-bit)
        self.assertLess(max_val_32, lsb_24 * 1.01, "Should default to 24-bit mode for non-16 strings")

        # Compare magnitudes to be sure
        self.assertGreater(max_val_16, max_val_32 * 100, "16-bit dither should be much larger than 24-bit dither")


if __name__ == "__main__":
    unittest.main()

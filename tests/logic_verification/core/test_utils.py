import unittest
import sys
import os

# Ensure src can be imported
sys.path.append(os.getcwd())

from src.core.utils import format_si


class TestUtils(unittest.TestCase):
    def test_format_si_basic(self):
        """Test basic SI formatting functionality."""
        # Simple cases
        self.assertEqual(format_si(1000, "Hz"), "1 kHz")
        self.assertEqual(format_si(0.001, "s"), "1 ms")
        self.assertEqual(format_si(1, "V"), "1 V")

        # Micro
        # Note: format_si uses 'µ' (U+00B5) or similar. Let's check implementation behavior.
        # implementation uses _SI_PREFIXES = { ..., -6: "µ", ... }
        self.assertEqual(format_si(1e-6, "s"), "1 µs")

    def test_format_si_precision(self):
        """Test sig_figs parameter."""
        val = 1234.5678
        # Default sig_figs=4
        self.assertEqual(format_si(val, "Hz"), "1.235 kHz")
        # sig_figs=5
        self.assertEqual(format_si(val, "Hz", sig_figs=5), "1.2346 kHz")
        # sig_figs=3
        self.assertEqual(format_si(val, "Hz", sig_figs=3), "1.23 kHz")

        val_small = 0.0012345678
        self.assertEqual(format_si(val_small, "s", sig_figs=4), "1.235 ms")

    def test_format_si_edge_cases(self):
        """Test edge cases: 0, None, Inf, NaN."""
        # Zero
        self.assertEqual(format_si(0, "Hz"), "0 Hz")
        self.assertEqual(format_si(0.0, "s"), "0 s")

        # Negative
        self.assertEqual(format_si(-1000, "Hz"), "-1 kHz")

        # None
        self.assertEqual(format_si(None, "Hz"), "-")

        # Inf
        self.assertEqual(format_si(float("inf"), "Hz"), "-")
        self.assertEqual(format_si(float("-inf"), "Hz"), "-")

        # NaN
        self.assertEqual(format_si(float("nan"), "Hz"), "-")

    def test_format_si_rounding_up(self):
        """Test rounding that bumps the prefix (e.g. 999.9 m -> 1.0 k)."""
        # 999.95 m -> 1.000 s if sig_figs=4
        val = 999.95e-3
        # 0.99995 s.
        # exp3 = -3 (m). scaled = 999.95.
        # with sig_figs=4 -> 999.95 rounds to 1000.
        # So format_si logic sees 1000 >= 1000. Bumps prefix to 0 (base).
        # New scaled: 0.99995.
        # Formats to "1".
        self.assertEqual(format_si(val, "s", sig_figs=4), "1 s")

        # Another case: 999.96 Hz
        # sig_figs=4 -> 1000.
        val = 999.96
        self.assertEqual(format_si(val, "Hz", sig_figs=4), "1 kHz")

    def test_format_si_large_numbers(self):
        """Test very large numbers."""
        self.assertEqual(format_si(1e6, "Hz"), "1 MHz")
        self.assertEqual(format_si(1e9, "Hz"), "1 GHz")
        self.assertEqual(format_si(2.5e6, "Hz"), "2.5 MHz")

    def test_format_si_small_numbers(self):
        """Test very small numbers."""
        self.assertEqual(format_si(1e-9, "s"), "1 ns")
        self.assertEqual(format_si(1e-12, "s"), "1 ps")

        # Test values relevant to Oscilloscope
        # 123.456 ns -> 1.235e-7 s
        val = 1.23456e-7
        self.assertEqual(format_si(val, "s", sig_figs=4), "123.5 ns")
        self.assertEqual(format_si(val, "s", sig_figs=5), "123.46 ns")

    def test_amplitude_to_linear(self):
        # Linear (0-1) / Amplitude
        import numpy as np
        from src.core import utils

        self.assertTrue(np.isclose(utils.amplitude_to_linear(0.5, "Linear (0-1)"), 0.5))
        self.assertTrue(np.isclose(utils.amplitude_to_linear(0.5, "Amplitude"), 0.5))

        # dBFS
        self.assertTrue(np.isclose(utils.amplitude_to_linear(0, "dBFS"), 1.0))
        self.assertTrue(np.isclose(utils.amplitude_to_linear(-20, "dBFS"), 0.1))

        # dBV
        self.assertTrue(
            np.isclose(utils.amplitude_to_linear(0, "dBV", gain=np.sqrt(2)), 1.0)
        )  # 1 Vrms -> sqrt(2) Vpeak -> 1.0 Linear

        # dBu
        self.assertTrue(np.isclose(utils.amplitude_to_linear(0, "dBu", gain=0.7746 * np.sqrt(2)), 1.0))

        # Vrms
        self.assertTrue(np.isclose(utils.amplitude_to_linear(1.0, "Vrms", gain=np.sqrt(2)), 1.0))

        # Vpeak
        self.assertTrue(np.isclose(utils.amplitude_to_linear(1.0, "Vpeak", gain=1.0), 1.0))

        # Clamping
        self.assertTrue(np.isclose(utils.amplitude_to_linear(2.0, "Linear (0-1)"), 1.0))
        self.assertTrue(np.isclose(utils.amplitude_to_linear(-0.5, "Linear (0-1)"), 0.0))

    def test_linear_to_amplitude(self):
        import numpy as np
        from src.core import utils

        # Linear (0-1) / Amplitude
        self.assertTrue(np.isclose(utils.linear_to_amplitude(0.5, "Linear (0-1)"), 0.5))
        self.assertTrue(np.isclose(utils.linear_to_amplitude(0.5, "Amplitude"), 0.5))

        # dBFS
        self.assertTrue(np.isclose(utils.linear_to_amplitude(1.0, "dBFS"), 0.0))
        self.assertTrue(np.isclose(utils.linear_to_amplitude(0.1, "dBFS"), -20.0, atol=1e-5))

        # dBV
        self.assertTrue(np.isclose(utils.linear_to_amplitude(1.0, "dBV", gain=np.sqrt(2)), 0.0, atol=1e-5))

        # dBu
        self.assertTrue(np.isclose(utils.linear_to_amplitude(1.0, "dBu", gain=0.7746 * np.sqrt(2)), 0.0, atol=1e-5))

        # Vrms
        self.assertTrue(np.isclose(utils.linear_to_amplitude(1.0, "Vrms", gain=np.sqrt(2)), 1.0))

        # Vpeak
        self.assertTrue(np.isclose(utils.linear_to_amplitude(1.0, "Vpeak", gain=1.0), 1.0))

    def test_resource_path_meipass(self):
        from unittest.mock import patch
        from src.core.utils import resource_path

        with patch("sys._MEIPASS", "/tmp/_MEI123456", create=True):
            self.assertEqual(resource_path("test.png"), os.path.join("/tmp/_MEI123456", "test.png"))

    def test_resource_path_exception_fallback_root(self):
        from unittest.mock import patch
        from src.core.utils import resource_path

        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS

        with patch("os.path.abspath", return_value="/fake/root"):
            with patch("os.path.exists", side_effect=lambda p: p == os.path.join("/fake/root", "test.png")):
                self.assertEqual(resource_path("test.png"), os.path.join("/fake/root", "test.png"))

    def test_resource_path_exception_fallback_src(self):
        from unittest.mock import patch
        from src.core.utils import resource_path

        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS

        with patch("os.path.abspath", return_value="/fake/root"):

            def mock_exists(p):
                if p == os.path.join("/fake/root", "test.png"):
                    return False
                if p == os.path.join("/fake/root", "src", "test.png"):
                    return True
                return False

            with patch("os.path.exists", side_effect=mock_exists):
                self.assertEqual(resource_path("test.png"), os.path.join("/fake/root", "src", "test.png"))

    def test_resource_path_exception_fallback_not_found(self):
        from unittest.mock import patch
        from src.core.utils import resource_path

        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS

        with patch("os.path.abspath", return_value="/fake/root"):
            with patch("os.path.exists", return_value=False):
                self.assertEqual(resource_path("test.png"), os.path.join("/fake/root", "test.png"))


if __name__ == "__main__":
    unittest.main()

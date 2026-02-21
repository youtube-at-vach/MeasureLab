import unittest
import numpy as np
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from src.core.analysis import _get_time_array, _get_reference_signals

class TestTimeArray(unittest.TestCase):
    def test_get_time_array_basic(self):
        """Test basic functionality of _get_time_array."""
        N = 100
        sr = 1000.0
        t = _get_time_array(N, sr)

        # Check type
        self.assertIsInstance(t, np.ndarray)
        self.assertEqual(t.dtype, np.float64)

        # Check shape
        self.assertEqual(t.shape, (N,))

        # Check values
        expected = np.arange(N) / sr
        np.testing.assert_array_equal(t, expected)

        # Check read-only
        self.assertFalse(t.flags.writeable)
        with self.assertRaises(ValueError):
            t[0] = 10.0

    def test_get_time_array_caching(self):
        """Test that _get_time_array is cached."""
        N = 100
        sr = 1000.0
        t1 = _get_time_array(N, sr)
        t2 = _get_time_array(N, sr)

        self.assertIs(t1, t2)

        t3 = _get_time_array(N, 2000.0)
        self.assertIsNot(t1, t3)

    def test_get_reference_signals_usage(self):
        """Test _get_reference_signals uses _get_time_array and returns correct values."""
        N = 100
        sr = 1000.0
        freq = 10.0

        sin_ref, cos_ref = _get_reference_signals(N, sr, freq)

        # Check read-only
        self.assertFalse(sin_ref.flags.writeable)
        self.assertFalse(cos_ref.flags.writeable)

        # Manual calculation
        t = _get_time_array(N, sr)
        theta = 2 * np.pi * freq * t
        expected_sin = np.sin(theta)
        expected_cos = np.cos(theta)

        np.testing.assert_array_equal(sin_ref, expected_sin)
        np.testing.assert_array_equal(cos_ref, expected_cos)

    def test_get_reference_signals_caching(self):
        """Test caching of reference signals."""
        N = 100
        sr = 1000.0
        freq = 10.0

        s1, c1 = _get_reference_signals(N, sr, freq)
        s2, c2 = _get_reference_signals(N, sr, freq)

        self.assertIs(s1, s2)
        self.assertIs(c1, c2)

if __name__ == '__main__':
    unittest.main()

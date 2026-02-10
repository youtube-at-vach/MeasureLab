import numpy as np
import pytest
from src.gui.widgets.bnim_meter import BNIMMeter

class TestBNIMFractionalDelay:
    """Tests for BNIMMeter._fractional_delay_zero_padded static method."""

    def test_zero_delay(self):
        """Test that delay_samples=0 returns the original array (copy behavior check)."""
        # Case 1: float32 input - should return same object due to copy=False
        x = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.0)
        np.testing.assert_array_equal(y, x)
        assert y is x

        # Case 2: float64 input - should return new float32 array
        x64 = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
        y64 = BNIMMeter._fractional_delay_zero_padded(x64, 0.0)
        np.testing.assert_array_equal(y64, x64.astype(np.float32))
        assert y64.dtype == np.float32
        assert y64 is not x64

    def test_integer_delay(self):
        """Test integer delay shifts the signal correctly."""
        x = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)

        # Delay by 1 sample
        y = BNIMMeter._fractional_delay_zero_padded(x, 1.0)
        expected = np.array([0.0, 10.0, 20.0, 30.0], dtype=np.float32)
        np.testing.assert_array_equal(y, expected)

        # Delay by 2 samples
        y2 = BNIMMeter._fractional_delay_zero_padded(x, 2.0)
        expected2 = np.array([0.0, 0.0, 10.0, 20.0], dtype=np.float32)
        np.testing.assert_array_equal(y2, expected2)

    def test_fractional_delay(self):
        """Test fractional delay (0.5) performs linear interpolation."""
        x = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float32)
        # Delay by 0.5 samples
        # y[1] corresponds to x at index 0.5 -> avg(x[0], x[1]) = 15
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.5)
        expected = np.array([0.0, 15.0, 25.0, 35.0], dtype=np.float32)
        np.testing.assert_array_almost_equal(y, expected, decimal=5)

    def test_fractional_delay_quarter(self):
        """Test fractional delay (0.25)."""
        x = np.array([0.0, 10.0, 20.0], dtype=np.float32)
        # Delay 0.25
        # y[1]: index 0.75 -> (1-0.75)*x[0] + 0.75*x[1] = 0.25*0 + 0.75*10 = 7.5
        # y[2]: index 1.75 -> (1-0.75)*x[1] + 0.75*x[2] = 0.25*10 + 0.75*20 = 2.5 + 15 = 17.5
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.25)
        expected = np.array([0.0, 7.5, 17.5], dtype=np.float32)
        np.testing.assert_array_almost_equal(y, expected, decimal=5)

    def test_large_delay(self):
        """Test delay >= length returns zeros."""
        x = np.array([1.0, 2.0, 3.0], dtype=np.float32)

        # Exactly length
        y = BNIMMeter._fractional_delay_zero_padded(x, 3.0)
        expected = np.zeros_like(x)
        np.testing.assert_array_equal(y, expected)

        # Much larger
        y2 = BNIMMeter._fractional_delay_zero_padded(x, 10.0)
        np.testing.assert_array_equal(y2, expected)

    def test_negative_delay(self):
        """Test negative delay returns original signal (as implemented)."""
        x = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        y = BNIMMeter._fractional_delay_zero_padded(x, -1.0)
        np.testing.assert_array_equal(y, x)
        assert y is x  # float32 optimization check

    def test_empty_input(self):
        """Test empty input returns empty array."""
        x = np.array([], dtype=np.float32)
        y = BNIMMeter._fractional_delay_zero_padded(x, 1.5)
        assert len(y) == 0
        assert y.dtype == np.float32

    def test_dtype_conversion(self):
        """Test that input is converted to float32."""
        x = np.array([1, 2, 3], dtype=np.int32)
        y = BNIMMeter._fractional_delay_zero_padded(x, 0.5)
        assert y.dtype == np.float32

        # x[0]=1, x[1]=2. interp at 0.5 -> 1.5
        # y[0]=0 (padding), y[1]=1.5, y[2]=2.5
        expected = np.array([0.0, 1.5, 2.5], dtype=np.float32)
        np.testing.assert_array_almost_equal(y, expected)

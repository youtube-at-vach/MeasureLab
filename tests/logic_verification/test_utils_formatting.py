import pytest
from src.core.utils import format_si

class TestFormatSI:
    """Tests for the format_si utility function."""

    def test_basic_scaling(self):
        """Test basic scaling with various powers of 10."""
        assert format_si(1e-9) == "1 n"
        assert format_si(1e-6) == "1 µ"
        assert format_si(1e-3) == "1 m"
        assert format_si(1) == "1"
        assert format_si(1e3) == "1 k"
        assert format_si(1e6) == "1 M"
        assert format_si(1e9) == "1 G"
        assert format_si(1e12) == "1 T"
        assert format_si(1e15) == "1 P"
        assert format_si(1e18) == "1 E"
        assert format_si(1e21) == "1 Z"
        assert format_si(1e24) == "1 Y"

    def test_zero(self):
        """Test formatting of zero."""
        assert format_si(0) == "0"
        assert format_si(0.0) == "0"
        assert format_si(0, unit="Hz") == "0 Hz"
        assert format_si(0.0, unit="V") == "0 V"
        # From test_utils_si.py
        assert format_si(0.0, "S") == "0 S"

    def test_negative_values(self):
        """Test formatting of negative values."""
        assert format_si(-1) == "-1"
        assert format_si(-1e3) == "-1 k"
        assert format_si(-500e-3) == "-500 m"

    def test_rounding_spillover(self):
        """Test rounding spillover (e.g., 999.95 -> 1.000 k)."""
        # 999.95 with 4 sig figs rounds to 1000, so it should bump to next prefix
        assert format_si(999.95, sig_figs=4) == "1 k"
        # 999.9 with 4 sig figs is just 999.9
        assert format_si(999.9, sig_figs=4) == "999.9"
        # 999.99 with 5 sig figs is 999.99
        assert format_si(999.99, sig_figs=5) == "999.99"

        # Edge case: Floating point precision issue (e.g., 0.99995 with 4 sig figs)
        # 0.99995 -> rounds to 1.000 (1000 m or 1)
        # Previous logic might return "999.9 m" due to precision loss in division by 0.001
        assert format_si(0.99995) == "1"

        # From test_utils_si.py
        # 0.9996 S is 999.6 mS; with 3 sig figs it should display as 1 S (spillover fix).
        assert format_si(0.9996, "S", sig_figs=3) == "1 S"

    def test_sig_figs(self):
        """Test significant figures formatting."""
        val = 12345.6789
        # 12.3456789 k -> 12.3 k (3 sig figs)
        assert format_si(val, sig_figs=3) == "12.3 k"
        # 12.3456789 k -> 12.35 k (4 sig figs)
        assert format_si(val, sig_figs=4) == "12.35 k"

    def test_small_numbers(self):
        """Test very small numbers."""
        assert format_si(1e-24) == "1 y"
        # Check below yotta (should clamp to y)
        assert format_si(1e-27) == "0.001 y"

    def test_large_numbers(self):
        """Test very large numbers."""
        assert format_si(1e24) == "1 Y"
        # Check above Yotta (should clamp to Y)
        assert format_si(1e27) == "1000 Y"

    def test_nan_inf(self):
        """Test NaN and Infinity handling."""
        assert format_si(float("nan")) == "-"
        assert format_si(float("inf")) == "-"
        assert format_si(float("-inf")) == "-"
        # From test_utils_si.py
        assert format_si(float("nan"), "S") == "-"
        assert format_si(float("inf"), "S") == "-"

    def test_invalid_input(self):
        """Test invalid input handling."""
        assert format_si("invalid") == "-"
        assert format_si(None) == "-"

    def test_custom_unit(self):
        """Test custom unit string."""
        assert format_si(1000, unit="Hz") == "1 kHz"
        assert format_si(0.001, unit="V") == "1 mV"
        assert format_si(100, unit="A") == "100 A"

    def test_admittance_prefixes(self):
        """Test admittance prefixes from test_utils_si.py."""
        assert format_si(0.00123, "S", sig_figs=4) == "1.23 mS"
        assert format_si(1.234e-6, "S", sig_figs=4) == "1.234 µS"
        assert format_si(-2.5e-9, "S", sig_figs=3) == "-2.5 nS"

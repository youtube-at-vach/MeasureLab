import os
import sys
from unittest.mock import patch

from src.core.utils import format_si, resource_path


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

    def test_invalid_input(self):
        """Test invalid input handling."""
        assert format_si("invalid") == "-"
        assert format_si(None) == "-"

    def test_custom_unit(self):
        """Test custom unit string."""
        assert format_si(1000, unit="Hz") == "1 kHz"
        assert format_si(0.001, unit="V") == "1 mV"
        assert format_si(100, unit="A") == "100 A"


class TestResourcePath:
    """Tests for the resource_path utility function."""

    def setup_method(self):
        """Ensure clean state for sys._MEIPASS before each test."""
        # Clean up _MEIPASS if it somehow exists (e.g. from a failed test)
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS

    def teardown_method(self):
        """Ensure clean state for sys._MEIPASS after each test."""
        if hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS

    def test_frozen_app(self):
        """Test resource_path when running as a frozen app (PyInstaller)."""
        mock_meipass = "/tmp/MEIPASS"
        # Use patch to set sys._MEIPASS temporarily
        with patch.object(sys, "_MEIPASS", mock_meipass, create=True):
            result = resource_path("test.png")
            assert result == os.path.join(mock_meipass, "test.png")

    def test_dev_env_in_root(self):
        """Test resource_path when running from source (dev environment)."""
        # Ensure _MEIPASS is definitely not present (setup/teardown handles this)
        assert not hasattr(sys, "_MEIPASS")

        base_path = "/app"
        with patch("os.path.abspath", return_value=base_path):
            # Scenario 1: File exists in base_path
            with patch("os.path.exists") as mock_exists:
                mock_exists.side_effect = lambda p: p == os.path.join(base_path, "test.png")

                result = resource_path("test.png")
                assert result == os.path.join(base_path, "test.png")

    def test_dev_env_in_src(self):
        """Test resource_path when file is in src/ subdirectory."""
        assert not hasattr(sys, "_MEIPASS")

        base_path = "/app"
        with patch("os.path.abspath", return_value=base_path):
            # Scenario 2: File does NOT exist in base_path, but exists in src/
            with patch("os.path.exists") as mock_exists:
                def side_effect(p):
                    if p == os.path.join(base_path, "test.png"):
                        return False
                    if p == os.path.join(base_path, "src", "test.png"):
                        return True
                    return False
                mock_exists.side_effect = side_effect

                result = resource_path("test.png")
                assert result == os.path.join(base_path, "src", "test.png")

    def test_dev_env_not_found(self):
        """Test resource_path when file is nowhere to be found."""
        assert not hasattr(sys, "_MEIPASS")

        base_path = "/app"
        with patch("os.path.abspath", return_value=base_path):
            with patch("os.path.exists", return_value=False):
                # Should fallback to base_path joined with relative path
                result = resource_path("missing.png")
                assert result == os.path.join(base_path, "missing.png")

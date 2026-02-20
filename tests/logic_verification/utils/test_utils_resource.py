import os
import sys
from unittest.mock import patch
from src.core.utils import resource_path

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

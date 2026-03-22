import unittest
from unittest.mock import MagicMock
import sys
import os
import shutil
import tempfile
import json


class TestImpedanceAnalyzerSecurity(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.test_dir, "test_cal_secure.json")

        # Setup mocks
        self.mock_pyqt = MagicMock()
        self.mock_sd = MagicMock()
        self.mock_pg = MagicMock()
        self.mock_loc = MagicMock()
        self.mock_loc.tr = lambda x, default=None: x

        # Mock numpy
        self.mock_numpy = MagicMock()
        self.mock_numpy.zeros.return_value = MagicMock()
        self.mock_numpy.isfinite.return_value = True
        self.mock_numpy.pi = 3.14159
        self.mock_numpy.array.return_value = MagicMock()

        # Mock scipy
        self.mock_scipy = MagicMock()
        self.mock_scipy.signal = MagicMock()
        self.mock_scipy.optimize = MagicMock()

        # Mock soundfile
        self.mock_sf = MagicMock()

        # Mock fft_manager
        self.mock_fft_manager = MagicMock()

        # Modules to patch in sys.modules
        self.modules_to_patch = {
            "PyQt6": self.mock_pyqt,
            "PyQt6.QtCore": self.mock_pyqt,
            "PyQt6.QtGui": self.mock_pyqt,
            "PyQt6.QtWidgets": self.mock_pyqt,
            "pyqtgraph": self.mock_pg,
            "sounddevice": self.mock_sd,
            "src.core.localization": self.mock_loc,
            "numpy": self.mock_numpy,
            "scipy": self.mock_scipy,
            "scipy.signal": self.mock_scipy.signal,
            "scipy.optimize": self.mock_scipy.optimize,
            "soundfile": self.mock_sf,
            "src.core.fft_manager": self.mock_fft_manager,
        }

        # Manual patching of sys.modules
        self.original_modules = {}
        for name, mock_obj in self.modules_to_patch.items():
            if name in sys.modules:
                self.original_modules[name] = sys.modules[name]
            sys.modules[name] = mock_obj

        # Force reload of the module under test to ensure it uses the mocked dependencies
        if "src.gui.widgets.impedance_analyzer" in sys.modules:
            del sys.modules["src.gui.widgets.impedance_analyzer"]

        try:
            import src.gui.widgets.impedance_analyzer

            self.ImpedanceAnalyzer = src.gui.widgets.impedance_analyzer.ImpedanceAnalyzer
        except ImportError as e:
            self.fail(f"Could not import ImpedanceAnalyzer even with mocks: {e}")

        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.sample_rate = 48000

        # Instantiate the analyzer
        self.analyzer = self.ImpedanceAnalyzer(self.mock_audio_engine)

    def tearDown(self):
        # Clean up temp dir
        shutil.rmtree(self.test_dir)

        # Restore sys.modules
        for name in self.modules_to_patch:
            if name in self.original_modules:
                sys.modules[name] = self.original_modules[name]
            else:
                del sys.modules[name]

        # Clean up the module from sys.modules
        if "src.gui.widgets.impedance_analyzer" in sys.modules:
            del sys.modules["src.gui.widgets.impedance_analyzer"]

    def test_save_calibration_permissions(self):
        """Test that save_calibration creates files with secure permissions (0o600)."""
        # Setup dummy calibration data
        self.analyzer.cal_open = {100.0: 10 + 10j}
        self.analyzer.cal_short = {100.0: 1 + 1j}
        self.analyzer.cal_load = {100.0: 50 + 0j}
        self.analyzer.load_standard_real = 50.0

        # Save the calibration
        self.analyzer.save_calibration(self.test_file)

        # Verify file exists
        self.assertTrue(os.path.exists(self.test_file))

        # Check permissions on POSIX systems
        if os.name == "posix":
            st = os.stat(self.test_file)
            permissions = st.st_mode & 0o777
            # We expect strict 0o600 permissions
            self.assertEqual(permissions, 0o600, f"File permissions should be 0o600, but got {oct(permissions)}")

        # Verify content integrity
        with open(self.test_file, "r") as f:
            data = json.load(f)
            self.assertIn("cal_open", data)
            self.assertIn("100.0", data["cal_open"])

import unittest
import os
import sys
import tempfile
import stat
from unittest.mock import MagicMock, patch

# 1. Import heavy dependencies
import numpy as np
import scipy.signal
import pyqtgraph as pg

# Ensure QApplication exists
from PyQt6.QtWidgets import QApplication
if not QApplication.instance():
    app = QApplication(sys.argv + ['-platform', 'offscreen'])

# 2. Setup mocks
mock_sd = MagicMock()
mock_sf = MagicMock()
mock_localization = MagicMock()
mock_localization.tr.side_effect = lambda key, default=None: str(key)

# 3. Force patch sys.modules BEFORE imports
sys.modules["sounddevice"] = mock_sd
sys.modules["soundfile"] = mock_sf
sys.modules["src.core.localization"] = mock_localization

# Clean up any potential previous imports
modules_to_reload = [
    "src.core.audio_engine",
    "src.gui.widgets.sound_quality_analyzer"
]
for m in modules_to_reload:
    if m in sys.modules:
        del sys.modules[m]

# 4. Import the target module
from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzerWidget

class TestSoundQualityAnalyzerPermissions(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_module = MagicMock()
        self.mock_module.audio_engine = MagicMock()

        self.widget = SoundQualityAnalyzerWidget(self.mock_module)

        # Populate analysis results
        self.widget.analysis_results = {
            "channels": [
                {
                    "name": "Left",
                    "integrated_lufs": -14.0,
                    "mean_sharpness": 1.2,
                    "mean_roughness": 0.5,
                    "mean_tonality": 0.1,
                    "mean_fluctuation": 0.2,
                    "mean_ai": 0.8
                }
            ]
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir)
        self.widget.close()

    @patch('src.gui.widgets.sound_quality_analyzer.QFileDialog.getSaveFileName')
    @patch('src.gui.widgets.sound_quality_analyzer.QMessageBox')
    def test_export_csv_permissions(self, mock_msgbox, mock_get_save_file_name):
        # Define the target file path
        target_path = os.path.join(self.test_dir, "test_export.csv")
        mock_get_save_file_name.return_value = (target_path, "CSV Files (*.csv)")

        # Call the export method
        self.widget.export_csv()

        # Check if file exists
        self.assertTrue(os.path.exists(target_path), "Export file was not created")

        # Check permissions
        st = os.stat(target_path)
        mode = st.st_mode

        # On POSIX, we expect strict permissions (0o600).
        if os.name == 'posix':
            # We expect that Group Read (0o040) OR Other Read (0o004) is likely present with default umask
            is_insecure = (mode & stat.S_IRGRP) or (mode & stat.S_IROTH)
            print(f"File mode: {oct(mode)}")

            # This test is designed to FAIL if the code is SECURE.
            # So if is_insecure is True, the test passes (confirming vulnerability).
            # NOW we expect is_insecure to be FALSE.

            # Update assertion for verification phase:
            self.assertFalse(is_insecure, f"File permissions {oct(mode)} are insecure! Expected 0o600 (or similar restrictive).")

if __name__ == '__main__':
    unittest.main()

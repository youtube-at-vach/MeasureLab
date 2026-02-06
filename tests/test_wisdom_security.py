import unittest
from unittest.mock import patch
import json
import base64
import pickle
from pathlib import Path
import logging
import os

# Configure logging to capture output
logging.basicConfig(level=logging.INFO)

from src.core import fft_manager  # noqa: E402

class TestWisdomSecurity(unittest.TestCase):
    def setUp(self):
        # Patch src.core.fft_manager.pyfftw
        # create=True ensures it works even if pyfftw is not installed in the test env
        self.pyfftw_patcher = patch('src.core.fft_manager.pyfftw', create=True)
        self.mock_pyfftw = self.pyfftw_patcher.start()

        # Configure the mock
        self.mock_pyfftw.export_wisdom.return_value = (b"mock_wisdom_1", b"mock_wisdom_2")

        # Save original HAS_PYFFTW state and force it to True
        self.orig_has_pyfftw = fft_manager.HAS_PYFFTW
        fft_manager.HAS_PYFFTW = True

        # Create a fresh instance
        self.manager = fft_manager.FFTManager()
        self.manager.wisdom_path = Path("test_wisdom_file")

    def tearDown(self):
        self.pyfftw_patcher.stop()
        fft_manager.HAS_PYFFTW = self.orig_has_pyfftw

        if self.manager.wisdom_path.exists():
            os.remove(self.manager.wisdom_path)

    def test_save_wisdom_json(self):
        """Test that wisdom is saved as JSON with base64 encoding."""
        self.manager.save_wisdom()

        if not self.manager.wisdom_path.exists():
            self.fail("Wisdom file was not created")

        with open(self.manager.wisdom_path, "rb") as f:
            content = f.read()

        # Try to parse as JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # If it fails, check if it was pickle (the failure mode before fix)
            try:
                import pickle
                pickle.loads(content)
                self.fail("Saved file is a pickle stream! Should be JSON.")
            except Exception:
                self.fail("Saved file is neither JSON nor Pickle?")

        # Verify content structure
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        # Verify decoded values
        val1 = base64.b64decode(data[0])
        val2 = base64.b64decode(data[1])
        self.assertEqual(val1, b"mock_wisdom_1")
        self.assertEqual(val2, b"mock_wisdom_2")

    def test_load_wisdom_json(self):
        """Test that wisdom can be loaded from JSON."""
        # Create a valid JSON wisdom file
        data = [
            base64.b64encode(b"loaded_wisdom_1").decode('ascii'),
            base64.b64encode(b"loaded_wisdom_2").decode('ascii')
        ]
        with open(self.manager.wisdom_path, "w") as f:
            json.dump(data, f)

        self.manager.load_wisdom()

        # Verify pyfftw.import_wisdom was called with correct data
        self.mock_pyfftw.import_wisdom.assert_called_with((b"loaded_wisdom_1", b"loaded_wisdom_2"))

    def test_legacy_pickle_ignored(self):
        """Test that legacy pickle files are ignored and pickle.load is not called."""
        # Create a pickle file
        with open(self.manager.wisdom_path, "wb") as f:
            pickle.dump((b"legacy_wisdom",), f)

        # Ensure load_wisdom doesn't crash on this file
        try:
            self.manager.load_wisdom()
        except Exception as e:
            self.fail(f"load_wisdom crashed on legacy file: {e}")

        # And verify import_wisdom was NOT called (since it was legacy data)
        self.mock_pyfftw.import_wisdom.assert_not_called()

if __name__ == '__main__':
    unittest.main()

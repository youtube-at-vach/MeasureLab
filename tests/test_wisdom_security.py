import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import json
import base64
import pickle
from pathlib import Path
import logging

# Configure logging to capture output
logging.basicConfig(level=logging.INFO)

# Mock pyfftw before importing fft_manager
mock_pyfftw = MagicMock()
mock_pyfftw.export_wisdom.return_value = (b"mock_wisdom_1", b"mock_wisdom_2")
sys.modules["pyfftw"] = mock_pyfftw

# Now import the module under test
from src.core import fft_manager  # noqa: E402

class TestWisdomSecurity(unittest.TestCase):
    def setUp(self):
        # Reset the mock for each test
        mock_pyfftw.reset_mock()
        mock_pyfftw.export_wisdom.return_value = (b"mock_wisdom_1", b"mock_wisdom_2")

        # Create a fresh instance
        self.manager = fft_manager.FFTManager()
        # Force HAS_PYFFTW to True for testing logic
        fft_manager.HAS_PYFFTW = True
        self.manager.wisdom_path = Path("test_wisdom_file")

    def tearDown(self):
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
        mock_pyfftw.import_wisdom.assert_called_with((b"loaded_wisdom_1", b"loaded_wisdom_2"))

    def test_legacy_pickle_ignored(self):
        """Test that legacy pickle files are ignored and pickle.load is not called."""
        # Create a pickle file
        with open(self.manager.wisdom_path, "wb") as f:
            pickle.dump((b"legacy_wisdom",), f)

        # We need to ensure pickle.load is NOT called.
        # Since we want to remove 'import pickle' from the source file,
        # we can't easily mock it inside the source file if it's not imported!
        # However, if the source file still has 'import pickle', we can patch it.
        # If the source file does NOT have 'import pickle', then this test passes automatically
        # (unless it crashes because it can't find pickle, which is also fine as long as it handles the error).

        # Let's try to patch pickle in the module if it exists
        if hasattr(fft_manager, 'pickle'):
            with patch('src.core.fft_manager.pickle') as mock_pickle:
                self.manager.load_wisdom()
                # If the code uses pickle.load, this assertion will fail (which is what we want for reproduction)
                # But wait, we want the test to pass *after* the fix.
                # Before the fix, pickle.load IS called.
                # So this test serves to verify the fix works (by NOT calling it).

                # If we expect the fix to ignore the file:
                mock_pickle.load.assert_not_called()
        else:
            # If pickle is not imported in fft_manager, we are good.
            # But we should ensure load_wisdom doesn't crash on this file.
            try:
                self.manager.load_wisdom()
            except Exception as e:
                self.fail(f"load_wisdom crashed on legacy file: {e}")

            # And verify import_wisdom was NOT called (since it was legacy data)
            mock_pyfftw.import_wisdom.assert_not_called()

if __name__ == '__main__':
    unittest.main()

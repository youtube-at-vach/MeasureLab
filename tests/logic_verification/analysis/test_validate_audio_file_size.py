import unittest
from unittest.mock import patch
from src.core.analysis import AudioCalc


class MockInfo:
    def __init__(self, frames, channels):
        self.frames = frames
        self.channels = channels


class TestValidateAudioFileSize(unittest.TestCase):
    def test_validate_audio_file_size_valid(self):
        with patch("src.core.analysis.sf.info") as mock_info:
            mock_info.return_value = MockInfo(1000, 2)
            valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
            self.assertTrue(valid)
            self.assertEqual(msg, "")

    def test_validate_audio_file_size_invalid(self):
        with patch("src.core.analysis.sf.info") as mock_info:
            mock_info.return_value = MockInfo(AudioCalc.MAX_AUDIO_SAMPLES, 2)
            valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
            self.assertFalse(valid)
            self.assertIn("File too large", msg)

    def test_validate_audio_file_size_error_path(self):
        with patch("src.core.analysis.sf.info") as mock_info:
            mock_info.side_effect = Exception("Mocked exception")
            valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
            self.assertFalse(valid)
            self.assertEqual(msg, "Failed to check file size: Mocked exception")

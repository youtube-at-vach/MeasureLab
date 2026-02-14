from unittest.mock import patch
import pytest

try:
    from src.core.analysis import AudioCalc
except ImportError:
    pytest.skip("Skipping due to import errors (likely missing scipy)", allow_module_level=True)

class MockInfo:
    def __init__(self, frames, channels):
        self.frames = frames
        self.channels = channels

def test_validate_audio_file_size_small():
    with patch("src.core.analysis.sf.info") as mock_info:
        # Small file: 1M samples * 2 channels = 2M < 500M
        mock_info.return_value = MockInfo(1_000_000, 2)

        valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
        assert valid
        assert msg == ""

def test_validate_audio_file_size_large():
    with patch("src.core.analysis.sf.info") as mock_info:
        # Large file: 300M samples * 2 channels = 600M > 500M
        mock_info.return_value = MockInfo(300_000_000, 2)

        valid, msg = AudioCalc.validate_audio_file_size("dummy_large.wav")
        assert not valid
        assert "File too large" in msg
        assert "600000000" in msg

def test_validate_audio_file_size_exact_limit():
    with patch("src.core.analysis.sf.info") as mock_info:
        # Exact limit: 500M samples * 1 channel = 500M
        mock_info.return_value = MockInfo(500_000_000, 1)

        valid, msg = AudioCalc.validate_audio_file_size("dummy_exact.wav")
        assert valid # Should be valid (<=)

def test_validate_audio_file_size_error():
    with patch("src.core.analysis.sf.info") as mock_info:
        mock_info.side_effect = Exception("File not found")

        valid, msg = AudioCalc.validate_audio_file_size("nonexistent.wav")
        assert not valid
        assert "Failed to check file size" in msg

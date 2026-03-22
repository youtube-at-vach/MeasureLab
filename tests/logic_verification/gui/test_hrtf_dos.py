import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from src.gui.widgets.hrtf_player import HRTFPlayer


class MockInfo:
    def __init__(self, frames, samplerate, channels):
        self.frames = frames
        self.samplerate = samplerate
        self.channels = channels


@pytest.fixture
def hrtf_player():
    engine = MagicMock()
    engine.sample_rate = 48000
    return HRTFPlayer(engine)


def test_load_music_dos_prevention(hrtf_player):
    """
    Verify that loading a file exceeding MAX_AUDIO_SAMPLES fails gracefully.
    """
    # Case 1: File too large
    with (
        patch("src.gui.widgets.hrtf_player.sf.info") as mock_info,
        patch("src.gui.widgets.hrtf_player.sf.read") as mock_read,
    ):
        # 600M frames, 1 channel = 600M samples > 500M
        mock_info.return_value = MockInfo(frames=600_000_000, samplerate=48000, channels=1)

        # If read were called, it would return dummy data
        mock_read.return_value = (np.zeros((100, 1)), 48000)

        success, msg = hrtf_player.load_music("huge_file.wav")

        # Should fail due to size check
        assert not success, "Should have rejected huge file"
        assert "File too large" in msg or "exceeds limit" in msg

        # Verify sf.read was NOT called
        mock_read.assert_not_called()


def test_load_music_valid_size(hrtf_player):
    """
    Verify that loading a normal file still works.
    """
    # Case 2: File within limits
    with (
        patch("src.gui.widgets.hrtf_player.sf.info") as mock_info,
        patch("src.gui.widgets.hrtf_player.sf.read") as mock_read,
    ):
        # 10M frames, 2 channels = 20M samples < 500M
        mock_info.return_value = MockInfo(frames=10_000_000, samplerate=48000, channels=2)

        # Return valid data
        fake_data = np.zeros((100, 2))
        mock_read.return_value = (fake_data, 48000)

        success, msg = hrtf_player.load_music("valid.wav")

        assert success
        mock_read.assert_called_once()

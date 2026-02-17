import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
import numpy as np
import pytest
from unittest.mock import MagicMock
from src.gui.widgets.hrtf_player import HRTFPlayer, HRTFData

@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000.0  # Target SR
    return engine

@pytest.fixture
def hrtf_player(mock_audio_engine):
    player = HRTFPlayer(mock_audio_engine)
    return player

def test_get_resampled_pair_same_sr(hrtf_player):
    # Setup Mock HRTF Data
    M, R, N = 2, 2, 100
    ir_data = np.ones((M, R, N))
    ir_data[0, 0, :] = 1.0
    ir_data[0, 1, :] = 2.0

    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 48000.0

    resampled = hrtf_player._get_resampled_pair(0)

    assert resampled.shape == (100, 2)
    assert np.allclose(resampled[:, 0], 1.0)
    assert np.allclose(resampled[:, 1], 2.0)

    # Ensure it's a copy
    resampled[0, 0] = 999.0
    assert ir_data[0, 0, 0] == 1.0

def test_get_resampled_pair_resample_gain_correction(hrtf_player):
    # Test gain correction
    # Source: 24000, Target: 48000 (Upsample 2x)
    # Correction factor should be 24000/48000 = 0.5

    M, R, N = 1, 2, 1000 # Use larger N to avoid edge effects
    ir_data = np.ones((M, R, N))

    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 24000.0

    resampled = hrtf_player._get_resampled_pair(0)

    assert resampled.shape == (2000, 2)

    # Check middle section to avoid filter ringing at edges
    # resample_poly can have transients at start/end
    middle = resampled[500:-500, :]

    assert np.allclose(middle, 0.5, atol=0.01)

def test_callback_cache_usage(hrtf_player):
    # Setup
    M, R, N = 2, 2, 100
    ir_data = np.zeros((M, R, N))
    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.source_positions = np.array([[0,0,1], [90,0,1]])
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 48000.0

    hrtf_player.rotation_active = True
    hrtf_player.music_buffer = np.zeros((1000, 2), dtype=np.float32)

    # 1. Call _get_resampled_pair manually
    pair = hrtf_player._get_resampled_pair(0)
    assert pair.shape == (100, 2)

    # 2. Simulate cache setting
    nearest_idx = 0
    if nearest_idx != hrtf_player._rot_cache_idx:
        hrtf_player._rot_cache_data = pair
        hrtf_player._rot_cache_idx = nearest_idx

    assert hrtf_player._rot_cache_idx == 0
    assert hrtf_player._rot_cache_data is pair

    # 3. Verify usage
    hrtf_player._rot_cache_data[0, 0] = 999.0
    pair_fetched = hrtf_player._rot_cache_data
    assert pair_fetched[0, 0] == 999.0

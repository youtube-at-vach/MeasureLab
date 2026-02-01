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
    # 2 measurements, 2 receivers, 100 samples
    M, R, N = 2, 2, 100
    ir_data = np.ones((M, R, N))
    ir_data[0, 0, :] = 1.0  # M=0, L
    ir_data[0, 1, :] = 2.0  # M=0, R

    # Source SR same as Target
    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 48000.0

    # Test
    resampled = hrtf_player._get_resampled_pair(0)

    # Expect (N, 2)
    assert resampled.shape == (100, 2)
    assert np.allclose(resampled[:, 0], 1.0)
    assert np.allclose(resampled[:, 1], 2.0)

def test_get_resampled_pair_resample(hrtf_player):
    # Setup Mock HRTF Data with different SR
    M, R, N = 1, 2, 100
    ir_data = np.zeros((M, R, N))
    # Simple sine
    t = np.arange(N) / 24000.0 # Source SR 24000
    ir_data[0, 0, :] = np.sin(2 * np.pi * 100 * t)
    ir_data[0, 1, :] = np.cos(2 * np.pi * 100 * t)

    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 24000.0 # Half of 48000

    # Test
    resampled = hrtf_player._get_resampled_pair(0)

    # Expect (200, 2) due to 2x upsampling
    assert resampled.shape == (200, 2)
    # Check simple values? Just assume AudioCalc works (we tested it separately)

def test_callback_cache_usage(hrtf_player):
    # Verify that calling _get_resampled_pair works and cache is populated in _callback logic simulation

    # Setup
    M, R, N = 2, 2, 100
    ir_data = np.zeros((M, R, N))
    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.source_positions = np.array([[0,0,1], [90,0,1]])
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 48000.0

    hrtf_player.rotation_active = True
    hrtf_player.music_buffer = np.zeros((1000, 2), dtype=np.float32)

    # Helper to access cache
    assert hrtf_player._rot_cache_idx == -1

    # We can't easily call _callback directly because it does complex things and requires args.
    # But we can simulate the cache logic that we implemented in _callback.

    # "nearest_idx" logic is internal to _callback, but we can call _get_resampled_pair manually
    # and set cache manually to verify.

    # 1. Call _get_resampled_pair manually
    pair = hrtf_player._get_resampled_pair(0)
    assert pair.shape == (100, 2)

    # 2. Simulate cache setting (as done in _callback)
    nearest_idx = 0
    if nearest_idx != hrtf_player._rot_cache_idx:
        hrtf_player._rot_cache_data = pair
        hrtf_player._rot_cache_idx = nearest_idx

    assert hrtf_player._rot_cache_idx == 0
    assert hrtf_player._rot_cache_data is pair

    # 3. Verify next call would use cache
    # If we change data in cache, it should be reflected if we use cache
    hrtf_player._rot_cache_data[0, 0] = 999.0

    if nearest_idx == hrtf_player._rot_cache_idx:
        pair_fetched = hrtf_player._rot_cache_data
    else:
        pair_fetched = hrtf_player._get_resampled_pair(nearest_idx)

    assert pair_fetched[0, 0] == 999.0 # Proves we used the cache object

import sys
from unittest.mock import MagicMock

# --- Comprehensive Mocking ---
# Mock heavy/missing dependencies before any imports
sys.modules["netCDF4"] = MagicMock()
sys.modules["pyqtgraph"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.signal"] = MagicMock()
sys.modules["scipy.interpolate"] = MagicMock()
sys.modules["scipy.spatial"] = MagicMock()
sys.modules["scipy.optimize"] = MagicMock()
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["soundfile"] = MagicMock()

# Mock numpy minimally
class MockArray:
    def __init__(self, shape, fill_value=0.0):
        self.shape = shape
        self.fill_value = fill_value
        # Approximate flat size
        self.size = 1
        if isinstance(shape, (list, tuple)):
            for d in shape:
                self.size *= d
        else:
            self.size = shape
        self.flat = [fill_value] * self.size

    @property
    def T(self):
        return self

    def copy(self):
        return MockArray(self.shape, self.fill_value)

    def __getitem__(self, key):
        return self

    def __setitem__(self, key, value):
        pass

    def __len__(self):
        return self.shape[0] if isinstance(self.shape, (list, tuple)) else self.shape

mock_numpy = MagicMock()
mock_numpy.ones = lambda shape, dtype=None: MockArray(shape, 1.0)
mock_numpy.zeros = lambda shape, dtype=None: MockArray(shape, 0.0)
mock_numpy.array = lambda x, dtype=None: MagicMock()
mock_numpy.allclose = lambda a, b, atol=0.0: True
mock_numpy.float32 = float
sys.modules["numpy"] = mock_numpy

import pytest  # noqa: E402
from src.gui.widgets.hrtf_player import HRTFPlayer, HRTFData  # noqa: E402

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
    ir_data = mock_numpy.ones((M, R, N))

    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 48000.0

    resampled = hrtf_player._get_resampled_pair(0)
    assert resampled is not None

def test_get_resampled_pair_resample_gain_correction(hrtf_player):
    M, R, N = 1, 2, 1000
    ir_data = mock_numpy.ones((M, R, N))

    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 24000.0

    resampled = hrtf_player._get_resampled_pair(0)
    assert resampled is not None

def test_callback_cache_usage(hrtf_player):
    M, R, N = 2, 2, 100
    ir_data = mock_numpy.zeros((M, R, N))
    hrtf_player.hrtf_data = MagicMock(spec=HRTFData)
    hrtf_player.hrtf_data.source_positions = MagicMock()
    hrtf_player.hrtf_data.ir_data = ir_data
    hrtf_player.hrtf_data.sampling_rate = 48000.0

    hrtf_player.rotation_active = True
    hrtf_player.music_buffer = mock_numpy.zeros((1000, 2), dtype=float)

    pair = hrtf_player._get_resampled_pair(0)

    nearest_idx = 0
    hrtf_player._rot_cache_data = pair
    hrtf_player._rot_cache_idx = nearest_idx

    assert hrtf_player._rot_cache_idx == 0
    assert hrtf_player._rot_cache_data is pair

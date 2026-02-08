import sys
import pytest
from unittest.mock import MagicMock, patch

# Module constants
from src.core.module_constants import ALL_MODULE_KEYS, MODULE_SIGNAL_GENERATOR

@pytest.fixture
def mock_heavy_dependencies():
    """
    Patches sys.modules to mock heavy dependencies only for the duration of the test.
    This prevents side effects on other tests that require the real modules.
    """
    mock_modules = {
        "PyQt6": MagicMock(),
        "PyQt6.QtCore": MagicMock(),
        "PyQt6.QtWidgets": MagicMock(),
        "PyQt6.QtGui": MagicMock(),
        "pyqtgraph": MagicMock(),
        "scipy": MagicMock(),
        "scipy.signal": MagicMock(),
        "scipy.ndimage": MagicMock(),
        "scipy.interpolate": MagicMock(),
        "pywt": MagicMock(),
        "netCDF4": MagicMock(),
        "sounddevice": MagicMock(),
        "soundfile": MagicMock(),
        "pyfftw": MagicMock(),
        "src.core.audio_engine": MagicMock(),
        "src.core.config_manager": MagicMock(),
        "src.core.localization": MagicMock(),
        "src.gui.widgets.detachable_wrapper": MagicMock(),
    }

    with patch.dict(sys.modules, mock_modules):
        yield

@pytest.fixture
def loaded_main_window_module(mock_heavy_dependencies):
    """
    Ensures that src.gui.main_window is imported (or reloaded) while the mocks are active.
    """
    import importlib
    import src.gui.main_window
    importlib.reload(src.gui.main_window)
    return src.gui.main_window

def test_module_keys_constants():
    # Verify we have keys
    assert len(ALL_MODULE_KEYS) > 0
    assert MODULE_SIGNAL_GENERATOR in ALL_MODULE_KEYS

@patch('src.gui.main_window.ConfigManager')
@patch('src.gui.main_window.AudioEngine')
@patch('src.gui.main_window.get_manager')
def test_load_module_class(mock_get_manager, mock_audio_engine, mock_config_manager, loaded_main_window_module):
    # Use the reloaded module
    _load_module_class = loaded_main_window_module._load_module_class

    # Test MODULE_SIGNAL_GENERATOR specifically
    try:
        cls = _load_module_class(MODULE_SIGNAL_GENERATOR)
        assert cls is not None
    except ImportError:
        pass
    except KeyError:
        pytest.fail("MODULE_SIGNAL_GENERATOR key raised KeyError")

    # Verify invalid key raises KeyError
    with pytest.raises(KeyError):
        _load_module_class("Invalid Key")

def test_load_all_modules(loaded_main_window_module):
    """Verify all defined module keys can be loaded without KeyError."""
    _load_module_class = loaded_main_window_module._load_module_class

    for key in ALL_MODULE_KEYS:
        try:
            _load_module_class(key)
        except KeyError:
             pytest.fail(f"KeyError for module: {key}")
        except ImportError:
             pass

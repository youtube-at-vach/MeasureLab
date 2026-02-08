import sys
from unittest.mock import MagicMock

# Mock heavy UI dependencies so tests can import src.gui.main_window in headless environments
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["PyQt6.QtGui"] = MagicMock()
sys.modules["pyqtgraph"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.signal"] = MagicMock()
sys.modules["scipy.ndimage"] = MagicMock()
sys.modules["scipy.interpolate"] = MagicMock()
sys.modules["pywt"] = MagicMock()
sys.modules["netCDF4"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["soundfile"] = MagicMock()
sys.modules["pyfftw"] = MagicMock()

# Mock internal dependencies imported at top level
sys.modules["src.core.audio_engine"] = MagicMock()
sys.modules["src.core.config_manager"] = MagicMock()
sys.modules["src.core.localization"] = MagicMock()
sys.modules["src.gui.widgets.detachable_wrapper"] = MagicMock()

import pytest  # noqa: E402
from unittest.mock import patch  # noqa: E402
from src.core.module_constants import ALL_MODULE_KEYS, MODULE_SIGNAL_GENERATOR  # noqa: E402

def test_module_keys_constants():
    # Verify we have keys
    assert len(ALL_MODULE_KEYS) > 0
    assert MODULE_SIGNAL_GENERATOR in ALL_MODULE_KEYS

@patch('src.gui.main_window.ConfigManager')
@patch('src.gui.main_window.AudioEngine')
@patch('src.gui.main_window.get_manager')
def test_load_module_class(mock_get_manager, mock_audio_engine, mock_config_manager):
    # We don't need to mock ThemeManager as it is imported inside MainWindow.__init__

    # Import inside the test to use the mocks
    from src.gui.main_window import _load_module_class

    # Test MODULE_SIGNAL_GENERATOR specifically
    try:
        cls = _load_module_class(MODULE_SIGNAL_GENERATOR)
        # With mocks, it might return a Mock object or the real class if imports worked (unlikely here)
        # Since we mocked sys.modules["PyQt6"], imports inside signal_generator probably succeeded returning a Mock class
        assert cls is not None
    except ImportError:
        pass
    except KeyError:
        pytest.fail("MODULE_SIGNAL_GENERATOR key raised KeyError")

    # Verify invalid key raises KeyError
    with pytest.raises(KeyError):
        _load_module_class("Invalid Key")

def test_load_all_modules():
    """Verify all defined module keys can be loaded without KeyError."""
    from src.gui.main_window import _load_module_class

    for key in ALL_MODULE_KEYS:
        try:
            _load_module_class(key)
        except KeyError:
             pytest.fail(f"KeyError for module: {key}")
        except ImportError:
             # Import errors are expected if dependencies are missing, but logic should be fine
             pass

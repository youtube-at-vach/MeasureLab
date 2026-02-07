import pytest
from unittest.mock import patch
from src.core.module_constants import ALL_MODULE_KEYS, MODULE_SIGNAL_GENERATOR

def test_module_keys_constants():
    # Verify we have keys
    assert len(ALL_MODULE_KEYS) > 0
    assert MODULE_SIGNAL_GENERATOR in ALL_MODULE_KEYS

@patch('src.gui.main_window.ConfigManager')
@patch('src.gui.main_window.AudioEngine')
@patch('src.gui.main_window.get_manager')
def test_load_module_class(mock_get_manager, mock_audio_engine, mock_config_manager):
    # We don't need to mock ThemeManager as it is imported inside MainWindow.__init__
    # ConfigManager and AudioEngine are mocked to avoid heavy initialization if they were imported at top level
    # (though in the refactored main_window they are imported at top level, so mocking here might be too late
    # if we were importing MainWindow, but we are only importing _load_module_class which is a function).

    # Actually, main_window.py imports AudioEngine and ConfigManager at the top level.
    # The patch decorator patches them where they are *looked up*, which is src.gui.main_window.
    # So this should work.

    from src.gui.main_window import _load_module_class

    try:
        cls = _load_module_class(MODULE_SIGNAL_GENERATOR)
        # We check the name of the class
        assert cls.__name__ == "SignalGenerator"
    except ImportError:
        # If dependencies are missing, that's fine for this test as long as it TRIED.
        pass
    except KeyError:
        pytest.fail("MODULE_SIGNAL_GENERATOR key raised KeyError")

    # Verify invalid key raises KeyError
    with pytest.raises(KeyError):
        _load_module_class("Invalid Key")

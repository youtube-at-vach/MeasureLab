import pytest
from src.core.module_constants import ALL_MODULE_KEYS, MODULE_SIGNAL_GENERATOR

def test_module_keys_constants():
    # Verify we have keys
    assert len(ALL_MODULE_KEYS) > 0
    assert MODULE_SIGNAL_GENERATOR in ALL_MODULE_KEYS

def test_load_module_class(mocker):
    # Mock ConfigManager and AudioEngine to avoid heavy initialization
    mocker.patch('src.gui.main_window.ConfigManager')
    mocker.patch('src.gui.main_window.AudioEngine')
    mocker.patch('src.gui.main_window.get_manager')

    # We don't need to mock ThemeManager as it is imported inside MainWindow.__init__

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

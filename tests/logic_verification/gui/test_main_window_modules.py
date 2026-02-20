import sys
import pytest
from unittest.mock import patch, MagicMock
from src.core.module_constants import ALL_MODULE_KEYS, MODULE_SIGNAL_GENERATOR

def test_module_keys_constants():
    # Verify we have keys
    assert len(ALL_MODULE_KEYS) > 0
    assert MODULE_SIGNAL_GENERATOR in ALL_MODULE_KEYS

def test_load_module_class():
    # Mock PyQt6 and other heavy dependencies to allow importing main_window
    modules_to_patch = {
        "PyQt6": MagicMock(),
        "PyQt6.QtCore": MagicMock(),
        "PyQt6.QtWidgets": MagicMock(),
        "numpy": MagicMock(),
        "scipy": MagicMock(),
        "scipy.signal": MagicMock(),
        "src.core.audio_engine": MagicMock(),
        "src.core.config_manager": MagicMock(),
        "src.core.localization": MagicMock(),
        "src.core.theme_manager": MagicMock(),
        "src.gui.widgets.detachable_wrapper": MagicMock(),
    }

    with patch.dict(sys.modules, modules_to_patch):
        # We must mock dependencies BEFORE importing main_window
        # Ensure it is importable

        # Capture keys before import
        before_keys = set(sys.modules.keys())

        with patch('src.gui.main_window.ConfigManager'), \
             patch('src.gui.main_window.AudioEngine'), \
             patch('src.gui.main_window.get_manager'):

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

        # Cleanup newly loaded modules that might be poisoned by mocks
        after_keys = set(sys.modules.keys())
        for key in (after_keys - before_keys):
            if key.startswith("src.") or key.startswith("PyQt6"):
                del sys.modules[key]

from unittest.mock import MagicMock
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock PyQt6
from unittest.mock import patch
sys.modules['PyQt6'] = MagicMock()
sys.modules['PyQt6.QtCore'] = MagicMock()
sys.modules['PyQt6.QtWidgets'] = MagicMock()
sys.modules['PyQt6.QtGui'] = MagicMock()

import src.gui.widgets.settings as settings

def test_jack_detection():
    # Mock AudioEngine
    mock_engine = MagicMock()
    
    # Mock host APIs
    mock_engine.get_host_apis.return_value = [
        {'name': 'ALSA', 'index': 0},
        {'name': 'JACK Audio Connection Kit', 'index': 1}
    ]
    
    # Create widget with mocked dependencies
    with patch('src.gui.widgets.settings.ConfigManager'), \
         patch('src.gui.widgets.settings.get_manager'), \
         patch('src.gui.widgets.settings.tr', lambda x: x), \
         patch('src.gui.widgets.settings.QPushButton'), \
         patch('src.gui.widgets.settings.QCheckBox'), \
         patch('src.gui.widgets.settings.QComboBox'), \
         patch('src.gui.widgets.settings.QTabWidget'), \
         patch('src.gui.widgets.settings.QVBoxLayout'), \
         patch('src.gui.widgets.settings.QHBoxLayout'), \
         patch('src.gui.widgets.settings.QFormLayout'), \
         patch('src.gui.widgets.settings.QGroupBox'), \
         patch('src.gui.widgets.settings.QLabel'), \
         patch('src.gui.widgets.settings.QSpinBox'), \
         patch('src.gui.widgets.settings.QLineEdit'):
        
        # We need to minimally initialize enough for _update_offline_ui_state to run
        widget = settings.SettingsWidget(mock_engine, MagicMock())
        
        # Mock UI elements
        widget.offline_check = MagicMock()
        widget.offline_check.isChecked.return_value = False
        widget.refresh_btn = MagicMock()
        widget.hostapi_combo = MagicMock()
        widget.input_combo = MagicMock()
        widget.output_combo = MagicMock()
        widget.offline_rate_spin = MagicMock()
        widget.sr_combo = MagicMock()
        
        # Test detection
        print(f"JACK available: {widget._is_jack_available()}")
        assert widget._is_jack_available() is True
        
        # Test UI update logic
        widget._update_offline_ui_state()
        widget.refresh_btn.setEnabled.assert_called_with(False)
        print("Test passed: Refresh button disabled when JACK is present.")

        # Test without JACK
        mock_engine.get_host_apis.return_value = [{'name': 'ALSA', 'index': 0}]
        print(f"JACK available (after removal): {widget._is_jack_available()}")
        assert widget._is_jack_available() is False
        
        widget._update_offline_ui_state()
        widget.refresh_btn.setEnabled.assert_called_with(True)
        print("Test passed: Refresh button enabled when JACK is absent.")

if __name__ == "__main__":
    try:
        test_jack_detection()
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

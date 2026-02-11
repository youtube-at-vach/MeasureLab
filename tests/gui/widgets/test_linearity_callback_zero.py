
import sys
from unittest.mock import MagicMock
import pytest
from PyQt6.QtCore import QObject, pyqtSignal

# Mock sounddevice if not present
try:
    import sounddevice # noqa: F401
except ImportError:
    sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.linearity_analyzer import LinearityAnalyzer
from src.core.audio_engine import AudioEngine

def test_callback_id_zero_handling():
    """
    Verifies that LinearityAnalyzer correctly handles callback_id=0 (which is False-y in Python).
    Previously, stop_analysis() failed to unregister callback 0 because of 'if self.callback_id:'.
    """
    # Setup
    audio_engine = MagicMock(spec=AudioEngine)
    audio_engine.sample_rate = 48000
    # Mock register_callback to return 0
    audio_engine.register_callback.return_value = 0
    
    analyzer = LinearityAnalyzer(audio_engine)
    
    # Start analysis -> should get callback_id = 0
    analyzer.start_analysis()
    assert analyzer.callback_id == 0
    assert analyzer.is_running is True
    
    # Stop analysis -> should unregister callback 0
    analyzer.stop_analysis()
    
    # Assertions
    audio_engine.unregister_callback.assert_called_with(0)
    assert analyzer.callback_id is None
    assert analyzer.is_running is False
    
    # Start again -> should NOT print "lingering callback" warning
    # We can check by ensuring unregister_callback wasn't called again (with 0) BEFORE start_analysis logic
    audio_engine.unregister_callback.reset_mock()
    audio_engine.register_callback.return_value = 1
    
    analyzer.start_analysis()
    
    # Should not have called unregister_callback (because callback_id was None)
    audio_engine.unregister_callback.assert_not_called()
    assert analyzer.callback_id == 1

if __name__ == "__main__":
    test_callback_id_zero_handling()

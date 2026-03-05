import os
from unittest.mock import MagicMock
import pytest

# Skip if PyQt6 is not installed
pytest.importorskip("PyQt6")

try:
    from PyQt6.QtWidgets import QApplication
    from src.gui.widgets.frequency_counter import FrequencyCounter, FrequencyCounterWidget
except ImportError:
    pytest.skip("Skipping GUI test due to missing dependencies", allow_module_level=True)

# Set environment for headless testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def frequency_counter():
    mock_audio_engine = MagicMock()
    mock_audio_engine.sample_rate = 48000
    mock_audio_engine.calibration = MagicMock()
    mock_audio_engine.calibration.frequency_calibration = 1.0

    counter = FrequencyCounter(mock_audio_engine)

    # Simulate running state
    counter.is_running = True
    counter.start_time = 1000.0
    counter.freq_history.append(100.0)
    counter.time_history.append(0.1)
    counter.selected_channel = 0
    return counter


def test_reset_state_clears_history(frequency_counter):
    # Test the reset_state method directly
    frequency_counter.reset_state()
    assert len(frequency_counter.freq_history) == 0
    assert len(frequency_counter.time_history) == 0
    assert frequency_counter.start_time != 1000.0


def test_widget_channel_change_resets_history(qapp, frequency_counter):
    # Create widget
    widget = FrequencyCounterWidget(frequency_counter)

    # Verify initial state (history has 1 item from fixture)
    assert len(frequency_counter.freq_history) == 1

    # Call on_channel_changed (simulate UI event)
    widget.on_channel_changed(1)

    # Verify channel updated
    assert frequency_counter.selected_channel == 1

    # Verify history cleared
    assert len(frequency_counter.freq_history) == 0

    # Cleanup properly to avoid segfaults and "pure virtual method called"
    widget.deleteLater()
    qapp.processEvents()

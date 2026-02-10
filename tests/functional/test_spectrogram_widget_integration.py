import sys
import os
import pytest
import numpy as np
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, os.getcwd())

from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWidget
from PyQt6.QtWidgets import QApplication

# Set offscreen to avoid display issues
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

def test_spectrogram_widget_update():
    # Ensure QApplication exists
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    # Mock register_callback to return a dummy ID
    mock_engine.register_callback.return_value = 123

    # Initialize Module
    module = Spectrogram(mock_engine)
    module.set_fft_size(1024)
    module.start_analysis()

    # Initialize Widget
    # NOTE: Widget init might reset buffers (via fft_combo signals), so we create it before populating data
    widget = SpectrogramWidget(module)
    
    # Fill audio buffer with some data so update_spectrogram has something to process
    # audio_buffer shape is (fft_size*2, 2)
    t = np.linspace(0, 1024/48000, 1024, endpoint=False)
    sine = 0.5 * np.sin(2 * np.pi * 1000 * t)
    # Put sine wave at the end of buffer
    module.audio_buffer[-1024:, 0] = sine
    module.audio_buffer[-1024:, 1] = sine

    # Run update_spectrogram
    # This calls get_cached_window internally
    try:
        widget.update_spectrogram()
    except Exception as e:
        pytest.fail(f"update_spectrogram raised exception: {e}")

    # Check if spectrogram_data was updated
    # Initial is -120.0
    # After update with sine wave, it should be higher
    last_idx = (module.spectrogram_ptr - 1) % module.history_length
    last_spectrum = module.spectrogram_buffer[last_idx]
    peak_val = np.max(last_spectrum)

    print(f"Peak Value: {peak_val}")
    assert peak_val > -100.0, "Spectrogram should have detected signal"

    # Clean up
    module.stop_analysis()
    # We don't need to explicitly close widget as it wasn't shown

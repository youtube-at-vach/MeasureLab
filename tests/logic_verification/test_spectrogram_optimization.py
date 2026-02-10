
import sys
import os
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

# Mock GUI dependencies
mock_qt_core = MagicMock()
class MockQObject:
    def __init__(self): pass
class MockQWidget:
    def __init__(self, *args, **kwargs): pass
    def update(self): pass
    def setStyleSheet(self, style): pass
    def setLayout(self, layout): pass

mock_qt_core.QObject = MockQObject
mock_qt_core.pyqtSignal = MagicMock(side_effect=lambda *args: MagicMock())

mock_qt_widgets = MagicMock()
mock_qt_widgets.QWidget = MockQWidget

# Setup QComboBox mock
mock_combo_instance = MagicMock()
mock_combo_instance.findText.return_value = -1
mock_combo_instance.currentText.return_value = "8192"
mock_combo_instance.count.return_value = 0
mock_qt_widgets.QComboBox = MagicMock(return_value=mock_combo_instance)

mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": mock_qt_core,
    "PyQt6.QtGui": MagicMock(),
    "PyQt6.QtWidgets": mock_qt_widgets,
    "pyqtgraph": MagicMock(),
    "sounddevice": MagicMock(),
}

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 44100
    def register_callback(self, callback):
        return 1
    def unregister_callback(self, id):
        pass

@pytest.fixture(autouse=True)
def mock_deps():
    with patch.dict(sys.modules, mock_modules):
        if "src.gui.widgets.spectrogram" in sys.modules:
            del sys.modules["src.gui.widgets.spectrogram"]
        yield

def test_update_spectrogram_fast_mode():
    from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWidget

    audio_engine = MockAudioEngine()
    module = Spectrogram(audio_engine)
    widget = SpectrogramWidget(module)

    # Initialize audio buffer with some random data
    module.audio_buffer[:] = np.random.random(module.audio_buffer.shape)
    module.audio_buffer_pos = 0 # reset

    module.sweep_speed_index = 0 # Fast
    module.start_analysis()

    # First update
    widget.update_spectrogram()

    # Check mag_buffer is created
    assert module.mag_buffer is not None
    assert len(module.mag_buffer) == module.fft_size // 2 + 1

    # Check accumulator behavior for Fast mode (target_frames=1)
    assert module.accumulator is None

    # Run again
    widget.update_spectrogram()
    assert module.accumulator is None

def test_update_spectrogram_medium_mode():
    from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWidget

    audio_engine = MockAudioEngine()
    module = Spectrogram(audio_engine)
    widget = SpectrogramWidget(module)
    module.audio_buffer[:] = np.random.random(module.audio_buffer.shape)

    module.sweep_speed_index = 1 # Medium, target=4
    module.start_analysis()

    # First update
    widget.update_spectrogram()

    # acc_count should be 1
    assert module.acc_count == 1
    assert module.accumulator is not None

    # Verify accumulator is a COPY
    assert module.accumulator is not module.mag_buffer, "Accumulator should be a copy in Medium mode"

    # Second update
    widget.update_spectrogram()
    assert module.acc_count == 2

    # Third
    widget.update_spectrogram()
    assert module.acc_count == 3

    # Fourth (Should trigger push and reset)
    widget.update_spectrogram()

    assert module.accumulator is None
    assert module.acc_count == 0

def test_buffer_resize():
    from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWidget

    audio_engine = MockAudioEngine()
    module = Spectrogram(audio_engine)
    widget = SpectrogramWidget(module)

    module.start_analysis()
    widget.update_spectrogram()

    old_buffer = module.mag_buffer
    assert old_buffer is not None

    # Change FFT size
    new_size = 1024
    module.set_fft_size(new_size)

    # Buffer should be None after reset
    assert module.mag_buffer is None

    # Update
    widget.update_spectrogram()

    # New buffer created
    assert module.mag_buffer is not None
    assert len(module.mag_buffer) == new_size // 2 + 1
    assert module.mag_buffer is not old_buffer

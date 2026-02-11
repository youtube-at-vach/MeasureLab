
import sys
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

class MockQThreadPool:
    def start(self, runnable):
        # Synchronous execution for testing logic
        runnable.run()

mock_qt_core.QObject = MockQObject
mock_qt_core.QRunnable = MockQObject
mock_qt_core.QThreadPool = MockQThreadPool

# Improved MockSignal that simulates per-instance behavior when used in a class attribute context
# BUT, if we just assign `pyqtSignal = lambda: MockSignal()`, and it's a class attribute, it runs once.
# To properly mock PyQt signals without the PyQt runtime, we need to ensure the worker instance gets a clean signal.
# We will do this by patching the Worker's init in the test setup.

class MockSignal:
    def __init__(self):
        self.callbacks = []
    def connect(self, cb):
        self.callbacks.append(cb)
    def emit(self, *args):
        for cb in self.callbacks:
            cb(*args)

mock_qt_core.pyqtSignal = lambda *args: MockSignal()

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
    # With MockQThreadPool, this runs synchronously
    widget.update_spectrogram()

    # Check accumulator behavior for Fast mode (target_frames=1)
    assert module.accumulator is None

    # Run again
    widget.update_spectrogram()
    assert module.accumulator is None

def test_update_spectrogram_medium_mode():
    from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWorker, SpectrogramWidget

    # Patch SpectrogramWorker to ensure signals are unique per instance
    original_init = SpectrogramWorker.__init__
    def new_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Manually reset signals to a new instance to simulate PyQt behavior
        # In real PyQt, 'signals' is a QObject with 'result' signal.
        # Our mock setup has 'signals' as an instance of SpectrogramWorkerSignals (mock QObject)
        # which has 'result' as a CLASS attribute (MockSignal instance).
        # We need to give this instance its OWN 'result'.

        # Create a new container with a new signal
        class InstanceSignals:
            result = MockSignal()
        self.signals = InstanceSignals()

    with patch.object(SpectrogramWorker, '__init__', new_init):
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

    module.spectrogram_ptr = 10
    module.accumulator = np.zeros(10)
    module.acc_count = 2

    # Change FFT size
    new_size = 1024
    module.set_fft_size(new_size)

    # Buffer pointers/state should be reset
    assert module.spectrogram_ptr == 0
    assert module.accumulator is None
    assert module.acc_count == 0

    expected_shape = (module.history_length, new_size // 2 + 1)
    assert module.spectrogram_buffer.shape == expected_shape

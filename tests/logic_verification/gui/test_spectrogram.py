import sys
import os
import unittest
import numpy as np
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

# Mock sounddevice to avoid import errors or audio device initialization
sys.modules["sounddevice"] = MagicMock()

from src.gui.widgets.spectrogram import Spectrogram, SpectrogramWorker, SpectrogramWidget  # noqa: E402
from src.core.fft_manager import WARMUP_SIZES  # noqa: E402
from pyqtgraph.graphicsItems.GradientEditorItem import Gradients  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


# Shared Mock AudioEngine
class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000  # Default
        self.block_size = 1024
        self.buffer_size = 1024

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, cb_id):
        pass


class TestSpectrogramBuffer(unittest.TestCase):
    def setUp(self):
        self.audio_engine = MockAudioEngine()
        self.spectrogram = Spectrogram(self.audio_engine)
        # Set a small buffer size for easier testing
        self.spectrogram.fft_size = 10
        self.spectrogram.reset_buffers()
        # audio_buffer size is fft_size * 2 = 20

    def test_linear_fill(self):
        frames = 5
        indata = np.ones((frames, 2))
        outdata = np.zeros((frames, 2))

        # Fill first 5
        self.spectrogram._callback(indata, outdata, frames, None, None)
        self.assertEqual(self.spectrogram.audio_buffer_pos, 5)

        latest = self.spectrogram.get_latest_samples(5)
        np.testing.assert_array_equal(latest, np.ones((5, 2)))

    def test_wrap_around(self):
        # Buffer size is 20.
        # Fill 15 samples (ones)
        indata_1 = np.ones((15, 2))
        outdata = np.zeros((15, 2))
        self.spectrogram._callback(indata_1, outdata, 15, None, None)
        self.assertEqual(self.spectrogram.audio_buffer_pos, 15)

        # Fill 10 samples (twos). This should wrap.
        indata_2 = np.full((10, 2), 2.0)
        self.spectrogram._callback(indata_2, outdata, 10, None, None)

        self.assertEqual(self.spectrogram.audio_buffer_pos, 5)

        # Check get_latest_samples (20 samples)
        # Should be 10 samples of 1.0 (oldest surviving), then 10 samples of 2.0 (newest)
        latest_20 = self.spectrogram.get_latest_samples(20)
        expected = np.concatenate((np.ones((10, 2)), np.full((10, 2), 2.0)))
        np.testing.assert_array_equal(latest_20, expected)


class TestSpectrogramFFTLogic(unittest.TestCase):
    def get_available_fft_sizes(self, speed_index):
        # Mocking the logic used in SpectrogramWidget
        if speed_index == 0:
            return [str(s) for s in WARMUP_SIZES if s <= 8192]
        else:
            return [str(s) for s in WARMUP_SIZES]

    def test_warmup_sizes_integrity(self):
        """Verify WARMUP_SIZES are as expected."""
        expected = [256, 512, 1024, 2048, 4096, 8192, 16384, 24000, 32768, 48000, 65536]
        self.assertEqual(WARMUP_SIZES, expected)

    def test_fast_speed_fft_sizes(self):
        """Verify that speed 0 (Fast) limits FFT sizes to 8192."""
        sizes = self.get_available_fft_sizes(0)
        self.assertIn("8192", sizes)
        self.assertIn("4096", sizes)
        self.assertNotIn("16384", sizes)

        max_size = max([int(s) for s in sizes])
        self.assertEqual(max_size, 8192)

    def test_slow_speed_fft_sizes(self):
        """Verify that speed > 0 allows larger FFT sizes."""
        for speed in [1, 2, 3]:
            sizes = self.get_available_fft_sizes(speed)
            self.assertIn("65536", sizes)
            max_size = max([int(s) for s in sizes])
            self.assertEqual(max_size, 65536)


class TestSpectrogramProcessing(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MockAudioEngine()
        self.spec = Spectrogram(self.mock_engine)
        self.spec.set_fft_size(1024)

    def test_spectrogram_worker_logic(self):
        """Verify that SpectrogramWorker correctly computes FFT and dB magnitude."""
        # 1000 Hz at 48kHz
        t = np.linspace(0, 1024 / 48000, 1024, endpoint=False)
        freq = 1000
        sine = 0.5 * np.sin(2 * np.pi * freq * t)

        # Create input buffer (stereo)
        raw_data = np.column_stack((sine, sine))

        # Create Worker
        worker = SpectrogramWorker(raw_data, "hann", "Left")

        # Capture result
        result_container = []
        # Mock signal behavior
        worker.signals.result = MagicMock()
        worker.signals.result.emit = lambda res: result_container.append(res)
        # Note: In real app, it's a pyqtSignal. Here we override emit.

        worker.run()

        self.assertEqual(len(result_container), 1)
        mag_db = result_container[0]

        # Check output shape (rfft of 1024 -> 513 bins)
        self.assertEqual(len(mag_db), 513)

        # Check peak frequency
        peak_bin = np.argmax(mag_db)
        peak_freq = peak_bin * (48000 / 1024)

        self.assertTrue(abs(peak_freq - 1000) < 50, f"Expected ~1000Hz, got {peak_freq}Hz")

    def test_spectrogram_worker_stereo_average(self):
        """Verify that average channel mode uses both channels."""
        raw_data = np.zeros((512, 2), dtype=np.float32)
        raw_data[:, 0] = 1.0

        worker = SpectrogramWorker(raw_data, "boxcar", "Average")
        result_container = []
        worker.signals.result = MagicMock()
        worker.signals.result.emit = lambda res: result_container.append(res)

        worker.run()

        self.assertEqual(len(result_container), 1)
        mag_db = result_container[0]
        self.assertGreater(mag_db[0], -10.0)

    def test_buffer_update(self):
        """Verify that add_spectrum updates the ring buffer correctly."""
        self.spec.history_length = 5
        self.spec.reset_buffers()

        frame = np.zeros(self.spec.fft_size // 2 + 1)
        frame[0] = 10.0

        self.spec.add_spectrum(frame)

        # Ptr should be 1
        self.assertEqual(self.spec.spectrogram_ptr, 1)
        self.assertTrue(np.array_equal(self.spec.spectrogram_buffer[0], frame))

        # Add more to wrap around
        for i in range(5):
            frame[0] = i
            self.spec.add_spectrum(frame.copy())

        # Total writes: 6. Buffer 5. Ptr -> 1.
        self.assertEqual(self.spec.spectrogram_ptr, 1)


# Mock Qt for Optimization and Style tests
mock_qt_core = MagicMock()


class MockQObject:
    def __init__(self):
        pass


class MockQWidget:
    def __init__(self, *args, **kwargs):
        pass

    def update(self):
        pass

    def setStyleSheet(self, style):
        pass

    def setLayout(self, layout):
        pass

    def setVisible(self, val):
        pass


class MockQThreadPool:
    def start(self, runnable):
        runnable.run()


mock_qt_core.QObject = MockQObject
mock_qt_core.QRunnable = MockQObject
mock_qt_core.QThreadPool = MockQThreadPool


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
mock_qt_widgets.QComboBox = MagicMock()
mock_qt_widgets.QComboBox().findText.return_value = -1
mock_qt_widgets.QComboBox().currentText.return_value = "8192"

mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": mock_qt_core,
    "PyQt6.QtGui": MagicMock(),
    "PyQt6.QtWidgets": mock_qt_widgets,
    "pyqtgraph": MagicMock(),
}


class TestSpectrogramOptimization(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.dict(sys.modules, mock_modules)
        self.patcher.start()
        # Force re-import of spectrogram module to pick up mocked Qt
        if "src.gui.widgets.spectrogram" in sys.modules:
            del sys.modules["src.gui.widgets.spectrogram"]

    def tearDown(self):
        self.patcher.stop()

    def test_update_spectrogram_medium_mode(self):
        # We need to ensure SpectrogramWidget can be imported with these mocks
        # We also need to re-import Spectrogram to ensure it uses the mocked dependencies
        from src.gui.widgets.spectrogram import SpectrogramWidget, Spectrogram, SpectrogramWorker

        # Patch Worker init to give unique signals per instance
        original_init = SpectrogramWorker.__init__

        def new_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)

            class InstanceSignals:
                result = MockSignal()

            self.signals = InstanceSignals()

        with patch.object(SpectrogramWorker, "__init__", new_init):
            audio_engine = MockAudioEngine()
            module = Spectrogram(audio_engine)
            widget = SpectrogramWidget(module)
            module.audio_buffer[:] = np.random.random(module.audio_buffer.shape)

            module.sweep_speed_index = 1  # Medium, target=4
            module.start_analysis()

            # First update
            widget.update_spectrogram()
            assert module.acc_count == 1
            assert module.accumulator is not None

            # Fourth update (should push)
            widget.update_spectrogram()
            widget.update_spectrogram()
            widget.update_spectrogram()

            assert module.acc_count == 0
            assert module.accumulator is None

    def test_buffer_resize(self):
        from src.gui.widgets.spectrogram import SpectrogramWidget, Spectrogram

        audio_engine = MockAudioEngine()
        module = Spectrogram(audio_engine)
        _ = SpectrogramWidget(module)

        module.start_analysis()

        module.spectrogram_ptr = 10
        module.accumulator = np.zeros(10)
        module.acc_count = 2

        # Change FFT size
        new_size = 1024
        module.set_fft_size(new_size)

        assert module.spectrogram_ptr == 0
        assert module.accumulator is None
        assert module.acc_count == 0


class TestSpectrogramStyle(unittest.TestCase):
    def test_spectrogram_style(self):
        # Heavy patching for style test
        with patch.dict(sys.modules, mock_modules):
            if "src.gui.widgets.spectrogram" in sys.modules:
                del sys.modules["src.gui.widgets.spectrogram"]

            from src.gui.widgets.spectrogram import SpectrogramWidget, Spectrogram
            from src.gui.styles import STYLE_TOGGLE_BTN_DARK, STYLE_TOGGLE_BTN_LIGHT

            mock_audio_engine = MagicMock()
            spectrogram = Spectrogram(mock_audio_engine)

            mock_app = MagicMock()
            mock_theme_manager = MagicMock()
            mock_app.theme_manager = mock_theme_manager
            mock_qt_widgets.QApplication.instance.return_value = mock_app

            mock_theme_manager.get_current_theme.return_value = "light"

            widget = SpectrogramWidget(spectrogram)

            # Test Dark Theme
            widget.apply_theme("dark")
            widget.toggle_btn.setStyleSheet.assert_called_with(STYLE_TOGGLE_BTN_DARK)

            # Test Light Theme
            widget.apply_theme("light")
            widget.toggle_btn.setStyleSheet.assert_called_with(STYLE_TOGGLE_BTN_LIGHT)


class TestSpectrogramColormaps(unittest.TestCase):
    def test_spectrogram_colormaps_exist(self):
        """
        Verify that all colormaps used in the Spectrogram widget exist in pyqtgraph.
        This ensures that future updates to pyqtgraph do not break the widget if presets are removed or renamed.
        """
        # List of colormaps used in SpectrogramWidget.init_ui
        # Note: 'greyscale' was removed in a previous step, so we don't test for it unless it's added back.
        # Current list in code: ["viridis", "plasma", "inferno", "magma", "turbo", "thermal", "flame", "yellowy", "bipolar", "spectrum", "cyclic"]
        used_colormaps = [
            "viridis",
            "plasma",
            "inferno",
            "magma",
            "turbo",
            "thermal",
            "flame",
            "yellowy",
            "bipolar",
            "spectrum",
            "cyclic",
        ]

        missing_colormaps = []
        for cmap in used_colormaps:
            if cmap not in Gradients:
                missing_colormaps.append(cmap)

        assert not missing_colormaps, f"The following colormaps are missing in pyqtgraph: {missing_colormaps}"


class TestSpectrogramLogBuffer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create QApplication if it doesn't exist
        if not QApplication.instance():
            cls.app = QApplication(sys.argv + ["-platform", "offscreen"])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.engine = MockAudioEngine()
        self.module = Spectrogram(self.engine)
        self.widget = SpectrogramWidget(self.module)
        self.module.is_running = True

        # Ensure fast speed so target_frames = 1
        self.module.sweep_speed_index = 0

        # Disable Timer so we can manually trigger update
        self.widget.timer.stop()

    def test_log_buffer_logic(self):
        # Set to Log Mode
        self.widget.scale_combo.setCurrentText("Log")

        # 1. Initial Update
        # Spectrogram buffer size: 500 x (2048//2 + 1) = 500 x 1025
        data_v1 = np.full(1025, -50.0, dtype=np.float32)

        # Call logic directly (bypassing threading/worker)
        self.widget.on_worker_result(data_v1)

        # Verify log_buffer exists and is populated
        self.assertIsNotNone(self.widget.log_spectrogram_buffer)
        self.assertEqual(self.widget.log_spectrogram_buffer.shape[0], self.module.history_length)

        # Check if data was written correctly
        # We need the indices
        indices = self.widget._log_map_cache[1]
        expected_v1 = data_v1[indices]

        ptr_v1 = self.module.spectrogram_ptr
        # Written at previous index
        idx_v1 = (ptr_v1 - 1 + self.module.history_length) % self.module.history_length

        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v1], expected_v1)

        # 2. Incremental Update
        data_v2 = np.full(1025, -20.0, dtype=np.float32)

        # Store state of buffer before update
        buffer_before = self.widget.log_spectrogram_buffer.copy()

        self.widget.on_worker_result(data_v2)

        ptr_v2 = self.module.spectrogram_ptr
        idx_v2 = (ptr_v2 - 1 + self.module.history_length) % self.module.history_length

        # Assert pointer moved
        self.assertEqual(ptr_v2, (ptr_v1 + 1) % self.module.history_length)

        # Assert new data is correct
        expected_v2 = data_v2[indices]
        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v2], expected_v2)

        # Assert OLD data (idx_v1) is UNCHANGED in the log buffer
        # This verifies we didn't wipe the buffer or do something weird
        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v1], buffer_before[idx_v1])

        # 3. Parameter Change (Min Freq) -> Should Reset Buffer
        self.widget.min_freq_spin.setValue(500)  # Change freq
        self.widget.on_freq_range_changed()

        # Trigger update again
        self.widget.on_worker_result(data_v1)

        # Buffer ID might be same (if numpy reuses) or different.
        # But content should be consistent.
        # If parameters changed, indices changed.
        new_indices = self.widget._log_map_cache[1]
        self.assertFalse(np.array_equal(indices, new_indices))

        # Verify the buffer now contains data mapped with NEW indices
        # Since we just did an update, the latest row (idx_v3) should have data_v1[new_indices]
        # But what about previous rows?
        # The optimization strategy says: "If changed, perform a full copy/initialization".
        # So ALL rows should be valid according to the new mapping (from raw buffer).

        # Raw buffer has history. We only added data_v1, data_v2, data_v1.
        # Check idx_v2 (which has data_v2).
        # It should now match data_v2[new_indices]

        # Note: raw buffer at idx_v2 is data_v2 (db).
        # We need to verify that log_buffer[idx_v2] == raw_buffer[idx_v2][new_indices]

        raw_row_v2 = self.module.spectrogram_buffer[idx_v2]
        expected_row_v2_new_map = raw_row_v2[new_indices]

        np.testing.assert_array_almost_equal(self.widget.log_spectrogram_buffer[idx_v2], expected_row_v2_new_map)


if __name__ == "__main__":
    unittest.main()

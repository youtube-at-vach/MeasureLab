import unittest
from unittest.mock import MagicMock, patch
import sys
import importlib
import numpy as np

# -----------------------------------------------------------------------------
# Common Mocks for Widget Tests
# -----------------------------------------------------------------------------

class MockQWidget(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__()
        pass
    def _get_child_mock(self, **kw):
        return MagicMock(**kw)

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.input_sensitivity = 1.0
        self.callbacks = {}

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, cid):
        pass

# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------

class TestOscilloscopeStaticMethods(unittest.TestCase):
    """Tests for static helper methods in Oscilloscope class."""

    def test_interp_crossing_time(self):
        # We need to import Oscilloscope.
        # Ideally we import it normally if dependencies allow.
        # Since we have numpy/scipy installed, it should work.
        from src.gui.widgets.oscilloscope import Oscilloscope

        # Rising crossing
        t = np.array([0.0, 1.0])
        y = np.array([-1.0, 1.0])
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "rising")
        self.assertAlmostEqual(res, 0.5)

        # Falling crossing
        y = np.array([1.0, -1.0])
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "falling")
        self.assertAlmostEqual(res, 0.5)

        # No crossing
        y = np.array([0.5, 1.0])
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "rising")
        self.assertIsNone(res)

        # Multiple crossings (pick first)
        t = np.array([0.0, 1.0, 2.0, 3.0])
        y = np.array([-1.0, 1.0, -1.0, 1.0])
        res = Oscilloscope._interp_crossing_time(t, y, 0.0, "rising")
        self.assertAlmostEqual(res, 0.5)

    def test_estimate_frequency_hz(self):
        from src.gui.widgets.oscilloscope import Oscilloscope
        sr = 48000
        f = 1000.0
        t = np.arange(sr // 10) / sr  # 0.1s
        y = 0.8 * np.sin(2 * np.pi * f * t)
        est = Oscilloscope.estimate_frequency_hz(t, y)
        self.assertIsNotNone(est)
        self.assertLess(abs(est - f), 5.0)

    def test_estimate_rise_fall_times(self):
        from src.gui.widgets.oscilloscope import Oscilloscope
        # Create a clean low->high ramp of 25us so 10-90% should be 20us.
        dt = 1e-6
        t = np.arange(0.0, 200e-6, dt)
        y = np.full_like(t, -1.0)

        t0 = 50e-6
        ramp = 25e-6
        t1 = t0 + ramp
        # Rising ramp
        idx = (t >= t0) & (t <= t1)
        y[idx] = -1.0 + 2.0 * ((t[idx] - t0) / ramp)
        y[t > t1] = 1.0

        # Falling ramp later
        t2 = 120e-6
        t3 = t2 + ramp
        idx2 = (t >= t2) & (t <= t3)
        y[idx2] = 1.0 - 2.0 * ((t[idx2] - t2) / ramp)
        y[t > t3] = -1.0

        rise_s, fall_s, low, high = Oscilloscope.estimate_rise_fall_times_s(t, y)
        self.assertIsNotNone(low)
        self.assertIsNotNone(high)
        self.assertIsNotNone(rise_s)
        self.assertIsNotNone(fall_s)

        self.assertLess(abs(rise_s - 20e-6), 2e-6)
        self.assertLess(abs(fall_s - 20e-6), 2e-6)


class TestOscilloscopeLogic(unittest.TestCase):
    """Tests for Oscilloscope logic (buffers, triggering) without UI."""

    def setUp(self):
        # We need to mock AudioEngine
        self.engine = MockAudioEngine()
        from src.gui.widgets.oscilloscope import Oscilloscope
        self.scope = Oscilloscope(self.engine)
        self.scope.buffer_size = 100
        self.scope.input_data = np.zeros((self.scope.buffer_size, 2))

    def test_get_display_data_basic(self):
        # Pulse at sample 50
        self.scope.input_data[:, 0] = 0.0
        self.scope.input_data[50:55, 0] = 1.0
        self.scope.write_index = 0

        self.scope.trigger_source = 0
        self.scope.trigger_mode = "Normal"
        self.scope.trigger_level = 0.5
        self.scope.trigger_slope = "Rising"

        # Display 10 samples (10ms at 1000Hz sr)
        self.engine.sample_rate = 1000
        window_duration = 0.01

        data = self.scope.get_display_data(window_duration)
        self.assertIsNotNone(data)
        self.assertEqual(len(data), 10)
        self.assertEqual(data[0, 0], 1.0)

    def test_get_display_data_wrap_around(self):
        # Write index at 50
        self.scope.write_index = 50
        # Pulse at logical index 80 -> physical 30
        self.scope.input_data[30:35, 0] = 1.0

        self.scope.trigger_source = 0
        self.scope.trigger_mode = "Normal"
        self.scope.trigger_level = 0.5
        self.scope.trigger_slope = "Rising"

        self.engine.sample_rate = 1000
        window_duration = 0.01

        data = self.scope.get_display_data(window_duration)
        self.assertIsNotNone(data)
        self.assertEqual(len(data), 10)
        self.assertEqual(data[0, 0], 1.0)


class TestOscilloscopeWidgetLogic(unittest.TestCase):
    """Tests for OscilloscopeWidget logic (UI interactions) using mocks."""

    def setUp(self):
        # Patch modules to allow loading Widget without real Qt
        self.patched_modules = {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": MagicMock(),
            "PyQt6.QtGui": MagicMock(),
            "PyQt6.QtWidgets": MagicMock(),
            "pyqtgraph": MagicMock(),
            "sounddevice": MagicMock(),
        }

        # Configure specifics
        self.patched_modules["PyQt6.QtWidgets"].QWidget = MockQWidget
        self.patched_modules["PyQt6.QtCore"].Qt.Orientation.Horizontal = 1

        # Mock QRectF
        def rect_side_effect(x, y, w, h):
            return (x, y, w, h)
        self.patched_modules["PyQt6.QtCore"].QRectF = MagicMock(side_effect=rect_side_effect)
        self.patched_modules["pyqtgraph"].QtCore.QRectF = MagicMock(side_effect=rect_side_effect)

        self.patcher = patch.dict(sys.modules, self.patched_modules)
        self.patcher.start()

        # Reload module
        if "src.gui.widgets.oscilloscope" in sys.modules:
            importlib.reload(sys.modules["src.gui.widgets.oscilloscope"])
        else:
            importlib.import_module("src.gui.widgets.oscilloscope")

        self.osc_module = sys.modules["src.gui.widgets.oscilloscope"]

    def tearDown(self):
        self.patcher.stop()

    def test_slider_sync(self):
        # Setup
        mock_audio_engine = MagicMock()
        mock_audio_engine.calibration.input_sensitivity = 1.0
        oscilloscope = self.osc_module.Oscilloscope(mock_audio_engine)
        widget = self.osc_module.OscilloscopeWidget(oscilloscope)

        # Test Timebase Slider -> Combo
        keys = widget.timebase_keys
        widget.timebase_combo.currentText.return_value = "DIFFERENT"

        idx = 0
        target_key = keys[idx]
        widget.on_timebase_slider_changed(idx)
        widget.timebase_combo.setCurrentText.assert_called_with(target_key)

    def test_persistence_rect_update(self):
        # Setup
        mock_audio_engine = MagicMock()
        mock_audio_engine.sample_rate = 48000
        mock_audio_engine.calibration.input_sensitivity = 1.0

        oscilloscope = self.osc_module.Oscilloscope(mock_audio_engine)
        widget = self.osc_module.OscilloscopeWidget(oscilloscope)

        # Configure mocks to prevent crashes
        widget.cursor_1.value.return_value = 0.0
        widget.cursor_2.value.return_value = 0.0

        # Enable persistence
        oscilloscope.persistence_mode = True
        oscilloscope.heatmap_l = np.zeros((600, 400))
        oscilloscope.heatmap_r = np.zeros((600, 400))
        oscilloscope.is_running = True
        oscilloscope.heatmap_size = (600, 400)

        # Mock logic methods
        oscilloscope.get_display_data = MagicMock(return_value=np.zeros((480, 2)))
        oscilloscope.process_queue = MagicMock()

        # Set timebase
        oscilloscope.timebase = 0.01

        # Update
        widget.update_plot()

        # Verify setRect
        # args: x, y, w, h. y=-1.1, h=2.2 (from VIEW_Y_MIN/MAX in widget code)
        # We expect (0, -1.1, 0.01, 2.2)
        widget.persistence_img.setRect.assert_called_with((0, -1.1, 0.01, 2.2))

if __name__ == '__main__':
    unittest.main()

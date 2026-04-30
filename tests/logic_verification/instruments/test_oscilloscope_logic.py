import unittest
from unittest.mock import MagicMock, patch
import sys
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
        # Allow capturing the callback for testing allocation/data flow
        cid = len(self.callbacks)
        self.callbacks[cid] = callback
        return cid

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

    def test_frequency_estimation_edge_cases(self):
        from src.gui.widgets.oscilloscope import Oscilloscope

        # Insufficient data
        t = np.array([0, 1, 2])
        y = np.array([0, 1, 0])
        self.assertIsNone(Oscilloscope.estimate_frequency_hz(t, y))
        self.assertIsNone(Oscilloscope.estimate_frequency_hz(None, None))

        # No crossings
        sample_rate = 1000
        t = np.arange(100) / sample_rate
        y = np.ones(100)
        self.assertIsNone(Oscilloscope.estimate_frequency_hz(t, y))

        # Exact zero crossings (< 2)
        t = np.array([0, 1, 2, 3, 4], dtype=float)
        y = np.array([-1, 0, 1, 0, -1], dtype=float)
        self.assertIsNone(Oscilloscope.estimate_frequency_hz(t, y))

        # Exact zero crossings (>= 2)
        t = np.arange(10, dtype=float)
        y = np.array([-1, 1, -1, 1, -1, 1, -1, 1, -1, 1], dtype=float)
        est = Oscilloscope.estimate_frequency_hz(t, y)
        self.assertIsNotNone(est)
        self.assertAlmostEqual(est, 0.5, places=6)


class TestOscilloscopeLogic(unittest.TestCase):
    """Tests for Oscilloscope logic (buffers, triggering) without UI."""

    def setUp(self):
        # We need to mock AudioEngine
        self.engine = MockAudioEngine()
        from src.gui.widgets.oscilloscope import Oscilloscope

        self.scope = Oscilloscope(self.engine)
        self.scope.buffer_size = 100
        self.scope.input_data = np.zeros((self.scope.buffer_size * 2, 2))

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
        # Also mirror
        self.scope.input_data[30 + self.scope.buffer_size : 35 + self.scope.buffer_size, 0] = 1.0

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

    def test_get_display_data_trigger_at_wrap_boundary(self):
        # Pulse spans across physical boundary
        # write_index = 50.
        # Logical index 45 to 55 crosses physical 95 -> 4
        # Pulse at logical 48.
        # Physical: (50+48)%100 = 98.
        # 98, 99, 0, 1, 2

        self.scope.write_index = 50
        self.scope.input_data[98, 0] = 1.0
        self.scope.input_data[99, 0] = 1.0
        self.scope.input_data[0, 0] = 1.0
        self.scope.input_data[1, 0] = 1.0
        self.scope.input_data[2, 0] = 1.0
        # Also mirror
        self.scope.input_data[98 + self.scope.buffer_size, 0] = 1.0
        self.scope.input_data[99 + self.scope.buffer_size, 0] = 1.0
        self.scope.input_data[0 + self.scope.buffer_size, 0] = 1.0
        self.scope.input_data[1 + self.scope.buffer_size, 0] = 1.0
        self.scope.input_data[2 + self.scope.buffer_size, 0] = 1.0

        self.scope.trigger_source = 0
        self.scope.trigger_mode = "Normal"
        self.scope.trigger_level = 0.5
        self.scope.trigger_slope = "Rising"

        self.engine.sample_rate = 1000
        window_duration = 0.01  # 10 samples

        data = self.scope.get_display_data(window_duration)

        self.assertIsNotNone(data)
        self.assertEqual(len(data), 10)
        self.assertEqual(data[0, 0], 1.0)

    def test_single_mode_stops_capture(self):
        self.engine.sample_rate = 48000
        self.scope.trigger_source = 0
        self.scope.trigger_slope = "Rising"
        self.scope.trigger_level = 0.0
        self.scope.trigger_mode = "Single"
        self.scope.single_shot_armed = True
        self.scope.single_shot_fired = False

        self.scope.buffer_size = 10000
        self.scope.input_data = np.full((self.scope.buffer_size * 2, 2), -1.0)  # Reset buffer

        # Searches window [7472, 9520] for 48000Hz, 10ms window
        crossing_prev = 7700
        crossing_now = 7701
        self.scope.input_data[crossing_prev, 0] = -0.5
        self.scope.input_data[crossing_now, 0] = 0.5

        window_duration = 0.01  # 10ms
        data = self.scope.get_display_data(window_duration)

        self.assertIsNotNone(data, "Should capture trigger")
        self.assertTrue(self.scope.single_shot_fired, "Should set fired flag")
        self.assertFalse(self.scope.single_shot_armed, "Should disarm")

        # After firing, further calls should not produce new data until re-armed.
        data2 = self.scope.get_display_data(window_duration)
        self.assertIsNone(data2, "Should not capture after firing in Single mode")

    def test_buffer_expansion_preserves_history_as_latest_samples(self):
        self.engine.sample_rate = 100
        self.scope.buffer_size = 8
        self.scope.input_data = np.zeros((self.scope.buffer_size * 2, 2))
        self.scope.write_index = 3

        physical = np.arange(self.scope.buffer_size, dtype=float)
        self.scope.input_data[: self.scope.buffer_size, 0] = physical
        self.scope.input_data[self.scope.buffer_size :, 0] = physical

        self.scope._ensure_buffer_capacity(0.2)

        data = self.scope._get_data_slice(0, self.scope.buffer_size)
        self.assertEqual(self.scope.write_index, 0)
        self.assertTrue(np.all(data[: self.scope.buffer_size - 8, 0] == 0.0))
        self.assertTrue(np.array_equal(data[-8:, 0], np.array([3, 4, 5, 6, 7, 0, 1, 2], dtype=float)))

    def test_long_timebase_keeps_trigger_at_full_resolution(self):
        self.engine.sample_rate = 48000
        window_duration = 1.0

        self.scope._ensure_buffer_capacity(window_duration)
        self.assertGreater(self.scope.buffer_size, 8192)

        self.scope.input_data[:] = -1.0
        self.scope.write_index = 0
        crossing_prev = 4095
        crossing_now = 4096
        self.scope.input_data[crossing_prev, 0] = -0.5
        self.scope.input_data[crossing_now : self.scope.buffer_size, 0] = 0.5
        self.scope.input_data[
            self.scope.buffer_size + crossing_now : self.scope.buffer_size * 2,
            0,
        ] = 0.5

        self.scope.trigger_source = 0
        self.scope.trigger_mode = "Normal"
        self.scope.trigger_level = 0.0
        self.scope.trigger_slope = "Rising"

        data = self.scope.get_display_data(window_duration)

        self.assertIsNotNone(data)
        self.assertEqual(len(data), 48000)
        self.assertEqual(data[0, 0], 0.5)

    def test_measurements_apply_calibration(self):
        # 1. Test with default sensitivity (1.0)
        t = np.linspace(0, 1, 1000)
        data = np.zeros((1000, 2))
        data[:, 0] = 0.5 * np.sin(2 * np.pi * 50 * t)  # Left
        data[:, 1] = 0.2 * np.sin(2 * np.pi * 50 * t)  # Right

        meas = self.scope.get_measurements(data)

        expected_l_rms = 0.5 / np.sqrt(2)
        expected_r_rms = 0.2 / np.sqrt(2)

        self.assertAlmostEqual(meas["l_rms"], expected_l_rms, places=3)
        self.assertAlmostEqual(meas["l_vpp"], 1.0, places=3)  # 0.5 to -0.5 -> 1.0 Vpp
        self.assertAlmostEqual(meas["r_rms"], expected_r_rms, places=3)

        # 2. Test with sensitivity = 2.0 (1.0 FS = 2.0 Volts)
        self.engine.calibration.input_sensitivity = 2.0
        meas_cal = self.scope.get_measurements(data)

        # RMS should double
        self.assertAlmostEqual(meas_cal["l_rms"], expected_l_rms * 2.0, places=3)
        self.assertAlmostEqual(meas_cal["l_vpp"], 2.0, places=3)

    def test_measurements_none_data(self):
        meas = self.scope.get_measurements(None)
        self.assertEqual(meas["l_rms"], 0.0)


class TestOscilloscopeAllocation(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MockAudioEngine()
        from src.gui.widgets.oscilloscope import Oscilloscope

        self.osc = Oscilloscope(self.mock_engine)

    def test_no_allocation_in_callback(self):
        """
        Verify that the Oscilloscope audio callback does not reallocate the input buffer
        or transfer buffer, ensuring zero-allocation in the audio thread.
        """
        self.osc.start_analysis()

        # Verify initial buffer IDs
        initial_transfer_id = id(self.osc.transfer_buffer)
        initial_internal_buffer_id = id(self.osc.transfer_buffer._buffer)

        # Get the registered callback
        # In this mock setup, we assume start_analysis calls register_callback
        # We need to manually verify if callback was registered in mock
        self.assertTrue(len(self.mock_engine.callbacks) > 0, "Callback should be registered")
        cb = self.mock_engine.callbacks[0]

        # Create dummy audio data
        frames = 1024
        indata = np.random.rand(frames, 2).astype(np.float32)
        outdata = np.zeros_like(indata)

        # Run callback multiple times
        for _ in range(10):
            cb(indata, outdata, frames, 0.0, None)

            # Verify transfer buffer object hasn't changed (reallocation check)
            self.assertEqual(
                id(self.osc.transfer_buffer),
                initial_transfer_id,
                "Transfer buffer should not be reallocated in callback",
            )
            self.assertEqual(
                id(self.osc.transfer_buffer._buffer),
                initial_internal_buffer_id,
                "Internal buffer should not be reallocated",
            )

        # Verify that data was actually written to transfer buffer
        # Write count should be 10 * 1024
        self.assertEqual(self.osc.transfer_buffer._write_index, 10 * 1024)


class TestOscilloscopeDataFlow(unittest.TestCase):
    def setUp(self):
        self.mock_engine = MockAudioEngine()
        from src.gui.widgets.oscilloscope import Oscilloscope

        self.osc = Oscilloscope(self.mock_engine)

    def test_oscilloscope_queue_data_flow(self):
        """
        Verify that data flows from callback -> transfer_buffer -> process_queue -> input_data.
        """
        self.osc.start_analysis()

        # Verify buffer is empty/reset
        self.assertEqual(self.osc.transfer_buffer._write_index, 0)
        self.assertEqual(self.osc.transfer_buffer._read_index, 0)

        # Get the registered callback
        self.assertTrue(len(self.mock_engine.callbacks) > 0)
        cb = self.mock_engine.callbacks[0]

        # Create test data
        frames = 100
        indata = np.ones((frames, 2), dtype=np.float32) * 0.5
        outdata = np.zeros_like(indata)

        # Call callback
        cb(indata, outdata, frames, 0.0, None)

        # Verify data is in transfer buffer
        self.assertEqual(self.osc.transfer_buffer._write_index, 100)
        self.assertEqual(self.osc.transfer_buffer._read_index, 0)

        # Check data content in transfer buffer
        # transfer_buffer is large, we check the first 100 samples
        self.assertTrue(np.allclose(self.osc.transfer_buffer._buffer[0:100], 0.5))

        # Verify input_data is still zero (before process_queue)
        self.assertTrue(np.all(self.osc.input_data == 0))

        # Call process_queue
        self.osc.process_queue()

        # Verify transfer buffer is read
        self.assertEqual(self.osc.transfer_buffer._read_index, 100)

        # Verify input_data has data
        self.assertEqual(self.osc.write_index, 100)
        self.assertTrue(np.allclose(self.osc.input_data[0:100], 0.5))
        # Also mirror
        self.assertTrue(np.allclose(self.osc.input_data[self.osc.buffer_size : self.osc.buffer_size + 100], 0.5))
        # The rest should be 0
        self.assertTrue(np.all(self.osc.input_data[100 : self.osc.buffer_size] == 0))
        self.assertTrue(np.all(self.osc.input_data[self.osc.buffer_size + 100 :] == 0))


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
            del sys.modules["src.gui.widgets.oscilloscope"]

        # We don't import here, we let test methods import to trigger mocks

    def tearDown(self):
        self.patcher.stop()

    def test_slider_sync(self):
        from src.gui.widgets.oscilloscope import Oscilloscope, OscilloscopeWidget

        # Setup
        mock_audio_engine = MagicMock()
        mock_audio_engine.calibration.input_sensitivity = 1.0
        oscilloscope = Oscilloscope(mock_audio_engine)
        widget = OscilloscopeWidget(oscilloscope)

        # Test Timebase Slider -> Combo
        keys = widget.timebase_keys
        widget.timebase_combo.currentText.return_value = "DIFFERENT"

        idx = 0
        target_key = keys[idx]
        widget.on_timebase_slider_changed(idx)
        widget.timebase_combo.setCurrentText.assert_called_with(target_key)

    def test_persistence_rect_update(self):
        from src.gui.widgets.oscilloscope import Oscilloscope, OscilloscopeWidget

        # Setup
        mock_audio_engine = MagicMock()
        mock_audio_engine.sample_rate = 48000
        mock_audio_engine.calibration.input_sensitivity = 1.0

        oscilloscope = Oscilloscope(mock_audio_engine)
        widget = OscilloscopeWidget(oscilloscope)

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

    def test_update_plot_measures_full_resolution_but_plots_decimated_data(self):
        from src.gui.widgets.oscilloscope import Oscilloscope, OscilloscopeWidget

        mock_audio_engine = MagicMock()
        mock_audio_engine.sample_rate = 48000
        mock_audio_engine.calibration.input_sensitivity = 1.0

        oscilloscope = Oscilloscope(mock_audio_engine)
        widget = OscilloscopeWidget(oscilloscope)
        widget.chk_wave_meas.isChecked.return_value = False
        widget.chk_cursors.isChecked.return_value = False

        data = np.zeros((48000, 2))
        data[12345, 0] = 1.0
        oscilloscope.is_running = True
        oscilloscope.timebase = 1.0
        oscilloscope.get_display_data = MagicMock(return_value=data)
        oscilloscope.process_queue = MagicMock()
        oscilloscope.get_measurements = MagicMock(return_value={"l_rms": 0.0, "l_vpp": 1.0, "r_rms": 0.0, "r_vpp": 0.0})

        widget.update_plot()

        measured_data = oscilloscope.get_measurements.call_args.args[0]
        self.assertEqual(len(measured_data), 48000)

        plot_t, plot_l = widget.curve_l.setData.call_args.args
        self.assertLessEqual(len(plot_t), oscilloscope.MAX_DISPLAY_SAMPLES)
        self.assertLessEqual(len(plot_l), oscilloscope.MAX_DISPLAY_SAMPLES)


if __name__ == "__main__":
    unittest.main()

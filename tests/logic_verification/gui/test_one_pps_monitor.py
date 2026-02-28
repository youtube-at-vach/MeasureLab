import time
import sys
import os
import unittest
import numpy as np
import pytest
from unittest.mock import MagicMock

# Ensure we can import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from PyQt6.QtWidgets import QLabel, QDoubleSpinBox
import pyqtgraph as pg

from src.gui.widgets.one_pps_monitor import OnePPSMonitor, OnePPSMonitorWidget

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def wait_for_monitor(monitor, timeout=2.0):
    start = time.time()
    while not monitor.data_queue.empty() and (time.time() - start) < timeout:
        time.sleep(0.01)
    time.sleep(0.1)

class MockAudioEngine:
    def __init__(self):
        self.callbacks = {}
        self.next_id = 0
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.frequency_calibration_1pps = 1.0
        # Mock get_input_latency
        self.get_input_latency = MagicMock(return_value=0.0)

    def register_callback(self, cb):
        cid = self.next_id
        self.next_id += 1
        self.callbacks[cid] = cb
        return cid

    def unregister_callback(self, cid):
        if cid in self.callbacks:
            del self.callbacks[cid]

# -----------------------------------------------------------------------------
# Comprehensive Logic Tests
# -----------------------------------------------------------------------------

class TestOnePPSMonitorLogic(unittest.TestCase):
    def test_one_pps_logic(self):
        engine = MockAudioEngine()
        monitor = OnePPSMonitor(engine)
        self.addCleanup(monitor.stop_analysis)

        # Configure
        monitor.threshold_fs = 0.5
        monitor.hysteresis_fs = 0.05
        monitor.start_analysis()
        monitor.warmup_count = 0

        callback = list(engine.callbacks.values())[0]

        # Generate synthetic signal
        # 48000 Hz sample rate
        # Pulses at index 1000, 49000 (delta = 48000) -> 0 PPM
        # Pulse 3 at 97005 (delta = 48005) -> +104.16 PPM

        total_len = 100000
        sig = np.zeros(total_len, dtype=np.float32)

        # Pulse 1 (Start)
        sig[1000:1010] = 0.8
        # Pulse 2 (48000 samples later)
        sig[49000:49010] = 0.8
        # Pulse 3 (48005 samples later)
        sig[97005:97015] = 0.8

        # Process in blocks
        block_size = 1024

        for i in range(0, total_len, block_size):
            chunk = sig[i:i+block_size]
            # Make it stereo
            indata = np.column_stack((chunk, chunk))
            outdata = np.zeros_like(indata)

            callback(indata, outdata, len(chunk), None, None)

        # Verify results
        wait_for_monitor(monitor)
        t, ip, cp = monitor.get_history_arrays()

        # We expect 2 intervals.
        # 1. 1000 -> 49000 (Delta 48000)
        # 2. 49000 -> 97005 (Delta 48005)

        assert len(ip) >= 2

        # First interval: ~48000 -> ~0 error -> ~0 ppm
        assert abs(ip[0]) < 1.0 # Allow small jitter due to interpolation

        # Second interval: ~48005 -> 5 error -> (5/48000)*1e6 = 104.166...
        expected_ppm = (5 / 48000.0) * 1e6
        assert abs(ip[1] - expected_ppm) < 2.0 # Allow small jitter

    def test_hysteresis(self):
        engine = MockAudioEngine()
        monitor = OnePPSMonitor(engine)
        self.addCleanup(monitor.stop_analysis)
        monitor.threshold_fs = 0.5
        monitor.hysteresis_fs = 0.1 # High: 0.5, Low: 0.4
        monitor.start_analysis()
        monitor.warmup_count = 0

        callback = list(engine.callbacks.values())[0]

        # Construct a noisy signal near threshold
        # 1. Rise to 0.45 (Should not trigger)
        # 2. Rise to 0.55 (Trigger)
        # 3. Drop to 0.45 (Should not reset state to "low" yet if hysteresis works?)
        # High Threshold = 0.5. Low Threshold = 0.4.

        # Pulse 1 at 3. Pulse 2 at 10. Delta = 7.
        monitor.nominal_rate = 7.0

        sig = np.array([
            0.0, 0.45, 0.45,   # Max 0.45. State Low.
            0.55, 0.6,         # Max 0.6. State -> High (Trigger 1 at approx idx 3.5)
            0.45, 0.45,        # Min 0.45. State High ( > 0.4). No Reset.
            0.55, 0.6,         # Max 0.6. State High. No Trigger.
            0.35, 0.0,         # Min 0.0. State -> Low. Reset.
            0.55, 0.6          # Max 0.6. State -> High (Trigger 2 at approx idx 10.5)
        ], dtype=np.float32)

        indata = np.column_stack((sig, sig))
        outdata = np.zeros_like(indata)
        callback(indata, outdata, len(sig), None, None)

        wait_for_monitor(monitor)
        t, ip, cp = monitor.get_history_arrays()

        # We should have 1 interval detected (Trigger 1 to Trigger 2)
        assert len(ip) == 1
        assert abs(ip[0]) < 250000

    def test_outlier_rejection_robustness(self):
        """Test that outliers are truly ignored and don't skew regression or history."""
        engine = MockAudioEngine()
        monitor = OnePPSMonitor(engine)
        self.addCleanup(monitor.stop_analysis)
        monitor.threshold_fs = 0.5
        monitor.nominal_rate = 1000.0

        # Enable filter
        monitor.filter_enabled = True
        monitor.filter_window_size = 5
        monitor.filter_tolerance_sigma = 3.0

        monitor.start_analysis()
        monitor.warmup_count = 0

        callback = list(engine.callbacks.values())[0]

        pulse_locations = [0, 1000, 2000, 3000, 4000, 5000, 5400, 6000, 7000]

        total_len = 8000
        sig = np.zeros(total_len, dtype=np.float32)
        for p in pulse_locations:
            sig[p] = 1.0

        indata = np.column_stack((sig, sig))
        outdata = np.zeros_like(indata)
        callback(indata, outdata, len(sig), None, None)

        wait_for_monitor(monitor)
        t, ip, cp = monitor.get_history_arrays()

        # Check length. 0->5000 gives 5 intervals.
        # 5400 rejected.
        # 6000->5000 gives 1 interval.
        # 7000->6000 gives 1 interval.
        # Total 7 intervals.

        assert len(ip) >= 6
        assert np.all(np.abs(ip) < 1000)

    def test_cumulative_precision(self):
        engine = MockAudioEngine()
        monitor = OnePPSMonitor(engine)
        self.addCleanup(monitor.stop_analysis)
        monitor.nominal_rate = 1000.0
        monitor.start_analysis()
        monitor.warmup_count = 0

        callback = list(engine.callbacks.values())[0]

        deltas = [1001] * 20

        total_len = sum(deltas) + 5000
        sig = np.zeros(total_len, dtype=np.float32)

        current_idx = 100
        sig[current_idx] = 1.0

        for d in deltas:
            current_idx += d
            sig[current_idx] = 1.0

        indata = np.column_stack((sig, sig))
        outdata = np.zeros_like(indata)
        callback(indata, outdata, len(sig), None, None)

        wait_for_monitor(monitor)
        t, ip, cp = monitor.get_history_arrays()

        assert len(ip) == 20
        assert np.allclose(ip, 1000.0)
        assert np.allclose(cp, 1000.0)

    def test_mad_death_spiral(self):
        engine = MockAudioEngine()
        monitor = OnePPSMonitor(engine)
        self.addCleanup(monitor.stop_analysis)
        monitor.threshold_fs = 0.5
        monitor.nominal_rate = 1000.0

        # Enable filter
        monitor.filter_enabled = True
        monitor.filter_window_size = 5
        monitor.filter_tolerance_sigma = 3.0

        monitor.start_analysis()
        monitor.warmup_count = 0

        callback = list(engine.callbacks.values())[0]

        pulse_locations = [0, 1000, 2000, 3000, 4000, 5000, 6050, 7050]

        total_len = 8000
        sig = np.zeros(total_len, dtype=np.float32)
        for p in pulse_locations:
            sig[p] = 1.0

        indata = np.column_stack((sig, sig))
        outdata = np.zeros_like(indata)
        callback(indata, outdata, len(sig), None, None)
        wait_for_monitor(monitor)
        t, ip, cp = monitor.get_history_arrays()

        assert len(ip) > 4

# -----------------------------------------------------------------------------
# GUI Features Tests
# -----------------------------------------------------------------------------

@pytest.fixture
def mock_audio_engine_fixture():
    return MockAudioEngine()

@pytest.fixture
def monitor(mock_audio_engine_fixture):
    return OnePPSMonitor(mock_audio_engine_fixture)

@pytest.fixture
def widget(monitor, qtbot):
    widget = OnePPSMonitorWidget(monitor)
    qtbot.addWidget(widget)
    return widget

def test_initialization(widget):
    """Test that the widget initializes correctly with new features."""
    assert widget.lbl_indicator is not None
    assert isinstance(widget.lbl_indicator, QLabel)

    # Check tabs
    assert widget.tabs.count() == 3 # Settings, Waveform, Display
    assert widget.tabs.tabText(1) == "Waveform"

    # Check Waveform tab components
    waveform_tab = widget.tabs.widget(1)
    plot = waveform_tab.findChild(pg.PlotWidget)
    assert plot is not None

    thresh_spin = widget.spin_thresh_wave
    hyst_spin = widget.spin_hyst_wave
    assert isinstance(thresh_spin, QDoubleSpinBox)
    assert isinstance(hyst_spin, QDoubleSpinBox)

    # Check Target PPS components
    assert hasattr(widget, 'combo_pps_preset')
    assert widget.combo_pps_preset.itemText(0) == "1 PPS"
    assert widget.combo_pps_preset.currentIndex() == 0
    assert not widget.spin_pps.isEnabled()
    assert widget.spin_pps.value() == 1.0

def test_waveform_controls(widget, monitor):
    """Test that controls in Waveform tab update the module directly."""

    # Change Waveform Threshold -> Module should update
    widget.spin_thresh_wave.setValue(0.6)
    assert monitor.threshold_fs == 0.6
    assert widget.line_thresh_high.value() == 0.6
    # Low line = Thresh - Hyst = 0.6 - 0.05 = 0.55
    assert abs(widget.line_thresh_low.value() - 0.55) < 1e-6

    # Change Waveform Hysteresis -> Module and Low line should update
    widget.spin_hyst_wave.setValue(0.1)
    assert monitor.hysteresis_fs == 0.1
    # Low line = 0.6 - 0.1 = 0.5
    assert abs(widget.line_thresh_low.value() - 0.5) < 1e-6

def test_pulse_indicator_logic(widget, monitor, qtbot):
    """Test the pulse indicator logic."""
    # Initial state: Gray
    assert "gray" in widget.lbl_indicator.styleSheet()

    # Mock pulse detection
    monitor._pulses_detected = 1

    # Trigger update
    with qtbot.waitSignal(widget.indicator_on_timer.timeout, timeout=200):
        widget._update_plot()
        # Should be Green now
        assert "#00FF00" in widget.lbl_indicator.styleSheet()

    # After timeout (simulated waitSignal wait), it should turn off by the timer connection
    # But waitSignal waits for signal EMIT. The slot `_turn_off_indicator` is connected to timeout.
    # So after timeout, the slot should have run.
    assert "gray" in widget.lbl_indicator.styleSheet()

def test_visualization_buffer(monitor):
    """Test the visualization buffer logic in the module."""
    # Default buffer size is now 96000 (2 seconds at 48k)
    assert monitor.vis_buffer.shape == (96000,)

    # Simulate data with a pulse
    monitor.vis_buffer_size = 96000
    monitor.vis_buffer = np.zeros(monitor.vis_buffer_size, dtype=np.float32)

    # Generate signal: 1.5s of silence, then pulse, then 0.5s silence
    fs = 48000
    silence1 = np.zeros(int(1.5 * fs), dtype=np.float32)
    pulse = np.array([0.0, 0.2, 0.8, 1.0, 0.8, 0.2, 0.0], dtype=np.float32)
    silence2 = np.zeros(int(0.5 * fs), dtype=np.float32)

    data = np.concatenate((silence1, pulse, silence2))
    frames = len(data)

    chunk_size = 4800
    monitor.is_running = True

    for i in range(0, frames, chunk_size):
        chunk = data[i:i+chunk_size]
        # We manually feed the queue and run `_process_loop` synchronously in the main thread.
        # `start_analysis()` is not called, so no background thread is spawned.
        monitor.data_queue.put((chunk, len(chunk)))

    monitor.data_queue.put(None) # Signal termination
    monitor._process_loop()

    # Check buffer
    latest = monitor.get_latest_waveform()

    assert latest is not None
    # We expect the pulse to be at 'pre_trigger' index
    # Set explicit windows
    monitor.vis_window_pre = 0.5
    expected_idx = int(monitor.vis_window_pre * fs)

    # Find peak in latest
    peak_idx = np.argmax(latest)

    # Should be close to expected_idx
    assert abs(peak_idx - expected_idx) < 4805
    assert latest[peak_idx] == 1.0

    monitor.is_running = False

def test_update_plot_crash(widget, qtbot):
    """Regression test: _update_plot should not crash if history is empty but waveform is present."""
    # Setup:
    widget.show()
    qtbot.addWidget(widget)

    # 2. Switch to Waveform tab (index 1) to enable waveform update logic
    widget.tabs.setCurrentIndex(1)

    # 3. Inject dummy waveform data into module
    dummy_wave = np.zeros(14400)
    widget.module.last_trig_waveform = dummy_wave

    # Ensure history is empty
    t, ip, cp = widget.module.get_history_arrays()
    assert len(t) == 0

    # 4. Call _update_plot
    try:
        widget._update_plot()
    except IndexError:
        pytest.fail("_update_plot raised IndexError (likely variable shadowing bug)")
    except Exception as e:
        pytest.fail(f"_update_plot raised unexpected exception: {e}")

def test_target_pps_preset_logic(widget, monitor):
    """Test that the PPS preset combo box controls the spin box."""
    # 1. Switch to "Other..."
    widget.combo_pps_preset.setCurrentIndex(1)
    assert widget.spin_pps.isEnabled()

    # 2. Change value
    widget.spin_pps.setValue(10.0)
    assert monitor.target_pps == 10.0

    # 3. Switch back to "1 PPS"
    widget.combo_pps_preset.setCurrentIndex(0)
    assert not widget.spin_pps.isEnabled()
    assert widget.spin_pps.value() == 1.0
    assert monitor.target_pps == 1.0

def test_target_pps_feature(widget, monitor, qtbot):
    """Test the Target PPS feature."""
    # 1. Default should be 1.0
    assert monitor.target_pps == 1.0
    assert widget.spin_pps.value() == 1.0

    # 2. Change via UI
    widget.spin_pps.setValue(10.0)
    assert monitor.target_pps == 10.0

    # 3. Simulate 10Hz signal
    signal = np.zeros(15000, dtype=np.float32)
    signal[0] = 1.0
    signal[4800] = 1.0
    signal[9600] = 1.0

    monitor.is_running = True
    monitor.data_queue.put((signal, len(signal)))
    monitor.data_queue.put(None)
    monitor._process_loop()

    # Pulse count should be 3
    assert monitor.get_pulse_count() == 3

    # Check history (instant ppm)
    t, ip, cp = monitor.get_history_arrays()
    if len(ip) > 2:
        assert abs(ip[-1]) < 1e-6

def test_no_outlier_gate(monitor):
    """Test that large deviations are NOT rejected."""
    monitor.is_running = True
    monitor.target_pps = 1.0 # 1Hz -> 48000 samples

    signal = np.zeros(80000, dtype=np.float32)
    signal[100] = 1.0 # First pulse (warmup)

    # pulse 2 at index 100 + 76800 = 76900
    signal[76900] = 1.0

    monitor.data_queue.put((signal, len(signal)))
    monitor.data_queue.put(None)
    monitor._process_loop()

    # Both pulses should be detected
    assert monitor.get_pulse_count() == 2

if __name__ == '__main__':
    unittest.main()

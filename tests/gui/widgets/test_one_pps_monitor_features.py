
import pytest
import numpy as np
from PyQt6.QtWidgets import QLabel, QDoubleSpinBox
import pyqtgraph as pg
from unittest.mock import MagicMock

from src.gui.widgets.one_pps_monitor import OnePPSMonitor, OnePPSMonitorWidget
from src.core.audio_engine import AudioEngine

@pytest.fixture
def mock_audio_engine():
    engine = MagicMock(spec=AudioEngine)
    engine.sample_rate = 48000
    engine.calibration = MagicMock()
    engine.calibration.frequency_calibration_1pps = 1.0
    return engine

@pytest.fixture
def monitor(mock_audio_engine):
    return OnePPSMonitor(mock_audio_engine)

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
    # We need enough data to fill pre-trigger and post-trigger
    # 2 seconds of data to be safe (96000 samples)
    monitor.vis_buffer_size = 96000
    monitor.vis_buffer = np.zeros(monitor.vis_buffer_size, dtype=np.float32)
    
    # Generate signal: 1.5s of silence, then pulse, then 0.5s silence
    fs = 48000
    silence1 = np.zeros(int(1.5 * fs), dtype=np.float32)
    pulse = np.array([0.0, 0.2, 0.8, 1.0, 0.8, 0.2, 0.0], dtype=np.float32) 
    silence2 = np.zeros(int(0.5 * fs), dtype=np.float32)
    
    data = np.concatenate((silence1, pulse, silence2))
    frames = len(data)
    
    # We need to feed it in chunks to simulate real-time and allow trigger logic to work
    # Feed 4800 frames at a time
    chunk_size = 4800
    monitor.is_running = True
    
    for i in range(0, frames, chunk_size):
        chunk = data[i:i+chunk_size]
        monitor.data_queue.put((chunk, len(chunk)))
        
    monitor.data_queue.put(None) # Signal termination
    monitor._process_loop() 
    
    # Check buffer
    latest = monitor.get_latest_waveform()
    
    assert latest is not None
    # We expect the pulse to be at 'pre_trigger' index
    # vis_window_pre = 0.1s = 4800 samples
    expected_idx = int(monitor.vis_window_pre * fs)
    
    # Find peak in latest
    peak_idx = np.argmax(latest)
    
    # Should be close to expected_idx
    # The extraction logic is precise, so it should be exactly or very close depending on rounding
    assert abs(peak_idx - expected_idx) < 5 
    assert latest[peak_idx] == 1.0

    monitor.is_running = False

def test_update_plot_crash(widget, qtbot):
    """Regression test: _update_plot should not crash if history is empty but waveform is present."""
    # Setup: 
    # 1. Widget is shown (tabs visible)
    widget.show()
    qtbot.addWidget(widget)
    
    # 2. Switch to Waveform tab (index 1) to enable waveform update logic
    widget.tabs.setCurrentIndex(1)
    
    # 3. Inject dummy waveform data into module
    # We need to mock get_latest_waveform to return something valid
    # And get_history_arrays to return EMPTY arrays (which is default state)
    
    # Creating a dummy waveform
    dummy_wave = np.zeros(14400)
    widget.module.last_trig_waveform = dummy_wave
    
    # Ensure history is empty (it is by default new module)
    t, ip, cp = widget.module.get_history_arrays()
    assert len(t) == 0
    
    # 4. Call _update_plot
    try:
        widget._update_plot()
    except IndexError:
        pytest.fail("_update_plot raised IndexError (likely variable shadowing bug)")
    except Exception as e:
        pytest.fail(f"_update_plot raised unexpected exception: {e}")

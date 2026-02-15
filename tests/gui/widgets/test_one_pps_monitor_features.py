
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

def test_control_synchronization(widget, monitor):
    """Test that controls in Settings and Waveform tabs are synchronized."""
    
    # Change Settings -> Waveform should update
    widget.spin_thresh.setValue(0.6)
    assert widget.spin_thresh_wave.value() == 0.6
    assert monitor.threshold_fs == 0.6
    
    widget.spin_hyst.setValue(0.1)
    assert widget.spin_hyst_wave.value() == 0.1
    assert monitor.hysteresis_fs == 0.1
    
    # Change Waveform -> Settings should update
    widget.spin_thresh_wave.setValue(0.4)
    assert widget.spin_thresh.value() == 0.4
    assert monitor.threshold_fs == 0.4
    
    widget.spin_hyst_wave.setValue(0.02)
    assert widget.spin_hyst.value() == 0.02
    assert monitor.hysteresis_fs == 0.02

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
    assert monitor.vis_buffer.shape == (48000,)
    
    # Simulate data
    data = np.ones(100, dtype=np.float32)
    frames = 100
    
    monitor.data_queue.put((data, frames))
    monitor.data_queue.put(None) # Signal termination
    monitor.is_running = True
    monitor._process_loop() # Run loop (will process data then break on None)
    
    # Check buffer
    latest = monitor.get_latest_waveform()
    # Should have 100 ones at the end (or near end depending on implementation roll)
    # The implementation rolls so oldest is at 0.
    # So newest data should be at the end.
    assert np.all(latest[-100:] == 1.0)
    assert latest[0] == 0.0

    monitor.is_running = False

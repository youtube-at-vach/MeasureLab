import os
import sys
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDoubleSpinBox

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.core.audio_engine import AudioEngine
from src.core.comparison_manager import ComparisonManager, ComparisonTrace, AxisMetadata
from src.gui.widgets.plot_comparer import PlotComparer, PlotComparerWidget


@pytest.fixture
def clean_manager():
    manager = ComparisonManager.instance()
    manager.clear_all_traces()
    yield manager
    manager.clear_all_traces()


def test_plot_comparer_widget_initialization(qtbot, clean_manager):
    # Mock audio engine
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)

    # Initially tree widget should be empty
    assert widget.tree_widget.topLevelItemCount() == 0
    # Master toggles container should be hidden
    assert widget.master_toggles_container.isHidden()


def test_plot_comparer_receives_data_and_updates_ui(qtbot, clean_manager):
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)

    # Create dummy trace with primary (Gain) and secondary (Phase) data
    trace = ComparisonTrace(
        id="t1",
        name="Mock Sweep",
        source_module="Network Analyzer",
        timestamp="2026-05-24T12:00:00",
        plot_type="frequency_response",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", True),
        y_axis=AxisMetadata("gain", "dB", "dB", False),
        y2_axis=AxisMetadata("phase", "deg", "deg", False),
        x_data=[10.0, 100.0, 1000.0],
        y_data=[1.0, 2.0, 3.0],
        y2_data=[10.0, 20.0, 30.0],
    )

    # Add trace to comparison manager
    clean_manager.add_trace(trace)

    # Tree widget should update with 1 top-level parent
    assert widget.tree_widget.topLevelItemCount() == 1
    parent_item = widget.tree_widget.topLevelItem(0)
    assert "Mock Sweep" in parent_item.text(0)
    assert parent_item.checkState(0) == Qt.CheckState.Checked

    # Check child nodes for parameters and adjustments
    # Children:
    # 0: Gain (dB)
    # 1: Phase (deg)
    # 2: Gain Offset
    # 3: Time Shift
    assert parent_item.childCount() == 4
    child_y = parent_item.child(0)
    child_y2 = parent_item.child(1)
    child_offset = parent_item.child(2)
    child_shift = parent_item.child(3)

    assert "Gain" in child_y.text(0)
    assert "Phase" in child_y2.text(0)
    assert "Gain Offset" in child_offset.text(0)
    assert "Frequency Shift" in child_shift.text(0)

    # Check Y-axis mapping comboboxes are loaded correctly
    combo_y = widget.tree_widget.itemWidget(child_y, 1)
    combo_y2 = widget.tree_widget.itemWidget(child_y2, 1)
    assert combo_y is not None
    assert combo_y2 is not None
    assert combo_y.currentText() == "Y1"
    assert combo_y2.currentText() == "Y2"

    # Check Inline adjustment spin boxes
    spin_offset = widget.tree_widget.itemWidget(child_offset, 1)
    spin_shift = widget.tree_widget.itemWidget(child_shift, 1)
    assert isinstance(spin_offset, QDoubleSpinBox)
    assert isinstance(spin_shift, QDoubleSpinBox)
    assert spin_offset.value() == 0.0
    assert spin_shift.value() == 0.0

    # Modify adjustments via inline SpinBoxes
    spin_offset.setValue(10.0)
    spin_shift.setValue(0.5)

    assert widget.trace_settings["t1"]["offset_db"] == 10.0
    assert widget.trace_settings["t1"]["shift"] == 0.5

    # Modify Y-axis selection and ensure settings are updated
    combo_y.setCurrentText("Y2")
    assert widget.trace_settings["t1"]["y_axis_choice"] == "Y2"

    # Re-draw shouldn't crash
    widget.replot()
    assert "t1" in widget.curve_items

    # 4. Test Parameter Master Toggles (Approach A)
    assert not widget.master_toggles_container.isHidden()
    assert "gain" in widget.master_toggles_checkboxes
    assert "phase" in widget.master_toggles_checkboxes

    cb_gain = widget.master_toggles_checkboxes["gain"]
    cb_phase = widget.master_toggles_checkboxes["phase"]

    assert cb_gain.isChecked()
    assert cb_phase.isChecked()

    # Toggle off Phase from the master checkbox
    cb_phase.setChecked(False)

    # Check that "phase" child checkstate inside the tree is synchronized to Unchecked
    assert child_y2.checkState(0) == Qt.CheckState.Unchecked
    assert widget.trace_settings["t1"]["y2_visible"] is False

    # Toggle off Gain child item manually inside the tree
    child_y.setCheckState(0, Qt.CheckState.Unchecked)
    widget.on_item_changed(child_y, 0)

    # Since all children (Gain and Phase) are now unchecked, the parent trace should become unchecked
    assert parent_item.checkState(0) == Qt.CheckState.Unchecked
    assert widget.trace_settings["t1"]["visible"] is False

    # Also, since all Gain sub-nodes are unchecked, the master "Gain" toggle should auto-uncheck
    assert cb_gain.isChecked() is False

    # Test Plot Type Filter
    widget.filter_combo.setCurrentIndex(2)  # Time Series (index 2)
    assert widget.tree_widget.topLevelItemCount() == 0  # Our frequency response sweep is filtered out
    assert widget.master_toggles_container.isHidden()  # Toggles should hide since no active traces

    widget.filter_combo.setCurrentIndex(0)  # All (index 0)
    assert widget.tree_widget.topLevelItemCount() == 1  # Should reappear
    assert not widget.master_toggles_container.isHidden()


def test_spectrum_analyzer_comparable_data(qtbot):
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget
    import numpy as np

    engine = AudioEngine()
    module = SpectrumAnalyzer(engine)
    widget = SpectrumAnalyzerWidget(module)
    qtbot.addWidget(widget)

    # When no data is cached, it should return an empty list
    assert widget.get_comparable_data() == []

    # Mock caching data (Single Mode)
    widget.last_freqs = np.array([20.0, 100.0, 1000.0])
    widget.last_mags = np.array([-10.0, -20.0, -30.0])

    traces = widget.get_comparable_data()
    assert len(traces) == 1
    trace = traces[0]
    assert trace.source_module == "Spectrum Analyzer"
    assert trace.plot_type == "spectrum"
    assert trace.x_axis.dimension == "frequency"
    assert trace.x_axis.is_log is True
    assert trace.y_axis.display_unit == "dBFS"
    assert trace.x_data == [20.0, 100.0, 1000.0]
    assert trace.y_data == [-10.0, -20.0, -30.0]

    # Mock caching data (Dual Mode)
    module.analysis_mode = "Spectrum"
    module.channel_mode = "Dual"
    widget.last_mags = np.column_stack(([-10.0, -20.0, -30.0], [-15.0, -25.0, -35.0]))

    traces = widget.get_comparable_data()
    assert len(traces) == 2
    assert " - L " in traces[0].name
    assert " - R " in traces[1].name
    assert traces[0].y_data == [-10.0, -20.0, -30.0]
    assert traces[1].y_data == [-15.0, -25.0, -35.0]


def test_plot_comparer_log_axis_for_spectrum(qtbot, clean_manager):
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)

    # Create dummy spectrum trace
    trace = ComparisonTrace(
        id="t2",
        name="Mock Spectrum",
        source_module="Spectrum Analyzer",
        timestamp="2026-05-24T12:00:00",
        plot_type="spectrum",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", True),
        y_axis=AxisMetadata("voltage", "FS", "dBFS", False),
        x_data=[20.0, 100.0, 1000.0],
        y_data=[-10.0, -20.0, -30.0],
    )

    clean_manager.add_trace(trace)
    widget.replot()

    # Log mode X should be enabled
    assert widget.is_log_x is True


def test_plot_comparer_dynamic_shifts(qtbot, clean_manager):
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)

    # 1. Frequency Domain Trace
    freq_trace = ComparisonTrace(
        id="t_freq",
        name="Freq Trace",
        source_module="Spectrum Analyzer",
        timestamp="2026-05-24T12:00:00",
        plot_type="spectrum",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", True),
        y_axis=AxisMetadata("voltage", "FS", "dBFS", False),
        x_data=[20.0, 100.0, 1000.0],
        y_data=[-10.0, -20.0, -30.0],
    )
    clean_manager.add_trace(freq_trace)

    # Filter combo: Index 0 is "frequency"
    widget.filter_combo.setCurrentIndex(0)

    # The Freq Trace parent should have 3 children: Voltage, Gain Offset, Frequency Shift
    parent_freq = widget.tree_widget.topLevelItem(0)
    assert parent_freq.childCount() == 3
    child_y_freq = parent_freq.child(0)
    child_offset_freq = parent_freq.child(1)
    child_shift_freq = parent_freq.child(2)

    assert "Voltage" in child_y_freq.text(0)
    assert "Gain Offset" in child_offset_freq.text(0)
    assert "Frequency Shift" in child_shift_freq.text(0)

    spin_shift_freq = widget.tree_widget.itemWidget(child_shift_freq, 1)
    assert spin_shift_freq.suffix() == " Hz"
    assert spin_shift_freq.maximum() == 100000.0
    assert spin_shift_freq.decimals() == 2

    clean_manager.clear_all_traces()

    # 2. Time Domain Trace
    time_trace = ComparisonTrace(
        id="t_time",
        name="Time Trace",
        source_module="Oscilloscope",
        timestamp="2026-05-24T12:00:00",
        plot_type="time_series",
        x_axis=AxisMetadata("time", "s", "s", False),
        y_axis=AxisMetadata("voltage", "V", "V", False),
        x_data=[0.0, 0.001, 0.002],
        y_data=[0.1, 0.2, 0.3],
    )
    clean_manager.add_trace(time_trace)

    # Filter combo: Index 1 is "time"
    widget.filter_combo.setCurrentIndex(1)

    parent_time = widget.tree_widget.topLevelItem(0)
    assert parent_time.childCount() == 3
    child_y_time = parent_time.child(0)
    child_offset_time = parent_time.child(1)
    child_shift_time = parent_time.child(2)

    assert "Voltage" in child_y_time.text(0)
    assert "Gain Offset" in child_offset_time.text(0)
    assert "Time Shift" in child_shift_time.text(0)

    spin_shift_time = widget.tree_widget.itemWidget(child_shift_time, 1)
    assert spin_shift_time.suffix() == " s"
    assert spin_shift_time.maximum() == 10.0
    assert spin_shift_time.decimals() == 4


def test_plot_comparer_manual_scale_overrides(qtbot, clean_manager):
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)

    # 1. Frequency Domain Trace
    trace = ComparisonTrace(
        id="t_scale",
        name="Freq Sweep",
        source_module="Spectrum Analyzer",
        timestamp="2026-05-24T12:00:00",
        plot_type="spectrum",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", True),
        y_axis=AxisMetadata("voltage", "FS", "dBFS", False),
        x_data=[20.0, 100.0, 1000.0],
        y_data=[-10.0, -20.0, -30.0],
    )
    clean_manager.add_trace(trace)
    widget.filter_combo.setCurrentIndex(0)  # Frequency domain

    # Initially scale overridden is False, X-Axis Log checkbox should be checked
    assert widget.scale_overridden is False
    assert widget.log_x_check.isChecked() is True
    assert widget.log_y_check.isChecked() is False

    # Simulate manual toggling
    widget.log_x_check.setChecked(False)
    # Toggling sets overridden flag and triggers replot
    assert widget.scale_overridden is True
    assert widget.is_log_x is False

    # Toggle Log Y
    widget.log_y_check.setChecked(True)
    assert widget.is_log_y is True


def test_plot_comparer_color_and_width_customization(qtbot, clean_manager):
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)

    trace = ComparisonTrace(
        id="t_custom",
        name="Sweep Trace",
        source_module="Spectrum Analyzer",
        timestamp="2026-05-24T12:00:00",
        plot_type="spectrum",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", True),
        y_axis=AxisMetadata("voltage", "FS", "dBFS", False),
        x_data=[20.0, 100.0, 1000.0],
        y_data=[-10.0, -20.0, -30.0],
    )
    clean_manager.add_trace(trace)

    settings = widget.trace_settings["t_custom"]
    assert settings["width"] == 2

    # Direct settings update simulation (mimicking dialog choice)
    settings["color"] = "#ff0000"
    settings["width"] = 4
    widget.replot()

    # Verify plot curve reflects modified settings
    y_curve, _ = widget.curve_items["t_custom"]
    assert y_curve is not None
    # Pyqtgraph plot item options or pen configurations can be checked
    pen = y_curve.opts['pen']
    from PyQt6.QtGui import QColor
    assert pen.width() == 4
    assert pen.color() == QColor("#ff0000")


def test_plot_comparer_interactive_cursor_readout(qtbot, clean_manager):
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)
    widget.show()
    widget.filter_combo.setCurrentIndex(0)

    trace = ComparisonTrace(
        id="t_cursor",
        name="Sweep Trace",
        source_module="Spectrum Analyzer",
        timestamp="2026-05-24T12:00:00",
        plot_type="spectrum",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", True),
        y_axis=AxisMetadata("voltage", "FS", "dBFS", False),
        x_data=[20.0, 100.0, 1000.0],
        y_data=[-10.0, -20.0, -30.0],
    )
    clean_manager.add_trace(trace)
    widget.refresh_trace_list()
    widget.replot()

    # Initially reading helper message
    assert "Move mouse over plot" in widget.readout_label.text()
    assert not widget.v_line.isVisible()
    assert not widget.h_line.isVisible()

    # Simulate mouse hover at mapped scene coordinate (e.g. 100 Hz = 0.1 kHz. log10(0.1) = -1.0)
    from PyQt6.QtCore import QPointF
    vb = widget.plot_item.vb
    scene_pos = vb.mapViewToScene(QPointF(-1.0, -20.0))

    widget.on_mouse_moved(scene_pos)

    assert widget.v_line.isVisible()
    assert widget.h_line.isVisible()
    assert widget.v_line.pos().x() == pytest.approx(-1.0)
    assert widget.h_line.pos().y() == pytest.approx(-20.0)

    # Readout label text should show interpolated values in kHz
    text = widget.readout_label.text()
    assert "0.100 kHz" in text
    assert "-20.00 dBFS" in text


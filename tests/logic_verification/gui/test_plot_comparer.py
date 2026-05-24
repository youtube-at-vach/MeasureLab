import os
import sys
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDoubleSpinBox, QCheckBox

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
        y2_data=[10.0, 20.0, 30.0]
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
    assert "Time Shift" in child_shift.text(0)

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

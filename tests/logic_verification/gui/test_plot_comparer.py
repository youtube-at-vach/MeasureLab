import os
import sys
import pytest
from PyQt6.QtCore import Qt

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

    # Initially list widget should be empty
    assert widget.list_widget.count() == 0
    assert not widget.offset_spin.isEnabled()
    assert not widget.shift_spin.isEnabled()


def test_plot_comparer_receives_data_and_updates_ui(qtbot, clean_manager):
    engine = AudioEngine()
    module = PlotComparer(engine)
    widget = PlotComparerWidget(module)
    qtbot.addWidget(widget)

    # Create dummy trace
    trace = ComparisonTrace(
        id="t1",
        name="Mock Sweep",
        source_module="Network Analyzer",
        timestamp="2026-05-24T12:00:00",
        plot_type="frequency_response",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", True),
        y_axis=AxisMetadata("gain", "dB", "dB", False),
        x_data=[10.0, 100.0, 1000.0],
        y_data=[1.0, 2.0, 3.0]
    )

    # Add trace to comparison manager
    clean_manager.add_trace(trace)

    # List widget should update
    assert widget.list_widget.count() == 1
    item = widget.list_widget.item(0)
    assert "Mock Sweep" in item.text()
    assert item.checkState() == Qt.CheckState.Checked

    # Select the item
    widget.list_widget.setCurrentItem(item)
    assert widget.offset_spin.isEnabled()
    assert widget.shift_spin.isEnabled()

    # Modify adjustments
    widget.offset_spin.setValue(10.0)
    widget.shift_spin.setValue(0.5)

    assert widget.trace_settings["t1"]["offset_db"] == 10.0
    assert widget.trace_settings["t1"]["shift"] == 0.5

    # Re-draw shouldn't crash
    widget.replot()
    assert "t1" in widget.curve_items

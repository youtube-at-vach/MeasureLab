import os
from unittest.mock import MagicMock
import pytest

# Skip if PyQt6 is not installed
pytest.importorskip("PyQt6")

try:
    from src.gui.widgets.frequency_counter import FrequencyCounter, FrequencyCounterWidget, FrequencyWorker
except ImportError:
    pytest.skip("Skipping GUI test due to missing dependencies", allow_module_level=True)

# Set environment for headless testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def frequency_counter():
    mock_audio_engine = MagicMock()
    mock_audio_engine.sample_rate = 48000
    mock_audio_engine.calibration = MagicMock()
    mock_audio_engine.calibration.frequency_calibration = 1.0

    counter = FrequencyCounter(mock_audio_engine)

    # Simulate running state
    counter.is_running = True
    counter.start_time = 1000.0
    counter.freq_history.append(100.0)
    counter.time_history.append(0.1)
    counter.selected_channel = 0
    return counter


def test_reset_state_clears_history(frequency_counter):
    # Test the reset_state method directly
    frequency_counter.reset_state()
    assert len(frequency_counter.freq_history) == 0
    assert len(frequency_counter.time_history) == 0
    assert frequency_counter.start_time != 1000.0


def test_widget_channel_change_resets_history(qapp, frequency_counter):
    # Create widget
    widget = FrequencyCounterWidget(frequency_counter)

    # Verify initial state (history has 1 item from fixture)
    assert len(frequency_counter.freq_history) == 1

    # Call on_channel_changed (simulate UI event)
    widget.on_channel_changed(1)

    # Verify channel updated
    assert frequency_counter.selected_channel == 1

    # Verify history cleared
    assert len(frequency_counter.freq_history) == 0

    # Cleanup properly to avoid segfaults and "pure virtual method called"
    widget.deleteLater()
    qapp.processEvents()


def test_widget_retains_worker_until_finished(qapp, qtbot, monkeypatch, frequency_counter):
    monkeypatch.setattr(
        "src.gui.widgets.frequency_counter.calculate_frequency_metrics",
        lambda *_args: (1000.0, -20.0),
    )
    widget = FrequencyCounterWidget(frequency_counter)
    worker = FrequencyWorker([], 48000, -60.0, 1.0)

    widget._start_worker(worker)

    assert worker in widget._active_workers
    qtbot.waitUntil(lambda: worker not in widget._active_workers, timeout=1000)
    widget.deleteLater()
    qapp.processEvents()


def test_frequency_worker_ignores_deleted_signals(monkeypatch):
    from PyQt6 import sip

    monkeypatch.setattr(
        "src.gui.widgets.frequency_counter.calculate_frequency_metrics",
        lambda *_args: (1000.0, -20.0),
    )
    worker = FrequencyWorker([], 48000, -60.0, 1.0)
    sip.delete(worker.signals)

    worker.run()


def test_frequency_counter_compact_mode(qapp, qtbot, frequency_counter):
    from src.gui.widgets.compactable_interface import CompactableWidgetInterface
    from unittest.mock import MagicMock
    from PyQt6.QtWidgets import QMainWindow

    # Create widget
    widget = FrequencyCounterWidget(frequency_counter)

    # Attach to a parent QMainWindow to mock and test adjustSize
    parent_win = QMainWindow()
    parent_win.adjustSize = MagicMock()
    widget.setParent(parent_win)

    # Verify inheritance and default state
    assert isinstance(widget, CompactableWidgetInterface)
    assert not widget.is_compact_mode()

    # Verify initial visibility (everything should be visible)
    assert not widget.controls_container.isHidden()
    assert not widget.tab_widget.isHidden()
    assert not widget.amp_label.isHidden()
    assert not widget.std_label.isHidden()
    assert not widget.allan_label.isHidden()

    # Toggle compact mode ON
    widget.set_compact_mode(True)
    assert widget.is_compact_mode()

    # Verify non-essential components are hidden
    assert widget.controls_container.isHidden()
    assert widget.tab_widget.isHidden()
    assert widget.amp_label.isHidden()
    assert widget.std_label.isHidden()
    assert widget.allan_label.isHidden()

    # Wait for the singleShot timer of 50ms to fire and check if adjustSize was called
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    # Reset mock for next check
    parent_win.adjustSize.reset_mock()

    # Toggle compact mode OFF
    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()

    # Verify everything is visible again
    assert not widget.controls_container.isHidden()
    assert not widget.tab_widget.isHidden()
    assert not widget.amp_label.isHidden()
    assert not widget.std_label.isHidden()
    assert not widget.allan_label.isHidden()

    # Wait for singleShot timer
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    # Cleanup properly
    widget.deleteLater()
    parent_win.deleteLater()
    qapp.processEvents()


def test_frequency_counter_exposes_run_button_to_measurement_console(qapp, qtbot, frequency_counter):
    from src.core.module_constants import MODULE_FREQUENCY_COUNTER
    from src.gui.module_registry import MODULE_REGISTRY
    from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper

    widget = FrequencyCounterWidget(frequency_counter)
    wrapper = DetachableWidgetWrapper(
        widget,
        "Frequency Counter",
        capabilities=MODULE_REGISTRY[MODULE_FREQUENCY_COUNTER].capabilities,
    )
    qtbot.addWidget(wrapper)

    assert wrapper.console_primary_action() is widget.run_btn

    frequency_counter.start_analysis = MagicMock()
    frequency_counter.stop_analysis = MagicMock()
    wrapper.console_primary_action().click()
    assert widget.run_btn.isChecked()
    assert frequency_counter.start_analysis.called

    wrapper.console_primary_action().click()
    assert not widget.run_btn.isChecked()
    assert frequency_counter.stop_analysis.called

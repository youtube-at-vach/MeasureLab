import os
import sys
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from src.gui.widgets.lufs_meter import LufsMeter, LufsMeterWidget
from src.gui.widgets.compactable_interface import CompactableWidgetInterface


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.input_sensitivity = 1.0
        self.calibration.get_input_offset_db.return_value = 0.0
        self.calibration.get_spl_offset_db.return_value = None

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, cid):
        pass


def test_lufs_meter_compact_mode(qtbot):
    from PyQt6.QtWidgets import QMainWindow

    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)

    # Attach to a parent QMainWindow to mock and test adjustSize
    parent_win = QMainWindow()
    parent_win.adjustSize = MagicMock()
    widget.setParent(parent_win)
    qtbot.addWidget(widget)

    assert isinstance(widget, CompactableWidgetInterface)
    assert not widget.is_compact_mode()
    assert not widget.sidebar.isHidden()
    assert not widget.tabs.isHidden()

    # Enable compact mode
    widget.set_compact_mode(True)
    assert widget.is_compact_mode()
    assert widget.sidebar.isHidden()
    assert widget.tabs.isHidden()

    # Wait for the singleShot timer of 50ms to fire and check if adjustSize was called
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    parent_win.adjustSize.reset_mock()

    # Disable compact mode
    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()
    assert not widget.sidebar.isHidden()
    assert not widget.tabs.isHidden()

    # Wait for singleShot timer
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    parent_win.deleteLater()


def test_lufs_readouts_survive_console_and_split_round_trip(qtbot):
    from PyQt6.QtWidgets import QMainWindow

    from PyQt6.QtCore import Qt

    from src.gui.measurement_console import InstrumentDockWidget
    from src.gui.module_registry import MODULE_REGISTRY
    from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper

    module = LufsMeter(MockAudioEngine())
    widget = LufsMeterWidget(module)
    wrapper = DetachableWidgetWrapper(widget, "LUFS Meter", capabilities=MODULE_REGISTRY["LUFS Meter"].capabilities)
    qtbot.addWidget(wrapper)
    window = QMainWindow()
    qtbot.addWidget(window)
    dock = InstrumentDockWidget("LUFS Meter", 0, "LUFS Meter", window)
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    wrapper.set_console_hosted(True)
    dock.set_instrument_widget(wrapper)
    wrapper.toggle_compact(True)
    window.show()

    dock._primary_button.click()
    assert module.is_running
    module.integrated_lufs = -23.2
    module.short_term_lufs = -22.8
    widget.update_display()
    assert widget.disp_i["label"].isVisible()
    assert widget.disp_i["label"].text() == "-23.2"
    assert widget.sidebar.isHidden()
    assert widget.tabs.isHidden()

    dock._primary_button.click()
    assert not module.is_running
    assert dock.take_instrument_widget() is wrapper
    wrapper.set_console_hosted(False)
    wrapper.split()
    widget.set_compact_mode(True)
    assert not widget.sidebar.isHidden()
    assert widget.disp_s["label"].text() == "-22.8"
    wrapper.reattach_all()
    widget.set_compact_mode(False)
    assert widget.display_widget.parent() is widget
    assert not widget.sidebar.isHidden()
    assert not widget.tabs.isHidden()
    assert widget.layout().stretch(widget.layout().indexOf(widget.display_widget)) == 1

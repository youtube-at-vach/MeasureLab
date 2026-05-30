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
    assert not widget.controls_widget.isHidden()
    assert not widget.tabs.isHidden()

    # Enable compact mode
    widget.set_compact_mode(True)
    assert widget.is_compact_mode()
    assert widget.controls_widget.isHidden()
    assert widget.tabs.isHidden()

    # Wait for the singleShot timer of 50ms to fire and check if adjustSize was called
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    parent_win.adjustSize.reset_mock()

    # Disable compact mode
    widget.set_compact_mode(False)
    assert not widget.is_compact_mode()
    assert not widget.controls_widget.isHidden()
    assert not widget.tabs.isHidden()

    # Wait for singleShot timer
    qtbot.wait(100)
    assert parent_win.adjustSize.called

    parent_win.deleteLater()

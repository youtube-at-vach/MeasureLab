from unittest.mock import MagicMock, patch
from PyQt6.QtCore import Qt
from src.gui.widgets.lufs_meter import LufsMeter, LufsMeterWidget


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_spl_offset_db.return_value = None

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, callback_id):
        pass


def test_lufs_meter_widget_initialization(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Verify initial states
    assert "-INF" in widget.m_val_label.text()
    assert "-INF" in widget.s_val_label.text()
    assert widget.target_spin.value() == -23.0
    assert widget.timer.isActive() is False


def test_lufs_meter_widget_toggle(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Initially not running
    assert not widget.module.is_running
    assert not widget.timer.isActive()

    # Click toggle
    qtbot.mouseClick(widget.toggle_btn, Qt.MouseButton.LeftButton)
    assert widget.module.is_running
    assert widget.timer.isActive()

    # Click toggle again
    qtbot.mouseClick(widget.toggle_btn, Qt.MouseButton.LeftButton)
    assert not widget.module.is_running
    assert not widget.timer.isActive()


def test_lufs_meter_widget_recovers_from_stream_start_failure(qtbot):
    engine = MockAudioEngine()
    engine.register_callback = MagicMock(side_effect=RuntimeError("device unavailable"))
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    with patch("src.gui.widgets.lufs_meter.QMessageBox") as message_box:
        qtbot.mouseClick(widget.toggle_btn, Qt.MouseButton.LeftButton)

    assert not module.is_running
    assert module.callback_id is None
    assert not widget.toggle_btn.isChecked()
    assert not widget.timer.isActive()
    assert widget.toggle_btn.text() == "Start Metering"
    message_box.critical.assert_called_once()


def test_lufs_meter_widget_update_display(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Needs to be running to update display
    widget.on_toggle(True)

    module.momentary_lufs = -15.0
    module.short_term_lufs = -18.0
    module.rms_l = -10.0
    module.rms_r = -10.0

    widget.update_display()

    # Check that labels were updated correctly
    assert "-15.0" in widget.m_val_label.text()
    assert "-18.0" in widget.s_val_label.text()
    assert "-10.0" in widget.l_val_label.text()
    assert "dBFS" in widget.l_val_label.text()
    assert "-10.0" in widget.r_val_label.text()
    assert "dBFS" in widget.r_val_label.text()


def test_lufs_meter_widget_never_presents_invalid_run_as_measurement(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)
    widget.on_toggle(True)
    module.measurement_valid = False

    widget.update_display()

    assert widget.m_val_label.text() == "INVALID"
    assert widget.s_val_label.text() == "INVALID"
    assert widget.disp_i["label"].text() == "INVALID"
    assert widget.disp_s["label"].text() == "INVALID"
    assert widget.card_threshold["label"].text() == "INVALID"


def test_lufs_meter_widget_reset_stats(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # Simulate some stats
    widget._m_min = -20.0
    widget._m_max = -5.0
    widget._m_sum = -100.0
    widget._m_n = 5

    # Reset stats
    qtbot.mouseClick(widget.reset_stats_btn, Qt.MouseButton.LeftButton)

    assert widget._m_min is None
    assert widget._m_max is None
    assert widget._m_sum == 0.0
    assert widget._m_n == 0


def test_lufs_meter_widget_target_changed(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    widget.target_spin.setValue(-14.0)

    assert module.target_lufs == -14.0
    # Also test the visual line placement
    assert widget.target_line.value() == -14.0

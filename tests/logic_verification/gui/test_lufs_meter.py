import pytest
from unittest.mock import MagicMock
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
    assert widget.spl_check.isChecked() is False
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

def test_lufs_meter_widget_spl_check(qtbot):
    engine = MockAudioEngine()
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    # When get_spl_offset_db returns None, SPL check shouldn't be enabled or checked
    assert not widget.spl_check.isEnabled()

    # Mock an active calibration
    engine.calibration.get_spl_offset_db.return_value = 0.0
    widget._sync_spl_checkbox()
    assert widget.spl_check.isEnabled()

    widget.spl_check.setChecked(True)
    assert widget.spl_check.isChecked()
    assert widget._show_spl

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

def test_lufs_meter_widget_spl_update_display(qtbot):
    engine = MockAudioEngine()
    engine.calibration.get_spl_offset_db.return_value = 100.0  # 0 dBFS = 100 dB SPL
    module = LufsMeter(engine)
    widget = LufsMeterWidget(module)
    qtbot.addWidget(widget)

    widget.on_toggle(True)
    widget._sync_spl_checkbox()
    widget.spl_check.setChecked(True)

    module.rms_c_l = -10.0
    module.rms_c_r = -10.0

    widget.update_display()

    # 100 - 10 = 90.0 dB SPL
    assert "90.0" in widget.l_val_label.text()
    assert "dB SPL" in widget.l_val_label.text()

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

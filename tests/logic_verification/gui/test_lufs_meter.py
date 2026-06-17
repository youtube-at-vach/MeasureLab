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


def test_lufs_meter_long_running_preallocation():
    import numpy as np
    engine = MockAudioEngine()
    captured_callback = None
    def mock_register(cb):
        nonlocal captured_callback
        captured_callback = cb
        return 1
    engine.register_callback = mock_register

    module = LufsMeter(engine)
    module.start_meter()

    assert captured_callback is not None

    # Call the callback to generate 10500 blocks for i_block_ms.
    # self._i_block_step = 0.1 * 48000 = 4800 samples.
    # Each callback call with 4800 samples adds 1 block.
    # Use an alternating signal (high frequency) to pass through the high-pass weighting filter.
    single_channel = np.tile(np.array([0.1, -0.1], dtype=np.float32), 2400)
    indata = np.column_stack((single_channel, single_channel))
    for _ in range(10500):
        captured_callback(indata, None, 4800, None, None)

    assert module._i_block_count == 10500
    assert len(module._i_block_ms) >= 10500

    # Verify update_integrated_lufs_if_dirty doesn't crash and updates correctly
    module.update_integrated_lufs_if_dirty()
    assert module._i_dirty is False


def test_lufs_meter_drift_correction():
    import numpy as np
    engine = MockAudioEngine()
    captured_callback = None
    def mock_register(cb):
        nonlocal captured_callback
        captured_callback = cb
        return 1
    engine.register_callback = mock_register

    module = LufsMeter(engine)
    module.start_meter()

    assert captured_callback is not None

    # Make 99 calls
    # Use alternating signal
    single_channel = np.tile(np.array([0.1, -0.1], dtype=np.float32), 128)
    indata = np.column_stack((single_channel, single_channel))
    for _ in range(99):
        captured_callback(indata, None, 256, None, None)

    # Inject a manual drift to _p_sum_m
    module._p_sum_m += 10.0

    # 100th call should trigger drift correction
    captured_callback(indata, None, 256, None, None)

    expected_sum = float(np.sum(module._p_ring_m, dtype=np.float64))
    assert np.isclose(module._p_sum_m, expected_sum, atol=1e-7)



import numpy as np

from src.gui.widgets.network_analyzer import NetworkAnalyzer, NetworkAnalyzerWidget


class MockCalibration:
    output_gain = 1.0
    input_sensitivity = 1.0


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MockCalibration()
        self.stream = None
        self.offline_mode = True

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, callback_id):
        pass


def _make_widget(qtbot):
    widget = NetworkAnalyzerWidget(NetworkAnalyzer(MockAudioEngine()))
    qtbot.addWidget(widget)
    return widget


def _curve_len(values):
    return 0 if values is None else len(values)


def test_update_ir_plot_updates_etc_curve(qtbot):
    widget = _make_widget(qtbot)

    time_ms = np.arange(8, dtype=float)
    ir_values = np.array([1.0, 0.5, 0.25, 0.125, 0.0625, 0.0, 0.0, 0.0])

    widget.update_ir_plot(time_ms, ir_values)

    etc_x, etc_y = widget.etc_curve.getData()
    assert np.array_equal(etc_x, time_ms)
    assert len(etc_y) == len(ir_values)
    assert np.max(etc_y) == 0.0
    assert np.min(etc_y) < -3.0
    assert np.all(etc_y <= 0.0)


def test_update_ir_plot_clears_etc_for_empty_or_silent_ir(qtbot):
    widget = _make_widget(qtbot)

    widget.update_ir_plot(np.array([]), np.array([]))
    etc_x, etc_y = widget.etc_curve.getData()
    assert _curve_len(etc_x) == 0
    assert _curve_len(etc_y) == 0

    widget.update_ir_plot(np.arange(4, dtype=float), np.zeros(4))
    etc_x, etc_y = widget.etc_curve.getData()
    assert _curve_len(etc_x) == 0
    assert _curve_len(etc_y) == 0


def test_network_analyzer_uses_fractional_octave_smoothing(qtbot):
    widget = _make_widget(qtbot)

    freqs = np.array([100.0, 105.0, 1000.0])
    mags = np.array([0.0, 6.0, 20.0])
    phases = np.array([170.0, -170.0, 45.0])

    mags_smooth, phases_smooth = widget._apply_smoothing(freqs, mags, phases, 3)

    expected_low_band = 20 * np.log10(np.mean(10 ** (mags[:2] / 20.0)))
    assert np.allclose(mags_smooth[:2], expected_low_band)
    assert np.isclose(mags_smooth[2], mags[2])
    assert np.all(np.abs(phases_smooth[:2]) > 170.0)


def test_etc_smoothing_is_independent_from_bode_smoothing(qtbot):
    widget = _make_widget(qtbot)
    widget.smooth_combo.setCurrentIndex(widget.smooth_combo.findData(3))
    widget.etc_smooth_combo.setCurrentIndex(widget.etc_smooth_combo.findData("heavy"))

    etc_db = np.array([0.0, -20.0, 0.0, -20.0, 0.0, -20.0, 0.0])
    smoothed = widget._apply_etc_smoothing(etc_db, widget.etc_smooth_combo.currentData())

    assert not np.array_equal(smoothed, etc_db)
    assert widget.smooth_combo.currentData() == 3
    assert widget.etc_smooth_combo.currentData() == "heavy"


def test_etc_smoothing_uses_time_based_strength(qtbot):
    widget = _make_widget(qtbot)

    times_ms = np.arange(401, dtype=float) * (1000.0 / 48000.0)
    etc_db = np.tile(np.array([0.0, -20.0]), 201)[: len(times_ms)]

    light = widget._apply_etc_smoothing(etc_db, "light", times_ms)
    medium = widget._apply_etc_smoothing(etc_db, "medium", times_ms)
    heavy = widget._apply_etc_smoothing(etc_db, "heavy", times_ms)

    assert np.std(light) < np.std(etc_db)
    assert np.std(medium) < np.std(light)
    assert np.std(heavy) < np.std(medium)

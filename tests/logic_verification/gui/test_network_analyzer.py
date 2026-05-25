import numpy as np
import pytest

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


_created_widgets: list[NetworkAnalyzerWidget] = []


@pytest.fixture(autouse=True)
def cleanup_widgets(qtbot):
    _created_widgets.clear()
    yield
    for w in _created_widgets:
        try:
            w.close()
            w.deleteLater()
        except Exception:
            pass
    _created_widgets.clear()
    try:
        qtbot.wait(50)
    except Exception:
        pass


def _make_widget(qtbot):
    widget = NetworkAnalyzerWidget(NetworkAnalyzer(MockAudioEngine()))
    qtbot.addWidget(widget)
    _created_widgets.append(widget)
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


def test_harmonics_plot_curves_and_visibility(qtbot):
    widget = _make_widget(qtbot)

    # Mock harmonics data
    freqs = np.array([100.0, 200.0, 500.0, 1000.0])
    data = {
        "freqs": freqs,
        "fundamental": np.array([0.0, -1.0, -2.0, -3.0]),
        "h2": np.array([-40.0, -42.0, -45.0, -48.0]),
        "h3": np.array([-50.0, -53.0, -56.0, -60.0]),
        "h4": np.array([-60.0, -64.0, -68.0, -72.0]),
        "h5": np.array([-70.0, -75.0, -80.0, -85.0]),
        "thd": np.array([-39.0, -41.0, -44.0, -47.0]),
    }

    widget.on_harmonics_result(data)

    # Verify curves got populated
    for key in ["fundamental", "h2", "h3", "h4", "h5", "thd"]:
        x, y = widget.h_curves[key].getData()
        assert np.allclose(x, np.log10(freqs))
        assert len(y) == len(freqs)

    # Test visibility checkboxes
    widget.show_h2_check.setChecked(False)
    x, y = widget.h_curves["h2"].getData()
    assert _curve_len(x) == 0  # Should be cleared

    widget.show_h2_check.setChecked(True)
    x, y = widget.h_curves["h2"].getData()
    assert _curve_len(x) == len(freqs)  # Restored


def test_harmonics_absolute_mode_and_units(qtbot):
    widget = _make_widget(qtbot)

    freqs = np.array([100.0, 1000.0])
    data = {
        "freqs": freqs,
        "fundamental": np.array([-10.0, -10.0]),
        "h2": np.array([-40.0, -40.0]),
        "h3": np.array([-50.0, -50.0]),
        "h4": np.array([-60.0, -60.0]),
        "h5": np.array([-70.0, -70.0]),
        "thd": np.array([-39.0, -39.0]),
    }
    widget.harmonics_data = data

    # Put widget in Single-Ch Absolute mode
    widget.single_mode_combo.setCurrentIndex(widget.single_mode_combo.findData("absolute"))
    widget.unit_combo.setCurrentText("dBFS")
    widget.module.amplitude = 0.5  # -6.02 dBFS
    out_amp_db = 20 * np.log10(0.5)

    widget.refresh_harmonics_plot()

    # The plotted absolute values should be shifted by out_amp_db
    x, y = widget.h_curves["h2"].getData()
    assert np.allclose(y, -40.0 + out_amp_db)


def test_calculate_harmonics_data_farina_math():
    # Instantiate analyzer
    analyzer = NetworkAnalyzer(MockAudioEngine())
    analyzer.start_freq = 20.0
    analyzer.end_freq = 20000.0
    analyzer.chirp_duration = 1.0

    # Create dummy impulse response data with a fundamental peak at peak_idx and an H2 peak before it
    sample_rate = 48000
    peak_idx = 10000
    ir_data = np.zeros(20000, dtype=float)
    ir_data[peak_idx] = 1.0

    # Add dummy H2 peak
    # ESS H2 offset calculation: delta_t_2 = T * ln(2) / ln(f2/f1)
    L = np.log(20000.0 / 20.0)
    delta_t_2 = 1.0 * np.log(2.0) / L
    peak_2 = peak_idx - int(sample_rate * delta_t_2)
    ir_data[peak_2] = 0.1

    valid_freqs = np.array([100.0, 1000.0])

    # Calculate harmonics data
    harmonics = analyzer._calculate_harmonics_data(
        ir_data=ir_data, peak_idx=peak_idx, sample_rate=sample_rate, valid_freqs=valid_freqs
    )

    assert "h2" in harmonics
    assert "h3" in harmonics
    assert "h4" in harmonics
    assert "h5" in harmonics
    assert len(harmonics["h2"]) == len(valid_freqs)


def test_harmonics_plot_percent_mode(qtbot):
    widget = _make_widget(qtbot)

    freqs = np.array([100.0, 1000.0])
    data = {
        "freqs": freqs,
        "fundamental": np.array([-10.0, -10.0]),
        "h2": np.array([-40.0, -40.0]),
        "h3": np.array([-50.0, -50.0]),
        "h4": np.array([-60.0, -60.0]),
        "h5": np.array([-70.0, -70.0]),
        "thd": np.array([-39.0, -39.0]),
    }
    widget.harmonics_data = data

    # Toggle percent mode checkbox
    widget.harmonics_as_percent_check.setChecked(True)
    widget.refresh_harmonics_plot()

    # In percent mode, the plotted values should be converted to percent relative to the fundamental
    # h2 raw db = -40, fundamental raw db = -10.
    # ratio = 10 ** ((-40 - (-10)) / 20) = 10 ** (-30 / 20) = 10 ** -1.5 = 0.03162277660168379
    # percent = 100.0 * 0.03162277660168379 = 3.162277660168379 %
    expected_h2_percent = 100.0 * (10 ** ((-40.0 - (-10.0)) / 20.0))
    x, y = widget.h_curves["h2"].getData()
    assert np.allclose(y, np.log10(expected_h2_percent))


def test_frequency_limits_update_on_sample_rate_change(qtbot):
    widget = _make_widget(qtbot)

    # By default, MockAudioEngine has sample_rate = 48000.
    # Nyquist should be 24000.
    widget.update_frequency_limits()
    assert widget.end_spin.maximum() == 24000.0
    assert widget.limit_spin.maximum() == 24000.0
    assert widget.min_limit_spin.maximum() == 24000.0

    # Simulate changing sample rate to 96000
    widget.module.audio_engine.sample_rate = 96000
    widget.update_frequency_limits()
    assert widget.end_spin.maximum() == 48000.0
    assert widget.limit_spin.maximum() == 48000.0
    assert widget.min_limit_spin.maximum() == 48000.0

    # Simulate changing sample rate to 44100
    # Values currently exceeding the new limits should be clamped
    widget.end_spin.setValue(48000.0)
    widget.module.audio_engine.sample_rate = 44100
    widget.update_frequency_limits()
    assert widget.end_spin.maximum() == 22050.0
    assert widget.end_spin.value() == 22050.0


def test_get_comparable_data_modes(qtbot):
    widget = _make_widget(qtbot)

    # Setup dummy data in the widget
    widget.freqs = [100.0, 1000.0]
    widget.mags = [-10.0, -20.0]
    widget.phases = [45.0, -45.0]

    # --- Mode 1: Transfer Function (XFER) ---
    widget.module.input_mode = "XFER"
    traces = widget.get_comparable_data()
    assert len(traces) == 1
    t = traces[0]
    assert t.y_axis.dimension == "gain"
    assert t.y_axis.display_unit == "dB"
    assert np.allclose(t.y_data, [-10.0, -20.0])
    assert t.calibration.reference_level == "relative"

    # --- Mode 2: Single-Channel Relative (relative) ---
    widget.module.input_mode = "L"
    widget.single_mode_combo.setCurrentIndex(widget.single_mode_combo.findData("relative"))
    traces = widget.get_comparable_data()
    assert len(traces) == 1
    t = traces[0]
    assert t.y_axis.dimension == "gain"
    assert t.y_axis.display_unit == "dB"
    assert np.allclose(t.y_data, [-10.0, -20.0])
    assert t.calibration.reference_level == "relative"

    # --- Mode 3: Single-Channel Absolute (absolute, uncalibrated) ---
    widget.single_mode_combo.setCurrentIndex(widget.single_mode_combo.findData("absolute"))
    widget.module.audio_engine.calibration.is_calibrated = False
    widget.module.amplitude = 1.0  # 0 dBFS
    traces = widget.get_comparable_data()
    assert len(traces) == 1
    t = traces[0]
    assert t.y_axis.dimension == "voltage"
    assert t.y_axis.display_unit == "dBFS"
    assert np.allclose(t.y_data, [10 ** (-10 / 20), 10 ** (-20 / 20)])
    assert t.calibration.reference_level == "relative"

    # --- Mode 4: Single-Channel Absolute (absolute, calibrated) ---
    widget.module.audio_engine.calibration.is_calibrated = True
    widget.module.audio_engine.calibration.input_sensitivity = 2.0
    traces = widget.get_comparable_data()
    assert len(traces) == 1
    t = traces[0]
    assert t.y_axis.dimension == "voltage"
    assert t.y_axis.display_unit == "dBV"
    assert np.allclose(t.y_data, [10 ** (-10 / 20) * 2.0, 10 ** (-20 / 20) * 2.0])
    assert t.calibration.reference_level == "absolute"


def test_get_comparable_data_applies_frequency_limits(qtbot):
    widget = _make_widget(qtbot)

    # Setup dummy data
    widget.freqs = [20.0, 100.0, 1000.0, 10000.0, 20000.0]
    widget.mags = [0.0, -5.0, -10.0, -15.0, -20.0]
    widget.phases = [10.0, 20.0, 30.0, 40.0, 50.0]

    widget.module.input_mode = "XFER"

    # Limit check enabled: max = 5000 Hz, min = 50 Hz
    widget.limit_check.setChecked(True)
    widget.limit_spin.setValue(5000.0)
    widget.min_limit_check.setChecked(True)
    widget.min_limit_spin.setValue(50.0)

    traces = widget.get_comparable_data()
    assert len(traces) == 1
    t = traces[0]

    # Should only contain 100.0 and 1000.0 Hz
    assert np.allclose(t.x_data, [100.0, 1000.0])
    assert np.allclose(t.y_data, [-5.0, -10.0])
    assert np.allclose(t.y2_data, [20.0, 30.0])

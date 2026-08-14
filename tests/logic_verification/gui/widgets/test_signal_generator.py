from dataclasses import fields
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt

import src.gui.widgets.signal_generator as signal_generator_module
from src.gui.widgets.signal_generator import PreferredNumberSpinBox, SignalGenerator, SignalParameters


@pytest.fixture
def signal_generator_widget(qtbot):
    engine = MagicMock()
    engine.sample_rate = 96000
    engine.calibration.output_gain = 1.0
    engine.calibration.output_gain_is_calibrated = False

    module = SignalGenerator(engine)
    widget = module.get_widget()
    qtbot.addWidget(widget)
    return widget, module, engine


def test_frequency_controls_allow_nyquist(signal_generator_widget):
    widget, _module, _engine = signal_generator_widget

    assert widget.freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.start_freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.end_freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.lpf_freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.hpf_freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.notch_freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.am_freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.fm_freq_spin.maximum() == pytest.approx(48000.0)
    assert widget.pm_freq_spin.maximum() == pytest.approx(48000.0)


def test_frequency_limits_follow_sample_rate_changes(signal_generator_widget):
    widget, module, engine = signal_generator_widget

    module.params_L.frequency = 50000.0
    module.params_R.frequency = 50000.0
    module.params_L.lpf_freq = 50000.0
    module.params_R.notch_freq = 50000.0

    engine.sample_rate = 44100
    widget._refresh_frequency_limits()

    assert widget.freq_spin.maximum() == pytest.approx(22050.0)
    assert module.params_L.frequency == pytest.approx(22050.0)
    assert module.params_R.frequency == pytest.approx(22050.0)
    assert module.params_L.lpf_freq < 22050.0
    assert module.params_R.notch_freq < 22050.0


def test_filter_cutoffs_are_clamped_below_nyquist(signal_generator_widget):
    widget, module, _engine = signal_generator_widget

    widget.update_param("lpf_freq", 48000.0)
    widget.update_param("hpf_freq", 48000.0)
    widget.update_param("notch_freq", 48000.0)

    assert widget.lpf_freq_spin.maximum() < 48000.0
    assert module.params_L.lpf_freq < 48000.0
    assert module.params_L.hpf_freq < 48000.0
    assert module.params_L.notch_freq < 48000.0


def test_frequency_slider_maps_to_nyquist(signal_generator_widget):
    widget, _module, _engine = signal_generator_widget

    assert widget._slider_to_freq(1000) == pytest.approx(48000.0)
    assert widget._freq_to_slider(48000.0) == 1000


def test_bin_snap_respects_frequency_lower_bound(signal_generator_widget):
    widget, module, engine = signal_generator_widget

    engine.sample_rate = 48000
    widget._refresh_frequency_limits(force=True)
    module.params_L.bin_center_snap = True
    module.params_L.fft_size = 16384

    widget.on_freq_spin_changed(1.0)

    assert widget.freq_spin.value() == pytest.approx(1.0)
    assert module.params_L.frequency == pytest.approx(1.0)


def test_frequency_step_keys_follow_125_series(qtbot):
    spin = PreferredNumberSpinBox()
    qtbot.addWidget(spin)
    spin.setRange(0.01, 100000.0)

    spin.setValue(1000.0)
    spin.stepBy(1)
    assert spin.value() == pytest.approx(2000.0)

    spin.stepBy(-1)
    assert spin.value() == pytest.approx(1000.0)

    spin.setValue(1500.0)
    spin.stepBy(1)
    assert spin.value() == pytest.approx(2000.0)
    spin.setValue(1500.0)
    spin.stepBy(-1)
    assert spin.value() == pytest.approx(1000.0)

    spin.setRange(0.0, 20000.0)
    spin.setDecimals(3)
    spin.setValue(0.0)
    spin.stepBy(1)
    assert spin.value() == pytest.approx(1.0)


def test_physical_output_units_require_calibration(signal_generator_widget):
    widget, module, engine = signal_generator_widget

    available_units = [widget.unit_combo.itemData(i) for i in range(widget.unit_combo.count())]
    assert available_units == ["Linear (0-1)", "dBFS"]

    engine.calibration.output_gain_is_calibrated = True
    engine.calibration.output_gain = 2.0
    widget._refresh_calibration_ui()
    available_units = [widget.unit_combo.itemData(i) for i in range(widget.unit_combo.count())]
    assert available_units == ["Linear (0-1)", "dBFS", "dBV", "dBu", "Vrms", "Vpeak"]

    widget.unit_combo.setCurrentIndex(widget.unit_combo.findData("Vrms"))
    amplitude_before = module.params_L.amplitude
    engine.calibration.output_gain_is_calibrated = False
    widget._refresh_calibration_ui()

    assert widget.unit_combo.currentData() == "dBFS"
    assert module.params_L.amplitude == amplitude_before


def test_frequency_sweep_forces_sine_and_locks_waveform(signal_generator_widget):
    widget, module, _engine = signal_generator_widget
    widget.wave_combo.setCurrentIndex(widget.wave_combo.findData("square"))
    assert module.params_L.waveform == "square"

    widget.sweep_group.setChecked(True)

    assert module.params_L.sweep_enabled is True
    assert module.params_L.waveform == "sine"
    assert widget.wave_combo.currentData() == "sine"
    assert widget.wave_combo.isEnabled() is False

    widget.sweep_group.setChecked(False)
    assert widget.wave_combo.isEnabled() is True


def test_unsupported_modulation_is_cleared_for_noise(signal_generator_widget):
    widget, module, _engine = signal_generator_widget
    widget.fm_group.setChecked(True)
    widget.pm_group.setChecked(True)
    assert module.params_L.fm_enabled is True
    assert module.params_L.pm_enabled is True

    widget.wave_combo.setCurrentIndex(widget.wave_combo.findData("noise"))

    assert module.params_L.fm_enabled is False
    assert module.params_L.pm_enabled is False
    assert widget.fm_group.isChecked() is False
    assert widget.pm_group.isChecked() is False
    assert widget.fm_group.isEnabled() is False
    assert widget.pm_group.isEnabled() is False


def test_filters_are_disabled_when_scipy_is_unavailable(qtbot, monkeypatch):
    monkeypatch.setattr(signal_generator_module, "scipy", None)
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.output_gain = 1.0
    engine.calibration.output_gain_is_calibrated = False
    widget = SignalGenerator(engine).get_widget()
    qtbot.addWidget(widget)

    assert widget.lpf_group.isEnabled() is False
    assert widget.hpf_group.isEnabled() is False
    assert widget.notch_group.isEnabled() is False
    assert "SciPy" in widget.lpf_group.toolTip()


def test_advanced_settings_fit_without_outer_scrolling(signal_generator_widget, qtbot):
    widget, _module, _engine = signal_generator_widget
    widget.setStyleSheet("font-size: 14px;")
    widget.resize(1100, 690)
    widget.show()
    widget.advanced_toggle.setChecked(True)
    qtbot.wait(1)

    assert widget.settings_scroll.verticalScrollBar().maximum() == 0


def test_routing_is_reflected_in_channel_badges(signal_generator_widget):
    widget, module, _engine = signal_generator_widget
    left_before = widget.left_condition_badge.text()
    right_before = widget.right_condition_badge.text()

    widget.route_l.click()

    assert module.output_mode == "L"
    assert widget.left_condition_badge.text() == left_before
    assert widget.right_condition_badge.text() != right_before


def test_link_copy_excludes_realtime_state(signal_generator_widget):
    widget, module, _engine = signal_generator_widget
    module.params_L.frequency = 1234.5
    module.params_L.am_depth = 37.0
    module.params_L._carrier_phase_rad = 1.25
    module.params_R._carrier_phase_rad = 2.5

    widget.copy_params(module.params_L, module.params_R)

    assert module.params_R.frequency == pytest.approx(1234.5)
    assert module.params_R.am_depth == pytest.approx(37.0)
    assert module.params_R._carrier_phase_rad == pytest.approx(2.5)
    for field in fields(SignalParameters):
        if not field.name.startswith("_"):
            assert getattr(module.params_R, field.name) == getattr(module.params_L, field.name)


def test_start_failure_restores_output_button(signal_generator_widget, qtbot):
    widget, module, engine = signal_generator_widget
    engine.register_callback.side_effect = RuntimeError("device unavailable")

    qtbot.mouseClick(widget.toggle_btn, Qt.MouseButton.LeftButton)

    assert module.is_playing is False
    assert module.callback_id is None
    assert widget.toggle_btn.isChecked() is False
    assert "device unavailable" in widget.output_message_label.text()


def test_output_overload_is_latched_limited_and_retained_after_stop():
    import numpy as np

    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.output_gain = 1.0
    engine.register_callback.return_value = "generator"
    module = SignalGenerator(engine)
    module.output_mode = "L"
    module.params_L.waveform = "sine"
    module.params_L.amplitude = 1.0
    module.params_L.am_enabled = True
    module.params_L.am_frequency = 100.0
    module.params_L.am_depth = 100.0

    module.start_generation()
    callback = engine.register_callback.call_args.args[0]
    outdata = np.zeros((512, 2))
    callback(None, outdata, len(outdata), None, None)

    assert module.output_overload_latched["L"] is True
    assert np.max(np.abs(outdata[:, 0])) <= 1.0
    module.stop_generation()
    assert module.output_overload_latched["L"] is True

    module.start_generation()
    assert module.output_overload_latched["L"] is False
    module.stop_generation()


def test_nonfinite_generator_output_is_sanitized_and_latched():
    import numpy as np

    module = SignalGenerator(MagicMock())
    samples = np.array([np.nan, np.inf, -np.inf, 0.5])

    module._limit_channel_output(samples, "L")

    assert np.all(np.isfinite(samples))
    assert np.max(np.abs(samples)) <= 1.0
    assert module.output_overload_latched["L"] is True


def test_signal_generator_phase_continuity():
    import numpy as np

    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.output_gain = 1.0
    engine.register_callback = MagicMock(return_value="mock_cb_id")
    engine.unregister_callback = MagicMock()

    module = SignalGenerator(engine)
    module.output_mode = "L"
    module.params_L.waveform = "sine"
    module.params_L.frequency = 1000.0
    module.params_L.amplitude = 1.0

    module.start_generation()
    assert engine.register_callback.called
    callback = engine.register_callback.call_args[0][0]

    # Run block 1
    frames = 512
    outdata = np.zeros((frames, 2))
    callback(None, outdata, frames, None, None)

    # Change frequency for block 2
    module.update_param(module.params_L, "frequency", 2000.0)
    outdata.fill(0)
    callback(None, outdata, frames, None, None)
    signal2 = outdata[:, 0].copy()

    # Total phase accumulated in block 1: frames * 2 * pi * 1000.0 / 48000.0
    phase_step1 = 2 * np.pi * 1000.0 / 48000.0
    expected_start_phase = (frames * phase_step1) % (2 * np.pi)

    # Waveform helper is amplitude * sin(phase)
    expected_start_val = np.sin(expected_start_phase)

    # First sample of block 2 must perfectly match expected_start_val
    assert np.isclose(signal2[0], expected_start_val, atol=1e-12)

    module.stop_generation()

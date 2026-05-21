from unittest.mock import MagicMock

import pytest

from src.gui.widgets.signal_generator import SignalGenerator


@pytest.fixture
def signal_generator_widget(qtbot):
    engine = MagicMock()
    engine.sample_rate = 96000
    engine.calibration.output_gain = 1.0

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

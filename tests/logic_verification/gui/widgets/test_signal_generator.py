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

    engine.sample_rate = 44100
    widget._refresh_frequency_limits()

    assert widget.freq_spin.maximum() == pytest.approx(22050.0)
    assert module.params_L.frequency == pytest.approx(22050.0)
    assert module.params_R.frequency == pytest.approx(22050.0)


def test_frequency_slider_maps_to_nyquist(signal_generator_widget):
    widget, _module, _engine = signal_generator_widget

    assert widget._slider_to_freq(1000) == pytest.approx(48000.0)
    assert widget._freq_to_slider(48000.0) == 1000

import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from src.gui.widgets.advanced_distortion_meter import (
    AdvancedDistortionMeter,
    AnalysisWorker,
    AdvancedDistortionMeterWidget,
)


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.output_gain = 1.0
    return engine


def test_advanced_distortion_meter_init(mock_audio_engine):
    meter = AdvancedDistortionMeter(mock_audio_engine)
    assert meter.name == "Advanced Distortion Meter"
    assert "Advanced distortion measurements" in meter.description
    assert meter.state == meter.STATE_IDLE
    assert meter.gen_amplitude == 0.5
    assert not meter.is_running
    assert len(meter.recording_buffer) == 65536


def test_amplitude_property(mock_audio_engine):
    meter = AdvancedDistortionMeter(mock_audio_engine)

    meter.gen_amplitude = -1.0
    assert meter.gen_amplitude == 0.0

    meter.gen_amplitude = 15.0
    assert meter.gen_amplitude == 10.0

    meter.gen_amplitude = 1.5
    assert meter.gen_amplitude == 1.5


def test_start_stop_analysis(mock_audio_engine):
    meter = AdvancedDistortionMeter(mock_audio_engine)
    meter.buffer_size = 1024

    # Configure mock
    mock_audio_engine.register_callback.return_value = 1234

    # Start analysis
    meter.start_analysis()
    assert meter.is_running
    assert meter.state == meter.STATE_MEASURING
    assert meter.write_index == 0
    mock_audio_engine.register_callback.assert_called_once()
    assert meter.callback_id == 1234

    # Start analysis again does nothing
    meter.start_analysis()
    mock_audio_engine.register_callback.assert_called_once()

    # Stop analysis
    meter.stop_analysis()
    assert not meter.is_running
    assert meter.state == meter.STATE_IDLE
    mock_audio_engine.unregister_callback.assert_called_once_with(1234)
    assert meter.callback_id is None


def test_generate_signals(mock_audio_engine):
    meter = AdvancedDistortionMeter(mock_audio_engine)
    meter.buffer_size = 1024

    # Test MIM
    meter.mode = "MIM"
    meter._update_output_buffer()
    assert len(meter.output_buffer) == 1024
    assert meter._mim_freqs is not None
    assert len(meter._mim_freqs) == meter.mim_tone_count

    # Test PIM
    meter.mode = "PIM"
    meter._update_output_buffer()
    assert len(meter.output_buffer) == 1024
    assert meter._pim_f1_actual is not None
    assert meter._pim_f2_actual is not None

    # Test SPDR
    meter.mode = "SPDR"
    meter._update_output_buffer()
    assert len(meter.output_buffer) == 1024


def test_analysis_worker(qtbot):
    data = np.zeros(1024)
    data[0] = 1.0  # Just some mock data
    sr = 48000

    worker = AnalysisWorker(data, sr, "MIM", {"mim_freqs": [1000.0]})

    # Setup mock signals to capture result
    mock_slot = MagicMock()
    worker.signals.result_ready.connect(mock_slot)

    with (
        patch("src.gui.widgets.advanced_distortion_meter.fft_manager") as mock_fft,
        patch("src.gui.widgets.advanced_distortion_meter.AudioCalc") as mock_calc,
    ):
        mock_fft.rfft.return_value = np.zeros(513)
        mock_fft.rfftfreq.return_value = np.linspace(0, 24000, 513)
        mock_calc.calculate_multitone_tdn.return_value = {"tdn_db": -60.0, "tdn": 0.1}

        worker.run()

        mock_fft.rfft.assert_called_once()
        mock_calc.calculate_multitone_tdn.assert_called_once()
        mock_slot.assert_called_once()

        result = mock_slot.call_args[0][0]
        assert "freqs" in result
        assert "mag_db" in result
        assert result["mode"] == "MIM"
        assert "mim" in result["metrics"]


def test_widget_mode_change(qtbot, mock_audio_engine):
    meter = AdvancedDistortionMeter(mock_audio_engine)
    widget = AdvancedDistortionMeterWidget(meter)
    qtbot.addWidget(widget)

    assert meter.mode == "MIM"  # Default

    # Change to SPDR
    widget.mode_combo.setCurrentIndex(1)
    assert meter.mode == "SPDR"
    assert widget.settings_stack.currentIndex() == 1

    # Change to PIM
    widget.mode_combo.setCurrentIndex(2)
    assert meter.mode == "PIM"
    assert widget.settings_stack.currentIndex() == 2

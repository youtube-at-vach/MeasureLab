import pytest
from unittest.mock import MagicMock
from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzerWidget, ImpedanceAnalyzer
from src.core.audio_engine import AudioEngine


@pytest.fixture
def mock_audio_engine():
    engine = MagicMock(spec=AudioEngine)
    engine.sample_rate = 48000
    return engine


@pytest.fixture
def impedance_module(mock_audio_engine):
    module = ImpedanceAnalyzer(mock_audio_engine)
    return module


def test_impedance_analyzer_widget_initialization(qtbot, impedance_module):
    widget = ImpedanceAnalyzerWidget(impedance_module)
    qtbot.addWidget(widget)

    assert widget.module == impedance_module
    assert widget.tabs.count() >= 2
    assert widget.toggle_btn.text() == "Start Measurement"
    assert widget.freq_spin.value() == 1000.0


def test_impedance_analyzer_widget_circuit_mode_change(qtbot, impedance_module):
    widget = ImpedanceAnalyzerWidget(impedance_module)
    qtbot.addWidget(widget)

    widget.circuit_combo.setCurrentText("Parallel")
    assert widget.results_widget.circuit_mode == "Parallel"

    widget.circuit_combo.setCurrentText("Series")
    assert widget.results_widget.circuit_mode == "Series"


def test_impedance_analyzer_widget_toggle_measurement(qtbot, impedance_module):
    widget = ImpedanceAnalyzerWidget(impedance_module)
    qtbot.addWidget(widget)

    assert not impedance_module.is_running
    widget.toggle_btn.click()
    assert impedance_module.is_running
    assert widget.toggle_btn.text() == "Stop"

    widget.toggle_btn.click()
    assert not impedance_module.is_running
    assert widget.toggle_btn.text() == "Start Measurement"


def test_impedance_analyzer_phase_continuity(impedance_module):
    import numpy as np

    # Setup mock register callback
    registered_callback = None

    def mock_register(cb):
        nonlocal registered_callback
        registered_callback = cb
        return 1

    impedance_module.audio_engine.register_callback = mock_register
    impedance_module.audio_engine.sample_rate = 48000
    impedance_module.gen_frequency = 1000.0
    impedance_module.gen_amplitude = 1.0
    impedance_module.output_channel = 0

    impedance_module.start_analysis()
    assert registered_callback is not None

    # Call callback for the first block (frames = 512)
    frames = 512
    indata = np.zeros((frames, 2))
    outdata = np.zeros((frames, 2))
    registered_callback(indata, outdata, frames, None, None)

    # Now change frequency
    impedance_module.gen_frequency = 2000.0

    # Call callback for the second block
    outdata.fill(0)
    registered_callback(indata, outdata, frames, None, None)
    signal2 = outdata[:, 0].copy()

    # The starting phase of block 2 must be exactly (frames * phase_step_1)
    phase_step_1 = 2 * np.pi * 1000.0 / 48000.0
    expected_phase_at_start_of_block2 = (frames * phase_step_1) % (2 * np.pi)
    expected_val = np.cos(expected_phase_at_start_of_block2)

    # Verify signal2[0] matches expected_val with phase continuity
    assert abs(signal2[0] - expected_val) < 1e-12


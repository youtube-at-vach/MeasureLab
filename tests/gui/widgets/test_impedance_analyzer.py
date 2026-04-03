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

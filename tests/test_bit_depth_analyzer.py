
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def analyzer():
    from src.core.audio_engine import AudioEngine
    from src.gui.widgets.bit_depth_analyzer import BitDepthAnalyzer
    engine = AudioEngine()
    # Mocking register_callback to avoid actual audio device access
    engine.register_callback = lambda cb: 123
    engine.unregister_callback = lambda id: None
    return BitDepthAnalyzer(engine)

def test_bit_depth_estimation_16bit(analyzer):
    analyzer.integration_time = 0
    analyzer.start_analysis()
    step = 2.0 / 65536.0
    t = np.linspace(-0.1, 0.1, 100000)
    quantized_signal = np.round(t / step) * step
    analyzer.audio_queue.put(quantized_signal)
    analyzer.process_queue()
    assert abs(analyzer._current_bit_depth - 16.0) < 0.5

def test_bit_depth_estimation_24bit(analyzer):
    analyzer.integration_time = 0
    analyzer.start_analysis()
    step = 2.0 / (2**24)
    quantized_signal = np.array([0, step, 3*step, 10*step, step, 0, -step])
    analyzer.audio_queue.put(quantized_signal)
    analyzer.process_queue()
    assert abs(analyzer._current_bit_depth - 24.0) < 0.5

def test_bit_depth_visualization(app, analyzer):
    from src.gui.widgets.bit_depth_analyzer import BitDepthAnalyzerWidget
    analyzer.integration_time = 0
    widget = BitDepthAnalyzerWidget(analyzer)
    analyzer.start_analysis()
    noise = np.random.uniform(-0.1, 0.1, 4096)
    analyzer.audio_queue.put(noise)
    analyzer.process_queue()
    widget.update_ui()
    assert widget.enob_value_label.text() != "0.0 bits"
    assert len(widget.enob_curve.getData()[1]) > 0

def test_heatmap_updates(app, analyzer):
    from src.gui.widgets.bit_depth_analyzer import BitDepthAnalyzerWidget
    analyzer.integration_time = 0
    widget = BitDepthAnalyzerWidget(analyzer)
    analyzer.start_analysis()
    silence_dither = np.random.normal(0, 1e-6, 4096)
    analyzer.audio_queue.put(silence_dither)
    analyzer.process_queue()
    widget.update_ui()
    assert np.any(widget.heatmap_data > 0)

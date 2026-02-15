
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from src.core.audio_engine import AudioEngine
from src.gui.widgets.bit_depth_analyzer import BitDepthAnalyzer, BitDepthAnalyzerWidget


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def analyzer():
    engine = AudioEngine()
    # Mocking register_callback to avoid actual audio device access
    engine.register_callback = lambda cb: 123
    engine.unregister_callback = lambda id: None
    return BitDepthAnalyzer(engine)


def test_bit_depth_estimation_16bit(analyzer):
    analyzer.integration_time = 0
    analyzer.start_analysis()
    
    # Generate slow ramp to ensure 1 LSB transitions
    # Slope must be < step size (approx) or at least ensure we hit adjacent levels.
    # 16-bit step ~ 3e-5.
    # 100k samples, range 2.0. Slope 2e-5.
    t = np.linspace(-0.1, 0.1, 100000)
    # Range -1 to 1. Quantized to 65536 levels.
    # Step size = 2 / 65536
    step = 2.0 / 65536.0
    
    # Simulate quantization
    clean_signal = t
    quantized_signal = np.round(clean_signal / step) * step
    
    # Push to queue
    analyzer.audio_queue.put(quantized_signal)
    
    # Process
    analyzer.process_queue()
    
    # Check estimation
    # Allow small error due to float precision
    assert abs(analyzer._current_bit_depth - 16.0) < 0.5


def test_bit_depth_estimation_24bit(analyzer):
    analyzer.integration_time = 0
    analyzer.start_analysis()
    
    # 24-bit step ~ 1.2e-7.
    # We need a very slow ramp or high sample count.
    # Let's use fewer samples but strictly controlled values.
    # Create steps of 1*q, 2*q, etc.
    step = 2.0 / (2**24)
    quantized_signal = np.array([0, step, 3*step, 10*step, step, 0, -step])
    
    analyzer.audio_queue.put(quantized_signal)
    analyzer.process_queue()
    
    assert abs(analyzer._current_bit_depth - 24.0) < 0.5


def test_bit_depth_visualization(app, analyzer):
    analyzer.integration_time = 0
    widget = BitDepthAnalyzerWidget(analyzer)
    analyzer.start_analysis()
    
    # Generate random noise (likely float precision -> high bit depth)
    noise = np.random.uniform(-0.1, 0.1, 4096)
    analyzer.audio_queue.put(noise)
    analyzer.process_queue()
    
    widget.update_ui()
    
    # Check if UI updated
    assert widget.enob_value_label.text() != "0.0 bits"
    assert len(widget.enob_curve.getData()[1]) > 0


def test_heatmap_updates(app, analyzer):
    analyzer.integration_time = 0
    widget = BitDepthAnalyzerWidget(analyzer)
    analyzer.start_analysis()
    
    # Generate dithered silence (small activity in LSBs)
    silence_dither = np.random.normal(0, 1e-6, 4096)
    analyzer.audio_queue.put(silence_dither)
    analyzer.process_queue()
    
    widget.update_ui()
    
    # Heatmap should have some data
    assert np.any(widget.heatmap_data > 0)

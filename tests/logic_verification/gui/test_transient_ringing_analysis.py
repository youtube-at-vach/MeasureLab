import numpy as np
import pytest
from src.core.audio_engine import AudioEngine
from src.gui.widgets.transient_analyzer import TransientAnalyzer

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000

def test_ringing_metrics_linear_phase():
    # Setup
    engine = MockAudioEngine()
    analyzer = TransientAnalyzer(engine)
    
    # Generate Sinc wave (perfectly symmetric ringing)
    fs = 48000
    t = np.linspace(-0.01, 0.01, 1000)  # 20ms duration
    sinc_data = np.sinc(t * 1000)  # central peak at t=0
    
    analyzer.fs = fs
    analyzer.final_data = sinc_data
    
    # Calculate ringing metrics with 2.0 ms window
    metrics = analyzer.calculate_ringing_metrics(window_width_ms=2.0)
    
    assert metrics is not None
    assert metrics["is_valid"] is True
    # For a perfect sinc, pre_energy should be very close to post_energy
    # Ratio should be close to 0 dB
    assert abs(metrics["ratio_db"]) < 1.0
    assert metrics["filter_type"] == "Linear Phase"

def test_ringing_metrics_minimum_phase():
    # Setup
    engine = MockAudioEngine()
    analyzer = TransientAnalyzer(engine)
    
    # Generate one-sided exponentially decaying sine wave (Min Phase simulation)
    fs = 48000
    n_samples = 1000
    peak_idx = 500
    
    data = np.zeros(n_samples)
    data[peak_idx] = 1.0  # The main impulse peak
    
    # Post-peak ringing
    t_post = np.arange(n_samples - peak_idx - 1) / fs
    data[peak_idx + 1:] = 0.5 * np.exp(-1000 * t_post) * np.sin(2 * np.pi * 5000 * t_post)
    
    # Pre-peak is completely zero
    analyzer.fs = fs
    analyzer.final_data = data
    
    metrics = analyzer.calculate_ringing_metrics(window_width_ms=2.0)
    
    assert metrics is not None
    assert metrics["is_valid"] is True
    # Since pre_energy is 0, ratio should be extremely low
    assert metrics["ratio_db"] < -20.0
    assert metrics["filter_type"] == "Minimum Phase"

def test_ringing_metrics_invalid_signal():
    # Setup
    engine = MockAudioEngine()
    analyzer = TransientAnalyzer(engine)
    
    # Generate pure sine wave (Low Crest Factor, not an impulse)
    fs = 48000
    t = np.arange(1000) / fs
    sine_data = np.sin(2 * np.pi * 1000 * t)
    
    analyzer.fs = fs
    analyzer.final_data = sine_data
    
    metrics = analyzer.calculate_ringing_metrics(window_width_ms=2.0)
    
    assert metrics is not None
    # Sine wave has low crest factor (~3 dB), should fail validation
    assert metrics["is_valid"] is False
    assert metrics["error_msg"] is not None

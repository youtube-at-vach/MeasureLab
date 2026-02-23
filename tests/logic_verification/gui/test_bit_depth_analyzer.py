
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def estimator():
    from src.core.bit_depth_estimator import BitDepthEstimator
    return BitDepthEstimator()

def test_bit_depth_estimation_16bit(estimator):
    # Setup 16-bit quantization
    step = 2.0 / 65536.0
    t = np.linspace(-0.1, 0.1, 10000)
    quantized_signal = np.round(t / step) * step

    estimator.add_samples(quantized_signal)
    results = estimator.analyze()

    assert results is not None
    assert abs(results["bit_depth"] - 16.0) < 0.5

def test_bit_depth_estimation_24bit(estimator):
    # Setup 24-bit quantization
    step = 2.0 / (2**24)
    # Ensure enough variance
    quantized_signal = np.array([0, step, 3*step, 10*step, step, 0, -step])

    estimator.add_samples(quantized_signal)
    results = estimator.analyze()

    assert results is not None
    assert abs(results["bit_depth"] - 24.0) < 0.5

def test_bit_depth_dialog(app):
    from src.core.audio_engine import AudioEngine
    from src.gui.widgets.settings import BitDepthDialog

    engine = AudioEngine()
    # Mocking register_callback
    engine.register_callback = lambda cb: 123
    engine.unregister_callback = lambda id: None

    dialog = BitDepthDialog(engine)
    dialog.start_analysis()

    # Simulate callback
    noise = np.random.uniform(-0.1, 0.1, (4096, 2))
    # Using internal estimator to bypass callback loop for test if needed, 
    # but let's test the callback registration indirectly by calling what callback would do
    # Actually, we can't easily invoke the callback defined inside start_analysis 
    # unless we captured it or refactored.
    # But we can test that UI updates don't crash when there's data in estimator

    dialog.estimator.add_samples(noise[:, 0])
    dialog.update_ui()

    assert dialog.enob_label.text() != "ENOB: -- bits"
    assert len(dialog.enob_history) > 0

    dialog.stop_analysis()
    dialog.close()

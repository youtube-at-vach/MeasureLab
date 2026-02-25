
import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

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

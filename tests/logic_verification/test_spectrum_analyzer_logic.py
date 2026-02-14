import sys
import os
from unittest.mock import MagicMock
import pytest

# Skip if dependencies missing
pytest.importorskip("PyQt6")
pytest.importorskip("pyqtgraph")
np = pytest.importorskip("numpy")

# Mock sounddevice if missing
if 'sounddevice' not in sys.modules:
    sys.modules['sounddevice'] = MagicMock()

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer
except ImportError:
    pytest.skip("Skipping due to import errors", allow_module_level=True)

def test_spectrum_analyzer_queue_data_flow():
    """
    Verify that data flows from callback -> queue -> process_queue -> input_data.
    """
    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration.input_sensitivity = 1.0

    # Capture callback
    callbacks = {}
    def register_callback(cb):
        cid = len(callbacks)
        callbacks[cid] = cb
        return cid
    mock_engine.register_callback.side_effect = register_callback

    # Init SpectrumAnalyzer
    # Mocking QWidget parent if needed?
    # SpectrumAnalyzer is a QWidget. We need QApplication or mock it.
    # But since we importorskip PyQt6, we assume it's there.
    # However, creating a QWidget without QApplication might fail.
    # We should ensure QApplication exists.
    from PyQt6.QtWidgets import QApplication
    if not QApplication.instance():
        QApplication([])

    sa = SpectrumAnalyzer(mock_engine)
    sa.set_buffer_size(4096)
    sa.start_analysis()

    # Verify queue exists (this will fail initially)
    if not hasattr(sa, 'audio_queue'):
        pytest.fail("SpectrumAnalyzer does not have 'audio_queue' attribute")

    # Verify queue is empty
    assert sa.audio_queue.empty()

    # Get callback
    cb = callbacks[0]

    # Create test data
    frames = 100
    indata = np.ones((frames, 2), dtype=np.float32) * 0.5
    outdata = np.zeros_like(indata)

    # Call callback
    cb(indata, outdata, frames, 0.0, None)

    # Verify data is in queue (this will fail initially if logic not changed)
    assert not sa.audio_queue.empty()
    assert sa.audio_queue.qsize() == 1

    # Verify process_queue exists
    if not hasattr(sa, 'process_queue'):
        pytest.fail("SpectrumAnalyzer does not have 'process_queue' method")

    # Call process_queue
    sa.process_queue()

    # Verify queue is empty
    assert sa.audio_queue.empty()

    # Verify input_data has data
    # sa.input_data is ring buffer. write_head should be advanced.
    # We wrote 100 frames. write_head should be 100 % buffer_size.
    # Buffer initialized to 0.
    # Data is 0.5.

    assert sa.write_head == 100
    assert np.allclose(sa.input_data[0:100], 0.5)
    assert np.all(sa.input_data[100:] == 0)

    print("Queue data flow test passed.")

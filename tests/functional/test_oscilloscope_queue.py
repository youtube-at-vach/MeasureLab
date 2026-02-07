
import sys
import os
import numpy as np
from unittest.mock import MagicMock

# Ensure sounddevice is mocked
if 'sounddevice' not in sys.modules:
    sys.modules['sounddevice'] = MagicMock()

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from src.gui.widgets.oscilloscope import Oscilloscope

def test_oscilloscope_queue_data_flow():
    """
    Verify that data flows from callback -> transfer_buffer -> process_queue -> input_data.
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

    # Init Oscilloscope
    osc = Oscilloscope(mock_engine)
    osc.start_analysis()

    # Verify buffer is empty/reset
    assert osc.transfer_write_count == 0
    assert osc.transfer_read_count == 0

    # Get callback
    cb = callbacks[0]

    # Create test data
    frames = 100
    indata = np.ones((frames, 2), dtype=np.float32) * 0.5
    outdata = np.zeros_like(indata)

    # Call callback
    cb(indata, outdata, frames, 0.0, None)

    # Verify data is in transfer buffer
    assert osc.transfer_write_count == 100
    assert osc.transfer_read_count == 0
    # Check data content in transfer buffer
    assert np.allclose(osc.transfer_buffer[0:100], 0.5)

    # Verify input_data is still zero (before process_queue)
    assert np.all(osc.input_data == 0)

    # Call process_queue
    osc.process_queue()

    # Verify transfer buffer is read
    assert osc.transfer_read_count == 100

    # Verify input_data has data
    # osc.input_data is ring buffer. write_index should be advanced.
    # We wrote 100 frames. write_index should be 100 % buffer_size.
    # Buffer initialized to 0.
    # Data is 0.5.

    assert osc.write_index == 100
    assert np.allclose(osc.input_data[0:100], 0.5)
    assert np.all(osc.input_data[100:] == 0)

    print("Transfer buffer data flow test passed.")

if __name__ == "__main__":
    try:
        test_oscilloscope_queue_data_flow()
    except AssertionError as e:
        print(f"Test Failed: {e}")
        sys.exit(1)

import sys
import os
from unittest.mock import MagicMock

# Ensure sounddevice is mocked before import
if 'sounddevice' not in sys.modules:
    sys.modules['sounddevice'] = MagicMock()

import numpy as np

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.gui.widgets.oscilloscope import Oscilloscope

def test_no_allocation_in_callback():
    """
    Verify that the Oscilloscope audio callback does not reallocate the input buffer.
    """
    # Mock AudioEngine
    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration.input_sensitivity = 1.0

    # Capture the callback
    callbacks = {}
    def register_callback(cb):
        cid = len(callbacks)
        callbacks[cid] = cb
        return cid

    mock_engine.register_callback.side_effect = register_callback

    # Init Oscilloscope
    osc = Oscilloscope(mock_engine)
    osc.start_analysis()

    # Verify initial state
    initial_id = id(osc.input_data)

    # Create dummy data
    frames = 1024
    indata = np.random.rand(frames, 2).astype(np.float32)
    outdata = np.zeros_like(indata)

    # Get the callback
    assert len(callbacks) > 0, "Callback not registered"
    cb = callbacks[0]

    # Call it multiple times to ensure wrapping logic doesn't trigger allocation
    for _ in range(10):
        cb(indata, outdata, frames, 0.0, None)
        assert id(osc.input_data) == initial_id, "Buffer was reallocated during callback!"

if __name__ == "__main__":
    # Allow running as script
    try:
        test_no_allocation_in_callback()
        print("Test Passed")
    except AssertionError as e:
        print(f"Test Failed: {e}")
        sys.exit(1)

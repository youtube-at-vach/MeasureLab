
import sys
import numpy as np
from unittest.mock import MagicMock

# Mock modules to avoid GUI/Audio dependencies
# We only mock sounddevice, not the whole audio engine module,
# because we want to import AudioEngine class if possible,
# BUT AudioEngine imports sounddevice.
sys.modules["sounddevice"] = MagicMock()
sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtCore"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = MagicMock()
sys.modules["pyqtgraph"] = MagicMock()

# Now we can import
# We need to make sure AudioEngine can be imported without crashing
from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer  # noqa: E402
# We don't need real AudioEngine, just a mock object is enough
# but SpectrumAnalyzer type hints might want it.

def test_spectrum_analyzer_allocation():
    print("Testing Spectrum Analyzer allocation behavior...")

    # Mock Engine
    engine = MagicMock()
    engine.sample_rate = 44100

    # Instantiate
    # SpectrumAnalyzer constructor takes audio_engine
    analyzer = SpectrumAnalyzer(engine)
    analyzer.start_analysis()

    # Verify Initial State
    initial_id = id(analyzer.input_data)
    print(f"Initial buffer ID: {initial_id}")

    # Create Dummy Data (Stereo)
    frames = 512
    indata = np.random.rand(frames, 2).astype(np.float32)
    outdata = np.zeros((frames, 2), dtype=np.float32)

    # Get the callback
    # start_analysis registers callback.
    args, _ = engine.register_callback.call_args
    callback = args[0]

    # Call callback once
    callback(indata, outdata, frames, 0, None)

    # Check ID
    new_id = id(analyzer.input_data)
    print(f"Post-callback buffer ID: {new_id}")

    if initial_id != new_id:
        print("FAIL: Buffer was re-allocated (ID changed).")
        return False
    else:
        print("PASS: Buffer ID is stable.")
        return True

if __name__ == "__main__":
    if not test_spectrum_analyzer_allocation():
        sys.exit(1)

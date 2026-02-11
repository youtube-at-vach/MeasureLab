
import sys
import time
import numpy as np
from unittest.mock import MagicMock

# --- MOCKING ---
# Mock sounddevice to avoid PortAudio requirement
mock_sd = MagicMock()
sys.modules['sounddevice'] = mock_sd

# Mock PyQt6 to avoid platform plugin issues if possible, but SignalGenerator uses QWidget base class.
# So we need PyQt6. But we can use offscreen platform.
# Or we can mock PyQt6.QtWidgets.QWidget?
# SignalGenerator inherits MeasurementModule.
# MeasurementModule is in src.measurement_modules.base.
# Let's import QApp.
from PyQt6.QtWidgets import QApplication  # noqa: E402

# Initialize QApp with offscreen platform explicitly in args
if not QApplication.instance():
    # Pass platform arg
    app = QApplication(sys.argv + ['-platform', 'offscreen'])
else:
    app = QApplication.instance()

try:
    # Now we can import our modules
    # Make sure we can find src
    import os
    if os.getcwd() not in sys.path:
        sys.path.append(os.getcwd())

    from src.gui.widgets.signal_generator import SignalGenerator, SignalParameters
    from src.core.audio_engine import AudioEngine
except ImportError as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

def run_test():
    print("Setting up test...")

    # Mock AudioEngine instance
    audio_engine = MagicMock(spec=AudioEngine)
    audio_engine.sample_rate = 48000

    gen = SignalGenerator(audio_engine)

    # Test Order 15
    print("\n--- Testing Order 15 ---")
    params = SignalParameters(mls_order=15)

    # Force fallback by patching scipy.signal.max_len_seq
    import scipy.signal
    original_max_len_seq = scipy.signal.max_len_seq

    def mock_max_len_seq(*args, **kwargs):
        raise RuntimeError("Forced failure for testing fallback")

    scipy.signal.max_len_seq = mock_max_len_seq

    try:
        start = time.time()
        signal = gen._generate_mls(params, 48000)
        end = time.time()

        print(f"Execution time: {end - start:.4f} s")
        print(f"Shape: {signal.shape}")

        expected_len = 2**15 - 1
        if len(signal) != expected_len:
            print(f"FAIL: Expected length {expected_len}, got {len(signal)}")
        else:
            print("PASS: Length correct")

        if not np.all(np.isin(signal, [-1.0, 1.0])):
             print("FAIL: Values not in {-1, 1}")
        else:
             print("PASS: Values correct")

    except Exception as e:
        print(f"FAIL: Exception raised: {e}")
        import traceback
        traceback.print_exc()

    # Test Order 18
    print("\n--- Testing Order 18 ---")
    params.mls_order = 18

    try:
        start = time.time()
        signal = gen._generate_mls(params, 48000)
        end = time.time()

        print(f"Execution time: {end - start:.4f} s")
        print(f"Shape: {signal.shape}")

        expected_len = 2**18 - 1
        if len(signal) != expected_len:
            print(f"FAIL: Expected length {expected_len}, got {len(signal)}")
        else:
            print("PASS: Length correct")

        if end - start > 0.05:
            print(f"WARNING: Performance seems slow ({end - start:.4f} s). Expected < 0.02s")
        else:
            print("PASS: Performance is good")

    except Exception as e:
        print(f"FAIL: Exception raised: {e}")
        traceback.print_exc()

    # Restore
    scipy.signal.max_len_seq = original_max_len_seq

if __name__ == "__main__":
    run_test()

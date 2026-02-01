
import os
import sys
import numpy as np
from unittest.mock import MagicMock, patch
import pytest

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.gui.widgets.signal_generator import SignalGenerator, SignalParameters

def test_mls_fallback_correctness():
    """
    Verifies that the fallback MLS generation (used when scipy is missing/fails)
    produces the exact same sequence as the scipy implementation.
    """
    # Setup
    mock_engine = MagicMock()
    sg = SignalGenerator(mock_engine)
    params = SignalParameters()
    params.waveform = 'mls'

    # Test a couple of orders
    for order in [10, 15]:
        params.mls_order = order
        print(f"Testing MLS order {order}...")

        # 1. Get reference signal using actual scipy (assuming it is installed in test env)
        try:
            import scipy.signal
            ref_seq, _ = scipy.signal.max_len_seq(order)
            ref_signal = ref_seq.astype(float) * 2 - 1
        except ImportError:
            pytest.skip("Scipy not installed, cannot verify fallback against reference implementation.")

        # 2. Force fallback by mocking max_len_seq to raise Exception
        # We patch where it is imported/used. The code imports it inside the method.
        # But if it's already imported in sys.modules, patch works on that.
        # However, the code does `import scipy.signal` inside the function.
        # If we patch `scipy.signal.max_len_seq`, it should work because the module object is the same.

        with patch('scipy.signal.max_len_seq', side_effect=RuntimeError("Forced failure for testing fallback")):
            # Note: We pass sample_rate but _generate_mls doesn't strictly use it for MLS length (it uses order)
            fallback_signal = sg._generate_mls(params, 48000)

        # 3. Verify
        # Check length
        expected_len = 2**order - 1
        assert len(fallback_signal) == expected_len, f"Length mismatch for order {order}"
        assert len(fallback_signal) == len(ref_signal)

        # Check content
        if not np.allclose(fallback_signal, ref_signal):
            diff_indices = np.where(~np.isclose(fallback_signal, ref_signal))[0]
            print(f"Mismatch at indices: {diff_indices[:10]}...")
            print(f"Fallback sample: {fallback_signal[diff_indices[0]]}")
            print(f"Reference sample: {ref_signal[diff_indices[0]]}")
            pytest.fail(f"Fallback MLS signal does not match Scipy implementation for order {order}")

    print("MLS Fallback Logic Verified Successfully.")

if __name__ == "__main__":
    # Allow running this file directly
    test_mls_fallback_correctness()

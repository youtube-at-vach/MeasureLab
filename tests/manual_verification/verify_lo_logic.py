
import sys
import os
import numpy as np

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.gui.widgets.distortion_analyzer import DistortionAnalyzer

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000

def test_thd_validity():
    engine = MockAudioEngine()
    analyzer = DistortionAnalyzer(engine)

    # helper to create mock harmonics
    def make_harmonics(fund_amp, distortion_amp):
        # Create one harmonic
        return np.array([distortion_amp])

    print("Testing THD validity logic...")

    # helper to build results dict
    def make_results(fund_rms, res_rms, harmonics, fund_amp=1.0):
        # Calc basic stats locally to match mock
        thd_linear = np.sqrt(np.sum(harmonics**2)) / fund_amp if fund_amp > 0 else 0
        thdn_linear = res_rms / fund_rms if fund_rms > 0 else 0

        return {
            "raw_fund_rms": fund_rms,
            "raw_res_rms": res_rms,
            "raw_fund_amp": fund_amp,
            "basic_wave": {"frequency": 1000, "amplitude_dbfs": -1.0},
            "raw_harmonics": harmonics,
            "fft_data": np.zeros(10),
            "thd_percent": thd_linear * 100,
            "thdn_percent": thdn_linear * 100
        }

    # Case 1: No Averaging, Invalid (THD+N < THD)
    analyzer.averaging = 0.0

    # THD = 1%, THD+N = 0.5% (Impossible)
    results_invalid_no_avg = make_results(
        fund_rms=1.0, 
        res_rms=0.005, 
        harmonics=np.array([0.01])
    )

    out_1 = analyzer._apply_result_averaging(results_invalid_no_avg)
    print(f"Case 1 (No Avg, Invalid): thd_valid = {out_1.get('thd_valid')}")
    assert not out_1.get('thd_valid'), "Case 1 failed"

    # Case 2: Averaging ON, Valid
    analyzer.averaging = 0.5
    analyzer.reset_averaging_state()

    # THD = 1%, THD+N = 1.41% (Valid)
    results_valid_avg = make_results(
        fund_rms=1.0,
        res_rms=np.sqrt(0.01**2 + 0.01**2), # Noise=Distortion
        harmonics=np.array([0.01])
    )

    # Feed twice to settle averaging a bit (start from None state)
    out_2 = analyzer._apply_result_averaging(results_valid_avg)
    print(f"Case 2 (Avg ON, Valid): thd_valid = {out_2.get('thd_valid')}")
    assert out_2.get('thd_valid'), "Case 2 failed"

    # Case 3: Averaging ON, Invalid
    analyzer.reset_averaging_state()
    # THD = 1%, THD+N = 0.5% (Impossible)
    results_invalid_avg = make_results(
        fund_rms=1.0,
        res_rms=0.005,
        harmonics=np.array([0.01])
    )

    out_3 = analyzer._apply_result_averaging(results_invalid_avg)
    print(f"Case 3 (Avg ON, Invalid): thd_valid = {out_3.get('thd_valid')}")
    assert not out_3.get('thd_valid'), "Case 3 failed"

    print("Logic verification passed!")

if __name__ == "__main__":
    test_thd_validity()

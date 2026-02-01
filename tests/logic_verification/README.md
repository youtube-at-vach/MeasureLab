# Logic Verification Tests

This directory contains tests that verify the mathematical and algorithmic correctness of the core analysis logic.

**Purpose:**
- Verify DSP algorithms against theoretical models (e.g. Sine wave RMS = -3.01dB).
- Check error bounds and tolerances (e.g. THD calculation error < 0.001%).
- Verify resilience to noise or edge cases in the math (e.g. NaN handling in math funcs, noise floor estimation).

**Contents:**
- `test_analysis_correctness.py`: Audio analysis logic (hum detection, noise profile).
- `test_frequency_counter.py`: Precision frequency estimation logic.
- `test_thd_calculation.py`: Harmonic distortion calculation accuracy.

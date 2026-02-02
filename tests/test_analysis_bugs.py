
import numpy as np
from src.core.analysis import AudioCalc

def test_lockin_empty_input():
    """
    Verify that calculate_lockin_measurement handles empty signal input gracefully
    without crashing (ZeroDivisionError or ValueError).
    """
    mag, phase = AudioCalc.calculate_lockin_measurement(
        np.array([]), 1000.0, 48000.0
    )
    assert mag == 0.0
    assert phase == 0.0

def test_analyze_harmonics_empty_input():
    """
    Verify that analyze_harmonics handles empty audio_data gracefully
    without crashing and returns a valid dictionary structure.
    """
    res = AudioCalc.analyze_harmonics(
        np.array([]), 1000.0, "hann", 48000.0
    )

    # Check essential keys
    assert "basic_wave" in res
    assert res["basic_wave"]["frequency"] == 0.0
    assert "harmonics" in res
    assert res["harmonics"] == []
    assert res["thd_percent"] == 0.0
    # Check that it doesn't return None or raise error
    assert isinstance(res, dict)

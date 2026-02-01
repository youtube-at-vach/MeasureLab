from collections import deque
from unittest.mock import MagicMock, patch

def test_calibration_poll_optimization():
    # Ensure sys.path includes src
    import sys
    from pathlib import Path
    _REPO_ROOT = Path(__file__).resolve().parents[1]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    # Import inside test
    from src.gui.widgets.timecode_monitor import TimecodeMonitor

    # Mock AudioEngine
    audio_engine = MagicMock()
    audio_engine.sample_rate = 48000

    monitor = TimecodeMonitor(audio_engine)

    # Setup calibration state manually
    monitor._cal_active = True
    monitor._cal_key = "L"
    monitor._cal_need = 30
    monitor._cal_started_at = 1000.0

    # Fill samples with known values
    # Format: (ref_t, diff, in_lat, out_lat)
    samples = []
    for i in range(100):
        samples.append((float(i), int(i), float(i), float(i)))

    monitor._cal_samples = deque(samples)

    # Mock time.time to return a time shortly after start (no timeout)
    with patch('time.time', return_value=1001.0):
        result = monitor.calibration_poll()

    assert result is not None
    assert result['ok'] is True
    assert result['samples'] == 30

    # Verify result calculation
    # We expect diffs to be the last 30 items: 70..99
    list(range(70, 100))
    # Median calculation in code:
    # diffs.sort()
    # mid = len(diffs) // 2
    # val = ...
    # len=30, mid=15.
    # diffs[15] is 70+15 = 85.
    # diffs[14] is 70+14 = 84.
    # (84+85)/2.0 = 84.5. round(84.5) -> 84.
    expected_delay = 84

    assert result['total_delay_frames'] == expected_delay

    # Case 2: Not enough samples
    monitor._cal_active = True # reset active (it was set False by success)
    monitor._cal_samples = deque(samples[:10]) # 10 items

    with patch('time.time', return_value=1001.0):
        result = monitor.calibration_poll()

    assert result is None

    # Case 3: Timeout
    monitor._cal_active = True
    monitor._cal_result = None # Reset result

    with patch('time.time', return_value=1010.0): # > 8.0s after 1000.0
        result = monitor.calibration_poll()

    assert result is not None
    assert result['ok'] is False
    assert result['reason'] == "timeout"

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from collections import deque

# Mock AudioEngine if needed
class MockAudioEngine:
    sample_rate = 48000
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, cid):
        pass

def test_deque_optimization():
    # We need to ensure we can import TimecodeMonitor
    # It imports QWidget, so we need a QApplication or just hope import works if no GUI is created?
    # PyQt6 import usually requires a display or at least successful library load.

    from src.gui.widgets.timecode_monitor import TimecodeMonitor

    ae = MockAudioEngine()
    monitor = TimecodeMonitor(ae)

    # Check _cal_samples
    # Before optimization: maxlen is None (or not set in constructor)
    # After optimization: maxlen should be 256

    # After optimization: maxlen should be set correctly

    assert isinstance(monitor._cal_samples, deque)
    assert monitor._cal_samples.maxlen == 256

    # Check channels
    ch = monitor.channels["L"]
    assert isinstance(ch.fps_intervals, deque)
    assert ch.fps_intervals.maxlen == 32

    assert isinstance(ch.jam_history, deque)
    assert ch.jam_history.maxlen == 256

if __name__ == "__main__":
    pass

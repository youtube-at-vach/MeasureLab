import threading
import unittest
import sys
import os
from unittest.mock import MagicMock

# Add src to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Mock sounddevice
sys.modules['sounddevice'] = MagicMock()

from src.core.audio_engine import VirtualStream  # noqa: E402

class TestVirtualStreamDummyTime(unittest.TestCase):
    def test_dummy_time_attributes(self):
        """
        Verify that the time object passed to the callback has the expected attributes:
        inputBufferAdcTime, outputBufferDacTime, currentTime.
        """
        callback_event = threading.Event()
        self.time_obj = None

        def callback(indata, outdata, frames, time_info, status):
            self.time_obj = time_info
            callback_event.set()

        # Create VirtualStream
        stream = VirtualStream(
            samplerate=48000,
            blocksize=1024,
            channels=(2, 2),
            callback=callback
        )

        stream.start()

        # Wait for callback
        if not callback_event.wait(timeout=2.0):
            stream.stop()
            self.fail("Callback was not called within timeout")

        stream.stop()

        # Verify attributes
        self.assertIsNotNone(self.time_obj, "Time object should not be None")
        self.assertTrue(hasattr(self.time_obj, "inputBufferAdcTime"), "Missing inputBufferAdcTime")
        self.assertTrue(hasattr(self.time_obj, "outputBufferDacTime"), "Missing outputBufferDacTime")
        self.assertTrue(hasattr(self.time_obj, "currentTime"), "Missing currentTime")

        # Verify values roughly correct (t, t+interval, t)
        t = self.time_obj.currentTime
        interval = 1024 / 48000

        self.assertAlmostEqual(self.time_obj.inputBufferAdcTime, t, delta=0.001)
        self.assertAlmostEqual(self.time_obj.outputBufferDacTime, t + interval, delta=0.001)

if __name__ == '__main__':
    unittest.main()

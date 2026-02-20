import threading
import unittest
import sys
from unittest.mock import MagicMock, patch

class TestVirtualStreamDummyTime(unittest.TestCase):
    def setUp(self):
        self.mock_sd = MagicMock()
        self.patcher = patch.dict(sys.modules, {'sounddevice': self.mock_sd})
        self.patcher.start()

        # Import module under test
        if "src.core.audio_engine" in sys.modules:
            del sys.modules["src.core.audio_engine"]

        import src.core.audio_engine
        self.VirtualStream = src.core.audio_engine.VirtualStream

    def tearDown(self):
        self.patcher.stop()
        if "src.core.audio_engine" in sys.modules:
            del sys.modules["src.core.audio_engine"]

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
        stream = self.VirtualStream(
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

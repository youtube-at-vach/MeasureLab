import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure src is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# --- Conditional Mock for numpy ---
# Only mock numpy if it's not already installed/available.
try:
    import numpy as np
except ImportError:
    mock_np = MagicMock()

    def mock_zeros(shape, dtype=None):
        m = MagicMock()
        m.shape = shape
        m.dtype = dtype
        # Allow equality check to return something truthy or expected
        m.__eq__ = lambda self, other: MagicMock()
        return m

    mock_np.zeros = mock_zeros
    mock_np.all = lambda x: True
    sys.modules["numpy"] = mock_np
    np = mock_np

# Mock sounddevice if not present
if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

from src.core.audio_engine import VirtualStream


class TestVirtualStreamTiming(unittest.TestCase):
    def setUp(self):
        self.samplerate = 1000
        self.blocksize = 100
        self.interval = 0.1
        self.callback = MagicMock()
        self.stream = VirtualStream(self.samplerate, self.blocksize, 2, self.callback)
        # Mock logger to avoid clutter
        self.stream.logger = MagicMock()

    @patch("src.core.audio_engine.time")
    def test_run_loop_normal_timing(self, mock_time):
        """Verify normal timing loop logic."""
        t0 = 1000.0

        # Scenario:
        # 1. init: next_call_time = t0
        # 2. Loop 1: t = t0 + 0.01. to_sleep = t0 - (t0+0.01) = -0.01. No sleep. next_call_time += 0.1 -> 1000.1.
        # 3. Loop 2: t = t0 + 0.02. to_sleep = 1000.1 - 1000.02 = 0.08. Sleep(0.08). next_call_time += 0.1 -> 1000.2.

        mock_time.monotonic.side_effect = [
            t0,  # init next_call_time
            t0 + 0.01,  # 1st loop t
            t0 + 0.02,  # 2nd loop t
        ]
        mock_time.time.side_effect = [2000.01, 2000.10]

        def callback_side_effect(*_args):
            if self.callback.call_count == 2:
                self.stream.active = False

        self.callback.side_effect = callback_side_effect
        self.stream._stop_event.wait = MagicMock(return_value=False)

        self.stream.active = True
        self.stream._run_loop()

        # Check wait calls
        # 1st loop: to_sleep negative, no wait.
        # 2nd loop: to_sleep = 0.08. Wait called.
        self.stream._stop_event.wait.assert_called_once()
        args, _ = self.stream._stop_event.wait.call_args
        self.assertAlmostEqual(args[0], 0.08, places=5)

        # Callback called twice
        self.assertEqual(self.callback.call_count, 2)

    @patch("src.core.audio_engine.time")
    def test_run_loop_drift_correction(self, mock_time):
        """Verify drift correction logic."""
        t0 = 1000.0

        # Scenario:
        # 1. init: next_call_time = t0
        # 2. Loop 1: t = t0 + 0.5 (Huge lag).
        #    Drift check: 1000.5 > 1000.0 + 0.1? Yes.
        #    next_call_time = 1000.5.
        #    to_sleep = 1000.5 - 1000.5 = 0. No sleep.
        #    next_call_time += 0.1 -> 1000.6.
        # 3. Loop 2: t = 1000.51.
        #    to_sleep = 1000.6 - 1000.51 = 0.09. Sleep(0.09).

        mock_time.monotonic.side_effect = [
            t0,  # init
            t0 + 0.5,  # 1st loop t (lag)
            t0 + 0.51,  # 2nd loop t
        ]
        mock_time.time.side_effect = [2000.5, 2000.6]

        def callback_side_effect(*_args):
            if self.callback.call_count == 2:
                self.stream.active = False

        self.callback.side_effect = callback_side_effect
        self.stream._stop_event.wait = MagicMock(return_value=False)

        self.stream.active = True
        self.stream._run_loop()

        # Verify wait called in 2nd loop with corrected time
        self.stream._stop_event.wait.assert_called_once()
        args, _ = self.stream._stop_event.wait.call_args
        self.assertAlmostEqual(args[0], 0.09, places=5)

        self.assertEqual(self.callback.call_count, 2)

    @patch("src.core.audio_engine.time")
    def test_run_loop_callback_exception(self, mock_time):
        """Verify loop continues after callback exception."""
        t0 = 1000.0
        mock_time.monotonic.return_value = t0
        mock_time.time.return_value = 2000.0

        def callback_side_effect(*_args):
            if self.callback.call_count == 1:
                raise ValueError("Test Error")
            self.stream.active = False

        self.callback.side_effect = callback_side_effect
        self.stream._stop_event.wait = MagicMock(return_value=False)

        self.stream.active = True
        self.stream._run_loop()

        # Verify callback called twice
        self.assertEqual(self.callback.call_count, 2)
        # Verify error logged
        self.stream.logger.error.assert_called()

    @patch("src.core.audio_engine.time")
    def test_callback_arguments(self, mock_time):
        """Verify callback arguments."""
        t0 = 1000.0
        wall_time = 2000.0
        mock_time.monotonic.return_value = t0
        mock_time.time.return_value = wall_time

        # Stop after 1 iteration
        def callback_side_effect(indata, outdata, frames, time_info, status):
            self.stream.active = False

            # Verify arguments inside callback
            self.assertEqual(frames, self.blocksize)
            self.assertEqual(indata.shape, (self.blocksize, 2))
            self.assertEqual(outdata.shape, (self.blocksize, 2))
            self.assertTrue(np.all(indata == 0))
            self.assertTrue(np.all(outdata == 0))

            # Verify time info
            self.assertEqual(time_info.currentTime, wall_time)
            self.assertEqual(time_info.inputBufferAdcTime, wall_time)
            self.assertEqual(time_info.outputBufferDacTime, wall_time + self.interval)

        self.callback.side_effect = callback_side_effect

        self.stream.active = True
        self.stream._run_loop()

        self.assertEqual(self.callback.call_count, 1)

    @patch("src.core.audio_engine.time")
    def test_stop_during_wait_does_not_emit_stale_callback(self, mock_time):
        """A stop request while sleeping must cancel the pending audio block."""
        t0 = 1000.0
        mock_time.monotonic.side_effect = [t0, t0 + 0.01, t0 + 0.02]
        mock_time.time.return_value = 2000.0

        def stop_on_wait(_duration):
            self.stream.active = False
            self.stream._stop_event.set()
            return True

        self.stream._stop_event.wait = MagicMock(side_effect=stop_on_wait)
        self.callback.side_effect = lambda *_args: None
        self.stream.active = True
        self.stream._run_loop()

        self.assertEqual(self.callback.call_count, 1)

    @patch("src.core.audio_engine.time")
    def test_wall_clock_adjustment_does_not_change_pacing(self, mock_time):
        """Wall-clock jumps affect timestamps, not callback scheduling."""
        t0 = 1000.0
        mock_time.monotonic.side_effect = [t0, t0, t0 + 0.02]
        mock_time.time.side_effect = [2000.0, 1000.0]
        self.stream._stop_event.wait = MagicMock(return_value=False)

        def callback_side_effect(*_args):
            if self.callback.call_count == 2:
                self.stream.active = False

        self.callback.side_effect = callback_side_effect
        self.stream.active = True
        self.stream._run_loop()

        self.assertEqual(self.callback.call_count, 2)
        self.stream._stop_event.wait.assert_called_once()
        wait_seconds = self.stream._stop_event.wait.call_args.args[0]
        self.assertAlmostEqual(wait_seconds, 0.08, places=9)


if __name__ == "__main__":
    unittest.main()

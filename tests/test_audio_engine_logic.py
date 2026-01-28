import unittest
from unittest.mock import MagicMock
import sys

# Mock sounddevice before importing AudioEngine
sys.modules['sounddevice'] = MagicMock()

from src.core.audio_engine import AudioEngine  # noqa: E402

class TestAudioEngineLogic(unittest.TestCase):
    def setUp(self):
        self.engine = AudioEngine()
        self.engine.stream = MagicMock() # Pretend stream is created so we don't hit _start_master_stream logic logic
        self.engine.logger = MagicMock()

    def test_register_unregister(self):
        def cb(*args):
            pass

        # Test Register
        cid = self.engine.register_callback(cb)

        # Check internal state
        self.assertIn(cid, self.engine.callbacks)
        self.assertEqual(self.engine.callbacks[cid], cb)

        # Check logging happened
        self.engine.logger.info.assert_called()
        # Verify call args
        args, _ = self.engine.logger.info.call_args
        self.assertIn(f"Registered callback {cid}", args[0])

        # Reset mock
        self.engine.logger.reset_mock()

        # Test Unregister
        self.engine.unregister_callback(cid)
        self.assertNotIn(cid, self.engine.callbacks)

        # Check logging happened
        self.engine.logger.info.assert_called()

        # We look through all calls because stop_stream might also log
        found_msg = False
        for call in self.engine.logger.info.call_args_list:
            if f"Unregistered callback {cid}" in call[0][0]:
                found_msg = True
                break

        self.assertTrue(found_msg, f"Did not find 'Unregistered callback {cid}' in logs")

    def test_unregister_nonexistent(self):
        # Unregistering a non-existent callback should not crash and might not log "Unregistered callback"
        # or it handles it gracefully.

        self.engine.unregister_callback(999)
        # Check callbacks still empty
        self.assertEqual(len(self.engine.callbacks), 0)

        # Check if it logged. The current code logs only "if callback_id in self.callbacks".
        # So it should NOT log "Unregistered callback 999"
        # Let's inspect calls.

        found_log = False
        for call in self.engine.logger.info.call_args_list:
            if "Unregistered callback 999" in call[0][0]:
                found_log = True

        self.assertFalse(found_log, "Should not log unregister for non-existent callback")

if __name__ == '__main__':
    unittest.main()

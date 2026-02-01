import unittest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from src.gui.widgets.loopback_finder import LoopbackFinder

class TestLoopbackFinderCLI(unittest.TestCase):
    def setUp(self):
        self.mock_audio_engine = MagicMock()
        self.mock_audio_engine.output_device = 1
        self.mock_audio_engine.sample_rate = 48000
        self.finder = LoopbackFinder(self.mock_audio_engine)

    def test_run_with_device_id_arg(self):
        args = Namespace(device_id=2)

        with patch.object(self.finder, 'perform_scan', return_value=[]) as mock_scan:
            self.finder.run(args)

            mock_scan.assert_called_once()
            call_args = mock_scan.call_args
            self.assertEqual(call_args[0][0], 2)  # device_id
            self.assertEqual(call_args[0][1], 48000) # sample_rate

    def test_run_without_device_id_arg(self):
        args = Namespace()

        with patch.object(self.finder, 'perform_scan', return_value=[]) as mock_scan:
            self.finder.run(args)

            mock_scan.assert_called_once()
            call_args = mock_scan.call_args
            self.assertEqual(call_args[0][0], 1)  # default from engine
            self.assertEqual(call_args[0][1], 48000)

    def test_run_with_none_device_id(self):
        args = Namespace(device_id=None)

        with patch.object(self.finder, 'perform_scan', return_value=[]) as mock_scan:
            self.finder.run(args)

            mock_scan.assert_called_once()
            call_args = mock_scan.call_args
            self.assertEqual(call_args[0][0], 1)  # default from engine

if __name__ == '__main__':
    unittest.main()


import unittest
from unittest.mock import MagicMock, patch
import sys
from PyQt6.QtCore import QObject, pyqtSignal

# Mimic the worker and signals structure
class NoiseAnalysisSignals(QObject):
    error = pyqtSignal(str)

class Worker:
    def __init__(self):
        self.signals = NoiseAnalysisSignals()

    def run(self):
        try:
            raise ValueError("Test")
        except Exception as e:
            self.signals.error.emit(str(e))

class TestSignals(unittest.TestCase):
    def test_signal_without_app(self):
        worker = Worker()
        slot = MagicMock()
        worker.signals.error.connect(slot)
        worker.run()
        slot.assert_called_once_with("Test")

if __name__ == "__main__":
    unittest.main()

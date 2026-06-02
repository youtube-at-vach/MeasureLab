import sys
import time
import threading
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread, QEventLoop, QTimer
from src.gui.widgets.distortion_analyzer import DistortionAnalyzerWidget, SweepWorker
from src.core.audio_engine import AudioEngine

app = QApplication(sys.argv)
engine = AudioEngine()

class MockModule:
    def __init__(self):
        self.audio_engine = engine
        self.buffer_size = 4096
        self.snap_to_bin_center = False
        self.gen_frequency = 1000
        self.gen_amplitude = 1.0
        self.average_count = 1
        self.capture_ready = False
        self.captured_buffer = None
        self.input_data = np.zeros(4096)
        self.window_type = "hann"
        self.filter_type = None

    def reset_averaging_state(self):
        pass

    def request_capture(self):
        self.capture_ready = False
        # simulate background capture taking 5ms
        def finish_capture():
            time.sleep(0.005) # simulate capture time
            self.capture_ready = True
            self.captured_buffer = self.input_data
        threading.Thread(target=finish_capture).start()

    def _apply_result_averaging(self, results):
        return results

module = MockModule()

def run_test():
    worker = SweepWorker(module, "frequency", 20, 20000, 10, duration_ms=10)
    # Monkeypatch the wait_time max to be just 10ms instead of 300 to focus on the capture loop
    original_run = worker.run

    # Actually let's just run it with duration_ms = 10
    start = time.time()
    worker.run()
    print(f"Elapsed: {time.time() - start:.4f}s")

run_test()

import sys
import time
from PyQt6.QtWidgets import QApplication
from src.instruments.distortion_analyzer_worker import DistortionAnalyzerModule
from src.core.audio_engine import AudioEngine

app = QApplication(sys.argv)
engine = AudioEngine()
module = DistortionAnalyzerModule(engine)

def benchmark():
    # Setup test condition
    module.snap_to_bin_center = False
    module.average_count = 1

    # Fast mock for audio callbacks and capture
    def mock_capture():
        module.captured_buffer = module.input_data.copy()
        module.capture_ready = True
    module.request_capture = mock_capture

    # We trigger run() of a SweepWorker directly
    from src.gui.widgets.distortion_analyzer import SweepWorker
    # Sweep over 100 points
    worker = SweepWorker(module, "frequency", 20, 20000, 100, duration_ms=10)

    start_time = time.time()
    worker.run()
    end_time = time.time()

    print(f"Sweep time for 100 points: {end_time - start_time:.4f} seconds")

benchmark()

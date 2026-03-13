import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.core.audio_engine import AudioEngine
from src.gui.widgets.lockin_spectrum_finder import LockInSpectrumFinder

def benchmark():
    app = QApplication(sys.argv)
    engine = AudioEngine()
    finder = LockInSpectrumFinder(engine)

    # Pre-fill some data to trigger calculation immediately
    import numpy as np
    finder.buffer_size = 8192
    finder.input_data = np.random.randn(8192, 2)
    finder.input_buffer_pos = 0
    finder.buffer_filled_samples = 8192
    finder.points = 100
    finder.mode = "Scan"

    start_time = time.perf_counter()

    # Emulate the run function to measure execution time
    finder.is_running = True
    finder.trigger_calculation()

    def check_done():
        if finder._is_calculating is False:
            end_time = time.perf_counter()
            print(f"Execution time: {end_time - start_time:.4f} seconds")
            app.quit()
        else:
            QTimer.singleShot(10, check_done)

    QTimer.singleShot(10, check_done)

    # Prevent infinite hang in test if failure
    QTimer.singleShot(5000, app.quit)
    app.exec()
    finder.cleanup()
    finder.cleanup()

if __name__ == "__main__":
    benchmark()

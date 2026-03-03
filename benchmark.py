import sys
from unittest.mock import MagicMock
sys.modules['sounddevice'] = MagicMock()
import time
import numpy as np
import scipy.signal as signal
from src.gui.widgets.sound_quality_analyzer import AnalysisWorker
from PyQt6.QtWidgets import QApplication

def benchmark():
    app = QApplication(sys.argv + ['-platform', 'offscreen'])
    sr = 48000
    duration = 10 # 10 seconds of audio
    audio = np.random.randn(sr * duration)

    worker = AnalysisWorker("dummy.wav", sr)

    # Baseline
    start = time.time()
    for _ in range(50):
        worker._calc_fluctuation_strength(audio, sr)
    baseline_time = time.time() - start

    print(f"Baseline Time (50 iterations): {baseline_time:.4f} seconds")

if __name__ == "__main__":
    benchmark()

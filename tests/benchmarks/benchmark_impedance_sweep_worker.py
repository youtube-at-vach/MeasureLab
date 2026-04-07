import time
import sys
import os
import threading
import numpy as np
from unittest.mock import MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer, ImpedanceSweepWorker, ImpedanceSweepConfig

def benchmark():
    mock_audio_engine = MagicMock()
    mock_audio_engine.sample_rate = 192000 # High sample rate

    analyzer = ImpedanceAnalyzer(mock_audio_engine)
    analyzer.buffer_size = 512 # Small buffer duration: 512 / 192000 = 0.0026s
    analyzer.set_base_buffer_size(512)
    # We set averaging count to a large value
    analyzer.averaging_count = 50

    # Simulate fast audio callback
    stop_event = threading.Event()

    config = ImpedanceSweepConfig(
        start_f=10000, end_f=20000, steps=10, log_sweep=True, settle_time=0.01, cal_mode=None
    )

    worker = ImpedanceSweepWorker(analyzer, config)

    cb_func = None
    def register(cb):
        nonlocal cb_func
        cb_func = cb
        return 1
    mock_audio_engine.register_callback = register

    def simulate_audio():
        frames_per_cb = 512
        interval = frames_per_cb / mock_audio_engine.sample_rate
        indata = np.zeros((frames_per_cb, 2))
        outdata = np.zeros((frames_per_cb, 2))
        while not stop_event.is_set():
            time.sleep(interval)
            if cb_func:
                cb_func(indata, outdata, frames_per_cb, None, None)

    t = threading.Thread(target=simulate_audio)
    t.start()

    start_time = time.time()
    worker.run()
    end_time = time.time()

    stop_event.set()
    t.join()

    print(f"Total sweep time: {end_time - start_time:.4f} seconds for {config.steps} steps.")

if __name__ == "__main__":
    benchmark()

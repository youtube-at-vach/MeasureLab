import sys
import os
import threading
import time

sys.path.append('.')

from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer, ImpedanceSweepWorker, ImpedanceSweepConfig
from unittest.mock import MagicMock

def worker_run_patched(self):
    print("Start run")
    if self.log_sweep:
        import numpy as np
        freqs = np.logspace(np.log10(self.start_f), np.log10(self.end_f), self.steps)
    else:
        freqs = np.linspace(self.start_f, self.end_f, self.steps)

    if not self.module.is_running:
        self.module.start_analysis()
        self._sleep_interruptible(0.5)

    for i, f in enumerate(freqs):
        print(f"Step {i}: f={f}")
        if self.is_cancelled:
            break

        self.module.gen_frequency = f
        self._sleep_interruptible(self.settle_time)
        print(f"  settled")
        if self.is_cancelled:
            break

        self.module.history_v.clear()
        self.module.history_i.clear()

        sample_rate = self.module.audio_engine.sample_rate
        buffer_duration = self.module.buffer_size / sample_rate
        wait_time = max(0.05, buffer_duration)
        print(f"  wait_time={wait_time}")

        self._sleep_interruptible(wait_time)
        if self.is_cancelled:
            break

        for avg in range(self.module.averaging_count):
            print(f"  avg {avg}")
            if self.is_cancelled:
                break
            self._sleep_interruptible(wait_time)
            if self.is_cancelled:
                break
            self.module.process_data(ignore_calibration=self.cal_mode in ("open", "short", "load"))

        print(f"  done avg")
        if self.cal_mode in ("open", "short", "load"):
            z = self.module.meas_z_raw
        else:
            z = self.module.meas_z_complex
        self.result.emit(f, z)
        self.progress.emit(int((i + 1) / self.steps * 100))

ImpedanceSweepWorker.run = worker_run_patched

mock_audio_engine = MagicMock()
mock_audio_engine.sample_rate = 192000
analyzer = ImpedanceAnalyzer(mock_audio_engine)
analyzer.set_base_buffer_size(512)
analyzer.averaging_count = 50
config = ImpedanceSweepConfig(start_f=10000, end_f=20000, steps=10, log_sweep=True, settle_time=0.01, cal_mode=None)
worker = ImpedanceSweepWorker(analyzer, config)

start = time.time()
worker.run()
print(time.time() - start)

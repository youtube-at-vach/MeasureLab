"""Synthetic callback microbenchmark; run with PYTHONPATH=. from the repo root.

No device I/O is performed. This measures producer cost, not hardware XRUNs.
"""

import time
import json
from types import SimpleNamespace
import numpy as np
from src.core.imd_sweep import BandPlan, SweepSettings
from src.core.imd_sweep_acquisition import SweepAcquisition, StepCapture
from src.gui.widgets.distortion_analyzer import DistortionAnalyzer

reports = []
for rate in (44100, 48000, 96000):
    for frames in (64, 256, 1024):
        callbacks = []
        engine = SimpleNamespace(
            sample_rate=rate,
            settings_generation=0,
            calibration=SimpleNamespace(settings_generation=0),
            output_overload_events=0,
            callback_error_count=0,
            register_callback=lambda cb, callbacks=callbacks: callbacks.append(cb),
        )
        module = DistortionAnalyzer(engine)
        module.signal_type = "smpte"
        module.start_analysis()
        old = callbacks[0]
        plan = BandPlan(SweepSettings(averages=32), rate)
        acq = SweepAcquisition(engine, plan, 0, 0, 0, 0)
        inp = np.zeros((frames, 2))
        out = np.zeros_like(inp)
        times = {}
        for name, callback in [("legacy_dual_tone", old), ("imd_sweep", acq.callback)]:
            durations = []
            for iteration in range(2200):
                if name == "imd_sweep" and (acq.command is None or acq.command.done):
                    acq.command = StepCapture("bench", iteration, -3, plan)
                    acq.command.settling = 0
                start = time.perf_counter_ns()
                callback(inp, out, frames, None, None)
                elapsed = time.perf_counter_ns() - start
                if name == "imd_sweep":
                    while acq.command.ready:
                        _, _, slot, _, _ = acq.command.ready.popleft()
                        acq.command.free.append(slot)
                if iteration >= 200:
                    durations.append(elapsed / 1000)
            times[name] = {"median_us": float(np.median(durations)), "p99_us": float(np.percentile(durations, 99))}
        reports.append({"rate": rate, "frames": frames, "period_us": frames / rate * 1e6, **times})
print(json.dumps(reports, indent=2))

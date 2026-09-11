"""Bounded, non-waiting audio producer for IMD sweep records."""

from collections import deque
import math

import numpy as np

from src.core.imd_sweep import BandPlan


class StepCapture:
    def __init__(self, run_id, index, level, plan: BandPlan):
        self.identity = (run_id, index)
        self.level = level
        self.amplitude = 10 ** (level / 20)
        if not math.isfinite(self.amplitude) or not 0 <= self.amplitude <= 1:
            raise ValueError("output_level_violation")
        self.buffers = [np.empty(plan.n) for _ in range(3)]
        self.free = deque(range(3))
        self.ready: deque = deque()
        self.slot = None
        self.position = 0
        self.records = 0
        self.flags: set[str] = set()
        self.settling = math.ceil(plan.settings.settling_ms * plan.sample_rate / 1000)
        self.start_sample = None
        self.end_sample = None
        self.done = False

    def feed(self, data, start_sample, plan):
        offset = 0
        while offset < len(data) and self.records < plan.settings.averages:
            if self.slot is None:
                if not self.free:
                    self.flags.add("input_discontinuity")
                    self.done = True
                    return
                self.slot = self.free.popleft()
                self.position = 0
                self.start_sample = start_sample + offset if self.start_sample is None else self.start_sample
            count = min(plan.n - self.position, len(data) - offset)
            self.buffers[self.slot][self.position : self.position + count] = data[offset : offset + count]
            offset += count
            self.position += count
            if self.position == plan.n:
                end = start_sample + offset
                # The slot stays leased until the consumer has finished its FFT.
                self.ready.append((self.identity, self.records, self.slot, end - plan.n, end))
                self.records += 1
                self.slot = None
                self.end_sample = end
        self.done = self.records == plan.settings.averages


class SweepAcquisition:
    """One producer owns phase/fade/sample positions; commands are object handoffs.

    deque append/popleft are atomic on supported CPython. No callback lock or
    wait is needed: each buffer is either free, producer-owned, or consumer-owned.
    """

    def __init__(self, engine, plan, input_channel, output_channel, generation, calibration_generation):
        self.engine = engine
        self.plan = plan
        self.input_channel = input_channel
        self.output_channel = output_channel
        self.generation = generation
        self.calibration_generation = calibration_generation
        self.command: StepCapture | None = None
        self.active: StepCapture | None = None
        self.stopping = False
        self.silent = False
        self.sample_index = 0
        self.phase1 = 0.0
        self.phase2 = 0.0
        self.amplitude = 0.0
        self.fade_start = 0.0
        self.target = 0.0
        self.fade_position = 0
        self.fade_samples = math.ceil(plan.settings.fade_ms * plan.sample_rate / 1000)
        self.fatal: str | None = None
        self.overload_events = engine.output_overload_events
        self.error_count = engine.callback_error_count

    def callback(self, indata, outdata, frames, time_info, status):
        outdata.fill(0)
        step = self.command
        try:
            self._process(step, indata, outdata, frames, status)
        except Exception:
            # Report to the worker without logging/formatting in the audio thread.
            self.fatal = "callback_exception"
            outdata.fill(0)
        self.sample_index += frames

    def _process(self, step, indata, outdata, frames, status):
        if (
            self.engine.settings_generation != self.generation
            or self.engine.calibration.settings_generation != self.calibration_generation
        ):
            self.fatal = "settings_changed"
        if self.engine.output_overload_events != self.overload_events:
            self.fatal = "output_clipping"
        if self.engine.callback_error_count != self.error_count:
            self.fatal = "callback_exception"
        if self.fatal:
            self.silent = True
            return
        if step is not self.active:
            self.active = step
            self.fade_start = self.amplitude
            self.target = step.amplitude if step is not None else 0.0
            self.fade_position = 0
        if self.stopping and self.target != 0:
            self.fade_start = self.amplitude
            self.target = 0.0
            self.fade_position = 0
        if step is not None and not step.done:
            if status and any(
                getattr(status, key, False)
                for key in ("input_underflow", "input_overflow", "output_underflow", "output_overflow")
            ):
                step.flags.add("xrun")
            if (
                indata.ndim != 2
                or len(indata) != frames
                or self.input_channel >= indata.shape[1]
                or outdata.ndim != 2
                or len(outdata) != frames
                or self.output_channel >= outdata.shape[1]
            ):
                step.flags.add("input_discontinuity")
                return
        # Vectorized generation, identical fixed frequencies across steps.
        t = np.arange(frames)
        p = self.plan.profile
        inc1, inc2 = 2 * np.pi * p.f1 / self.plan.sample_rate, 2 * np.pi * p.f2 / self.plan.sample_rate
        wave = (p.ratio * np.sin(self.phase1 + t * inc1) + np.sin(self.phase2 + t * inc2)) / (p.ratio + 1)
        self.phase1 = (self.phase1 + frames * inc1) % (2 * np.pi)
        self.phase2 = (self.phase2 + frames * inc2) % (2 * np.pi)
        remaining_fade = max(0, self.fade_samples - self.fade_position)
        if remaining_fade:
            fraction = np.minimum((t + self.fade_position + 1) / self.fade_samples, 1)
            envelope = self.fade_start + (self.target - self.fade_start) * fraction
            self.amplitude = float(envelope[-1])
            wave *= envelope
            self.fade_position += frames
        else:
            wave *= self.target
            self.amplitude = self.target
        if self.output_channel < outdata.shape[1]:
            outdata[:, self.output_channel] = wave
        if self.stopping:
            self.silent = self.amplitude == 0
            return
        if step is None or step.done or step.flags:
            return
        offset = min(frames, remaining_fade)
        settling = min(frames - offset, step.settling)
        step.settling -= settling
        offset += settling
        if offset < frames:
            step.feed(indata[offset:, self.input_channel], self.sample_index + offset, self.plan)

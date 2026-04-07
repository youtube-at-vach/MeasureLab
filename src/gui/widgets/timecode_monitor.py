import itertools
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from functools import partial
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import numpy as np

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.core.ltc import LTCDecoder, LTCEncoder
from src.measurement_modules.base import MeasurementModule
from src.gui.styles import MONOSPACE_FONT_FAMILY


@dataclass
class _LTCGenState:
    encoder: LTCEncoder
    gen_buffer: deque = field(default_factory=deque)
    gen_tc_buffer: deque = field(default_factory=deque)
    gen_current: Optional[np.ndarray] = None
    gen_current_tc: str = "--:--:--:--"
    gen_pos: int = 0
    frames_generated: int = 0
    recycle_pool: deque = field(default_factory=deque)
    tod_epoch_base: Optional[float] = None
    free_run_start_time: float = 0.0
    jam_base_total_frames: Optional[int] = None
    jam_base_fps: Optional[float] = None


@dataclass
class _JamMemory:
    valid: bool = False
    tc_raw: str = "--:--:--:--"
    captured_at: float = 0.0
    fps: float = 30.0
    total_frames: int = 0


@dataclass
class _TimecodeChannelState:
    key: str
    input_channel: int
    output_channel: int
    decoder: LTCDecoder
    fps: float = 30.0
    fps_drop_frame: bool = False
    decoded_tc: str = "--:--:--:--"
    locked: bool = False
    input_level_db: float = -100.0
    input_offset_frames: int = 0
    display_tz_enabled: bool = False
    display_tz_name: str = "System"
    generator_enabled: bool = False
    generator_mode: str = "tod"
    generator_jam_slot: int = 0
    gen_offset_frames: int = 0
    gen: _LTCGenState = None
    estimated_fps: float = 0.0
    last_frame_time: Optional[float] = None
    last_decoded_epoch: Optional[float] = None
    fps_intervals: deque = field(default_factory=partial(deque, maxlen=32))
    jam_history: deque = field(default_factory=partial(deque, maxlen=256))
    last_input_latency_sec: float = 0.0
    last_output_latency_sec: float = 0.0


class TimecodeMonitor(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.callback_id = None
        self._registered_callback = None

        # Settings (legacy convenience, maps to Left channel)
        self.fps = 30.0

        # Audio Gate
        self.gate_threshold_db = -50.0

        self.detected_fps = 0.0

        # Output linking
        self.link_enabled = False
        self.link_source = "L"  # 'L' or 'R'

        sr = int(getattr(self.audio_engine, "sample_rate", 48000))

        dec_l = LTCDecoder(sr, self.fps)
        dec_r = LTCDecoder(sr, self.fps)
        enc_l = LTCEncoder(sr, self.fps)
        enc_r = LTCEncoder(sr, self.fps)

        self.channels: Dict[str, _TimecodeChannelState] = {
            "L": _TimecodeChannelState(
                key="L",
                input_channel=0,
                output_channel=0,
                decoder=dec_l,
                fps=self.fps,
                display_tz_enabled=False,
                display_tz_name="System",
                gen=_LTCGenState(encoder=enc_l),
            ),
            "R": _TimecodeChannelState(
                key="R",
                input_channel=1,
                output_channel=1,
                decoder=dec_r,
                fps=self.fps,
                display_tz_enabled=False,
                display_tz_name="System",
                gen=_LTCGenState(encoder=enc_r),
            ),
        }

        self.jam_memories: list[_JamMemory] = [_JamMemory() for _ in range(5)]

        self._cal_lock = threading.Lock()
        self._cal_active = False
        self._cal_key = "L"
        self._cal_prev_gen_enabled: Optional[bool] = None
        self._cal_samples: deque = deque(maxlen=256)
        self._cal_need = 30
        self._cal_started_at = 0.0
        self._cal_result = None

        self._last_stream_epoch: Optional[float] = None

    def _cal_stop_generator_if_needed(self, key: str) -> None:
        prev = self._cal_prev_gen_enabled
        if prev is None:
            prev = False

        ch = self.channels.get(key)
        if ch is None:
            return

        if not bool(prev):
            ch.generator_enabled = False
            ch.gen.frames_generated = 0
            ch.gen.gen_buffer.clear()
            ch.gen.gen_tc_buffer.clear()
            ch.gen.gen_current = None
            ch.gen.gen_current_tc = "--:--:--:--"
            ch.gen.gen_pos = 0
            ch.gen.tod_epoch_base = None
            ch.gen.free_run_start_time = 0.0
            ch.gen.jam_base_total_frames = None
            ch.gen.jam_base_fps = None

    def set_fps(self, fps: float):
        fps = float(fps)
        if fps <= 0:
            return

        # Legacy behavior: update both channels.
        self.fps = fps
        self.detected_fps = 0.0

        sr = int(getattr(self.audio_engine, "sample_rate", 48000))
        for ch in self.channels.values():
            ch.fps = fps
            ch.decoder.reset(sr, fps)
            ch.decoded_tc = "--:--:--:--"
            ch.locked = False
            ch.gen.encoder.sample_rate = sr
            ch.gen.encoder.set_fps(fps)
            ch.gen.gen_buffer.clear()
            ch.gen.gen_tc_buffer.clear()
            ch.gen.gen_current = None
            ch.gen.gen_current_tc = "--:--:--:--"
            ch.gen.gen_pos = 0
            ch.gen.frames_generated = 0
            ch.gen.tod_epoch_base = None
            ch.gen.free_run_start_time = 0.0

    def set_channel_fps(self, key: str, fps: float):
        fps = float(fps)
        if fps <= 0:
            return

        sr = int(getattr(self.audio_engine, "sample_rate", 48000))
        ch = self.channels[key]
        ch.fps = fps
        ch.decoder.reset(sr, fps)
        ch.decoded_tc = "--:--:--:--"
        ch.locked = False
        ch.gen.encoder.sample_rate = sr
        ch.gen.encoder.set_fps(fps)
        ch.gen.gen_buffer.clear()
        ch.gen.gen_tc_buffer.clear()
        ch.gen.gen_current = None
        ch.gen.gen_current_tc = "--:--:--:--"
        ch.gen.gen_pos = 0
        ch.gen.frames_generated = 0
        ch.gen.tod_epoch_base = None
        ch.gen.free_run_start_time = 0.0

        if key == "L":
            self.fps = fps

    @property
    def name(self) -> str:
        return "Timecode Monitor & Generator"

    @property
    def description(self) -> str:
        return tr("LTC (Linear Timecode) Reader and Generator.")

    def get_widget(self):
        return TimecodeMonitorWidget(self)

    def start_analysis(self):
        if self.is_running:
            return

        # Be defensive: if a callback is still registered (e.g. from a previous
        # stop/start cycle), ensure it's cleaned up before registering another.
        if (self.callback_id is not None) or (self._registered_callback is not None):
            self.stop_analysis()

        self.is_running = True

        sr = int(getattr(self.audio_engine, "sample_rate", 48000))
        for ch in self.channels.values():
            ch.gen.encoder.sample_rate = sr
            ch.gen.encoder.set_fps(ch.fps)
            ch.gen.tod_epoch_base = None
            ch.gen.jam_base_total_frames = None
            ch.gen.jam_base_fps = None

            ch.decoder.reset(sr, ch.fps)
            ch.decoded_tc = "--:--:--:--"
            ch.locked = False

            ch.gen.frames_generated = 0
            ch.gen.gen_buffer.clear()
            ch.gen.gen_tc_buffer.clear()
            ch.gen.gen_current = None
            ch.gen.gen_current_tc = "--:--:--:--"
            ch.gen.gen_pos = 0
            ch.gen.free_run_start_time = 0.0

        def callback(indata, outdata, frames, time_info, status):
            # Always start from silence for this module's output.
            outdata.fill(0)

            now = time.time()
            input_adc = None
            current_t = None
            output_dac = None
            try:
                input_adc = getattr(time_info, "inputBufferAdcTime", None)
                current_t = getattr(time_info, "currentTime", None)
                output_dac = getattr(time_info, "outputBufferDacTime", None)
            except Exception:
                input_adc = None
                current_t = None
                output_dac = None

            # IMPORTANT: PortAudio time_info times are in the stream timebase
            # (not guaranteed to be Unix epoch). Convert them to an epoch-like
            # timebase by estimating an offset from time.time().
            epoch_now = float(now)
            epoch_offset = 0.0
            if current_t is not None:
                try:
                    epoch_offset = float(epoch_now) - float(current_t)
                except Exception:
                    epoch_offset = 0.0

            if current_t is None:
                current_t_epoch = float(epoch_now)
            else:
                current_t_epoch = float(current_t) + float(epoch_offset)

            input_adc_epoch = None
            if input_adc is not None:
                try:
                    input_adc_epoch = float(input_adc) + float(epoch_offset)
                except Exception:
                    input_adc_epoch = None

            output_dac_epoch = None
            if output_dac is not None:
                try:
                    output_dac_epoch = float(output_dac) + float(epoch_offset)
                except Exception:
                    output_dac_epoch = None

            self._last_stream_epoch = (
                float(output_dac_epoch) if output_dac_epoch is not None else float(current_t_epoch)
            )

            for ch in self.channels.values():
                if indata is not None and getattr(indata, "shape", None) is not None:
                    if indata.shape[1] > ch.input_channel:
                        in_sig = indata[:, ch.input_channel]

                        rms = np.sqrt(np.mean(in_sig**2))
                        ch.input_level_db = 20 * np.log10(rms + 1e-9)

                        if ch.input_level_db > self.gate_threshold_db:
                            process_sig = in_sig
                        else:
                            process_sig = np.zeros_like(in_sig)

                        decoded = ch.decoder.process_samples(process_sig)
                        if decoded:
                            ch.decoded_tc = ch.decoder.decoded_tc
                            ch.locked = bool(ch.decoder.locked)

                            if input_adc_epoch is not None:
                                try:
                                    ch.last_input_latency_sec = float(current_t_epoch) - float(input_adc_epoch)
                                except Exception:
                                    pass
                            if output_dac_epoch is not None:
                                try:
                                    ch.last_output_latency_sec = float(output_dac_epoch) - float(current_t_epoch)
                                except Exception:
                                    pass

                            frame_t_epoch = float(now)
                            try:
                                off = getattr(ch.decoder, "last_frame_offset_in_chunk", None)
                                sr = int(getattr(self.audio_engine, "sample_rate", 48000))
                                if sr > 0 and input_adc_epoch is not None and off is not None:
                                    frame_t_epoch = float(input_adc_epoch) + (float(off) / float(sr))
                            except Exception:
                                frame_t_epoch = float(now)

                            if ch.last_frame_time is not None:
                                dt = float(frame_t_epoch - ch.last_frame_time)
                                if 0.015 <= dt <= 0.08:
                                    ch.fps_intervals.append(dt)
                                    avg = float(sum(ch.fps_intervals)) / float(len(ch.fps_intervals))
                                    if avg > 0:
                                        ch.estimated_fps = 1.0 / avg
                            ch.last_frame_time = float(frame_t_epoch)
                            ch.last_decoded_epoch = float(frame_t_epoch)

                            if self._cal_active and ch.key == self._cal_key:
                                parsed_dec = self._parse_tc(ch.decoded_tc)
                                if parsed_dec is not None:
                                    fps = float(ch.fps) if ch.fps else 30.0
                                    if fps <= 0:
                                        fps = 30.0
                                    nominal_fps = int(round(fps))
                                    if nominal_fps <= 0:
                                        nominal_fps = 30

                                    sr = int(getattr(self.audio_engine, "sample_rate", 48000))
                                    if sr <= 0:
                                        sr = 48000

                                    # Reference time for expected TC: input buffer mid-point time.
                                    # If PortAudio ADC time isn't available, fall back to callback time.
                                    ref_t = float(current_t_epoch)
                                    if input_adc_epoch is not None:
                                        ref_t = float(input_adc_epoch) + (float(frames) / (2.0 * float(sr)))

                                    exp_tc = self._tc_from_timestamp(float(ref_t), float(fps))
                                    parsed_exp = self._parse_tc(exp_tc)
                                    if parsed_exp is not None:
                                        hh, mm, ss, ff = parsed_dec
                                        dec_total = ((hh * 3600 + mm * 60 + ss) * nominal_fps) + int(ff)
                                        eh, em, es, ef = parsed_exp
                                        exp_total = ((eh * 3600 + em * 60 + es) * nominal_fps) + int(ef)
                                        frames_per_day = 24 * 3600 * nominal_fps
                                        if frames_per_day > 0:
                                            diff = (int(exp_total) - int(dec_total)) % int(frames_per_day)
                                            if diff > frames_per_day // 2:
                                                diff -= frames_per_day
                                        else:
                                            diff = int(exp_total) - int(dec_total)

                                        with self._cal_lock:
                                            self._cal_samples.append(
                                                (
                                                    float(ref_t),
                                                    int(diff),
                                                    float(getattr(ch, "last_input_latency_sec", 0.0)),
                                                    float(getattr(ch, "last_output_latency_sec", 0.0)),
                                                )
                                            )

                            parsed = self._parse_tc(ch.decoded_tc)
                            if parsed is not None:
                                fps = float(ch.fps) if ch.fps else 30.0
                                nominal_fps = int(round(fps))
                                if nominal_fps <= 0:
                                    nominal_fps = 30
                                hh, mm, ss, ff = parsed
                                total_frames = ((hh * 3600 + mm * 60 + ss) * nominal_fps) + int(ff)
                                ch.jam_history.append((float(frame_t_epoch), int(total_frames)))

            if self.link_enabled:
                src_key = self.link_source if self.link_source in self.channels else "L"
                src = self.channels[src_key]
                if src.generator_enabled:
                    gen = self._get_generator_samples(src, frames)
                    if gen is not None and len(gen) == frames:
                        gen = gen * 0.5
                        out_ch = outdata.shape[1]
                        if out_ch > 0:
                            for dst_key in ("L", "R"):
                                dst = self.channels[dst_key]
                                out_idx = int(dst.output_channel)
                                if 0 <= out_idx < out_ch:
                                    outdata[:, out_idx] = gen
            else:
                for ch in self.channels.values():
                    if ch.generator_enabled:
                        gen = self._get_generator_samples(ch, frames)
                        if gen is not None and len(gen) == frames:
                            gen = gen * 0.5

                            out_ch = outdata.shape[1]
                            if out_ch <= 0:
                                continue

                            out_idx = int(ch.output_channel)
                            if out_idx < 0 or out_idx >= out_ch:
                                continue

                            outdata[:, out_idx] = gen

        # Keep a reference to the exact callback function object so we can
        # locate/unregister it even if the numeric ID is lost.
        self._registered_callback = callback
        self.callback_id = self.audio_engine.register_callback(callback)

    def _find_registered_callback_id(self) -> Optional[int]:
        """Best-effort lookup of our registered callback ID.

        This is a defensive fallback for cases where the numeric callback ID was
        lost (e.g. a historical bug where callback_id=0 was treated as falsy).
        """
        cb = getattr(self, "_registered_callback", None)
        if cb is None:
            return None

        engine = getattr(self, "audio_engine", None)
        callbacks = getattr(engine, "callbacks", None)
        lock = getattr(engine, "lock", None)
        if callbacks is None:
            return None

        try:
            if lock is None:
                for cid, fn in list(callbacks.items()):
                    if fn is cb:
                        return int(cid)
                return None

            with lock:
                for cid, fn in list(callbacks.items()):
                    if fn is cb:
                        return int(cid)
        except Exception:
            return None

        return None

    def _get_generator_samples(self, ch: _TimecodeChannelState, frames: int) -> np.ndarray:
        """Return exactly `frames` samples of generated LTC (mono)."""
        if frames <= 0:
            return np.zeros((0,), dtype=np.float32)

        out = np.zeros((frames,), dtype=np.float32)
        out_pos = 0

        while out_pos < frames:
            if ch.gen.gen_current is None or ch.gen.gen_pos >= len(ch.gen.gen_current):
                if ch.gen.gen_current is not None:
                    # Recycle the underlying buffer if possible
                    cand = ch.gen.gen_current
                    if getattr(cand, "base", None) is not None:
                        cand = cand.base

                    if isinstance(cand, np.ndarray):
                        if len(ch.gen.recycle_pool) < 16:
                            ch.gen.recycle_pool.append(cand)
                    ch.gen.gen_current = None

                if ch.gen.gen_buffer:
                    ch.gen.gen_current = ch.gen.gen_buffer.popleft()
                    if ch.gen.gen_tc_buffer:
                        ch.gen.gen_current_tc = str(ch.gen.gen_tc_buffer.popleft())
                    else:
                        ch.gen.gen_current_tc = "--:--:--:--"
                    ch.gen.gen_pos = 0
                else:
                    self._generate_next_frame(ch)
                    continue

            remaining_out = frames - out_pos
            remaining_in = len(ch.gen.gen_current) - ch.gen.gen_pos
            to_copy = remaining_out if remaining_out < remaining_in else remaining_in

            if to_copy > 0:
                out[out_pos : out_pos + to_copy] = ch.gen.gen_current[ch.gen.gen_pos : ch.gen.gen_pos + to_copy]
                out_pos += to_copy
                ch.gen.gen_pos += to_copy

        return out

    def _generate_next_frame(self, ch: _TimecodeChannelState):
        if ch.generator_mode == "jam":
            fps = float(ch.fps) if ch.fps else 30.0
            if fps <= 0:
                fps = 30.0

            slot = int(ch.generator_jam_slot) if ch.generator_jam_slot is not None else 0
            if slot < 0:
                slot = 0
            elif slot > 4:
                slot = 4

            base = ch.gen.jam_base_total_frames
            base_fps = ch.gen.jam_base_fps
            if base is None or base_fps is None or abs(float(base_fps) - float(fps)) > 1e-6:
                mem = self.jam_memories[slot] if 0 <= slot < len(self.jam_memories) else None
                if mem is None or (not mem.valid):
                    base = 0
                else:
                    mem_fps = float(mem.fps) if mem.fps else 30.0
                    mem_nominal_fps = int(round(mem_fps))
                    if mem_nominal_fps <= 0:
                        mem_nominal_fps = 30

                    gen_nominal_fps = int(round(fps))
                    if gen_nominal_fps <= 0:
                        gen_nominal_fps = 30

                    base_seconds = float(mem.total_frames) / float(mem_nominal_fps)
                    now_epoch = float(getattr(self, "_last_stream_epoch", None) or time.time())
                    elapsed_seconds = float(now_epoch) - float(mem.captured_at)
                    current_seconds = base_seconds + float(elapsed_seconds)
                    current_seconds = current_seconds % 86400.0

                    base = int(math.floor(current_seconds * float(gen_nominal_fps)))
                ch.gen.jam_base_total_frames = int(base)
                ch.gen.jam_base_fps = float(fps)

            offset_frames = int(getattr(ch, "gen_offset_frames", 0) or 0)
            total_frames = int(ch.gen.jam_base_total_frames) + int(ch.gen.frames_generated) + int(offset_frames)

            nominal_fps = int(round(fps))
            if nominal_fps <= 0:
                nominal_fps = 30

            frames_per_day = 24 * 3600 * nominal_fps
            if frames_per_day > 0:
                total_frames = total_frames % frames_per_day

            hh = int(total_frames // (3600 * nominal_fps))
            rem = int(total_frames % (3600 * nominal_fps))
            mm = int(rem // (60 * nominal_fps))
            rem = int(rem % (60 * nominal_fps))
            ss = int(rem // nominal_fps)
            ff = int(rem % nominal_fps)

            ch.gen.frames_generated += 1

        elif ch.generator_mode == "free":
            # Relative to start
            if ch.gen.free_run_start_time == 0:
                ch.gen.free_run_start_time = time.time()

            # Simple frame counter
            total_frames = ch.gen.frames_generated
            # Or based on time?
            # Let's just increment frame by frame to ensure continuity.
            # But we need to initialize 'total_frames' based on 'free_run_start_time'?
            # For free run, we usually just start at 00:00:00:00 or user set value.
            # Let's implement continuous increment.

            # Calculate TC from total frames
            # fps
            fps = float(ch.fps) if ch.fps else 30.0
            hh = int(total_frames / (fps * 3600)) % 24
            rem = total_frames % (int(fps * 3600))
            mm = int(rem / (fps * 60))
            rem = rem % (int(fps * 60))
            ss = int(rem / fps)
            ff = int(rem % fps)

            ch.gen.frames_generated += 1

        else:
            # Time of Day (system local time).
            # Use a stable epoch base + frame counter so we don't jitter/jump due
            # to callback scheduling or buffer prefill.
            if ch.gen.tod_epoch_base is None:
                ch.gen.tod_epoch_base = time.time()

            fps = float(ch.fps) if ch.fps else 30.0
            if fps <= 0:
                fps = 30.0

            offset_frames = int(getattr(ch, "gen_offset_frames", 0) or 0)
            t_target = ch.gen.tod_epoch_base + ((ch.gen.frames_generated + offset_frames) / fps)
            # Use UTC for LTC generation always. Display converts to Local if needed.
            dt = datetime.fromtimestamp(t_target, timezone.utc)

            hh = dt.hour
            mm = dt.minute
            ss = dt.second

            frac = t_target - math.floor(t_target)
            ff = int(frac * fps)
            nominal_fps = int(round(fps))
            if nominal_fps <= 0:
                nominal_fps = 30
            if ff < 0:
                ff = 0
            elif ff >= nominal_fps:
                ff = nominal_fps - 1

            ch.gen.frames_generated += 1

        tc = f"{int(hh):02}:{int(mm):02}:{int(ss):02}:{int(ff):02}"

        # Attempt to reuse buffer from recycle pool
        out_buf = None
        req_size = int(ch.gen.encoder.samples_per_frame) + 2
        while ch.gen.recycle_pool:
            cand = ch.gen.recycle_pool.pop()
            if len(cand) >= req_size:
                out_buf = cand
                break
            # Discard too-small buffers (e.g. if FPS changed)

        samples = ch.gen.encoder.generate_frame(hh, mm, ss, ff, out_buffer=out_buf)
        ch.gen.gen_buffer.append(samples)
        ch.gen.gen_tc_buffer.append(tc)

    def stop_analysis(self):
        cid = self.callback_id

        # callback_id can be 0 (valid). Use explicit None checks.
        if cid is None:
            cid = self._find_registered_callback_id()

        if cid is not None:
            try:
                self.audio_engine.unregister_callback(cid)
            except Exception:
                pass

        self.callback_id = None
        self._registered_callback = None
        self.is_running = False

    def process(self):
        left = self.channels["L"]
        right = self.channels["R"]
        return {
            "fps": float(left.fps),
            "L": {
                "fps": float(left.fps),
                "fps_est": float(left.estimated_fps),
                "tc": self._get_display_timecode(left.decoded_tc, left.input_offset_frames, key="L"),
                "tc_raw": left.decoded_tc,
                "locked": bool(left.locked),
                "level": float(left.input_level_db),
            },
            "R": {
                "fps": float(right.fps),
                "fps_est": float(right.estimated_fps),
                "tc": self._get_display_timecode(right.decoded_tc, right.input_offset_frames, key="R"),
                "tc_raw": right.decoded_tc,
                "locked": bool(right.locked),
                "level": float(right.input_level_db),
            },
        }

    def calibration_start(self, key: str, need_frames: Optional[int] = None) -> None:
        k = str(key) if key in self.channels else "L"
        fps = float(self.channels[k].fps) if self.channels[k].fps else 30.0
        if fps <= 0:
            fps = 30.0
        n = int(round(fps)) if need_frames is None else int(need_frames)
        if n <= 0:
            n = 30

        with self._cal_lock:
            self._cal_active = True
            self._cal_key = k
            self._cal_prev_gen_enabled = bool(self.channels[k].generator_enabled)
            self._cal_samples.clear()
            self._cal_need = int(n)
            self._cal_started_at = time.time()
            self._cal_result = None

    def calibration_poll(self):
        with self._cal_lock:
            if not self._cal_active:
                return self._cal_result

            need = int(self._cal_need)
            started = float(self._cal_started_at)
            key = str(self._cal_key)

            # Optimization: avoid full list copy of the deque.
            # We only need the last 'need' samples.
            current_len = len(self._cal_samples)
            if current_len < need:
                samples = []
            else:
                # Efficiently retrieve last 'need' elements by iterating from the end
                rev_samples = list(itertools.islice(reversed(self._cal_samples), need))
                samples = rev_samples[::-1]

        if (time.time() - started) > 8.0:
            with self._cal_lock:
                self._cal_active = False
                if self._cal_result is None:
                    self._cal_result = {"ok": False, "reason": "timeout"}
            self._cal_stop_generator_if_needed(key)
            return self._cal_result

        if len(samples) < need:
            return None

        arr = np.array(samples)
        diffs = arr[:, 1].astype(int).tolist()
        out_lat = arr[:, 3].astype(float).tolist()

        diffs.sort()
        mid = len(diffs) // 2
        total_delay_frames = (
            int(diffs[mid]) if (len(diffs) % 2 == 1) else int(round((diffs[mid - 1] + diffs[mid]) / 2.0))
        )

        out_lat.sort()
        mid2 = len(out_lat) // 2
        out_sec = float(out_lat[mid2]) if (len(out_lat) % 2 == 1) else float((out_lat[mid2 - 1] + out_lat[mid2]) / 2.0)

        ch = self.channels[key]
        fps = float(ch.fps) if ch.fps else 30.0
        if fps <= 0:
            fps = 30.0

        out_frames = int(round(float(out_sec) * float(fps)))
        in_frames = int(total_delay_frames) - int(out_frames)

        for dst_key in ("L", "R"):
            dst = self.channels.get(dst_key)
            if dst is None:
                continue
            dst.gen_offset_frames = int(out_frames)
            dst.input_offset_frames = int(in_frames)

        with self._cal_lock:
            self._cal_active = False
            self._cal_result = {
                "ok": True,
                "key": str(key),
                "samples": int(need),
                "total_delay_frames": int(total_delay_frames),
                "in_delay_frames": int(in_frames),
                "out_delay_frames": int(out_frames),
            }

        self._cal_stop_generator_if_needed(key)
        return self._cal_result

    def jam_capture(self, key: str, slot: int) -> bool:
        if key not in self.channels:
            return False

        s = int(slot)
        if s < 0:
            s = 0
        elif s > 4:
            s = 4

        ch = self.channels[key]
        parsed = self._parse_tc(ch.decoded_tc)
        if parsed is None:
            return False

        fps = float(ch.fps) if ch.fps else 30.0
        nominal_fps = int(round(fps))
        if nominal_fps <= 0:
            nominal_fps = 30

        hh, mm, ss, ff = parsed
        total_frames = ((hh * 3600 + mm * 60 + ss) * nominal_fps) + int(ff)

        # Apply input delay compensation (if any)
        try:
            total_frames += int(ch.input_offset_frames)
        except Exception:
            pass

        mem = self.jam_memories[s]
        mem.valid = True
        mem.tc_raw = ch.decoded_tc
        mem.captured_at = float(getattr(ch, "last_decoded_epoch", None) or time.time())
        mem.fps = float(fps)
        mem.total_frames = int(total_frames)
        self.jam_memories[s] = mem
        return True

    def jam_capture_precise(self, key: str, slot: int, window_seconds: float = 0.8, min_samples: int = 12) -> bool:
        if key not in self.channels:
            return False

        s = int(slot)
        if s < 0:
            s = 0
        elif s > 4:
            s = 4

        ch = self.channels[key]
        if not ch.jam_history:
            return False

        fps = float(ch.fps) if ch.fps else 30.0
        if fps <= 0:
            fps = 30.0
        nominal_fps = int(round(fps))
        if nominal_fps <= 0:
            nominal_fps = 30

        now = time.time()
        window = float(window_seconds)
        if window <= 0:
            window = 0.8

        jam_hist = list(ch.jam_history)
        if not jam_hist:
            return False

        samples_np = np.array(jam_hist, dtype=np.float64)
        t_all = samples_np[:, 0]
        f_all = samples_np[:, 1].astype(np.int64)

        mask_window = (float(now) - t_all) <= window

        if np.sum(mask_window) < int(min_samples):
            n_keep = max(int(min_samples), 1)
            t_samples = t_all[-n_keep:]
            f_samples = f_all[-n_keep:]
        else:
            t_samples = t_all[mask_window]
            f_samples = f_all[mask_window]

        if len(t_samples) < int(min_samples):
            return False

        # Sort by time
        sort_idx = np.argsort(t_samples)
        t_samples = t_samples[sort_idx]
        f_samples = f_samples[sort_idx]

        frames_per_day = int(24 * 3600 * nominal_fps)
        if frames_per_day > 0:
            diffs = np.diff(f_samples)
            offsets = np.zeros_like(diffs, dtype=np.int64)
            offsets[diffs < -(frames_per_day // 2)] = frames_per_day
            offsets[diffs > (frames_per_day // 2)] = -frames_per_day
            offset_cumsum = np.concatenate(([0], np.cumsum(offsets)))
            f_u = f_samples + offset_cumsum
        else:
            f_u = f_samples

        o_arr = f_u.astype(np.float64) - (float(fps) * t_samples)
        if len(o_arr) == 0:
            return False

        med = np.median(o_arr)
        abs_dev = np.abs(o_arr - med)
        mad = np.median(abs_dev)
        if mad <= 1e-9:
            mad = 0.0

        if mad == 0.0:
            keep_mask = np.ones(len(o_arr), dtype=bool)
        else:
            keep_mask = abs_dev <= (3.0 * mad)

        if np.sum(keep_mask) < int(min_samples):
            keep_t = t_samples
            keep_f = f_u
        else:
            keep_t = t_samples[keep_mask]
            keep_f = f_u[keep_mask]

        offsets2 = keep_f.astype(np.float64) - (float(fps) * keep_t)
        b = float(np.median(offsets2))

        f_last = int(keep_f[-1])
        if float(fps) <= 0:
            return False
        captured_at = (float(f_last) - float(b)) / float(fps)

        # Apply input delay compensation (if any)
        final_total_frames = int(f_last)
        try:
            final_total_frames += int(ch.input_offset_frames)
        except Exception:
            pass

        mem = self.jam_memories[s]
        mem.valid = True
        mem.tc_raw = ch.decoded_tc
        mem.captured_at = float(captured_at)
        mem.fps = float(fps)
        mem.total_frames = int(final_total_frames)
        self.jam_memories[s] = mem
        return True

    def jam_capture_auto_precise(self, key: str) -> int:
        if key not in self.channels:
            return -1

        free_idx = None
        oldest_idx = 0
        oldest_ts = float("inf")
        for i, m in enumerate(self.jam_memories):
            if not m.valid and free_idx is None:
                free_idx = i
            if m.valid and float(m.captured_at) < oldest_ts:
                oldest_ts = float(m.captured_at)
                oldest_idx = i

        idx = int(free_idx) if free_idx is not None else int(oldest_idx)
        ok = self.jam_capture_precise(key, idx)
        if not ok:
            ok = self.jam_capture(key, idx)
        return idx if ok else -1

    def jam_get_current_tc(self, slot: int) -> str:
        s = int(slot)
        if s < 0:
            s = 0
        elif s > 4:
            s = 4

        mem = self.jam_memories[s]
        if not mem.valid:
            return "--:--:--:--"

        fps = float(mem.fps) if mem.fps else 30.0
        nominal_fps = int(round(fps))
        if nominal_fps <= 0:
            nominal_fps = 30

        now = time.time()
        elapsed_frames = int(math.floor((float(now) - float(mem.captured_at)) * float(fps)))
        total_frames = int(mem.total_frames) + int(elapsed_frames)
        frames_per_day = 24 * 3600 * nominal_fps
        if frames_per_day > 0:
            total_frames = total_frames % frames_per_day

        hh = int(total_frames // (3600 * nominal_fps))
        rem = int(total_frames % (3600 * nominal_fps))
        mm = int(rem // (60 * nominal_fps))
        rem = int(rem % (60 * nominal_fps))
        ss = int(rem // nominal_fps)
        ff = int(rem % nominal_fps)
        return f"{hh:02}:{mm:02}:{ss:02}:{ff:02}"

    def _parse_tc(self, tc: str):
        """Parse 'HH:MM:SS:FF' into ints. Returns (hh, mm, ss, ff) or None."""
        if not tc or tc.count(":") != 3:
            return None
        try:
            hh_s, mm_s, ss_s, ff_s = tc.split(":")
            hh = int(hh_s)
            mm = int(mm_s)
            ss = int(ss_s)
            ff = int(ff_s)
        except Exception:
            return None

        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 60 and 0 <= ff <= 99):
            return None
        return hh, mm, ss, ff

    def _tc_from_timestamp(self, t: float, fps: float) -> str:
        if fps <= 0:
            fps = 30.0
        nominal_fps = int(round(fps))
        if nominal_fps <= 0:
            nominal_fps = 30

        dt = datetime.fromtimestamp(float(t), timezone.utc)
        hh = dt.hour
        mm = dt.minute
        ss = dt.second
        frac = float(t) - math.floor(float(t))
        ff = int(frac * float(fps))
        if ff < 0:
            ff = 0
        elif ff >= nominal_fps:
            ff = nominal_fps - 1
        return f"{hh:02}:{mm:02}:{ss:02}:{ff:02}"

    def _get_display_timecode(
        self, tc: Optional[str] = None, input_offset_ms: Optional[float] = None, key: str = "L"
    ) -> str:
        """Return display timecode string.

        Applies optional input delay compensation and optional timezone display conversion.
        (LTC does not carry a date; we use today's UTC date for TZ conversion.)
        """
        ch = self.channels.get(key, self.channels["L"])

        if tc is None:
            tc = ch.decoded_tc

        if input_offset_ms is None:
            try:
                input_offset_ms = float(ch.input_offset_frames)
            except Exception:
                input_offset_ms = 0.0

        if (not ch.display_tz_enabled) and (abs(float(input_offset_ms)) < 1e-9):
            return tc

        parsed = self._parse_tc(tc)
        if parsed is None:
            return tc

        hh, mm, ss, ff = parsed
        fps = float(ch.fps) if ch.fps else 30.0
        if fps <= 0:
            fps = 30.0

        try:
            nominal_fps = int(round(fps))
            if nominal_fps <= 0:
                nominal_fps = 30

            offset_seconds = float(input_offset_ms) / float(fps)

            # Seconds-of-day from decoded LTC.
            total_seconds = (hh * 3600.0) + (mm * 60.0) + float(min(ss, 59)) + (float(ff) / fps)
            total_seconds += float(offset_seconds)

            if not ch.display_tz_enabled:
                # Pure offset + wrap within 24h.
                total_seconds = total_seconds % 86400.0
                disp_h = int(total_seconds // 3600)
                total_seconds -= disp_h * 3600
                disp_m = int(total_seconds // 60)
                total_seconds -= disp_m * 60
                disp_s = int(total_seconds)
                frac = total_seconds - disp_s
                disp_f = int(frac * fps)
                if disp_f < 0:
                    disp_f = 0
                elif disp_f >= nominal_fps:
                    disp_f = nominal_fps - 1
                return f"{disp_h:02}:{disp_m:02}:{disp_s:02}:{disp_f:02}"

            # TZ display enabled: interpret decoded time-of-day as UTC.
            utc_today = datetime.now(timezone.utc).date()
            base_utc = datetime(
                utc_today.year,
                utc_today.month,
                utc_today.day,
                0,
                0,
                0,
                0,
                tzinfo=timezone.utc,
            )
            dt_utc = base_utc + timedelta(seconds=total_seconds)

            tz_name = (ch.display_tz_name or "System").strip()
            if tz_name.lower() == "utc":
                tz = timezone.utc
            elif tz_name.lower() == "system":
                tz = datetime.now().astimezone().tzinfo
            else:
                if ZoneInfo is None:
                    tz = datetime.now().astimezone().tzinfo
                else:
                    tz = ZoneInfo(tz_name)

            dt_disp = dt_utc.astimezone(tz)
            frac = dt_disp.microsecond / 1_000_000.0
            ff_disp = int(frac * fps)
            if ff_disp < 0:
                ff_disp = 0
            elif ff_disp >= nominal_fps:
                ff_disp = nominal_fps - 1

            return f"{dt_disp.hour:02}:{dt_disp.minute:02}:{dt_disp.second:02}:{ff_disp:02}"
        except Exception:
            return tc

    @property
    def decoded_tc(self) -> str:
        return self.channels["L"].decoded_tc

    @decoded_tc.setter
    def decoded_tc(self, v: str):
        self.channels["L"].decoded_tc = v

    @property
    def input_offset_ms(self) -> float:
        ch = self.channels["L"]
        fps = float(ch.fps) if ch.fps else 30.0
        if fps <= 0:
            fps = 30.0
        return (float(ch.input_offset_frames) / float(fps)) * 1000.0

    @input_offset_ms.setter
    def input_offset_ms(self, v: float):
        ch = self.channels["L"]
        fps = float(ch.fps) if ch.fps else 30.0
        if fps <= 0:
            fps = 30.0
        ch.input_offset_frames = int(round((float(v) / 1000.0) * float(fps)))

    @property
    def gen_offset_ms(self) -> float:
        ch = self.channels["L"]
        fps = float(ch.fps) if ch.fps else 30.0
        if fps <= 0:
            fps = 30.0
        return (float(ch.gen_offset_frames) / float(fps)) * 1000.0

    @gen_offset_ms.setter
    def gen_offset_ms(self, v: float):
        ch = self.channels["L"]
        fps = float(ch.fps) if ch.fps else 30.0
        if fps <= 0:
            fps = 30.0
        ch.gen_offset_frames = int(round((float(v) / 1000.0) * float(fps)))

    @property
    def generator_enabled(self) -> bool:
        return bool(self.channels["L"].generator_enabled)

    @generator_enabled.setter
    def generator_enabled(self, v: bool):
        self.channels["L"].generator_enabled = bool(v)

    @property
    def generator_mode(self) -> str:
        return str(self.channels["L"].generator_mode)

    @generator_mode.setter
    def generator_mode(self, v: str):
        self.channels["L"].generator_mode = str(v)

    @property
    def display_tz_enabled(self) -> bool:
        return bool(self.channels["L"].display_tz_enabled)

    @display_tz_enabled.setter
    def display_tz_enabled(self, v: bool):
        self.channels["L"].display_tz_enabled = bool(v)

    @property
    def display_tz_name(self) -> str:
        return str(self.channels["L"].display_tz_name)

    @display_tz_name.setter
    def display_tz_name(self, v: str):
        self.channels["L"].display_tz_name = str(v)


class TimecodeMonitorWidget(QWidget):
    def __init__(self, module: TimecodeMonitor):
        super().__init__()
        self.module = module
        self._gen_buttons: Dict[str, QPushButton] = {}
        self._gen_out_labels: Dict[str, QLabel] = {}
        self._mode_combos: Dict[str, QComboBox] = {}
        self._jam_slot_combos: Dict[str, QComboBox] = {}
        self._tz_combos: Dict[str, QComboBox] = {}
        self._in_delay_spins: Dict[str, QSpinBox] = {}
        self._out_delay_spins: Dict[str, QSpinBox] = {}

        # UI update timer (runs only while monitoring is active).
        self.timer = QTimer(self)
        self.timer.setInterval(50)  # 20Hz UI update
        self.timer.timeout.connect(self.update_ui)

        self._monitor_toggle_btn: Optional[QPushButton] = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        display_row = QHBoxLayout()

        self.tc_label_L = QLabel("--:--:--:--")
        self.tc_label_R = QLabel("--:--:--:--")
        self.sync_led_L = QLabel(tr("SYNC"))
        self.sync_led_R = QLabel(tr("SYNC"))
        self.fps_est_label_L = QLabel(tr("FPS: --"))
        self.fps_est_label_R = QLabel(tr("FPS: --"))
        self.level_label_L = QLabel("-- dB")
        self.level_label_R = QLabel("-- dB")

        def build_display_frame(
            title: str, key: str, tc_label: QLabel, sync_led: QLabel, fps_label: QLabel, level_label: QLabel
        ):
            frame = QFrame()
            frame.setStyleSheet("background-color: #111; border: 2px solid #555; border-radius: 8px;")
            v = QVBoxLayout(frame)
            v.setContentsMargins(8, 6, 8, 6)
            v.setSpacing(4)

            header = QHBoxLayout()
            hdr = QLabel(title)
            hdr.setStyleSheet("color: #888; font-weight: bold;")
            header.addWidget(hdr)
            header.addStretch()
            v.addLayout(header)

            tc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # QFont constructor takes a single family name.
            # We use the first one from our stack and rely on Qt's internal fallback,
            # or pass the first one and then set the families list.
            font_families = [f.strip() for f in MONOSPACE_FONT_FAMILY.split(",")]
            font = QFont()
            font.setFamilies(font_families)
            font.setPointSize(44)
            font.setWeight(QFont.Weight.Bold)
            tc_label.setFont(font)
            tc_label.setStyleSheet("color: #ff3333;")
            v.addWidget(tc_label)

            jam_row = QHBoxLayout()
            jam_btn = QPushButton(tr("JAM"))
            jam_btn.setMinimumHeight(26)
            jam_btn.clicked.connect(lambda _=False, k=key: self._on_jam_capture_auto(k))
            jam_row.addWidget(jam_btn)
            jam_msg = QLabel("")
            jam_msg.setStyleSheet("color: #888;")
            jam_row.addWidget(jam_msg)
            jam_row.addStretch()
            v.addLayout(jam_row)

            self._jam_capture_msg[key] = jam_msg

            status = QHBoxLayout()
            sync_led.setStyleSheet(
                "color: #333; font-weight: bold; border: 1px solid #333; padding: 2px 5px; border-radius:4px;"
            )
            status.addWidget(sync_led)

            fps_label.setStyleSheet("color: #888;")
            status.addWidget(fps_label)
            status.addStretch()
            level_label.setStyleSheet("color: #888;")
            status.addWidget(level_label)
            v.addLayout(status)
            return frame

        self._jam_capture_msg = {}
        display_row.addWidget(
            build_display_frame(
                tr("Left"), "L", self.tc_label_L, self.sync_led_L, self.fps_est_label_L, self.level_label_L
            )
        )
        display_row.addWidget(
            build_display_frame(
                tr("Right"), "R", self.tc_label_R, self.sync_led_R, self.fps_est_label_R, self.level_label_R
            )
        )
        layout.addLayout(display_row)

        # Monitor start/stop (ALSA/standard modes can benefit from explicitly stopping).
        monitor_row = QHBoxLayout()
        self._monitor_toggle_btn = QPushButton(tr("Start Monitor"))
        self._monitor_toggle_btn.setCheckable(True)
        self._monitor_toggle_btn.setChecked(False)
        self._monitor_toggle_btn.clicked.connect(self._on_monitor_toggled)
        monitor_row.addWidget(self._monitor_toggle_btn)
        monitor_row.addStretch()
        layout.addLayout(monitor_row)

        # CH offset visualization (L/R LTC frame difference)
        self.ltc_offset_label = QLabel(tr("CH Δ (R-L): --"))
        self.ltc_offset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_families = [f.strip() for f in MONOSPACE_FONT_FAMILY.split(",")]
        font = QFont()
        font.setFamilies(font_families)
        font.setPointSize(11)
        self.ltc_offset_label.setFont(font)
        self.ltc_offset_label.setStyleSheet("color: #888;")
        layout.addWidget(self.ltc_offset_label)

        controls_group = QGroupBox(tr("Output"))
        c_layout = QGridLayout()

        self.link_check = QCheckBox(tr("Link Stereo Output"))
        self.link_check.setChecked(bool(self.module.link_enabled))
        self.link_check.toggled.connect(self.on_link_toggled)
        c_layout.addWidget(self.link_check, 0, 0, 1, 2)

        c_layout.addWidget(QLabel(tr("Link Source:")), 1, 0)
        self.link_src_combo = QComboBox()
        self.link_src_combo.addItem(tr("Left"), "L")
        self.link_src_combo.addItem(tr("Right"), "R")
        self.link_src_combo.setCurrentIndex(0 if self.module.link_source == "L" else 1)
        self.link_src_combo.currentIndexChanged.connect(self.on_link_source_changed)
        c_layout.addWidget(self.link_src_combo, 1, 1)
        self.link_src_combo.setEnabled(bool(self.module.link_enabled))

        controls_group.setLayout(c_layout)
        layout.addWidget(controls_group)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_channel_tab("L"), tr("Left"))
        self.tabs.addTab(self._build_channel_tab("R"), tr("Right"))
        self.tabs.addTab(self._build_jam_tab(), tr("JAM"))
        self.tabs.addTab(self._build_calibration_tab(), tr("Calibration"))
        layout.addWidget(self.tabs)

        layout.addStretch()
        self.setLayout(layout)

        # Default to stopped; user explicitly starts monitoring.
        QTimer.singleShot(0, lambda: self._set_monitor_running(False))

    def _set_monitor_running(self, running: bool) -> None:
        running = bool(running)

        if self._monitor_toggle_btn is not None:
            # Keep the button state/text in sync even if start/stop is called programmatically.
            try:
                self._monitor_toggle_btn.blockSignals(True)
                self._monitor_toggle_btn.setChecked(running)
            finally:
                self._monitor_toggle_btn.blockSignals(False)
            self._monitor_toggle_btn.setText(tr("Stop Monitor") if running else tr("Start Monitor"))

        if running:
            self.module.start_analysis()
            if not self.timer.isActive():
                self.timer.start()
        else:
            self.module.stop_analysis()
            if self.timer.isActive():
                self.timer.stop()

    def _on_monitor_toggled(self, checked: bool) -> None:
        self._set_monitor_running(bool(checked))

    def closeEvent(self, event):
        # Ensure we don't keep decoding/generating LTC after the widget is closed.
        try:
            self._set_monitor_running(False)
        except Exception:
            pass
        return super().closeEvent(event)

    def on_link_toggled(self, checked: bool):
        self.module.link_enabled = bool(checked)
        self.link_src_combo.setEnabled(bool(checked))
        if checked:
            src = self.module.link_source if self.module.link_source in ("L", "R") else "L"
            other = "R" if src == "L" else "L"
            if self.module.channels[other].generator_enabled:
                self.module.channels[other].generator_enabled = False
            if self._gen_buttons.get(other) is not None:
                self._gen_buttons[other].setChecked(False)
                self._gen_buttons[other].setText(tr("Enable Generator"))

    def on_link_source_changed(self):
        self.module.link_source = self.link_src_combo.currentData() or "L"
        if self.module.link_enabled:
            for key in ("L", "R"):
                if self.module.channels[key].generator_enabled:
                    self.module.channels[key].generator_enabled = False
                if self._gen_buttons.get(key) is not None:
                    self._gen_buttons[key].setChecked(False)
                    self._gen_buttons[key].setText(tr("Enable Generator"))

    def update_ui(self):
        data = self.module.process()
        left = data.get("L", {})
        right = data.get("R", {})

        self.tc_label_L.setText(left.get("tc", "--:--:--:--"))
        self.tc_label_R.setText(right.get("tc", "--:--:--:--"))

        if left.get("locked", False):
            self.sync_led_L.setStyleSheet(
                "color: #0f0; font-weight: bold; border: 1px solid #0f0; background-color: #003300; padding: 2px 5px; border-radius:4px;"
            )
        else:
            self.sync_led_L.setStyleSheet(
                "color: #555; font-weight: normal; border: 1px solid #555; padding: 2px 5px; border-radius:4px;"
            )

        if right.get("locked", False):
            self.sync_led_R.setStyleSheet(
                "color: #0f0; font-weight: bold; border: 1px solid #0f0; background-color: #003300; padding: 2px 5px; border-radius:4px;"
            )
        else:
            self.sync_led_R.setStyleSheet(
                "color: #555; font-weight: normal; border: 1px solid #555; padding: 2px 5px; border-radius:4px;"
            )

        self.level_label_L.setText(tr("{0} dB").format(f"{float(left.get('level', -100.0)):.1f}"))
        self.level_label_R.setText(tr("{0} dB").format(f"{float(right.get('level', -100.0)):.1f}"))

        fpsl = float(left.get("fps_est", 0.0))
        fpsr = float(right.get("fps_est", 0.0))
        self.fps_est_label_L.setText(tr("FPS: {0}").format(self._format_fps_est("L", fpsl)))
        self.fps_est_label_R.setText(tr("FPS: {0}").format(self._format_fps_est("R", fpsr)))

        self._update_ltc_offset_label()

        # Generator: show the currently-output LTC timecode (small display).
        labels = self._gen_out_labels
        channels = self.module.channels

        lbl_l = labels.get("L")
        ch_l = channels.get("L")
        if lbl_l is not None and ch_l is not None:
            if getattr(ch_l, "generator_enabled", False):
                gen = ch_l.gen
                tc = str(getattr(gen, "gen_current_tc", "--:--:--:--") or "--:--:--:--")
                lbl_l.setText(tr("Gen Out: {0}").format(tc))
            else:
                lbl_l.setText(tr("Gen Out: --:--:--:--"))

        lbl_r = labels.get("R")
        ch_r = channels.get("R")
        if lbl_r is not None and ch_r is not None:
            if getattr(ch_r, "generator_enabled", False):
                gen = ch_r.gen
                tc = str(getattr(gen, "gen_current_tc", "--:--:--:--") or "--:--:--:--")
                lbl_r.setText(tr("Gen Out: {0}").format(tc))
            else:
                lbl_r.setText(tr("Gen Out: --:--:--:--"))

        if getattr(self, "_jam_tab_index", None) is not None and self.tabs.currentIndex() == self._jam_tab_index:
            now = time.time()
            if not hasattr(self, "_jam_last_update"):
                self._jam_last_update = 0.0
            if (now - float(self._jam_last_update)) >= 0.5:
                self._jam_last_update = now
                self.update_jam_ui()

        if getattr(self, "_cal_tab_index", None) is not None and self.tabs.currentIndex() == self._cal_tab_index:
            res = self.module.calibration_poll()
            if res is not None and getattr(self, "_cal_status", None) is not None:
                if not bool(res.get("ok", False)):
                    self._cal_status.setText(tr("Calibration failed"))
                else:
                    for k in ("L", "R"):
                        if self._in_delay_spins.get(k) is not None:
                            self._in_delay_spins[k].setValue(int(res.get("in_delay_frames", 0)))
                        if self._out_delay_spins.get(k) is not None:
                            self._out_delay_spins[k].setValue(int(res.get("out_delay_frames", 0)))
                        btn = self._gen_buttons.get(k)
                        ch = self.module.channels.get(k)
                        if btn is not None and ch is not None:
                            btn.setChecked(bool(ch.generator_enabled))
                            btn.setText(tr("Stop Generator") if ch.generator_enabled else tr("Enable Generator"))
                    self._cal_status.setText(
                        tr("Done: In={0}fr Out={1}fr Total={2}fr").format(
                            str(int(res.get("in_delay_frames", 0))),
                            str(int(res.get("out_delay_frames", 0))),
                            str(int(res.get("total_delay_frames", 0))),
                        )
                    )

    def _on_jam_capture_auto(self, key: str):
        """JAM button behavior:

        - Immediately sync to external LTC (current decoded TC for this channel)
        - Save the external TC into the currently selected JAM memory slot
        - Switch generator mode to JAM and start output

        Memory switching remains available after sync.
        """

        # Rotate-save: store external TC into a JAM memory slot (free slot first, else overwrite oldest).
        idx = self.module.jam_capture_auto_precise(key)
        if idx < 0:
            # Failure: abort JAM operation only; keep measurement/monitoring running.
            if self._jam_capture_msg.get(key) is not None:
                self._jam_capture_msg[key].setText(tr("JAM failed"))
            return

        self._start_generator_jam_sync(key, int(idx))

        if self._jam_capture_msg.get(key) is not None:
            self._jam_capture_msg[key].setText(tr("Saved: Mem {0}").format(str(int(idx) + 1)))

    def _start_generator_jam_sync(self, key: str, slot: int) -> None:
        # Link-mode handling: only the selected side should generate.
        if self.module.link_enabled:
            other = "R" if key == "L" else "L"
            self.module.link_source = key
            if getattr(self, "link_src_combo", None) is not None:
                if self.link_src_combo.currentData() != key:
                    self.link_src_combo.setCurrentIndex(0 if key == "L" else 1)

            self.module.channels[other].generator_enabled = False
            if self._gen_buttons.get(other) is not None:
                self._gen_buttons[other].setChecked(False)
                self._gen_buttons[other].setText(tr("Enable Generator"))

        ch = self.module.channels.get(key)
        if ch is None:
            return

        s = int(slot)
        if s < 0:
            s = 0
        elif s > 4:
            s = 4
        ch.generator_jam_slot = int(s)

        jam_combo = self._jam_slot_combos.get(key)
        if jam_combo is not None:
            try:
                jam_combo.blockSignals(True)
                jam_combo.setCurrentIndex(int(s))
            finally:
                jam_combo.blockSignals(False)

        # Switch to JAM mode and restart generator state so output locks immediately.
        ch.generator_mode = "jam"
        ch.generator_enabled = True
        ch.gen.frames_generated = 0
        ch.gen.gen_buffer.clear()
        ch.gen.gen_tc_buffer.clear()
        ch.gen.gen_current = None
        ch.gen.gen_current_tc = "--:--:--:--"
        ch.gen.gen_pos = 0
        ch.gen.tod_epoch_base = None
        ch.gen.free_run_start_time = 0.0
        ch.gen.jam_base_total_frames = None
        ch.gen.jam_base_fps = None

        btn = self._gen_buttons.get(key)
        if btn is not None:
            btn.setChecked(True)
            btn.setText(tr("Stop Generator"))

        mode_combo = self._mode_combos.get(key)
        if mode_combo is not None:
            # Update UI without re-triggering _on_mode_changed.
            try:
                mode_combo.blockSignals(True)
                mode_combo.setCurrentIndex(2)  # JAM
            finally:
                mode_combo.blockSignals(False)

    def _update_ltc_offset_label(self) -> None:
        if getattr(self, "ltc_offset_label", None) is None:
            return

        left = self.module.channels.get("L")
        right = self.module.channels.get("R")
        if left is None or right is None:
            self.ltc_offset_label.setText(tr("CH Δ (R-L): --"))
            return

        fps_l = float(getattr(left, "fps", 0.0) or 0.0)
        fps_r = float(getattr(right, "fps", 0.0) or 0.0)
        nominal_l = int(round(fps_l)) if fps_l > 0 else 0
        nominal_r = int(round(fps_r)) if fps_r > 0 else 0

        if nominal_l <= 0 or nominal_r <= 0 or nominal_l != nominal_r:
            self.ltc_offset_label.setText(tr("CH Δ (R-L): --"))
            return

        # Prefer the latest decoded frame totals.
        lf = None
        rf = None
        try:
            if left.jam_history:
                lf = int(left.jam_history[-1][1])
        except Exception:
            lf = None
        try:
            if right.jam_history:
                rf = int(right.jam_history[-1][1])
        except Exception:
            rf = None

        if lf is None or rf is None:
            # Fallback: parse decoded TC strings.
            pl = self.module._parse_tc(getattr(left, "decoded_tc", ""))
            pr = self.module._parse_tc(getattr(right, "decoded_tc", ""))
            if pl is None or pr is None:
                self.ltc_offset_label.setText(tr("CH Δ (R-L): --"))
                return
            hh, mm, ss, ff = pl
            lf = ((hh * 3600 + mm * 60 + ss) * nominal_l) + int(ff)
            hh, mm, ss, ff = pr
            rf = ((hh * 3600 + mm * 60 + ss) * nominal_r) + int(ff)

        frames_per_day = int(24 * 3600 * nominal_l)
        diff = int(rf) - int(lf)
        if frames_per_day > 0:
            half = frames_per_day // 2
            diff = ((diff + half) % frames_per_day) - half

        ms = (float(diff) / float(nominal_l)) * 1000.0
        self.ltc_offset_label.setText(
            tr("CH Δ (R-L): {0} fr ({1} ms)").format(
                f"{diff:+d}",
                f"{ms:+.1f}",
            )
        )

    def _build_channel_tab(self, key: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        ch = self.module.channels[key]

        top_row = QHBoxLayout()

        settings = QGroupBox(tr("Channel Settings"))
        sl = QGridLayout()

        sl.addWidget(QLabel(tr("Frame Rate:")), 0, 0)
        fps_combo = QComboBox()
        fps_combo.addItems(["23.98", "24.00", "25.00", "30.0D", "30.0", "29.97D", "29.97"])
        fps_combo.setCurrentText(self._format_fps_option(float(ch.fps), bool(getattr(ch, "fps_drop_frame", False))))
        fps_combo.currentTextChanged.connect(lambda t="", k=key: self._on_fps_changed(k, t))
        sl.addWidget(fps_combo, 0, 1)

        tz_check = QCheckBox(tr("Display Local Time"))
        tz_check.setChecked(bool(ch.display_tz_enabled))
        tz_check.toggled.connect(lambda checked=False, k=key: self._on_tz_toggled(k, checked))
        sl.addWidget(tz_check, 0, 2)

        sl.addWidget(QLabel(tr("Display TZ:")), 1, 2)
        tz_combo = QComboBox()
        tz_combo.setEditable(True)
        tz_options = [
            ("System", tr("System")),
            ("UTC", tr("UTC")),
            ("Asia/Tokyo", tr("Asia/Tokyo")),
            ("Europe/London", tr("Europe/London")),
            ("America/New_York", tr("America/New_York")),
        ]
        for value, label in tz_options:
            tz_combo.addItem(label, value)

        current_value = ch.display_tz_name or "System"
        idx = tz_combo.findData(current_value)
        if idx < 0:
            tz_combo.addItem(current_value, current_value)
            idx = tz_combo.findData(current_value)
        tz_combo.setCurrentIndex(idx if idx >= 0 else 0)
        tz_combo.currentTextChanged.connect(
            lambda text="", k=key, c=tz_combo: self._on_tz_changed(k, text, c.currentData())
        )
        tz_combo.setEnabled(bool(ch.display_tz_enabled))
        sl.addWidget(tz_combo, 1, 3)
        self._tz_combos[key] = tz_combo

        settings.setLayout(sl)
        top_row.addWidget(settings, 2)

        g = QGroupBox(tr("Generator"))
        gl = QGridLayout()

        gl.addWidget(QLabel(tr("Gen Mode:")), 0, 0)
        mode_combo = QComboBox()
        mode_combo.addItem(tr("Time of Day"), "tod")
        mode_combo.addItem(tr("Free Run"), "free")
        mode_combo.addItem(tr("JAM"), "jam")
        if ch.generator_mode == "tod":
            mode_combo.setCurrentIndex(0)
        elif ch.generator_mode == "free":
            mode_combo.setCurrentIndex(1)
        else:
            mode_combo.setCurrentIndex(2)
        mode_combo.currentIndexChanged.connect(
            lambda _=0, k=key, c=mode_combo: self._on_mode_changed(k, c.currentData())
        )
        gl.addWidget(mode_combo, 0, 1)
        self._mode_combos[key] = mode_combo

        gl.addWidget(QLabel(tr("JAM Mem:")), 3, 0)
        jam_combo = QComboBox()
        for i in range(5):
            jam_combo.addItem(tr("Mem {0}").format(str(i + 1)), i)
        cur_slot = int(ch.generator_jam_slot) if ch.generator_jam_slot is not None else 0
        if cur_slot < 0:
            cur_slot = 0
        elif cur_slot > 4:
            cur_slot = 4
        jam_combo.setCurrentIndex(cur_slot)
        # Use index (0-4) directly; some environments may not reliably return userData via currentData().
        jam_combo.currentIndexChanged.connect(lambda idx=0, k=key: self._on_jam_slot_changed(k, int(idx)))
        gl.addWidget(jam_combo, 3, 1)
        self._jam_slot_combos[key] = jam_combo

        gen_btn = QPushButton(tr("Enable Generator"))
        gen_btn.setCheckable(True)
        gen_btn.setChecked(bool(ch.generator_enabled))
        gen_btn.clicked.connect(lambda checked=False, k=key, b=gen_btn: self._on_gen_toggle(k, checked, b))
        gen_btn.setText(tr("Stop Generator") if ch.generator_enabled else tr("Enable Generator"))
        gl.addWidget(gen_btn, 0, 2, 2, 1)
        self._gen_buttons[key] = gen_btn

        gen_out = QLabel(tr("Gen Out: --:--:--:--"))
        gen_out.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_families = [f.strip() for f in MONOSPACE_FONT_FAMILY.split(",")]
        font = QFont()
        font.setFamilies(font_families)
        font.setPointSize(10)
        gen_out.setFont(font)
        gen_out.setStyleSheet("color: #888;")
        gl.addWidget(gen_out, 2, 2)
        self._gen_out_labels[key] = gen_out

        gl.addWidget(QLabel(tr("In Delay (fr):")), 1, 0)
        in_spin = QSpinBox()
        in_spin.setRange(-100000, 100000)
        in_spin.setValue(int(ch.input_offset_frames))
        in_spin.valueChanged.connect(lambda v=0, k=key: self._set_in_offset(k, v))
        gl.addWidget(in_spin, 1, 1)
        self._in_delay_spins[key] = in_spin

        gl.addWidget(QLabel(tr("Out Delay (fr):")), 2, 0)
        out_spin = QSpinBox()
        out_spin.setRange(-100000, 100000)
        out_spin.setValue(int(ch.gen_offset_frames))
        out_spin.valueChanged.connect(lambda v=0, k=key: self._set_out_offset(k, v))
        gl.addWidget(out_spin, 2, 1)
        self._out_delay_spins[key] = out_spin

        g.setLayout(gl)
        top_row.addWidget(g, 3)

        v.addLayout(top_row)
        v.addStretch()
        return w

    def _on_mode_changed(self, key: str, mode: str):
        ch = self.module.channels[key]
        ch.generator_mode = str(mode)
        ch.gen.frames_generated = 0
        ch.gen.gen_buffer.clear()
        ch.gen.gen_tc_buffer.clear()
        ch.gen.gen_current = None
        ch.gen.gen_current_tc = "--:--:--:--"
        ch.gen.gen_pos = 0
        ch.gen.free_run_start_time = 0.0
        ch.gen.tod_epoch_base = None
        ch.gen.jam_base_total_frames = None
        ch.gen.jam_base_fps = None

    def _on_jam_slot_changed(self, key: str, slot: int):
        ch = self.module.channels[key]
        s = int(slot)
        if s < 0:
            s = 0
        elif s > 4:
            s = 4
        ch.generator_jam_slot = int(s)
        ch.gen.jam_base_total_frames = None
        ch.gen.jam_base_fps = None

        # If currently generating in JAM mode, flush buffered frames so the new
        # memory slot takes effect immediately.
        if bool(getattr(ch, "generator_enabled", False)) and str(getattr(ch, "generator_mode", "")) == "jam":
            ch.gen.frames_generated = 0
            ch.gen.gen_buffer.clear()
            ch.gen.gen_tc_buffer.clear()
            ch.gen.gen_current = None
            ch.gen.gen_current_tc = "--:--:--:--"
            ch.gen.gen_pos = 0

    def _on_gen_toggle(self, key: str, checked: bool, btn: QPushButton):
        if self.module.link_enabled:
            # In link mode, only one side should generate; choose the side that was toggled.
            other = "R" if key == "L" else "L"
            self.module.link_source = key
            if self.link_src_combo.currentData() != key:
                self.link_src_combo.setCurrentIndex(0 if key == "L" else 1)

            self.module.channels[other].generator_enabled = False
            if self._gen_buttons.get(other) is not None:
                self._gen_buttons[other].setChecked(False)
                self._gen_buttons[other].setText(tr("Enable Generator"))

        ch = self.module.channels[key]
        ch.generator_enabled = bool(checked)
        if checked:
            ch.gen.frames_generated = 0
            ch.gen.gen_buffer.clear()
            ch.gen.gen_tc_buffer.clear()
            ch.gen.gen_current = None
            ch.gen.gen_current_tc = "--:--:--:--"
            ch.gen.gen_pos = 0
            ch.gen.tod_epoch_base = None
            ch.gen.free_run_start_time = 0.0
            ch.gen.jam_base_total_frames = None
            ch.gen.jam_base_fps = None
        else:
            ch.gen.gen_current_tc = "--:--:--:--"

        # UX Improvement: Auto-start monitor if enabling generator and not running
        if checked and not self.module.is_running:
            self._set_monitor_running(True)

        btn.setText(tr("Stop Generator") if checked else tr("Enable Generator"))

    def _build_jam_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        grid_box = QGroupBox(tr("JAM Memories"))
        gl = QGridLayout()

        gl.addWidget(QLabel(tr("Slot")), 0, 0)
        gl.addWidget(QLabel(tr("Captured")), 0, 1)
        gl.addWidget(QLabel(tr("Current")), 0, 2)

        self._jam_labels = {}
        row = 1
        for slot in range(5):
            gl.addWidget(QLabel(str(slot + 1)), row, 0)
            cap = QLabel("--:--:--:--")
            cur = QLabel("--:--:--:--")
            font_families = [f.strip() for f in MONOSPACE_FONT_FAMILY.split(",")]
            font = QFont()
            font.setFamilies(font_families)
            font.setPointSize(10)
            cap.setFont(font)
            cur.setFont(font)
            gl.addWidget(cap, row, 1)
            gl.addWidget(cur, row, 2)
            self._jam_labels[(slot, "cap")] = cap
            self._jam_labels[(slot, "cur")] = cur
            row += 1

        grid_box.setLayout(gl)
        v.addWidget(grid_box)
        v.addStretch()

        self._jam_tab_index = 2
        self.update_jam_ui()
        return w

    def update_jam_ui(self):
        if not hasattr(self, "_jam_labels"):
            return

        for slot in range(5):
            mem = self.module.jam_memories[slot]
            cap = mem.tc_raw if mem.valid else "--:--:--:--"
            cur = self.module.jam_get_current_tc(slot) if mem.valid else "--:--:--:--"
            if self._jam_labels.get((slot, "cap")) is not None:
                self._jam_labels[(slot, "cap")].setText(cap)
            if self._jam_labels.get((slot, "cur")) is not None:
                self._jam_labels[(slot, "cur")].setText(cur)

    def _on_fps_changed(self, key: str, text: str):
        fps, drop_frame = self._parse_fps_option(text)
        if fps is None or float(fps) <= 0:
            return
        self.module.channels[key].fps_drop_frame = bool(drop_frame)
        self.module.set_channel_fps(key, float(fps))

    def _on_tz_toggled(self, key: str, checked: bool):
        ch = self.module.channels[key]
        ch.display_tz_enabled = bool(checked)
        if self._tz_combos.get(key) is not None:
            self._tz_combos[key].setEnabled(bool(checked))

    def _on_tz_changed(self, key: str, text: str, data: Optional[str] = None):
        ch = self.module.channels[key]
        value = data if data is not None else text
        ch.display_tz_name = str(value).strip() if value else "System"

    def _parse_fps_option(self, text: str) -> tuple[Optional[float], bool]:
        t = (text or "").strip()
        drop_frame = False
        if t.endswith("D"):
            drop_frame = True
            t = t[:-1]

        mapping = {
            "23.98": 23.976,
            "24.00": 24.0,
            "25.00": 25.0,
            "30.0": 30.0,
            "29.97": 29.97,
        }

        if t in mapping:
            return float(mapping[t]), drop_frame

        try:
            return float(t), drop_frame
        except Exception:
            return None, drop_frame

    def _format_fps_option(self, fps: float, drop_frame: bool = False) -> str:
        presets = [23.976, 24.0, 25.0, 30.0, 29.97]
        labels = ["23.98", "24.00", "25.00", "30.0", "29.97"]
        if fps <= 0:
            base = "30.0"
        else:
            best_i = 0
            best_d = float("inf")
            for i, p in enumerate(presets):
                d = abs(float(fps) - float(p))
                if d < best_d:
                    best_d = d
                    best_i = i
            base = labels[best_i]

        if base in ("29.97", "30.0") and drop_frame:
            return f"{base}D"
        return base

    def _format_fps_est(self, key: str, fps_est: float) -> str:
        if float(fps_est) <= 0:
            return "--"
        ch = self.module.channels.get(key)
        drop_frame = bool(getattr(ch, "fps_drop_frame", False)) if ch is not None else False
        return self._format_fps_option(float(fps_est), drop_frame)

    def _set_in_offset(self, key: str, v: float):
        self.module.channels[key].input_offset_frames = int(round(float(v)))

    def _set_out_offset(self, key: str, v: float):
        self.module.channels[key].gen_offset_frames = int(round(float(v)))

    def _build_calibration_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        box = QGroupBox(tr("TC I/O Delay Calibration"))
        gl = QGridLayout()

        gl.addWidget(QLabel(tr("Channel:")), 0, 0)
        self._cal_ch = QComboBox()
        self._cal_ch.addItem(tr("Left"), "L")
        self._cal_ch.addItem(tr("Right"), "R")
        gl.addWidget(self._cal_ch, 0, 1)

        self._cal_btn = QPushButton(tr("Run Calibration"))
        self._cal_btn.clicked.connect(self._on_run_calibration)
        gl.addWidget(self._cal_btn, 1, 0, 1, 2)

        self._cal_status = QLabel(tr("Connect output to input and run."))
        self._cal_status.setStyleSheet("color: #888;")
        gl.addWidget(self._cal_status, 2, 0, 1, 2)

        box.setLayout(gl)
        v.addWidget(box)
        v.addStretch()

        self._cal_tab_index = 3
        return w

    def _on_run_calibration(self):
        # Ensure monitor is running
        self._set_monitor_running(True)

        key = "L"
        try:
            key = self._cal_ch.currentData() or "L"
        except Exception:
            key = "L"

        ch = self.module.channels.get(key, self.module.channels["L"])
        self.module.calibration_start(key)
        ch.generator_mode = "tod"
        ch.generator_enabled = True
        ch.gen.frames_generated = 0
        ch.gen.gen_buffer.clear()
        ch.gen.gen_tc_buffer.clear()
        ch.gen.gen_current = None
        ch.gen.gen_current_tc = "--:--:--:--"
        ch.gen.gen_pos = 0
        ch.gen.tod_epoch_base = None
        ch.gen.free_run_start_time = 0.0
        ch.gen.jam_base_total_frames = None
        ch.gen.jam_base_fps = None
        if getattr(self, "_cal_status", None) is not None:
            self._cal_status.setText(tr("Calibrating..."))

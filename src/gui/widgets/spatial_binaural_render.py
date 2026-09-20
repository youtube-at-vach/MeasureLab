"""Offline binaural rendering, independent of the mixer controls and playback."""

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from threading import Event
from typing import TYPE_CHECKING

import numpy as np
import soundfile as sf
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal, pyqtSlot
from scipy.signal import fftconvolve

from src.core.analysis import AudioCalc
from src.core.localization import tr
from src.core.true_peak import EXPORT_TRUE_PEAK_CEILING, estimate_true_peak

if TYPE_CHECKING:
    from src.gui.widgets.hrtf_player import HRTFData


@dataclass(frozen=True)
class TrackConfig:
    path: str
    az: float = 0
    el: float = 0
    gain_db: float = 0


@dataclass(frozen=True)
class RenderResult:
    audio: np.ndarray
    sample_rate: int
    attenuation_db: float


def interpolate_hrir(hrtf_data: "HRTFData", target_az: float, target_el: float, k=3, p=2.0) -> np.ndarray:
    """Blend the nearest measured HRIRs using spherical angular distance."""
    pos = np.deg2rad(hrtf_data.source_positions[:, :2])
    az, el = np.deg2rad([target_az, target_el])
    cos_distance = np.sin(el) * np.sin(pos[:, 1]) + np.cos(el) * np.cos(pos[:, 1]) * np.cos(pos[:, 0] - az)
    distances = np.arccos(np.clip(cos_distance, -1, 1))
    indices = np.argsort(distances)[:k]
    nearest = distances[indices]
    if nearest[0] < 1e-6:
        return hrtf_data.ir_data[indices[0]].T.astype(np.float64)
    weights = 1 / (nearest**p + 1e-9)
    weights /= weights.sum()
    return np.einsum("m,mrn->nr", weights, hrtf_data.ir_data[indices], dtype=np.float64)


def validate_hrtf(data: "HRTFData") -> None:
    ir = data.ir_data
    positions = data.source_positions
    if (
        ir.ndim != 3
        or ir.shape[0] == 0
        or ir.shape[1] != 2
        or ir.shape[2] == 0
        or positions.ndim != 2
        or positions.shape[0] != ir.shape[0]
        or positions.shape[1] < 2
        or not np.isfinite(ir).all()
        or not np.isfinite(positions).all()
        or not np.isfinite(data.sampling_rate)
        or data.sampling_rate <= 0
    ):
        raise ValueError(tr("Invalid stereo HRTF data."))


class RenderWorker(QThread):
    """Store the outcome before QThread.finished; never shadow its lifetime signal."""

    progress = pyqtSignal(int, str)

    def __init__(
        self, tracks_data, hrtf_data, target_sr, start_sec=None, duration_sec=None, parent=None, output_path=None
    ):
        super().__init__(parent)
        self.tracks = tuple(t if isinstance(t, TrackConfig) else TrackConfig(**t) for t in tracks_data)
        self.hrtf_data = hrtf_data
        self.target_sr = int(target_sr)
        self.start_sec = start_sec
        self.duration_sec = duration_sec
        self.cancelled = Event()
        self.result: RenderResult | None = None
        self.error: Exception | None = None
        self.output_path = output_path
        self.output_saved = False
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @pyqtSlot()
    def shutdown(self):
        self.cancel()
        self.wait()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            self.result = self._render()
            if self.result is not None and self.output_path is not None:
                self._save_output(self.result)
        except Exception as exc:
            self.error = exc

    def _save_output(self, result):
        """Write off the GUI thread; cancellation never leaves a partial destination."""
        target = Path(self.output_path)
        self.progress.emit(100, tr("Saving"))
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".wav", delete=False) as temp:
            temporary = Path(temp.name)
        try:
            with sf.SoundFile(temporary, "w", samplerate=result.sample_rate, channels=2, subtype="FLOAT") as output:
                for start in range(0, len(result.audio), 65536):
                    if self.cancelled.is_set():
                        return
                    output.write(result.audio[start : start + 65536])
            if not self.cancelled.is_set():
                os.replace(temporary, target)
                self.output_saved = True
        finally:
            temporary.unlink(missing_ok=True)

    def _render(self):
        validate_hrtf(self.hrtf_data)
        if self.target_sr <= 0:
            raise ValueError(tr("Invalid sample rate"))
        master = np.zeros((0, 2), dtype=np.float64)
        # Read, convolve and release one source at a time instead of retaining
        # every decoded source alongside the output bus.
        for i, track in enumerate(self.tracks):
            if self.cancelled.is_set():
                return None
            self.progress.emit(int(90 * i / len(self.tracks)), tr("Loading track {0}...").format(i + 1))
            info = sf.info(track.path)
            start = int((self.start_sec or 0) * info.samplerate)
            if start >= info.frames:
                continue  # A source that has ended contributes silence, never its last second.
            frames = info.frames - start
            if self.duration_sec is not None:
                frames = min(frames, round(self.duration_sec * info.samplerate))
            data, sr = sf.read(track.path, always_2d=True, start=start, frames=frames)
            if not np.isfinite(data).all():
                raise ValueError(tr("Audio contains non-finite samples: {0}").format(track.path))
            if self.cancelled.is_set():
                return None
            data = data.mean(axis=1)
            if sr != self.target_sr:
                data = AudioCalc.resample(data, sr, self.target_sr)
            data *= 10 ** (track.gain_db / 20)
            if not len(data):
                continue
            self.progress.emit(int(90 * (i + 0.5) / len(self.tracks)), tr("Rendering track {0}...").format(i + 1))
            hrir = interpolate_hrir(self.hrtf_data, track.az, track.el)
            if self.hrtf_data.sampling_rate != self.target_sr:
                hrir = AudioCalc.resample(hrir, self.hrtf_data.sampling_rate, self.target_sr)
                hrir *= self.hrtf_data.sampling_rate / self.target_sr
            length = len(data) + len(hrir) - 1
            if length > len(master):
                master = np.pad(master, ((0, length - len(master)), (0, 0)))
            for channel in range(2):
                if self.cancelled.is_set():
                    return None
                master[:length, channel] += fftconvolve(data, hrir[:, channel], mode="full")
        if self.cancelled.is_set():
            return None
        if not len(master):
            raise ValueError(tr("No audio in the selected range."))
        if not np.isfinite(master).all():
            raise ValueError(tr("Invalid rendered audio."))
        self.progress.emit(95, tr("Checking output peak..."))
        peak = estimate_true_peak(master)
        scale = min(1.0, EXPORT_TRUE_PEAK_CEILING / peak) if peak > 0 else 1.0
        master *= scale
        if self.cancelled.is_set():
            return None
        self.progress.emit(100, tr("Done"))
        return RenderResult(master.astype(np.float32), self.target_sr, float(-20 * np.log10(scale)))

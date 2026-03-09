import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import pyqtSignal, QObject, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.core.localization import tr
from src.core.sonifier import PeakToneSonifier
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


def _get_mains_note(base: int, order: int) -> str:
    freq = base * order
    if order == 1:
        return f"Mains Power ({base}Hz)"
    elif order == 2:
        return f"Rectified Mains ({freq}Hz)"
    else:
        suffix = "th"
        if order == 3:
            suffix = "rd"
        return f"Mains {order}{suffix} Harmonic ({freq}Hz)"


def _get_default_targets(
    mains_freq: float | None = None,
    mains_harmonics: int = 16,
    include_musical_scale: bool = False,
    a4_freq: float = 440.0,
) -> dict:
    targets = {
        997.0: "Standard Test Tone (997Hz)",
        1000.0: "Standard Test Tone (1kHz) / USB Frame (1ms)",
        8000.0: "Audio Sample Rate (8kHz) / USB Audio Packet (125µs)",
        11025.0: "Audio Sample Rate (11.025kHz)",
        15625.0: "CRT Horizontal Scan (PAL/SECAM 15.625kHz)",
        15734.0: "CRT Horizontal Scan (NTSC 15.734kHz)",
        16000.0: "Audio Sample Rate (16kHz)",
        19000.0: "FM Pilot Tone (19kHz)",
        20000.0: "Upper Hearing Limit / SMPS Noise (20kHz)",
        22050.0: "Audio Sample Rate (22.05kHz)",
        24000.0: "Audio Sample Rate Base (24kHz)",
        25000.0: "SMPS Noise (25kHz)",
        30000.0: "SMPS Noise (30kHz)",
        31250.0: "CRT Monitor Scan (31.25kHz) / MIDI Baud Rate",
        31468.0: "CRT Monitor Scan / VGA (31.468kHz)",
        31500.0: "LCD / CRT Monitor Scan (31.5kHz)",
        32000.0: "Audio Sample Rate (32kHz)",
        32768.0: "RTC Crystal Oscillator (32.768kHz)",
        37900.0: "CRT Monitor Scan (37.9kHz)",
        38000.0: "FM Stereo Subcarrier (38kHz)",
        40000.0: "Ultrasonic Transducer / SMPS Noise (40kHz)",
        44100.0: "CD Audio (44.1kHz)",
        46875.0: "CRT Monitor Scan (46.875kHz)",
        47202.0: "CRT Monitor Scan (47.202kHz)",
        48000.0: "DAT/Video Audio (48kHz)",
        48400.0: "CRT Monitor Scan (48.4kHz)",
        50000.0: "SMPS Noise (50kHz)",
        57000.0: "RDS / RBDS (57kHz)",
        60000.0: "SMPS Noise (60kHz)",
        62936.0: "CRT Monitor Scan (62.936kHz)",
        80000.0: "SMPS Noise (80kHz)",
        88200.0: "Hi-Res Audio (88.2kHz)",
        96000.0: "Hi-Res Audio (96kHz)",
        100000.0: "SMPS Noise (100kHz)",
    }

    bases = [50.0, 60.0] if mains_freq is None else [mains_freq]

    for _order in range(1, mains_harmonics + 1):
        for _base in bases:
            _f = float(_base * _order)
            _note = _get_mains_note(int(_base), _order)
            if _f in targets:
                if _note not in targets[_f]:
                    targets[_f] += f" / {_note}"
            else:
                targets[_f] = _note

    if include_musical_scale:
        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        for p in range(12, 128):  # C0 to G9
            freq = round(a4_freq * (2.0 ** ((p - 69) / 12.0)), 2)
            if 10.0 <= freq <= 192000.0:
                octave = (p // 12) - 1
                name = note_names[p % 12]
                note_str = f"Note {name}{octave} ({freq}Hz)"
                if freq in targets:
                    if note_str not in targets[freq]:
                        targets[freq] += f" / {note_str}"
                else:
                    targets[freq] = note_str

    return targets


# Used for decoupling background thread results to GUI thread safely.
# Used for decoupling background thread results to GUI thread safely.
class FinderSignals(QObject):
    result_ready = pyqtSignal(object)
    sweep_started = pyqtSignal(object)
    progress_update = pyqtSignal(int, int, object, object, object)


class LockInSpectrumFinder(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.lock = threading.Lock()

        # Input buffer (stereo)
        self.buffer_size = 262144
        self.input_data = np.zeros((self.buffer_size, 2))
        self.input_buffer_pos = 0
        self.buffer_filled_samples = 0
        self._analysis_warmed_up = False

        # Analysis parameters
        self.points = 256
        self.start_freq = 20.0
        self.stop_freq = 20000.0
        self.spacing = "Log"  # "Lin" or "Log"

        # Audio params
        self.input_channel = 0  # 0: Left, 1: Right

        # State
        self.callback_id = None
        self.signals = FinderSignals()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._calculation_future = None

        # Mode
        self.mode = "Scan"  # "Scan" or "Zoom"
        self.zoom_center_freq = 1000.0
        self.zoom_span = 10.0
        self.track_peak = False

        # Scan Mode Specifics
        self.include_scan_targets = True
        self.octave_ref_freq = 1000.0

        # Mains Power Settings
        self.mains_freq = None  # None means both 50 and 60 Hz
        self.mains_harmonics_count = 16

        # Musical Scale Settings
        self.include_musical_scale = False
        self.a4_freq = 440.0

        self.current_targets = self._load_user_targets()
        self._module_keys = [
            "Standard Test Tone (997Hz)",
            "Standard Test Tone (1kHz) / USB Frame (1ms)",
            "Audio Sample Rate (8kHz) / USB Audio Packet (125µs)",
            "Audio Sample Rate (11.025kHz)",
            "CRT Horizontal Scan (PAL/SECAM 15.625kHz)",
            "CRT Horizontal Scan (NTSC 15.734kHz)",
            "Audio Sample Rate (16kHz)",
            "FM Pilot Tone (19kHz)",
            "Upper Hearing Limit / SMPS Noise (20kHz)",
            "Audio Sample Rate (22.05kHz)",
            "Audio Sample Rate Base (24kHz)",
            "SMPS Noise (25kHz)",
            "SMPS Noise (30kHz)",
            "CRT Monitor Scan (31.25kHz) / MIDI Baud Rate",
            "CRT Monitor Scan / VGA (31.468kHz)",
            "LCD / CRT Monitor Scan (31.5kHz)",
            "Audio Sample Rate (32kHz)",
            "RTC Crystal Oscillator (32.768kHz)",
            "CRT Monitor Scan (37.9kHz)",
            "FM Stereo Subcarrier (38kHz)",
            "Ultrasonic Transducer / SMPS Noise (40kHz)",
            "CD Audio (44.1kHz)",
            "CRT Monitor Scan (46.875kHz)",
            "CRT Monitor Scan (47.202kHz)",
            "DAT/Video Audio (48kHz)",
            "CRT Monitor Scan (48.4kHz)",
            "SMPS Noise (50kHz)",
            "RDS / RBDS (57kHz)",
            "SMPS Noise (60kHz)",
            "CRT Monitor Scan (62.936kHz)",
            "SMPS Noise (80kHz)",
            "Hi-Res Audio (88.2kHz)",
            "Hi-Res Audio (96kHz)",
            "SMPS Noise (100kHz)",
            "Mains Power (50Hz)",
            "Mains Power (60Hz)",
            "Rectified Mains (100Hz)",
            "Rectified Mains (120Hz)",
            # Note: 3rd+ harmonics generated via f"Mains {order}{suffix} Harmonic ({freq}Hz)"
            # are harder to track but usually follow a pattern.
        ]

        # Analysis Settings
        self.window_type = "none"  # "none", "hann", "hamming", "blackmanharris"

        # Display
        self.display_unit = "dBFS"  # "dBFS", "dBV", "dB SPL"

        # Sonifier
        self.sonifier = PeakToneSonifier(sample_rate=self.audio_engine.sample_rate)

    @property
    def name(self) -> str:
        return "Lock-in Spectrum Finder"

    @property
    def description(self) -> str:
        return "High-resolution spectrum finder using parallel lock-in detection (matrix projection)."

    def _load_user_targets(self) -> dict:
        path = ""
        try:
            path = os.path.join(ConfigManager.get_user_data_dir(), "user_scan_targets.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {float(k): v for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to load user targets from {path}: {e}")
        return _get_default_targets(
            self.mains_freq, self.mains_harmonics_count, self.include_musical_scale, self.a4_freq
        )

    def update_generator_targets(self):
        """Regenerate targets based on current generator settings, merging with custom ones.
        Removes previously generated targets and applies new ones, preserving custom targets.
        """
        # 1. Clean up old generated targets from current targets
        to_delete = []
        for f, note in list(self.current_targets.items()):
            if "Mains" in note or "Note " in note:
                # Split by ' / ' and keep parts that don't look like generated targets
                parts = [
                    p.strip() for p in note.split(" / ") if "Mains" not in p and not p.strip().startswith("Note ")
                ]
                if parts:
                    self.current_targets[f] = " / ".join(parts)
                else:
                    to_delete.append(f)

        for f in to_delete:
            del self.current_targets[f]

        # 2. Get the new default targets, which include the desired generated targets
        new_defaults = _get_default_targets(
            self.mains_freq, self.mains_harmonics_count, self.include_musical_scale, self.a4_freq
        )

        # 3. Merge new targets into current_targets
        for f, note in new_defaults.items():
            if f not in self.current_targets:
                self.current_targets[f] = note
            else:
                # Just merge the generated parts to avoid duplicating base default notes
                gen_parts = [p.strip() for p in note.split(" / ") if "Mains" in p or p.strip().startswith("Note ")]
                for gp in gen_parts:
                    if gp not in self.current_targets[f]:
                        self.current_targets[f] += f" / {gp}"

        self.save_user_targets(self.current_targets)

    def save_user_targets(self, targets: dict):
        self.current_targets = targets
        path = ""
        try:
            path = os.path.join(ConfigManager.get_user_data_dir(), "user_scan_targets.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in targets.items()}, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save user targets back to {path}: {e}")

    def get_widget(self):
        return LockInSpectrumFinderWidget(self)

    def start_analysis(self):
        if self.is_running:
            return
        self.is_running = True
        self._analysis_warmed_up = False
        self.sonifier.set_sample_rate(self.audio_engine.sample_rate)

        with self.lock:
            self.input_data = np.zeros((self.buffer_size, 2))
            self.input_buffer_pos = 0
            self.buffer_filled_samples = 0

        def callback(indata, outdata, frames, time, status):
            if not self.is_running:
                outdata.fill(0)
                return

            self.sonifier.process(outdata)

            if indata.shape[1] >= 2:
                new_data = indata[:, :2]
            else:
                new_data = np.column_stack((indata[:, 0], indata[:, 0]))

            n = len(new_data)

            with self.lock:
                p = self.input_buffer_pos
                if p + n <= self.buffer_size:
                    self.input_data[p : p + n] = new_data
                    self.input_buffer_pos = (p + n) % self.buffer_size
                else:
                    chunk1 = self.buffer_size - p
                    chunk2 = n - chunk1
                    self.input_data[p:] = new_data[:chunk1]
                    self.input_data[:chunk2] = new_data[chunk1:]
                    self.input_buffer_pos = chunk2

                self.buffer_filled_samples = min(self.buffer_size, self.buffer_filled_samples + n)

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            self.is_running = False
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def clear_buffer(self):
        with self.lock:
            self.input_data.fill(0)
            self.input_buffer_pos = 0
            self.buffer_filled_samples = 0

    def _get_min_analysis_samples(self) -> int:
        fs = max(1, int(self.audio_engine.sample_rate))

        if self.mode == "Zoom":
            warmup = max(4096, int(fs * 0.10))
        else:
            warmup = max(8192, int(fs * 0.25))

        return min(self.buffer_size, warmup)

    def get_data_snapshot(self, min_samples: int | None = None):
        with self.lock:
            filled = self.buffer_filled_samples
            if min_samples is None:
                min_samples = self.buffer_size

            if filled < min_samples:
                return None
            if filled < self.buffer_size:
                return self.input_data[:filled].copy()

            data = self.input_data.copy()
            pos = self.input_buffer_pos

        if pos == 0:
            return data
        return np.concatenate((data[pos:], data[:pos]))

    def trigger_calculation(self):
        """Called by GUI timer to check if ready and submit background job."""
        if not self.is_running:
            return

        # Don't queue multiple if one is still running
        if self._calculation_future is not None and not self._calculation_future.done():
            return

        min_samples = self.buffer_size if self._analysis_warmed_up else self._get_min_analysis_samples()
        data = self.get_data_snapshot(min_samples=min_samples)
        if data is None:
            return

        # Clear buffer only after we know the snapshot will be used.
        self.clear_buffer()

        sig = data[:, self.input_channel]
        fs = self.audio_engine.sample_rate

        # Capture current params safely
        p_start = self.start_freq
        p_stop = self.stop_freq
        p_points = self.points
        p_spacing = self.spacing
        p_unit = self.display_unit
        p_offset_dbv = self.audio_engine.calibration.get_input_offset_db()
        p_offset_spl = self.audio_engine.calibration.get_spl_offset_db()
        p_mode = self.mode
        p_zoom_center = self.zoom_center_freq
        p_zoom_span = self.zoom_span
        p_window = self.window_type
        p_include_targets = self.include_scan_targets
        p_octave_ref = self.octave_ref_freq
        p_targets = self.current_targets.copy()

        self._calculation_future = self.executor.submit(
            self._do_calculation,
            sig,
            fs,
            p_start,
            p_stop,
            p_points,
            p_spacing,
            p_unit,
            p_offset_dbv,
            p_offset_spl,
            p_mode,
            p_zoom_center,
            p_zoom_span,
            p_window,
            p_include_targets,
            p_octave_ref,
            p_targets,
        )
        self._analysis_warmed_up = True

    def _select_peak_freqs(self, freqs: np.ndarray, mags_db: np.ndarray) -> list[float]:
        if len(freqs) == 0 or len(mags_db) == 0:
            return []

        if len(freqs) <= 2:
            order = np.argsort(mags_db)[::-1]
            return [float(freqs[i]) for i in order[: self.sonifier.max_peaks]]

        candidate_idx = []
        for idx in range(len(mags_db)):
            left = mags_db[idx - 1] if idx > 0 else -np.inf
            right = mags_db[idx + 1] if idx < len(mags_db) - 1 else -np.inf
            if mags_db[idx] >= left and mags_db[idx] >= right:
                candidate_idx.append(idx)

        if not candidate_idx:
            candidate_idx = list(range(len(mags_db)))

        ranked = sorted(candidate_idx, key=lambda i: mags_db[i], reverse=True)
        top_idx = ranked[: self.sonifier.max_peaks]
        return [float(freqs[i]) for i in top_idx]

    def _update_sonifier_peaks(self, freqs: np.ndarray, mags_db: np.ndarray):
        if len(freqs) == 0:
            self.sonifier.update_peaks([])
            return

        self.sonifier.update_peaks(
            self._select_peak_freqs(freqs, mags_db),
            spectrum_range=(float(freqs[0]), float(freqs[-1])),
        )

    def _do_calculation(
        self,
        sig,
        fs,
        start_f,
        stop_f,
        points,
        spacing,
        display_unit,
        offset_dbv,
        offset_spl,
        mode="Scan",
        zoom_center=1000.0,
        zoom_span=10.0,
        window_type="none",
        include_targets=True,
        octave_ref=1000.0,
        targets=None,
    ):
        """
        Background heavy lifting: Matrix projection or Zoom DDC
        """
        import time
        import scipy.signal as signal

        N = len(sig)
        t = np.arange(N, dtype=np.float64) / fs

        if mode == "Zoom":
            s_f = zoom_center - zoom_span
            e_f = zoom_center + zoom_span
            freqs = np.linspace(s_f, e_f, points)
            self.signals.sweep_started.emit((freqs, []))

            # 1. Baseband mixing (DDC)
            sig_c = sig * np.exp(-1j * 2 * np.pi * zoom_center * t)

            # 2. Decimate to reduce points
            # 巨大な間引き率によるハングを防ぐため、100Hz以上のサンプリングレートを維持
            target_fs = max(zoom_span * 4, 100.0)
            M = max(1, int(fs / target_fs))

            if M > 1:
                sig_dec = signal.resample_poly(sig_c, 1, M)
            else:
                sig_dec = sig_c

            fs_dec = fs / M
            N_dec = len(sig_dec)
            t_dec = np.arange(N_dec) / fs_dec

            freqs_offset = np.linspace(-zoom_span, zoom_span, points)
            mags_db_all = np.zeros(points)

            # --- 窓関数の適用 ---
            if window_type == "none":
                window = np.ones(N_dec, dtype=np.float64)
                sig_dec_win = sig_dec
                window_coherent_gain = 1.0
            else:
                window = signal.get_window(window_type, N_dec)
                sig_dec_win = sig_dec * window
                window_coherent_gain = np.mean(window)
                if window_coherent_gain == 0:
                    window_coherent_gain = 1.0

            chunk_size = 32
            for i in range(0, points, chunk_size):
                if not self.is_running:
                    break
                end_idx = min(i + chunk_size, points)
                f_chunk = freqs_offset[i:end_idx]
                phase = t_dec[:, np.newaxis] * f_chunk
                exp_chunk = np.exp(-2j * np.pi * phase)
                # Direct correlation on decimated baseband with windowing (vectorized)
                vals = (sig_dec_win @ exp_chunk) / (N_dec * window_coherent_gain)
                amp = np.abs(vals) * 2.0
                if display_unit in ["dBV", "dB SPL"]:
                    amp /= np.sqrt(2.0)

                mags_db_chunk = 20.0 * np.log10(amp + 1e-15)
                if display_unit == "dBV":
                    mags_db_chunk += offset_dbv
                elif display_unit == "dB SPL" and offset_spl is not None:
                    mags_db_chunk += offset_spl

                mags_db_all[i:end_idx] = mags_db_chunk

                # Compute Phase
                phases = np.angle(vals)

                # Emit result chunk back to GUI thread
                self.signals.progress_update.emit(i, end_idx, freqs_offset[i:end_idx].copy(), mags_db_chunk.copy(), phases.copy())
                time.sleep(0.005)

            if self.is_running:
                self._update_sonifier_peaks(freqs, mags_db_all)
                # phases unmerged across chunks back to main for zoom (optional completeness)
                self.signals.result_ready.emit((freqs, mags_db_all))
            return

        # Scan Mode (Matrix Projection)
        if spacing == "Log":
            # Avoid log of 0 or negative
            s_f = max(0.1, start_f)
            freqs = np.logspace(np.log10(s_f), np.log10(stop_f), points)
        elif spacing == "Integer":
            freqs = np.unique(np.round(np.linspace(start_f, stop_f, points)))
            freqs = freqs[freqs >= 1.0]  # Prevent 0 Hz
        elif spacing == "Int x Sync":
            df = fs / N
            freqs = np.unique(np.round(np.linspace(start_f, stop_f, points) / df) * df)
            freqs = freqs[freqs >= df]  # Prevent 0 Hz and extremely low frequencies
            if len(freqs) == 0:
                freqs = np.array([df])
        elif spacing.endswith("Octave"):
            try:
                frac = spacing.split(" ")[0].split("/")
                b = float(frac[1]) / float(frac[0])
            except Exception:
                b = 3.0

            n_start = int(np.floor(b * np.log2(start_f / octave_ref)))
            n_stop = int(np.ceil(b * np.log2(stop_f / octave_ref)))
            n_vals = np.arange(n_start, n_stop + 1)
            freqs = octave_ref * (2.0 ** (n_vals / b))
            # Clip bounds exactly
            freqs = freqs[(freqs >= start_f) & (freqs <= stop_f)]
            if len(freqs) == 0:
                freqs = np.array([start_f, stop_f])
        else:  # "Lin"
            freqs = np.linspace(start_f, stop_f, points)

        marker_freqs = []
        if include_targets and targets:
            marker_freqs = [f for f in targets.keys() if start_f < f < stop_f]
            if marker_freqs:
                # np.unique stably sorts and prevents duplicates
                freqs = np.unique(np.concatenate([freqs, marker_freqs]))

        points = len(freqs)

        self.signals.sweep_started.emit((freqs, marker_freqs))

        # To prevent CPU overallocation and buffer underruns, we process in chunks.
        # This spreads the load and allows for progressive UI updates (sliding line).
        chunk_size = 32
        mags_db_all = np.zeros(points)

        # --- 初期窓関数の適用 (指定された窓関数) ---
        # このNはsig全体の長さ
        import scipy.signal as signal

        if window_type == "none":
            window_orig = np.ones(N, dtype=np.float64)
        else:
            window_orig = signal.get_window(window_type, N)
        sqrt_win_orig = np.sqrt(np.maximum(window_orig, 0.0))
        sig_win_orig = sig * sqrt_win_orig

        decimation_cache = {
            1: (sig_win_orig, sqrt_win_orig, N, fs, t),
        }

        for i in range(0, points, chunk_size):
            if not self.is_running:
                break

            end_idx = min(i + chunk_size, points)
            current_points = end_idx - i
            num_bases = 1 + current_points * 2
            f_chunk = freqs[i:end_idx]

            # --- Multi-rate downsampling ---
            max_f = f_chunk[-1]
            target_fs = max_f * 4.0
            M = max(1, int(fs / target_fs))

            cached = decimation_cache.get(M)
            if cached is None:
                sig_dec = signal.resample_poly(sig, 1, M)
                N_chunk = len(sig_dec)
                fs_dec = fs / M
                if window_type == "none":
                    window_dec = np.ones(N_chunk, dtype=np.float64)
                else:
                    window_dec = signal.get_window(window_type, N_chunk)
                sqrt_win = np.sqrt(np.maximum(window_dec, 0.0))
                sig_win = sig_dec * sqrt_win
                t_chunk = np.arange(N_chunk, dtype=np.float64) / fs_dec
                cached = (sig_win, sqrt_win, N_chunk, fs_dec, t_chunk)
                decimation_cache[M] = cached

            sig_win, sqrt_win, N_chunk, fs_dec, t_chunk = cached

            two_pi_t = 2.0 * np.pi * t_chunk
            phase = two_pi_t[:, np.newaxis] * f_chunk

            # Allocate Windowed Basis Matrix for the local chunk
            # [1, cos(w1), sin(w1), cos(w1), sin(w1), ...]
            B_win = np.empty((N_chunk, num_bases), dtype=np.float64)  # 高精度化 (float64)
            B_win[:, 0] = sqrt_win  # DC includes the window weight

            # Compute and apply window weight directly in pre-allocated array
            np.cos(phase, out=B_win[:, 1::2])
            B_win[:, 1::2] *= sqrt_win[:, np.newaxis]

            np.sin(phase, out=B_win[:, 2::2])
            B_win[:, 2::2] *= sqrt_win[:, np.newaxis]

            # Free memory immediately
            del phase

            # Since B can be huge, we use Gram directly for speed:
            gram = np.dot(B_win.T, B_win)
            rhs = np.dot(B_win.T, sig_win)

            try:
                # try speedy solve
                coeff = np.linalg.solve(gram, rhs)
            except np.linalg.LinAlgError:
                # fallback
                coeff = np.linalg.lstsq(B_win, sig_win, rcond=None)[0]

            # Extract magnitudes for this chunk
            X = coeff[1:]
            iq = X.reshape(-1, 2)
            amp = np.hypot(iq[:, 0], iq[:, 1])
            if display_unit in ["dBV", "dB SPL"]:
                amp /= np.sqrt(2.0)

            mags_db_chunk = 20.0 * np.log10(amp + 1e-15)
            if display_unit == "dBV":
                mags_db_chunk += offset_dbv
            elif display_unit == "dB SPL" and offset_spl is not None:
                mags_db_chunk += offset_spl

            mags_db_all[i:end_idx] = mags_db_chunk

            # iq[:,0] is cos component, iq[:,1] is sin component
            # Standard phase from complex is angle(cos - j*sin)
            phases = np.arctan2(-iq[:, 1], iq[:, 0])

            # Emit result chunk back to GUI thread
            self.signals.progress_update.emit(i, end_idx, freqs[i:end_idx].copy(), mags_db_chunk.copy(), phases.copy())

            # Sleep briefly to ensure audio callback is not starved
            time.sleep(0.005)

        if self.is_running:
            self._update_sonifier_peaks(freqs, mags_db_all)
            self.signals.result_ready.emit((freqs, mags_db_all))


class LockInSpectrumFinderWidget(QWidget):
    def __init__(self, module: LockInSpectrumFinder):
        super().__init__()
        self.module = module
        self.init_ui()

        self.module.signals.result_ready.connect(self.on_result_ready)
        self.module.signals.sweep_started.connect(self.on_sweep_started)
        self.module.signals.progress_update.connect(self.on_progress_update)

        self.timer = QTimer()
        self.timer.timeout.connect(self.check_calculation)
        self.timer.setInterval(100)  # Check every 100ms

    def init_ui(self):
        layout = QHBoxLayout()

        # LEFT: Controls
        left_panel = QVBoxLayout()
        settings_group = QGroupBox(tr("Settings"))
        form = QFormLayout()

        self.btn_toggle = QPushButton(tr("Start Analysis"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle)
        self.btn_toggle.setStyleSheet("QPushButton:checked { background-color: #ccffcc; }")
        form.addRow(self.btn_toggle)

        # Mode Selection
        self.combo_mode = QComboBox()
        self.combo_mode.addItem(tr("Scan"), "Scan")
        self.combo_mode.addItem(tr("Zoom"), "Zoom")
        idx = self.combo_mode.findData(self.module.mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        form.addRow(tr("Mode:"), self.combo_mode)

        # Averages (EMA)
        self.lbl_averages = QLabel(tr("Averages:"))
        self.spin_averages = QSpinBox()
        self.spin_averages.setRange(1, 1000)
        self.spin_averages.setValue(1)
        self.spin_averages.valueChanged.connect(self.on_averages_changed)
        form.addRow(self.lbl_averages, self.spin_averages)

        # Buffer size
        self.combo_buffer = QComboBox()
        self._update_buffer_options()
        form.addRow(tr("Buffer Size:"), self.combo_buffer)

        # Input Channel
        self.combo_input_ch = QComboBox()
        self.combo_input_ch.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)")])
        self.combo_input_ch.setCurrentIndex(self.module.input_channel)
        self.combo_input_ch.currentIndexChanged.connect(self.on_input_ch_changed)
        form.addRow(tr("Input Ch:"), self.combo_input_ch)

        # Grid settings
        self.spin_points = QSpinBox()
        self.spin_points.setRange(16, 1024)
        self.spin_points.setValue(self.module.points)
        self.spin_points.setSingleStep(32)
        self.spin_points.valueChanged.connect(self.on_points_changed)
        form.addRow(tr("Basis Points:"), self.spin_points)

        # Window Function
        self.lbl_window = QLabel(tr("Window:"))
        self.combo_window = QComboBox()
        self.combo_window.addItems(["none", "blackmanharris", "hann", "hamming"])
        self.combo_window.setCurrentText(self.module.window_type)
        self.combo_window.currentTextChanged.connect(self.on_window_changed)
        form.addRow(self.lbl_window, self.combo_window)

        # Display Unit
        self.lbl_unit = QLabel(tr("Display Unit:"))
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["dBFS", "dBV", "dB SPL"])
        self.combo_unit.setCurrentText(self.module.display_unit)
        self.combo_unit.currentTextChanged.connect(self.on_unit_changed)
        form.addRow(self.lbl_unit, self.combo_unit)

        self.lbl_start_f = QLabel(tr("Start Freq:"))
        self.spin_start_f = QDoubleSpinBox()
        self.spin_start_f.setRange(1.0, 192000.0)
        self.spin_start_f.setValue(self.module.start_freq)
        self.spin_start_f.setSuffix(" Hz")
        self.spin_start_f.valueChanged.connect(self.on_start_f_changed)
        form.addRow(self.lbl_start_f, self.spin_start_f)

        self.lbl_stop_f = QLabel(tr("Stop Freq:"))
        self.spin_stop_f = QDoubleSpinBox()
        self.spin_stop_f.setRange(10.0, 192000.0)
        self.spin_stop_f.setValue(self.module.stop_freq)
        self.spin_stop_f.setSuffix(" Hz")
        self.spin_stop_f.valueChanged.connect(self.on_stop_f_changed)
        form.addRow(self.lbl_stop_f, self.spin_stop_f)

        self.lbl_spacing = QLabel(tr("Spacing:"))
        self.combo_spacing = QComboBox()
        self.combo_spacing.addItem(tr("Log"), "Log")
        self.combo_spacing.addItem(tr("Lin"), "Lin")
        self.combo_spacing.addItem(tr("Integer"), "Integer")
        self.combo_spacing.addItem(tr("Int x Sync"), "Int x Sync")
        self.combo_spacing.addItem(tr("1/3 Octave"), "1/3 Octave")
        self.combo_spacing.addItem(tr("1/6 Octave"), "1/6 Octave")
        self.combo_spacing.addItem(tr("1/12 Octave"), "1/12 Octave")
        self.combo_spacing.addItem(tr("1/24 Octave"), "1/24 Octave")
        self.combo_spacing.addItem(tr("1/48 Octave"), "1/48 Octave")
        self.combo_spacing.addItem(tr("1/96 Octave"), "1/96 Octave")
        idx = self.combo_spacing.findData(self.module.spacing)
        if idx >= 0:
            self.combo_spacing.setCurrentIndex(idx)
        self.combo_spacing.currentIndexChanged.connect(self.on_spacing_changed)
        form.addRow(self.lbl_spacing, self.combo_spacing)

        # Add Include Scan Targets Option
        self.chk_include_targets = QCheckBox(tr("Include Scan Targets"))
        self.chk_include_targets.setChecked(self.module.include_scan_targets)
        self.chk_include_targets.stateChanged.connect(self.on_include_targets_changed)
        form.addRow(tr("Scan Targets:"), self.chk_include_targets)

        self.lbl_octave_ref = QLabel(tr("Octave Ref Freq:"))
        self.spin_octave_ref = QDoubleSpinBox()
        self.spin_octave_ref.setRange(1.0, 192000.0)
        self.spin_octave_ref.setValue(self.module.octave_ref_freq)
        self.spin_octave_ref.setSuffix(" Hz")
        self.spin_octave_ref.valueChanged.connect(self.on_octave_ref_changed)
        form.addRow(self.lbl_octave_ref, self.spin_octave_ref)

        # Zoom Mode Fields
        self.lbl_zoom_center = QLabel(tr("Zoom Center:"))
        self.spin_zoom_center = QDoubleSpinBox()
        self.spin_zoom_center.setRange(1.0, 192000.0)
        self.spin_zoom_center.setValue(self.module.zoom_center_freq)
        self.spin_zoom_center.setSuffix(" Hz")
        self.spin_zoom_center.valueChanged.connect(self.on_zoom_center_changed)

        self.chk_track_peak = QCheckBox(tr("Track Peak"))
        self.chk_track_peak.setChecked(self.module.track_peak)
        self.chk_track_peak.stateChanged.connect(self.on_track_peak_changed)

        hbox_zoom_center = QHBoxLayout()
        hbox_zoom_center.setContentsMargins(0, 0, 0, 0)
        hbox_zoom_center.addWidget(self.spin_zoom_center)
        hbox_zoom_center.addWidget(self.chk_track_peak)
        form.addRow(self.lbl_zoom_center, hbox_zoom_center)

        self.lbl_zoom_span = QLabel(tr("Zoom Span (±):"))
        self.spin_zoom_span = QDoubleSpinBox()
        self.spin_zoom_span.setRange(0.1, 10000.0)
        self.spin_zoom_span.setValue(self.module.zoom_span)
        self.spin_zoom_span.setSuffix(" Hz")
        self.spin_zoom_span.valueChanged.connect(self.on_zoom_span_changed)
        form.addRow(self.lbl_zoom_span, self.spin_zoom_span)

        self._update_ui_visibility()

        settings_group.setLayout(form)

        self.tabs = QTabWidget()
        self.tabs.addTab(settings_group, tr("Settings"))

        # Targets Tab
        target_tab = QWidget()
        target_layout = QVBoxLayout(target_tab)
        target_layout.setContentsMargins(0, 0, 0, 0)

        self.table_targets = QTableWidget(0, 2)
        self.table_targets.setHorizontalHeaderLabels([tr("Frequency (Hz)"), tr("Cause / Note")])
        self.table_targets.horizontalHeader().setStretchLastSection(True)
        self.table_targets.verticalHeader().setVisible(False)
        self.table_targets.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_targets.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_targets.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        self._populate_targets_table()

        target_layout.addWidget(self.table_targets)
        self.table_targets.cellDoubleClicked.connect(self.on_target_double_clicked)

        # Add target control buttons
        btn_layout = QGridLayout()
        self.btn_add_target = QPushButton(tr("Add"))
        self.btn_add_target.clicked.connect(self.on_add_target)
        self.btn_del_target = QPushButton(tr("Delete"))
        self.btn_del_target.clicked.connect(self.on_delete_target)
        self.btn_import_targets = QPushButton(tr("Import Targets"))
        self.btn_import_targets.clicked.connect(self.on_import_targets)
        self.btn_export_targets = QPushButton(tr("Export Targets"))
        self.btn_export_targets.clicked.connect(self.on_export_targets)
        self.btn_zoom_target = QPushButton(tr("Zoom to Selected"))
        self.btn_zoom_target.clicked.connect(self.on_zoom_target)
        self.btn_reset_targets = QPushButton(tr("Reset Defaults"))
        self.btn_reset_targets.clicked.connect(self.on_reset_targets)

        btn_layout.addWidget(self.btn_add_target, 0, 0)
        btn_layout.addWidget(self.btn_del_target, 0, 1)
        btn_layout.addWidget(self.btn_zoom_target, 0, 2)
        btn_layout.addWidget(self.btn_import_targets, 1, 0)
        btn_layout.addWidget(self.btn_export_targets, 1, 1)
        btn_layout.addWidget(self.btn_reset_targets, 1, 2)

        target_layout.addLayout(btn_layout)

        self.tabs.addTab(target_tab, tr("Scan Targets"))

        # Target Generators Tab
        gen_tab = QWidget()
        gen_layout = QVBoxLayout(gen_tab)

        # Mains Power Group
        mains_group = QGroupBox(tr("Mains Power"))
        mains_form = QFormLayout()

        self.combo_mains_freq = QComboBox()
        self.combo_mains_freq.addItem(tr("Both (50/60 Hz)"), None)
        self.combo_mains_freq.addItem("50 Hz", 50.0)
        self.combo_mains_freq.addItem("60 Hz", 60.0)
        idx = self.combo_mains_freq.findData(self.module.mains_freq)
        if idx >= 0:
            self.combo_mains_freq.setCurrentIndex(idx)
        self.combo_mains_freq.currentIndexChanged.connect(self.on_mains_freq_changed)
        mains_form.addRow(tr("Mains Frequency:"), self.combo_mains_freq)

        self.spin_mains_harmonics = QSpinBox()
        self.spin_mains_harmonics.setRange(1, 100)
        self.spin_mains_harmonics.setValue(self.module.mains_harmonics_count)
        self.spin_mains_harmonics.valueChanged.connect(self.on_mains_harmonics_changed)
        mains_form.addRow(tr("Number of Harmonics:"), self.spin_mains_harmonics)

        mains_group.setLayout(mains_form)
        gen_layout.addWidget(mains_group)

        # Musical Scale Group
        scale_group = QGroupBox(tr("Musical Scale (Equal Temperament)"))
        scale_form = QFormLayout()

        self.chk_musical_scale = QCheckBox(tr("Include Musical Scale"))
        self.chk_musical_scale.setChecked(self.module.include_musical_scale)
        self.chk_musical_scale.stateChanged.connect(self.on_musical_scale_changed)
        scale_form.addRow(self.chk_musical_scale)

        self.spin_a4_freq = QDoubleSpinBox()
        self.spin_a4_freq.setRange(400.0, 500.0)
        self.spin_a4_freq.setDecimals(2)
        self.spin_a4_freq.setValue(self.module.a4_freq)
        self.spin_a4_freq.setSuffix(" Hz")
        self.spin_a4_freq.valueChanged.connect(self.on_a4_freq_changed)
        scale_form.addRow(tr("A4 Reference Frequency:"), self.spin_a4_freq)

        scale_group.setLayout(scale_form)
        gen_layout.addWidget(scale_group)

        gen_layout.addStretch()

        self.btn_apply_gen = QPushButton(tr("Apply Generation Settings"))
        self.btn_apply_gen.clicked.connect(self.on_apply_gen)
        gen_layout.addWidget(self.btn_apply_gen)

        self.tabs.addTab(gen_tab, tr("Target Generators"))

        # Audio Sonification Tab
        sonification_tab = QWidget()
        sonification_layout = QVBoxLayout(sonification_tab)

        sonification_group = QGroupBox(tr("Audio Sonification"))
        sonification_form = QFormLayout()

        self.chk_sonification_enable = QCheckBox(tr("Enable Sonification"))
        self.chk_sonification_enable.setChecked(self.module.sonifier.enabled)
        self.chk_sonification_enable.stateChanged.connect(self.on_audio_enable_toggled)
        sonification_form.addRow(self.chk_sonification_enable)

        self.lbl_sonification_info = QLabel(
            ""
        )
        self.lbl_sonification_info.setWordWrap(True)
        sonification_form.addRow(self.lbl_sonification_info)

        self.combo_sonification_mode = QComboBox()
        self.combo_sonification_mode.addItem(tr("Chord Tones"), self.module.sonifier.MODE_CHORD)
        self.combo_sonification_mode.addItem(tr("Rhythmic Beeps"), self.module.sonifier.MODE_SWEEP_BEEPS)
        idx = self.combo_sonification_mode.findData(self.module.sonifier.mode)
        if idx >= 0:
            self.combo_sonification_mode.setCurrentIndex(idx)
        self.combo_sonification_mode.currentIndexChanged.connect(self.on_audio_mode_changed)
        sonification_form.addRow(tr("Playback Mode:"), self.combo_sonification_mode)

        self.spin_sonification_peaks = QSpinBox()
        self.spin_sonification_peaks.setRange(1, self.module.sonifier.MAX_SUPPORTED_PEAKS)
        self.spin_sonification_peaks.setValue(self.module.sonifier.max_peaks)
        self.spin_sonification_peaks.valueChanged.connect(self.on_audio_peaks_changed)
        sonification_form.addRow(tr("Peak Count:"), self.spin_sonification_peaks)

        self.spin_sonification_vol = QDoubleSpinBox()
        self.spin_sonification_vol.setRange(0.0, 100.0)
        self.spin_sonification_vol.setValue(self.module.sonifier.master_volume * 100.0)
        self.spin_sonification_vol.setSuffix(" %")
        self.spin_sonification_vol.valueChanged.connect(self.on_audio_volume_changed)
        sonification_form.addRow(tr("Volume:"), self.spin_sonification_vol)

        self.combo_sonification_ch = QComboBox()
        self.combo_sonification_ch.addItem(tr("Left (Ch 1)"), 0)
        self.combo_sonification_ch.addItem(tr("Right (Ch 2)"), 1)
        self.combo_sonification_ch.addItem(tr("Both"), 2)
        idx = self.combo_sonification_ch.findData(self.module.sonifier.output_channel)
        if idx >= 0:
            self.combo_sonification_ch.setCurrentIndex(idx)
        self.combo_sonification_ch.currentIndexChanged.connect(self.on_audio_channel_changed)
        sonification_form.addRow(tr("Output Channel:"), self.combo_sonification_ch)

        sonification_group.setLayout(sonification_form)
        sonification_layout.addWidget(sonification_group)
        sonification_layout.addStretch()

        self.tabs.addTab(sonification_tab, tr("Audio Sonification"))
        self._update_audio_sonification_info()

        left_panel.addWidget(self.tabs)

        # Status Label
        ov_group = QGroupBox(tr("Status"))
        ov_layout = QVBoxLayout()
        self.lbl_status = QLabel(tr("Ready"))
        self.lbl_status.setStyleSheet("font-size: 14px;")
        ov_layout.addWidget(self.lbl_status)
        ov_group.setLayout(ov_layout)
        left_panel.addWidget(ov_group)

        left_panel.addStretch()
        layout.addLayout(left_panel, 1)

        # RIGHT: Plot
        right_panel = QVBoxLayout()
        self.plot = pg.PlotWidget(title=tr("Lock-in Spectrum"))
        self.plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot.setLabel("left", tr("Amplitude"), units=self.module.display_unit)
        self.plot.showGrid(x=True, y=True)
        self.plot.setYRange(-180, 10)
        self.curve = self.plot.plot(pen="y")

        self.scatter = pg.ScatterPlotItem(
            size=10,
            pen=pg.mkPen(None),
            brush=pg.mkBrush(255, 0, 0, 200),
            hoverable=True,
            hoverSize=15,
            tip=self._get_marker_tooltip,
        )
        self.plot.addItem(self.scatter)
        self.scatter.sigClicked.connect(self.on_scatter_clicked)

        # Initialize Log mode visual
        self._update_plot_log_mode()

        right_panel.addWidget(self.plot)
        layout.addLayout(right_panel, 3)

        self.setLayout(layout)

    def _get_marker_tooltip(self, x, y, data):
        if not data:
            return ""

        freq = data.get("freq", 0.0)
        mag = data.get("mag", -180.0)
        phase = data.get("phase_deg", 0.0)
        note = data.get("note", "")
        unit = data.get("unit", "")

        text = (
            f"<b>{tr(note)}</b><br>"
            f"{tr('Frequency:')} {freq:.1f} Hz<br>"
            f"{tr('Magnitude:')} {mag:.2f} {unit}<br>"
            f"{tr('Phase:')} {phase:.1f}°"
        )
        return text

    def _update_ui_visibility(self):
        is_zoom = self.module.mode == "Zoom"

        self.lbl_start_f.setVisible(not is_zoom)
        self.spin_start_f.setVisible(not is_zoom)
        self.lbl_stop_f.setVisible(not is_zoom)
        self.spin_stop_f.setVisible(not is_zoom)
        self.lbl_spacing.setVisible(not is_zoom)
        self.combo_spacing.setVisible(not is_zoom)
        self.chk_include_targets.setVisible(not is_zoom)
        self.lbl_octave_ref.setVisible(not is_zoom)
        self.spin_octave_ref.setVisible(not is_zoom)

        self.lbl_zoom_center.setVisible(is_zoom)
        self.spin_zoom_center.setVisible(is_zoom)
        self.chk_track_peak.setVisible(is_zoom)
        self.lbl_zoom_span.setVisible(is_zoom)
        self.spin_zoom_span.setVisible(is_zoom)

    def _update_buffer_options(self):
        """Update buffer size choices based on mode."""
        # Block signals to avoid triggering on_buffer_changed during refill
        self.combo_buffer.blockSignals(True)

        current_val = str(self.module.buffer_size)

        if self.module.mode == "Scan":
            # Up to 512k (approx 500k)
            options = ["65536", "131072", "262144", "524288"]
        else:
            # Up to 8M
            options = ["65536", "131072", "262144", "524288", "1048576", "2097152", "4194304", "8388608"]

        self.combo_buffer.clear()
        self.combo_buffer.addItems(options)

        if current_val in options:
            self.combo_buffer.setCurrentText(current_val)
        else:
            # Auto-cap at max available for this mode
            new_val = options[-1]
            self.combo_buffer.setCurrentText(new_val)
            self.module.buffer_size = int(new_val)

        # Re-connect/unblock signals
        try:
            self.combo_buffer.currentTextChanged.disconnect()
        except TypeError:
            pass
        self.combo_buffer.currentTextChanged.connect(self.on_buffer_changed)
        self.combo_buffer.blockSignals(False)

    def _update_plot_log_mode(self):
        if self.module.mode == "Scan" and self.module.spacing == "Log":
            self.plot.getPlotItem().setLogMode(x=True, y=False)
        else:
            self.plot.getPlotItem().setLogMode(x=False, y=False)

    def reset_averaging(self):
        self.averaged_amps = None
        self.frames_counted = 0

    def on_averages_changed(self, val):
        self.reset_averaging()

    def on_mode_changed(self, idx):
        self.module.mode = self.combo_mode.itemData(idx)
        self._update_plot_log_mode()
        self._update_ui_visibility()
        self._update_buffer_options()
        self.reset_averaging()

    def on_toggle(self, checked):
        if checked:
            self.reset_averaging()
            self.module.start_analysis()
            self.timer.start()
            self.btn_toggle.setText(tr("Stop Analysis"))
            self.lbl_status.setText(tr("Buffering..."))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.btn_toggle.setText(tr("Start Analysis"))
            self.lbl_status.setText(tr("Stopped"))

    def on_buffer_changed(self, text):
        self.module.buffer_size = int(text)
        self.reset_averaging()
        if self.module.is_running:
            self.module.stop_analysis()
            self.module.start_analysis()

    def on_input_ch_changed(self, idx):
        self.module.input_channel = idx
        self.reset_averaging()

    def on_points_changed(self, val):
        self.module.points = val
        self.reset_averaging()

    def on_start_f_changed(self, val):
        self.module.start_freq = val
        self.reset_averaging()

    def on_stop_f_changed(self, val):
        self.module.stop_freq = val
        self.reset_averaging()

    def on_spacing_changed(self, idx):
        self.module.spacing = self.combo_spacing.itemData(idx)
        self._update_plot_log_mode()
        self.reset_averaging()

    def on_zoom_center_changed(self, val):
        self.module.zoom_center_freq = val
        self.reset_averaging()

    def on_zoom_span_changed(self, val):
        self.module.zoom_span = val
        self.reset_averaging()

    def on_track_peak_changed(self, state):
        self.module.track_peak = bool(state)

    def on_window_changed(self, text):
        self.module.window_type = text
        self.reset_averaging()

    def on_unit_changed(self, text):
        self.module.display_unit = text
        self.plot.setLabel("left", tr("Amplitude"), units=text)
        self.reset_averaging()

    def check_calculation(self):
        if not self.module.is_running:
            return

        with self.module.lock:
            filled = self.module.buffer_filled_samples
            size = self.module.buffer_size

        target_samples = size if self.module._analysis_warmed_up else self.module._get_min_analysis_samples()

        if filled < target_samples:
            pct = int((filled / max(1, target_samples)) * 100)
            if self.module._calculation_future is None or self.module._calculation_future.done():
                self.lbl_status.setText(tr("Buffering... {}%").format(pct))
            return

        # Trigger background computation
        self.module.trigger_calculation()

    def on_sweep_started(self, payload):
        freqs, marker_freqs = payload
        self.current_freqs = freqs.copy()
        self.current_marker_freqs = marker_freqs

        if not hasattr(self, "averaged_amps") or self.averaged_amps is None or len(self.averaged_amps) != len(freqs):
            self.averaged_amps = np.zeros(len(freqs))
            self.frames_counted = 0

            # Reset X-axis plot range on new parameters
            # Handle Log scale formatting internally for UI bounds
            xmin, xmax = freqs[0], freqs[-1]
            if self.module.mode == "Scan" and self.module.spacing == "Log" and xmin > 0:
                xmin, xmax = np.log10(xmin), np.log10(xmax)
            self.plot.setXRange(xmin, xmax, padding=0.0)

        if not hasattr(self, "current_mags") or len(self.current_mags) != len(freqs):
            self.current_mags = np.full(len(freqs), -180.0)

        self.frames_counted += 1

        if not hasattr(self, "sweep_line"):
            self.sweep_line = pg.InfiniteLine(angle=90, movable=False, pen="r")
            self.plot.addItem(self.sweep_line)

        self.sweep_line.show()
        val = freqs[0]
        if self.module.mode == "Scan" and self.module.spacing == "Log" and val > 0:
            val = np.log10(val)
        self.sweep_line.setValue(val)
        self.scatter.setData([])  # clear markers
        self.lbl_status.setText(tr("Calculating... 0%"))

    def _update_scatter_plot(self):
        if not hasattr(self, "current_marker_freqs") or not self.current_marker_freqs:
            self.scatter.setData([])
            return

        pts = []
        for mf in self.current_marker_freqs:
            idx = np.searchsorted(self.current_freqs, mf)

            def check_and_add(i, mf=mf):
                if 0 <= i < len(self.current_freqs) and np.isclose(self.current_freqs[i], mf, atol=1e-3):
                    y = self.current_mags[i]
                    x = mf
                    phase = float(self.current_phases[i]) if hasattr(self, "current_phases") else 0.0
                    note = self.module.current_targets.get(mf, "Unknown")
                    unit = self.module.display_unit

                    # Store rich data in the item
                    data_obj = {"freq": mf, "mag": y, "phase_deg": np.degrees(phase), "note": note, "unit": unit}

                    if self.module.mode == "Scan" and self.module.spacing == "Log" and x > 0:
                        x = np.log10(x)
                    if y > -170:
                        pts.append({"pos": (x, y), "data": data_obj})
                    return True
                return False

            if not check_and_add(idx):
                check_and_add(idx - 1)

        self.scatter.setData(pts)

    def on_progress_update(self, start_idx, end_idx, f_chunk, m_chunk, p_chunk):
        if not hasattr(self, "current_freqs") or not hasattr(self, "current_mags"):
            return

        if not hasattr(self, "current_phases") or len(self.current_phases) != len(self.current_freqs):
            self.current_phases = np.zeros(len(self.current_freqs))

        if (
            not hasattr(self, "averaged_amps")
            or self.averaged_amps is None
            or len(self.averaged_amps) != len(self.current_freqs)
        ):
            self.averaged_amps = np.zeros(len(self.current_freqs))
            self.frames_counted = 1

        self.current_phases[start_idx:end_idx] = p_chunk

        alpha = 1.0 / min(self.spin_averages.value(), max(1, self.frames_counted))

        a_chunk = 10.0 ** (m_chunk / 20.0)

        if self.frames_counted <= 1:
            self.averaged_amps[start_idx:end_idx] = a_chunk
        else:
            self.averaged_amps[start_idx:end_idx] = (1.0 - alpha) * self.averaged_amps[
                start_idx:end_idx
            ] + alpha * a_chunk

        avg_db = 20.0 * np.log10(self.averaged_amps[start_idx:end_idx] + 1e-15)
        self.current_mags[start_idx:end_idx] = avg_db
        self.curve.setData(self.current_freqs, self.current_mags)

        self._update_scatter_plot()

        if hasattr(self, "sweep_line"):
            self.sweep_line.show()
            val = f_chunk[-1]
            if self.module.mode == "Scan" and self.module.spacing == "Log" and val > 0:
                val = np.log10(val)
            self.sweep_line.setValue(val)
        pct = int((end_idx / len(self.current_freqs)) * 100)
        avg_text = ""
        if self.spin_averages.value() > 1:
            avg_text = (
                f" [{tr('Avg:')} {min(self.spin_averages.value(), self.frames_counted)}/{self.spin_averages.value()}]"
            )
        self.lbl_status.setText(tr("Calculating... {}%").format(pct) + avg_text)

    def on_result_ready(self, result):
        freqs, mags_db = result
        self.curve.setData(self.current_freqs, self.current_mags)
        self._update_scatter_plot()
        if hasattr(self, "sweep_line"):
            self.sweep_line.hide()

        avg_text = ""
        if self.spin_averages.value() > 1:
            avg_text = (
                f" [{tr('Avg:')} {min(self.spin_averages.value(), self.frames_counted)}/{self.spin_averages.value()}]"
            )
        self.lbl_status.setText(tr("Spectrum Updated") + avg_text)

        if self.module.mode == "Zoom" and self.module.track_peak:
            peak_idx = int(np.argmax(self.current_mags))
            new_center = float(self.current_freqs[peak_idx])
            if abs(new_center - self.module.zoom_center_freq) > 1e-6:
                self.spin_zoom_center.setValue(new_center)

    def on_include_targets_changed(self, state):
        self.module.include_scan_targets = bool(state)
        self.reset_averaging()

    def on_octave_ref_changed(self, val):
        self.module.octave_ref_freq = val
        self.reset_averaging()

    def on_target_double_clicked(self, row, column):
        item = self.table_targets.item(row, 0)
        if item:
            freq = float(item.text())
            self._transition_to_zoom(freq)

    def on_scatter_clicked(self, plot, points):
        if not points:
            return
        data = points[0].data()
        freq = float(data["freq"])
        self._transition_to_zoom(freq)

    def _transition_to_zoom(self, freq):
        idx = self.combo_mode.findData("Zoom")
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self.spin_zoom_center.setValue(freq)

    def _populate_targets_table(self):
        targets = self.module.current_targets
        self.table_targets.setRowCount(len(targets))
        for i, (freq, note) in enumerate(sorted(targets.items())):
            self.table_targets.setItem(i, 0, QTableWidgetItem(f"{freq:.1f}"))
            self.table_targets.setItem(i, 1, QTableWidgetItem(tr(note)))

    def on_add_target(self):
        freq, ok_f = QInputDialog.getDouble(self, tr("Add Target"), tr("Frequency (Hz):"), 1000.0, 0.1, 192000.0, 1)
        if not ok_f:
            return
        note, ok_n = QInputDialog.getText(self, tr("Add Target"), tr("Note:"))
        if not ok_n:
            return

        self.module.current_targets[freq] = note
        self.module.save_user_targets(self.module.current_targets)
        self._populate_targets_table()
        self.reset_averaging()

    def on_delete_target(self):
        row = self.table_targets.currentRow()
        if row < 0:
            return

        item = self.table_targets.item(row, 0)
        if item:
            freq = float(item.text())
            if freq in self.module.current_targets:
                del self.module.current_targets[freq]
                self.module.save_user_targets(self.module.current_targets)
                self._populate_targets_table()
                self.reset_averaging()

    def on_zoom_target(self):
        row = self.table_targets.currentRow()
        if row < 0:
            return
        item = self.table_targets.item(row, 0)
        if item:
            freq = float(item.text())
            self._transition_to_zoom(freq)

    def on_import_targets(self):
        file_path, _ = QFileDialog.getOpenFileName(self, tr("Import Targets"), "", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                new_targets = {float(k): str(v) for k, v in data.items()}
                self.module.save_user_targets(new_targets)
                self._populate_targets_table()
                self.reset_averaging()
            except Exception as e:
                QMessageBox.critical(self, tr("Error"), f"{tr('Failed to import targets:')}\n{e}")

    def on_export_targets(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, tr("Export Targets"), "scan_targets.json", "JSON Files (*.json)"
        )
        if file_path:
            try:
                fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    data = {str(k): v for k, v in self.module.current_targets.items()}
                    json.dump(data, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, tr("Success"), tr("Targets exported successfully."))
            except Exception as e:
                QMessageBox.critical(self, tr("Error"), f"{tr('Failed to export targets:')}\n{e}")

    def on_reset_targets(self):
        reply = QMessageBox.question(
            self,
            tr("Reset Defaults"),
            tr("Are you sure you want to reset targets to default?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.module.save_user_targets(
                _get_default_targets(
                    self.module.mains_freq,
                    self.module.mains_harmonics_count,
                    self.module.include_musical_scale,
                    self.module.a4_freq,
                )
            )
            self._populate_targets_table()
            self.reset_averaging()

    def on_mains_freq_changed(self, idx):
        self.module.mains_freq = self.combo_mains_freq.itemData(idx)

    def on_mains_harmonics_changed(self, val):
        self.module.mains_harmonics_count = val

    def on_musical_scale_changed(self, state):
        self.module.include_musical_scale = bool(state)

    def on_a4_freq_changed(self, val):
        self.module.a4_freq = val

    def on_apply_gen(self):
        self.module.update_generator_targets()
        self._populate_targets_table()
        self.reset_averaging()
        QMessageBox.information(self, tr("Success"), tr("Scan targets updated with generator settings."))

    def on_audio_enable_toggled(self, state):
        self.module.sonifier.set_enabled(bool(state))

    def on_audio_mode_changed(self, idx):
        mode = self.combo_sonification_mode.itemData(idx)
        if mode is not None:
            self.module.sonifier.set_mode(mode)
            self._update_audio_sonification_info()

    def on_audio_peaks_changed(self, val):
        self.module.sonifier.set_max_peaks(val)

    def on_audio_volume_changed(self, val):
        self.module.sonifier.set_volume(val / 100.0)

    def on_audio_channel_changed(self, idx):
        ch = self.combo_sonification_ch.itemData(idx)
        if ch is not None:
            self.module.sonifier.set_output_channel(ch)

    def _update_audio_sonification_info(self):
        mode = self.module.sonifier.mode
        if mode == self.module.sonifier.MODE_SWEEP_BEEPS:
            text = tr(
                "Queues short and long beeps at a steady tempo inspired by Morse timing. Playback stays readable even when scan updates are irregular."
            )
        else:
            text = tr(
                "Plays the strongest sweep peaks as simultaneous tones synchronized with the moving analysis line. More peaks increase CPU load."
            )
        self.lbl_sonification_info.setText(text)

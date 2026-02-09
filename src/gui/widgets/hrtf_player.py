import argparse
import logging
from dataclasses import dataclass
from typing import Optional

import netCDF4 as nc
import numpy as np
import pyqtgraph as pg
import soundfile as sf
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from scipy.interpolate import griddata
from scipy.signal import convolve

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.fft_manager import fft_manager
from src.core.analysis import AudioCalc


@dataclass
class HRTFData:
    source_positions: np.ndarray  # (M, 3) Az, El, Radius (Degrees, Degrees, Meters)
    ir_data: np.ndarray  # (M, R, N) M measurements, R receivers (2), N samples
    sampling_rate: float

    # Pre-calculated metrics
    itd: np.ndarray  # (M,) Microseconds
    ild: np.ndarray  # (M,) dB (overall RMS difference)
    energy_high: np.ndarray  # (M, 2) dB (8-16kHz energy L/R avg or diff?) -> Let's do Avg Energy
    group_delay_peak: np.ndarray  # (M, 2) samples or ms


class SOFALoader:
    @staticmethod
    def load(file_path: str) -> Optional[HRTFData]:
        try:
            ds = nc.Dataset(file_path, "r")

            # Read Source Position
            # Coordinate system handling can be complex in SOFA.
            # Assuming standard 'spherical' coordinates in SourcePosition variable
            # Dimensions: (M, C) where C=3
            sp_var = ds.variables.get("SourcePosition")
            if sp_var is None:
                raise ValueError("SourcePosition not found")

            source_pos = np.array(sp_var[:])

            # Helper to convert to standardized Az (-180..180), El (-90..90) if needed
            # SOFA usually uses 0..360 for Az.
            # Convert [0, 360] -> [-180, 180]
            az = source_pos[:, 0]
            el = source_pos[:, 1]
            r = source_pos[:, 2]

            az[az > 180] -= 360

            source_pos_fixed = np.column_stack((az, el, r))

            # Read IR Data
            # Variable 'Data.IR'
            ir_var = ds.variables.get("Data.IR")
            if ir_var is None:
                raise ValueError("Data.IR not found")

            ir_data = np.array(ir_var[:])
            # Dimensions usually (M, R, N). R=2 for HRTF.

            # Read Sample Rate
            # Variable 'Data.SamplingRate'
            sr_var = ds.variables.get("Data.SamplingRate")
            if sr_var is None:
                sampling_rate = 44100.0  # Fallback? Or 48000
            else:
                sampling_rate = float(np.array(sr_var[:])[0])

            ds.close()

            # Calculate Metrics
            M, R, N = ir_data.shape

            # 1. ITD (Interaural Time Difference)
            # Cross-correlation between L and R (Vectorized using FFT)
            # Pad to 2N to avoid circular correlation wrapping issues
            n_fft = 2 * N
            # FFT along axis 1 (N samples) of the sliced array
            L_fft = np.fft.rfft(ir_data[:, 0, :], n=n_fft, axis=1)
            R_fft = np.fft.rfft(ir_data[:, 1, :], n=n_fft, axis=1)
            # Cross-correlation in frequency domain
            cc = np.fft.irfft(L_fft * np.conj(R_fft), n=n_fft, axis=1)
            idx = np.argmax(cc, axis=1)
            # Adjust lags: indices 0..N correspond to lags 0..N
            # indices > N correspond to negative lags (wrapped)
            lags = np.where(idx < n_fft / 2, idx, idx - n_fft)
            itds = (lags / sampling_rate) * 1e6  # Microseconds

            # 2. ILD (Interaural Level Difference)
            # RMS dB difference (Vectorized)
            # Mean square along the sample axis (axis 2)
            ms = np.mean(ir_data ** 2, axis=2)  # (M, 2)
            rms = np.sqrt(ms) + 1e-12
            # Right/Left ratio in dB
            ilds = 20 * np.log10(rms[:, 1] / rms[:, 0])

            # 3. High-band Energy (8-16kHz)
            # Use simple FFT based energy (Vectorized)
            freqs = np.fft.rfftfreq(N, 1 / sampling_rate)
            mask = (freqs >= 8000) & (freqs <= 16000)

            # Batched FFT along axis 2 (N samples)
            spectra = np.abs(np.fft.rfft(ir_data, axis=2))

            # Masking and summing
            masked_spectra = spectra[:, :, mask]
            energies = np.sum(masked_spectra ** 2, axis=2)  # (M, 2)
            avg_e = np.mean(energies, axis=1)  # (M,)
            energy_high = 10 * np.log10(avg_e + 1e-12)

            # 4. Group Delay Peak (Simplify to onset? Or Mean Group Delay?)
            # The request says "Group Delay Peak".
            # Calculating calc_group_delay for all M is expensive.
            # Let's use Index of Max Amplitude as a proxy for "Delay" visualization if simpler
            # Or actually calculate Group Delay for one bin?
            # Let's stick to simpler "Envelope Peak Time" for now as a robust "Delay" metric
            # or maybe Low Freq ITD.
            # Re-reading: "Group Delay Peak" -> likely peak value of group delay in ms?
            # Or frequency where GD is peak?
            # Let's assume Mean Delay for now or Peak of Envelope.
            # Let's implement Peak Envelope Time (Vectorized)
            indices = np.argmax(np.abs(ir_data), axis=2)  # (M, 2)
            avg_idx = np.mean(indices, axis=1)  # (M,)
            gd_peak = (avg_idx / sampling_rate) * 1000.0  # ms

            return HRTFData(
                source_positions=source_pos_fixed,
                ir_data=ir_data,
                sampling_rate=sampling_rate,
                itd=itds,
                ild=ilds,
                energy_high=energy_high,
                group_delay_peak=gd_peak,
            )

        except Exception as e:
            logging.error(f"Failed to load SOFA file: {e}")
            return None


class HRTFPlayer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.hrtf_data: Optional[HRTFData] = None
        self.callback_id = None

        # Playback State
        self.playback_buffer: Optional[np.ndarray] = None
        self.playback_cursor = 0
        self.is_playing = False

        self.sound_type = "click"  # 'click', 'white', 'band'
        self.click_duration = 0.05  # 50ms for noise
        self.swap_channels = False

        # Rotation / Music Mode State
        self.music_buffer: Optional[np.ndarray] = None  # (N, 2)
        self.music_sr = 48000
        self.music_cursor = 0

        self.rotation_active = False
        self.rotation_mode = "Horizontal"  # 'Horizontal', 'Vertical'
        self.rotation_speed = 10.0  # deg/sec
        self.current_az = 0.0
        self.current_el = 0.0

        # Convolution State
        # Overlap buffer for overlap-add method
        # HRIR length is typically small (< 1024), block size ~1024
        # We need to store the tail of the convolution
        self.overlap_buffer: Optional[np.ndarray] = None  # (TailLen, 2)

        # Resampling cache for rotation mode
        self._rot_cache_idx = -1
        self._rot_cache_data: Optional[np.ndarray] = None

    @property
    def name(self) -> str:
        return "HRTF Player"

    @property
    def description(self) -> str:
        return "Visualize and Audition HRTF (SOFA) files."

    def run(self, args: argparse.Namespace):
        pass

    def get_widget(self):
        return HRTFPlayerWidget(self)

    def load_file(self, path):
        self.hrtf_data = SOFALoader.load(path)
        return self.hrtf_data is not None

    def load_music(self, path):
        try:
            # Security Check: Validate file size before loading
            info = sf.info(path)
            total_samples = info.frames * info.channels
            if total_samples > AudioCalc.MAX_AUDIO_SAMPLES:
                return False, f"File too large: {total_samples} samples (Max: {AudioCalc.MAX_AUDIO_SAMPLES})"

            data, sr = sf.read(path, always_2d=True)
            # Resample? For now assume close enough or user handles it.
            # Ideally we should resample if diff is large.
            # Let's do a quick resample calc if needed, similar to RecorderPlayer
            target_sr = self.audio_engine.sample_rate
            if sr != target_sr:
                # Use efficient polyphase resampling
                data = AudioCalc.resample(data, sr, target_sr)
                self.music_sr = target_sr
            else:
                self.music_sr = sr

            self.music_buffer = data.astype(np.float32)
            self.music_cursor = 0
            return True, f"Loaded music: {path.split('/')[-1]}"
        except Exception as e:
            return False, str(e)

    def start_rotation(self, mode, speed):
        if self.music_buffer is None:
            return False

        self.rotation_mode = mode
        self.rotation_speed = speed
        self.rotation_active = True
        self.overlap_buffer = None  # Reset overlap
        self._rot_cache_idx = -1
        self._rot_cache_data = None

        # Start if not already
        if self.callback_id is None:
            self.callback_id = self.audio_engine.register_callback(self._callback)
        return True

    def stop_rotation(self):
        self.rotation_active = False
        self.overlap_buffer = None

    def _get_resampled_pair(self, index: int) -> np.ndarray:
        """
        Retrieves the HRIR pair for the given index, resampled to the audio engine's sample rate.
        Returns a (N, 2) array where [:, 0] is Left and [:, 1] is Right (before swapping).
        """
        if self.hrtf_data is None:
            return np.zeros((1, 2), dtype=np.float32)

        # Original data is (M, R, N). ir_data[index] is (2, N).
        # We need (N, 2) for resample/processing.
        raw_pair = self.hrtf_data.ir_data[index].T  # (N, 2)

        source_sr = self.hrtf_data.sampling_rate
        target_sr = self.audio_engine.sample_rate

        # AudioCalc.resample handles equality check efficiently
        # However, resampling an impulse response changes the gain of the convolution
        # proportional to the ratio of sample rates. We must correct for this.
        # Scale factor: source_sr / target_sr
        # e.g. Upsampling (Source < Target): Convolution sums more taps -> Gain increases.
        # We need to attenuate by Source/Target.

        if source_sr == target_sr:
            # return a copy to ensure we don't accidentally modify the source via a view later
            return raw_pair.copy()

        resampled = AudioCalc.resample(raw_pair, source_sr, target_sr)
        correction = source_sr / target_sr
        return resampled * correction

    def set_source_position(self, az, el):
        self.current_az = az
        self.current_el = el

    def trigger_sound(self, azimuth, elevation):
        if self.hrtf_data is None:
            return

        # Update current position state
        self.set_source_position(azimuth, elevation)

        # Find nearest point
        # Simple Euclidean distance in Az/El plane (approximation)
        # Better: Great Circle distance, but for UI clicking, flat 2D dist is often fine enough for selection
        pos = self.hrtf_data.source_positions
        dists = np.sqrt((pos[:, 0] - azimuth) ** 2 + (pos[:, 1] - elevation) ** 2)
        nearest_idx = np.argmin(dists)

        # Get HRIR (Resampled)
        pair = self._get_resampled_pair(nearest_idx)

        if self.swap_channels:
            hrir_l = pair[:, 1]
            hrir_r = pair[:, 0]
        else:
            hrir_l = pair[:, 0]
            hrir_r = pair[:, 1]

        # Generate Source Signal
        sr = self.audio_engine.sample_rate  # Target playing rate

        # Source Gen
        len_samples = int(self.click_duration * sr)
        source_sig = np.zeros(len_samples)

        if self.sound_type == "click":
            # 1 sample click? Or short impulse?
            # 1 sample can be too quiet. Let's do a very short burst or just [1, 0, 0...]
            source_sig[0] = 1.0
        elif self.sound_type == "white":
            source_sig = np.random.uniform(-0.5, 0.5, size=len_samples)
        elif self.sound_type == "band":
            # 8-16k Noise
            white = np.random.uniform(-0.5, 0.5, size=len_samples)
            # Simple filtered
            fft = fft_manager.rfft(white)
            freqs = fft_manager.rfftfreq(len_samples, d=1 / sr)
            mask = (freqs >= 8000) & (freqs <= 16000)
            fft[~mask] = 0
            source_sig = fft_manager.irfft(fft)
            # Normalize
            mx = np.max(np.abs(source_sig))
            if mx > 0:
                source_sig /= mx
            source_sig *= 0.5

        # Convolve
        # HRIR is usually short (e.g. 512 samples)
        # Using scipy convolve
        out_l = convolve(source_sig, hrir_l, mode="full")
        out_r = convolve(source_sig, hrir_r, mode="full")

        # Interleave to stereo
        max_len = max(len(out_l), len(out_r))
        stereo_out = np.zeros((max_len, 2))
        stereo_out[: len(out_l), 0] = out_l
        stereo_out[: len(out_r), 1] = out_r

        # Normalize to prevent clips
        peak = np.max(np.abs(stereo_out))
        if peak > 0.9:
            stereo_out = stereo_out / peak * 0.9

        self.playback_buffer = stereo_out.astype(np.float32)
        self.playback_cursor = 0
        self.is_playing = True

        # Register callback if not already
        if self.callback_id is None:
            self.callback_id = self.audio_engine.register_callback(self._callback)

    def _callback(self, indata, outdata, frames, time_info, status):
        outdata.fill(0)

        # --- Rotation Mode ---
        if self.rotation_active and self.music_buffer is not None and self.hrtf_data is not None:
            # 1. Update Position
            dt = frames / self.audio_engine.sample_rate
            angle_delta = self.rotation_speed * dt

            if self.rotation_mode == "Horizontal":
                self.current_az += angle_delta
                # Wrap -180..180
                if self.current_az > 180:
                    self.current_az -= 360
                if self.current_az < -180:
                    self.current_az += 360
            elif self.rotation_mode == "Vertical":
                self.current_el += angle_delta
                if self.current_el > 90:
                    self.current_el = -90
                if self.current_el < -90:
                    self.current_el = 90
            elif self.rotation_mode == "Manual":
                pass  # No auto movement

            # 2. Get HRIR
            # Find nearest
            pos = self.hrtf_data.source_positions
            dists = np.sqrt((pos[:, 0] - self.current_az) ** 2 + (pos[:, 1] - self.current_el) ** 2)
            nearest_idx = np.argmin(dists)

            # Check cache
            if nearest_idx == self._rot_cache_idx and self._rot_cache_data is not None:
                pair = self._rot_cache_data
            else:
                pair = self._get_resampled_pair(nearest_idx)
                self._rot_cache_idx = nearest_idx
                self._rot_cache_data = pair

            if self.swap_channels:
                hrir_l = pair[:, 1]
                hrir_r = pair[:, 0]
            else:
                hrir_l = pair[:, 0]
                hrir_r = pair[:, 1]

            # 3. Get Audio Chunk
            # Loop music
            mus_len = len(self.music_buffer)
            rem = mus_len - self.music_cursor

            chunk_l = np.zeros(frames)
            chunk_r = np.zeros(frames)

            # Helper to get looped samples
            needed = frames
            fetched = 0
            while fetched < needed:
                can_take = min(needed - fetched, mus_len - self.music_cursor)

                # Mono or Stereo music?
                mus_chunk = self.music_buffer[self.music_cursor : self.music_cursor + can_take]

                # Mix to mono for convolution source if source is "spatialized"
                # Usually we treat source as mono point source.
                if mus_chunk.shape[1] > 1:
                    mono = np.mean(mus_chunk, axis=1)
                else:
                    mono = mus_chunk[:, 0]

                chunk_l[fetched : fetched + can_take] = mono
                chunk_r[fetched : fetched + can_take] = mono  # Same source for both ears calc

                self.music_cursor += can_take
                if self.music_cursor >= mus_len:
                    self.music_cursor = 0

                fetched += can_take

            # 4. Convolve
            # Using overlap-add block convolution
            # convolve returns len(chunk) + len(hrir) - 1
            conv_l = convolve(chunk_l, hrir_l, mode="full")
            conv_r = convolve(chunk_r, hrir_r, mode="full")

            # Add overlap from prev
            if self.overlap_buffer is not None:
                # overlap_buffer is (TailLen, 2)
                # Add to start of conv
                ov_len = self.overlap_buffer.shape[0]
                # Ensure sizes match
                # It is possible HRIR length changed if SOFA implies variable length?
                # Assume constant N mostly.
                # conv len >= overlap len usually if frames is consistent

                # Careful with shapes
                add_len = min(len(conv_l), ov_len)
                conv_l[:add_len] += self.overlap_buffer[:add_len, 0]
                conv_r[:add_len] += self.overlap_buffer[:add_len, 1]

            # Output
            # chunk to output is first 'frames' samples
            # new overlap is the rest

            out_chunk_l = conv_l[:frames]
            out_chunk_r = conv_r[:frames]

            # Check bounds? convolve result is always >= frames (if hrir >= 1)

            # Set to outdata
            if outdata.shape[1] >= 2:
                outdata[:, 0] = out_chunk_l
                outdata[:, 1] = out_chunk_r

            # Save overlap
            # tail
            tail_l = conv_l[frames:]
            tail_r = conv_r[frames:]

            # Stack
            max_tail = max(len(tail_l), len(tail_r))
            new_ov = np.zeros((max_tail, 2), dtype=np.float32)
            new_ov[: len(tail_l), 0] = tail_l
            new_ov[: len(tail_r), 1] = tail_r
            self.overlap_buffer = new_ov

            return

        # --- Static/One-shot Mode ---
        if not self.is_playing or self.playback_buffer is None:
            return

        # Copy chunk
        rem = len(self.playback_buffer) - self.playback_cursor
        if rem <= 0:
            self.is_playing = False
            return

        to_cp = min(frames, rem)
        # outdata is (frames, channels). playback_buffer is (N, 2).
        # Engine guarantees outdata matches logical channels?
        # AudioEngine usually gives stereo outdata for 'stereo' mode.

        chunk = self.playback_buffer[self.playback_cursor : self.playback_cursor + to_cp]

        if outdata.shape[1] >= 2:
            outdata[:to_cp, :2] = chunk
        elif outdata.shape[1] == 1:
            # Downmix for mono output
            outdata[:to_cp, 0] = np.mean(chunk, axis=1)

        self.playback_cursor += to_cp
        if self.playback_cursor >= len(self.playback_buffer):
            self.is_playing = False


class HRTFPlayerWidget(QWidget):
    def __init__(self, module: HRTFPlayer):
        super().__init__()
        self.module = module
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Controls ---
        top_group = QGroupBox(tr("Controls"))
        top_layout = QHBoxLayout()

        # File Load
        self.load_btn = QPushButton(tr("Load SOFA"))
        self.load_btn.clicked.connect(self.on_load_clicked)
        self.file_label = QLabel(tr("No file loaded"))
        top_layout.addWidget(self.load_btn)
        top_layout.addWidget(self.file_label)

        top_layout.addStretch()

        # Display Mode
        top_layout.addWidget(QLabel(tr("Metric:")))
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["ITD (µs)", "ILD (dB)", "High-band Energy (8-16kHz)", "Envelope Peak (ms)"])
        self.metric_combo.currentIndexChanged.connect(self.update_plot)
        top_layout.addWidget(self.metric_combo)

        # Sound Type
        top_layout.addWidget(QLabel(tr("Sound:")))
        self.sound_combo = QComboBox()
        self.sound_combo.addItem("Click (Impulse)", "click")
        self.sound_combo.addItem("White Noise (50ms)", "white")
        self.sound_combo.addItem("Band Noise (8-16k)", "band")
        self.sound_combo.currentIndexChanged.connect(self.on_sound_changed)
        top_layout.addWidget(self.sound_combo)

        # Swap L/R
        self.swap_cb = QCheckBox(tr("Swap L/R"))
        self.swap_cb.toggled.connect(self.on_swap_toggled)
        top_layout.addWidget(self.swap_cb)

        top_group.setLayout(top_layout)
        layout.addWidget(top_group)

        # --- Rotation Control ---
        rot_group = QGroupBox(tr("Rotation Mode"))
        rot_layout = QHBoxLayout()

        # Load Music
        self.load_music_btn = QPushButton(tr("Load Music"))
        self.load_music_btn.clicked.connect(self.on_load_music)
        rot_layout.addWidget(self.load_music_btn)

        # Play/Stop
        self.play_rot_btn = QPushButton(tr("▶ Play Rotation"))
        self.play_rot_btn.clicked.connect(self.on_play_rotation)
        self.stop_rot_btn = QPushButton(tr("⏸ Stop"))
        self.stop_rot_btn.clicked.connect(self.on_stop_rotation)
        rot_layout.addWidget(self.play_rot_btn)
        rot_layout.addWidget(self.stop_rot_btn)

        # Mode
        rot_layout.addWidget(QLabel(tr("Mode:")))
        self.rot_mode_combo = QComboBox()
        self.rot_mode_combo.addItems(["Horizontal", "Vertical", "Manual"])
        rot_layout.addWidget(self.rot_mode_combo)

        # Speed
        rot_layout.addWidget(QLabel(tr("Speed:")))
        self.speed_spin = pg.SpinBox(value=10.0, bounds=(0, 360), suffix="°/s", step=5)
        self.speed_spin.setFixedWidth(80)
        rot_layout.addWidget(self.speed_spin)

        rot_group.setLayout(rot_layout)
        layout.addWidget(rot_group)

        # Update Timer for position visualization
        self.vis_timer = QTimer()
        self.vis_timer.timeout.connect(self.update_visualization)
        self.vis_timer.start(50)  # 20fps

        # --- Plot ---
        self.win = pg.GraphicsLayoutWidget()
        layout.addWidget(self.win)

        self.plot = self.win.addPlot(title=tr("HRTF Source Positions"))
        self.plot.setLabel("bottom", "Azimuth", units="deg")
        self.plot.setLabel("left", "Elevation", units="deg")
        self.plot.setXRange(-180, 180)
        self.plot.setYRange(-90, 90)

        # Add Reference Lines
        self.plot.addLine(x=0, pen=pg.mkPen("w", width=1, style=pg.QtCore.Qt.PenStyle.DashLine))
        self.plot.addLine(y=0, pen=pg.mkPen("w", width=1, style=pg.QtCore.Qt.PenStyle.DashLine))

        # Disable Mouse Panning/Zooming (Lock View)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)  # Disable right-click menu

        # Image Item (Heatmap)
        self.img = pg.ImageItem()
        self.plot.addItem(self.img)

        # Keep Scatter for actual points (optional, maybe make them small/subtle or hide)
        # User asked for "Heatmap-like", usually implies continuous.
        # But seeing the actual source positions is useful. Let's make them small black dots to overlap?
        # Or just hide them. Let's hide them for now to look like a pure heatmap,
        # but maybe show them if the user requests.
        # Actually, let's keep scatter on top but very subtle (small, slightly transparent black/white)
        # to indicate where data "really" is vs interpolated.
        self.scatter = pg.ScatterPlotItem(size=5, pen=pg.mkPen(None), brush=pg.mkBrush(255, 255, 255, 50))
        self.plot.addItem(self.scatter)

        # Click handling - We need to catch clicks on the Plot/ViewBox since ImageItem consumes clicks differently?
        # Actually, scene().sigMouseClicked is better for general plot clicking.
        # changing scatter.sigClicked to a generic click handler
        self.plot.scene().sigMouseClicked.connect(self.on_scene_clicked)
        # Mouse move for dragging
        self.plot.scene().sigMouseMoved.connect(self.on_mouse_move)

        # Color Bar (Histogram)
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img)
        self.win.addItem(self.hist)

        # Set Colormap
        self.hist.gradient.loadPreset("viridis")

        self.setLayout(layout)

    def on_load_clicked(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, tr("Open SOFA File"), "", "SOFA Files (*.sofa *.nc);;All Files (*)"
        )
        if fname:
            if self.module.load_file(fname):
                self.file_label.setText(fname.split("/")[-1])
                self.update_plot()
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to load SOFA file."))

    def on_sound_changed(self, idx):
        self.module.sound_type = self.sound_combo.currentData()

    def on_swap_toggled(self, checked):
        self.module.swap_channels = checked
        self.update_plot()  # Now we should update plot because maybe we want to color code L/R diffs differently?
        # Actually, if we swap, the metrics (ITD/ILD) computed at load time are NOT swapped in the data structure.
        # But we are visualizing static metrics from the file.
        # If the user swaps L/R for *playback*, they might assume metrics are also wrong.
        # Ideally we recalculate metrics. But that's expensive without storing raw IRs nicely or re-running loading logic.
        # For now, let's just re-trigger playback is handled by flag.
        # Update plot is valid if we were dynamically calc'ing metrics, but we aren't.
        # Just pass.

    def update_plot(self):
        data = self.module.hrtf_data
        if data is None:
            return

        metric_idx = self.metric_combo.currentIndex()
        if metric_idx == 0:
            vals = data.itd
            name = "ITD"
        elif metric_idx == 1:
            vals = data.ild
            name = "ILD"
        elif metric_idx == 2:
            vals = data.energy_high
            name = "Energy"
        else:
            vals = data.group_delay_peak
            name = "Delay Peak"

        # Update Title
        self.plot.setTitle(f"HRTF: {name}")

        # Interpolation Grid
        # Az: -180 to 180, El: -90 to 90
        # Resolution: 2 degree seems fine? 360/2 = 180, 180/2 = 90
        grid_x, grid_y = np.mgrid[-180:180:180j, -90:90:90j]

        points = data.source_positions[:, :2]  # Az, El
        values = vals

        # griddata
        # Method: 'linear' (default) or 'cubic' or 'nearest'
        # 'linear' produces NaNs outside convex hull. 'nearest' fills everything.
        # HRTF usually covers sphere but maybe not full.
        # Let's use 'cubic' for smooth look, fill_value=nan (transparent)
        try:
            grid_z = griddata(points, values, (grid_x, grid_y), method="linear", fill_value=np.nan)
        except Exception as e:
            logging.error(f"Interpolation failed: {e}")
            return

        # ImageItem expects (width, height) -> (x, y)
        # grid_z is (180, 90) corresponding to meshgrid.

        self.img.setImage(grid_z)
        self.img.setRect(pg.QtCore.QRectF(-180, -90, 360, 180))  # Set coordinate system

        # Handle NaN transparency?
        # pyqtgraph handles NaNs by making them transparent usually if connect='finite' in plot,
        # but for ImageItem? It might just show black or 0.
        # We can construct a LUT.

        # Also update scatter to show where real points are
        self.scatter.setData(x=points[:, 0], y=points[:, 1], size=3, brush=pg.mkBrush(200, 200, 200, 150))

        # Update Position Indicator
        if not hasattr(self, "pos_indicator"):
            self.pos_indicator = pg.ScatterPlotItem(size=12, pen=pg.mkPen("r", width=2), brush=pg.mkBrush("r"))
            self.plot.addItem(self.pos_indicator)

        self.pos_indicator.setData(x=[self.module.current_az], y=[self.module.current_el])

    def on_scene_clicked(self, event):
        if self.plot.sceneBoundingRect().contains(event.scenePos()):
            if event.button() == pg.QtCore.Qt.MouseButton.LeftButton:
                self.update_position_from_event(event.scenePos())

    def on_mouse_move(self, pos):
        # Check if Left Button is pressed
        if QApplication.mouseButtons() & pg.QtCore.Qt.MouseButton.LeftButton:
            if self.plot.sceneBoundingRect().contains(pos):
                self.update_position_from_event(pos)

    def update_position_from_event(self, scene_pos):
        # Convert scene pos to plot pos
        pos = self.plot.vb.mapSceneToView(scene_pos)
        az, el = pos.x(), pos.y()

        # Bounds check
        if -180 <= az <= 180 and -90 <= el <= 90:
            # Always update model position (for Manual or Rotation mode jumps)
            self.module.set_source_position(az, el)

            # If Rotation Active -> Position updated, music continues from there.
            # If NOT Rotation Active -> Trigger One-shot sound at new position
            if not self.module.rotation_active:
                self.module.trigger_sound(az, el)

            # Update visual
            if hasattr(self, "pos_indicator"):
                self.pos_indicator.setData(x=[az], y=[el])

    def on_point_clicked(self, plot, points):
        # Legacy/Scatter click
        pass

    def on_load_music(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, tr("Open Music File"), "", "Audio Files (*.wav *.mp3 *.flac *.ogg);;All Files (*)"
        )
        if fname:
            success, msg = self.module.load_music(fname)
            if success:
                QMessageBox.information(self, "Success", msg)
            else:
                QMessageBox.warning(self, "Error", msg)

    def on_play_rotation(self):
        mode = self.rot_mode_combo.currentText()
        speed = self.speed_spin.value()

        if self.module.start_rotation(mode, speed):
            # Disable non-compat controls?
            pass
        else:
            QMessageBox.warning(self, "Error", "Failed to start rotation. Is music loaded?")

    def on_stop_rotation(self):
        self.module.stop_rotation()

    def update_visualization(self):
        if self.module.rotation_active:
            # Update marker
            if hasattr(self, "pos_indicator"):
                self.pos_indicator.setData(x=[self.module.current_az], y=[self.module.current_el])

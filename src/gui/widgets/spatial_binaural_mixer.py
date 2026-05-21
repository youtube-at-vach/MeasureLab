from typing import Optional

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QScrollArea,
    QGroupBox,
    QMessageBox,
    QProgressDialog,
    QFrame,
    QCheckBox,
    QDoubleSpinBox,
    QSpinBox,
)


from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.analysis import AudioCalc
from src.gui.widgets.hrtf_player import SOFALoader, HRTFData


def interpolate_hrir(hrtf_data: HRTFData, target_az: float, target_el: float, k: int = 3, p: float = 2.0) -> np.ndarray:
    """
    Interpolate HRIR using Inverse Distance Weighting (IDW) from k-nearest neighbors.
    """
    pos = hrtf_data.source_positions
    deg2rad = np.pi / 180.0
    az_rad = target_az * deg2rad
    el_rad = target_el * deg2rad
    pos_az_rad = pos[:, 0] * deg2rad
    pos_el_rad = pos[:, 1] * deg2rad

    # Calculate angular distance on a sphere
    cos_terms = np.sin(el_rad) * np.sin(pos_el_rad) + np.cos(el_rad) * np.cos(pos_el_rad) * np.cos(pos_az_rad - az_rad)
    cos_terms = np.clip(cos_terms, -1.0, 1.0)
    dists = np.arccos(cos_terms)

    nearest_indices = np.argsort(dists)[:k]
    nearest_dists = dists[nearest_indices]

    # Exact match handling
    if nearest_dists[0] < 1e-6:
        return hrtf_data.ir_data[nearest_indices[0]].T.astype(np.float64)

    epsilon = 1e-9
    weights = 1.0 / (nearest_dists**p + epsilon)
    weights /= np.sum(weights)

    N = hrtf_data.ir_data.shape[2]
    blended_hrir = np.zeros((N, 2), dtype=np.float64)

    for idx, w in zip(nearest_indices, weights, strict=True):
        pair = hrtf_data.ir_data[idx].T.astype(np.float64)
        blended_hrir += pair * w

    return blended_hrir


class RenderWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)

    def __init__(self, tracks_data, hrtf_data, target_sr, start_sec=None, duration_sec=None):
        super().__init__()
        self.tracks_data = tracks_data
        self.hrtf_data = hrtf_data
        self.target_sr = target_sr
        self.start_sec = start_sec
        self.duration_sec = duration_sec
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            processed_tracks = []

            for i, track in enumerate(self.tracks_data):
                if self.is_cancelled:
                    self.finished.emit(None)
                    return
                self.progress.emit(10, tr("Loading track {0}...").format(i + 1))

                info = sf.info(track["path"])
                if self.start_sec is not None and self.duration_sec is not None:
                    start_frame = int(self.start_sec * info.samplerate)
                    if start_frame >= info.frames:
                        start_frame = max(0, info.frames - info.samplerate)  # if start exceeds file

                    frames_to_read = int(self.duration_sec * info.samplerate)
                    frames_to_read = min(frames_to_read, info.frames - start_frame)

                    data, sr = sf.read(track["path"], always_2d=True, start=start_frame, frames=frames_to_read)
                else:
                    data, sr = sf.read(track["path"], always_2d=True)

                if sr != self.target_sr:
                    data = AudioCalc.resample(data, sr, self.target_sr)

                # Convert to mono if it's stereo
                if data.shape[1] > 1:
                    data = np.mean(data, axis=1)
                else:
                    data = data[:, 0]

                # Apply track gain
                gain_linear = 10 ** (track["gain_db"] / 20.0)
                data *= gain_linear
                processed_tracks.append(data)

            if not processed_tracks:
                raise ValueError(tr("No valid tracks to render."))

            N_hrir = 0
            if self.hrtf_data:
                N_hrir_orig = self.hrtf_data.ir_data.shape[2]
                N_hrir = int(N_hrir_orig * self.target_sr / self.hrtf_data.sampling_rate)

            max_mix_len = max(len(t) for t in processed_tracks) + N_hrir
            master_bus = np.zeros((max_mix_len, 2), dtype=np.float64)

            for i, (audio_data, config) in enumerate(zip(processed_tracks, self.tracks_data, strict=True)):
                if self.is_cancelled:
                    self.finished.emit(None)
                    return
                self.progress.emit(20 + int(70 * i / len(processed_tracks)), tr("Rendering track {0}...").format(i + 1))

                hrir_orig = interpolate_hrir(self.hrtf_data, config["az"], config["el"])
                if self.hrtf_data.sampling_rate != self.target_sr:
                    hrir = AudioCalc.resample(hrir_orig, self.hrtf_data.sampling_rate, self.target_sr)
                    correction = self.hrtf_data.sampling_rate / self.target_sr
                    hrir *= correction
                else:
                    hrir = hrir_orig

                # Full offline FFT Convolution (highest mathematical accuracy)
                conv_l = fftconvolve(audio_data, hrir[:, 0], mode="full")
                conv_r = fftconvolve(audio_data, hrir[:, 1], mode="full")

                master_bus[: len(conv_l), 0] += conv_l
                master_bus[: len(conv_r), 1] += conv_r

            peak = np.max(np.abs(master_bus))
            if peak > 0.99:
                master_bus = (master_bus / peak) * 0.99

            self.progress.emit(100, tr("Done"))
            self.finished.emit(master_bus.astype(np.float32))
        except Exception as e:
            self.finished.emit(e)


class TrackControlUI(QFrame):
    removed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.file_path = None
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()

        self.load_btn = QPushButton(tr("Load Audio"))
        self.load_btn.clicked.connect(self.on_load)
        self.name_label = QLabel(tr("No file"))
        self.name_label.setFixedWidth(150)

        layout.addWidget(self.load_btn)
        layout.addWidget(self.name_label)

        layout.addWidget(QLabel(tr("Azimuth:")))
        self.az_spin = QSpinBox()
        self.az_spin.setRange(-180, 180)
        self.az_spin.setSuffix("°")
        self.az_spin.setSingleStep(1)
        self.az_spin.setValue(0)
        layout.addWidget(self.az_spin)

        layout.addWidget(QLabel(tr("Elevation:")))
        self.el_spin = QSpinBox()
        self.el_spin.setRange(-90, 90)
        self.el_spin.setSuffix("°")
        self.el_spin.setSingleStep(1)
        self.el_spin.setValue(0)
        layout.addWidget(self.el_spin)

        layout.addWidget(QLabel(tr("Gain:")))
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60.0, 12.0)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.setSingleStep(1.0)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setValue(0.0)
        layout.addWidget(self.gain_spin)

        self.mute_btn = QPushButton(tr("Mute"))
        self.mute_btn.setCheckable(True)
        layout.addWidget(self.mute_btn)

        self.solo_btn = QPushButton(tr("Solo"))
        self.solo_btn.setCheckable(True)
        layout.addWidget(self.solo_btn)

        self.remove_btn = QPushButton("X")
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.remove_btn)

        self.setLayout(layout)

    def on_load(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, tr("Open Audio"), "", "Audio Files (*.wav *.mp3 *.flac *.ogg);;All Files (*)"
        )
        if fname:
            self.file_path = fname
            self.name_label.setText(fname.split("/")[-1])


class SpatialBinauralMixer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.hrtf_data: Optional[HRTFData] = None

        self.playback_buffer: Optional[np.ndarray] = None
        self.playback_cursor = 0
        self.is_playing = False
        self.callback_id = None

    @property
    def name(self) -> str:
        return tr("Spatial Binaural Mixer")

    @property
    def description(self) -> str:
        return tr("Offline High-Quality HRTF Multitrack Spatial Renderer.")

    def get_widget(self):
        return SpatialBinauralMixerWidget(self)

    def _callback(self, indata, outdata, frames, time_info, status):
        outdata.fill(0)
        if not self.is_playing or self.playback_buffer is None:
            return

        rem = len(self.playback_buffer) - self.playback_cursor
        if rem <= 0:
            self.is_playing = False
            return

        to_cp = min(frames, rem)
        chunk = self.playback_buffer[self.playback_cursor : self.playback_cursor + to_cp]

        if outdata.shape[1] >= 2:
            outdata[:to_cp, :2] = chunk
        elif outdata.shape[1] == 1:
            outdata[:to_cp, 0] = np.mean(chunk, axis=1)

        self.playback_cursor += to_cp
        if self.playback_cursor >= len(self.playback_buffer):
            self.is_playing = False


class SpatialBinauralMixerWidget(QWidget):
    def __init__(self, module: SpatialBinauralMixer):
        super().__init__()
        self.module = module
        self.tracks = []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # SOFA Settings
        sofa_group = QGroupBox(tr("Spatial Settings (SOFA)"))
        sofa_layout = QHBoxLayout()
        self.load_sofa_btn = QPushButton(tr("Load SOFA"))
        self.load_sofa_btn.clicked.connect(self.on_load_sofa)
        self.sofa_label = QLabel(tr("No SOFA loaded"))
        sofa_layout.addWidget(self.load_sofa_btn)
        sofa_layout.addWidget(self.sofa_label)
        sofa_layout.addStretch()
        sofa_group.setLayout(sofa_layout)
        layout.addWidget(sofa_group)

        # Tracks
        tracks_group = QGroupBox(tr("Tracks"))
        tracks_layout = QVBoxLayout()

        self.tracks_area = QScrollArea()
        self.tracks_area.setWidgetResizable(True)
        self.tracks_container = QWidget()
        self.tracks_inner_layout = QVBoxLayout()
        self.tracks_inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tracks_container.setLayout(self.tracks_inner_layout)
        self.tracks_area.setWidget(self.tracks_container)

        self.add_track_btn = QPushButton(tr("Add Track"))
        self.add_track_btn.clicked.connect(self.add_track)

        tracks_layout.addWidget(self.add_track_btn)
        tracks_layout.addWidget(self.tracks_area)
        tracks_group.setLayout(tracks_layout)
        layout.addWidget(tracks_group)

        # Preview Settings
        preview_group = QGroupBox(tr("Preview Settings"))
        preview_layout = QHBoxLayout()

        self.preview_cb = QCheckBox(tr("Preview Mode"))
        self.preview_cb.stateChanged.connect(self.on_preview_cb_changed)

        preview_layout.addWidget(self.preview_cb)
        preview_layout.addWidget(QLabel(tr("Start:")))
        self.start_sec_spin = QDoubleSpinBox()
        self.start_sec_spin.setRange(0.0, 3600.0)
        self.start_sec_spin.setSingleStep(1.0)
        self.start_sec_spin.setSuffix(" s")
        self.start_sec_spin.setDecimals(1)
        self.start_sec_spin.setValue(0.0)
        self.start_sec_spin.setEnabled(False)
        preview_layout.addWidget(self.start_sec_spin)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedWidth(24)
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self.on_prev_preview)
        preview_layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedWidth(24)
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self.on_next_preview)
        preview_layout.addWidget(self.next_btn)

        preview_layout.addWidget(QLabel(tr("Duration:")))
        self.duration_sec_spin = QDoubleSpinBox()
        self.duration_sec_spin.setRange(0.1, 600.0)
        self.duration_sec_spin.setSingleStep(1.0)
        self.duration_sec_spin.setSuffix(" s")
        self.duration_sec_spin.setDecimals(1)
        self.duration_sec_spin.setValue(10.0)
        self.duration_sec_spin.setEnabled(False)
        preview_layout.addWidget(self.duration_sec_spin)
        preview_layout.addStretch()
        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        # Export Actions
        actions_group = QGroupBox(tr("Render Actions"))
        actions_layout = QHBoxLayout()

        self.play_btn = QPushButton(tr("▶ Render & Monitor"))
        self.play_btn.clicked.connect(self.on_render_play)
        self.stop_btn = QPushButton(tr("⏸ Stop Monitor"))
        self.stop_btn.clicked.connect(self.on_stop_play)

        self.export_btn = QPushButton(tr("Render to WAV"))
        self.export_btn.clicked.connect(self.on_export)

        actions_layout.addWidget(self.play_btn)
        actions_layout.addWidget(self.stop_btn)
        actions_layout.addWidget(self.export_btn)
        actions_layout.addStretch()
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        self.setLayout(layout)

    def on_preview_cb_changed(self, state):
        is_checked = self.preview_cb.isChecked()
        self.start_sec_spin.setEnabled(is_checked)
        self.duration_sec_spin.setEnabled(is_checked)
        self.prev_btn.setEnabled(is_checked)
        self.next_btn.setEnabled(is_checked)

    def on_prev_preview(self):
        dur = self.duration_sec_spin.value()
        curr = self.start_sec_spin.value()
        self.start_sec_spin.setValue(max(0.0, curr - dur))

    def on_next_preview(self):
        dur = self.duration_sec_spin.value()
        curr = self.start_sec_spin.value()
        self.start_sec_spin.setValue(curr + dur)

    def on_load_sofa(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, tr("Open SOFA File"), "", "SOFA Files (*.sofa *.nc);;All Files (*)"
        )
        if fname:
            try:
                data = SOFALoader.load(fname)
                if data:
                    self.module.hrtf_data = data
                    self.sofa_label.setText(fname.split("/")[-1])
                else:
                    raise ValueError("Loader returned None")
            except Exception as e:
                QMessageBox.warning(self, tr("Error"), tr("Failed to load SOFA file: {0}").format(e))

    def add_track(self):
        track = TrackControlUI()
        track.removed.connect(self.remove_track)
        self.tracks.append(track)
        self.tracks_inner_layout.addWidget(track)

    def remove_track(self, track):
        self.tracks.remove(track)
        self.tracks_inner_layout.removeWidget(track)
        track.deleteLater()

    def _collect_track_configs(self):
        solo_active = any(t.solo_btn.isChecked() for t in self.tracks)
        configs = []
        for t in self.tracks:
            if not t.file_path:
                continue
            if solo_active and not t.solo_btn.isChecked():
                continue
            if not solo_active and t.mute_btn.isChecked():
                continue
            configs.append(
                {"path": t.file_path, "az": t.az_spin.value(), "el": t.el_spin.value(), "gain_db": t.gain_spin.value()}
            )
        return configs

    def start_render(self, callback):
        if not self.module.hrtf_data:
            QMessageBox.warning(self, tr("Error"), tr("Please load a SOFA file first."))
            return

        configs = self._collect_track_configs()
        if not configs:
            QMessageBox.warning(self, tr("Error"), tr("No valid tracks to render."))
            return

        self.pd = QProgressDialog(tr("Rendering Mix..."), tr("Cancel"), 0, 100, self)
        self.pd.setWindowModality(Qt.WindowModality.WindowModal)
        self.pd.show()

        start_sec = self.start_sec_spin.value() if self.preview_cb.isChecked() else None
        duration_sec = self.duration_sec_spin.value() if self.preview_cb.isChecked() else None

        self.worker = RenderWorker(
            configs,
            self.module.hrtf_data,
            self.module.audio_engine.sample_rate,
            start_sec=start_sec,
            duration_sec=duration_sec,
        )
        self.worker.progress.connect(self.pd.setValue)
        self.pd.canceled.connect(self.worker.cancel)

        def on_finished(result):
            self.pd.close()
            if result is None:
                pass  # Cancelled
            elif isinstance(result, Exception):
                QMessageBox.warning(self, tr("Error"), str(result))
            else:
                callback(result)

        self.worker.finished.connect(on_finished)
        self.worker.start()

    def on_render_play(self):
        def play_callback(buffer):
            self.module.playback_buffer = buffer
            self.module.playback_cursor = 0
            self.module.is_playing = True
            if self.module.callback_id is None:
                self.module.callback_id = self.module.audio_engine.register_callback(self.module._callback)

        self.start_render(play_callback)

    def on_stop_play(self):
        self.module.is_playing = False

    def on_export(self):
        def export_callback(buffer):
            fname, _ = QFileDialog.getSaveFileName(self, tr("Export WAV"), "", "WAV Files (*.wav)")
            if fname:
                try:
                    # Exporting as FLOAT to preserve dynamic range
                    sf.write(fname, buffer, self.module.audio_engine.sample_rate, subtype="FLOAT")
                    QMessageBox.information(self, tr("Success"), tr("WAV Export Successful"))
                except Exception as e:
                    QMessageBox.warning(self, tr("Error"), str(e))

        self.start_render(export_callback)

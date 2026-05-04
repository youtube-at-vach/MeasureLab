import logging
import os

import numpy as np
import pyqtgraph as pg
import soundfile as sf
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core.analysis import AudioCalc
from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)

MAX_WAVEFORM_POINTS = 6000


class WaveformLoadWorker(QThread):
    finished = pyqtSignal(bool, object, str, str)  # success, data, message, file_path

    def __init__(self, file_path: str, target_sr: int):
        super().__init__()
        self.file_path = file_path
        self.target_sr = target_sr

    def run(self):
        try:
            valid, msg = AudioCalc.validate_audio_file_size(self.file_path)
            if not valid:
                self.finished.emit(False, None, msg, self.file_path)
                return

            info = sf.info(self.file_path)
            file_sr = int(info.samplerate)
            data, _ = sf.read(self.file_path, always_2d=True)

            if file_sr != self.target_sr:
                data = AudioCalc.resample(data, file_sr, self.target_sr)

            data = np.asarray(data, dtype=np.float32)
            channels = int(data.shape[1]) if data.ndim > 1 else 1
            duration = len(data) / max(1, self.target_sr)
            message = tr("Loaded: {0} ({1}Hz, {2}ch, {3:.2f}s)").format(
                os.path.basename(self.file_path), self.target_sr, channels, duration
            )
            self.finished.emit(True, data, message, self.file_path)
        except Exception as exc:
            logger.exception("Failed to load waveform audio file")
            self.finished.emit(False, None, str(exc), self.file_path)


class WaveformLoopPlayer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.widget = None
        self.callback_id = None

        self.playback_buffer: np.ndarray | None = None
        self.playback_pos = 0
        self.is_playing = False
        self.loop_selection = True
        self.playback_gain_db = 0.0
        self.output_mode = "Stereo"

        self.selection_start = 0
        self.selection_end = 0
        self.file_path = ""

    @property
    def name(self) -> str:
        return "Waveform Loop Player"

    @property
    def description(self) -> str:
        return "Load an audio file, inspect the waveform, and loop a selected region."

    def get_widget(self):
        if self.widget is None:
            self.widget = WaveformLoopPlayerWidget(self)
        return self.widget

    @property
    def sample_rate(self) -> int:
        return int(getattr(self.audio_engine, "sample_rate", 48000) or 48000)

    @property
    def duration_seconds(self) -> float:
        if self.playback_buffer is None:
            return 0.0
        return len(self.playback_buffer) / max(1, self.sample_rate)

    def set_playback_data(self, data: np.ndarray, file_path: str = ""):
        self.stop_playback(reset_to_region=False)
        self.playback_buffer = np.asarray(data, dtype=np.float32)
        self.playback_pos = 0
        self.file_path = file_path

        total = len(self.playback_buffer)
        self.selection_start = 0
        self.selection_end = total

    def set_selection_seconds(self, start_s: float, end_s: float):
        if self.playback_buffer is None:
            self.selection_start = 0
            self.selection_end = 0
            return

        total = len(self.playback_buffer)
        sr = max(1, self.sample_rate)
        start = int(round(max(0.0, start_s) * sr))
        end = int(round(max(0.0, end_s) * sr))
        start = max(0, min(start, total))
        end = max(0, min(end, total))

        if end <= start:
            end = min(total, start + 1)
            if end <= start:
                start = max(0, end - 1)

        self.selection_start = start
        self.selection_end = end
        if self.playback_pos < start or self.playback_pos >= end:
            self.playback_pos = start

    def get_selection_seconds(self) -> tuple[float, float]:
        sr = max(1, self.sample_rate)
        return self.selection_start / sr, self.selection_end / sr

    def seek_seconds(self, seconds: float):
        if self.playback_buffer is None:
            return
        total = len(self.playback_buffer)
        pos = int(round(seconds * max(1, self.sample_rate)))
        self.playback_pos = max(0, min(pos, total))

    def start_playback(self):
        if self.playback_buffer is None or len(self.playback_buffer) == 0:
            return
        start, end = self._active_region()
        if self.playback_pos < start or self.playback_pos >= end:
            self.playback_pos = start
        self.is_playing = True
        self._ensure_callback()

    def pause_playback(self):
        self.is_playing = False
        self._check_stop_callback()

    def stop_playback(self, reset_to_region: bool = True):
        self.is_playing = False
        if reset_to_region:
            self.playback_pos = self._active_region()[0]
        self._check_stop_callback()

    def _ensure_callback(self):
        if self.callback_id is None:
            self.callback_id = self.audio_engine.register_callback(self.audio_callback)

    def _check_stop_callback(self):
        if not self.is_playing and self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def _active_region(self) -> tuple[int, int]:
        if self.playback_buffer is None:
            return 0, 0
        total = len(self.playback_buffer)
        if total == 0:
            return 0, 0
        start = max(0, min(int(self.selection_start), total - 1))
        end = max(start + 1, min(int(self.selection_end), total))
        return start, end

    def audio_callback(self, indata, outdata, frames, time_info, status):
        del indata, time_info, status
        outdata.fill(0)

        current_buffer = self.playback_buffer
        if not self.is_playing or current_buffer is None or len(current_buffer) == 0:
            return

        start, end = self._active_region()
        if end <= start:
            self.is_playing = False
            return

        out_index = 0
        while out_index < frames and self.is_playing:
            pos = self.playback_pos
            if pos < start or pos >= end:
                if self.loop_selection:
                    pos = start
                    self.playback_pos = start
                else:
                    self.is_playing = False
                    break

            to_copy = min(frames - out_index, end - pos)
            chunk = current_buffer[pos : pos + to_copy]
            if self.playback_gain_db != 0.0:
                chunk = chunk * (10 ** (self.playback_gain_db / 20.0))

            self._mix_to_output(chunk, outdata[out_index : out_index + to_copy])
            self.playback_pos = pos + to_copy
            out_index += to_copy

            if self.playback_pos >= end:
                if self.loop_selection:
                    self.playback_pos = start
                else:
                    self.is_playing = False
                    break

    def _mix_to_output(self, chunk: np.ndarray, out_slice: np.ndarray):
        if chunk.ndim == 1:
            chunk = chunk[:, np.newaxis]

        file_ch = chunk.shape[1]
        out_ch = out_slice.shape[1]

        if self.output_mode == "Stereo":
            if file_ch == 1:
                out_slice[:, 0] = chunk[:, 0]
                if out_ch > 1:
                    out_slice[:, 1] = chunk[:, 0]
            else:
                limit = min(file_ch, out_ch)
                out_slice[:, :limit] = chunk[:, :limit]
        elif self.output_mode == "Left":
            out_slice[:, 0] = chunk[:, 0]
        elif self.output_mode == "Right":
            if out_ch > 1:
                out_slice[:, 1] = chunk[:, 0] if file_ch == 1 else chunk[:, 1]
            else:
                out_slice[:, 0] = chunk[:, 0] if file_ch == 1 else chunk[:, 1]
        elif self.output_mode == "Mono":
            mono = np.mean(chunk, axis=1) if file_ch > 1 else chunk[:, 0]
            out_slice[:, 0] = mono
            if out_ch > 1:
                out_slice[:, 1] = mono


class WaveformLoopPlayerWidget(QWidget):
    def __init__(self, module: WaveformLoopPlayer):
        super().__init__()
        self.module = module
        self.load_worker = None
        self.progress_dialog = None
        self._updating_region = False
        self._updating_spinboxes = False

        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(50)

    def init_ui(self):
        layout = QVBoxLayout()

        self.file_label = QLabel(tr("No file loaded"))
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#080808")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("left", tr("Amplitude"))
        self.plot_widget.setLabel("bottom", tr("Time"), units="s")
        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.waveform_curve = self.plot_widget.plot([], [], pen=pg.mkPen("#7fd3ff", width=1))
        self.cursor_line = pg.InfiniteLine(pos=0.0, angle=90, pen=pg.mkPen("#ffcc33", width=2))
        self.region = pg.LinearRegionItem(values=(0.0, 0.0), movable=True, brush=(80, 160, 255, 45))
        self.region.setZValue(10)
        self.region.sigRegionChangeFinished.connect(self.on_region_changed)
        self.plot_widget.addItem(self.region)
        self.plot_widget.addItem(self.cursor_line)
        self.plot_widget.scene().sigMouseClicked.connect(self.on_plot_clicked)
        layout.addWidget(self.plot_widget, stretch=1)

        hint = QLabel(tr("Click waveform to seek. Drag the highlighted region edges to set the loop."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        controls = QGroupBox(tr("Playback"))
        controls_layout = QVBoxLayout()

        main_buttons = QHBoxLayout()
        self.load_btn = QPushButton(tr("Load Audio"))
        self.load_btn.clicked.connect(self.on_load)
        self.play_btn = QPushButton(tr("Play"))
        self.play_btn.clicked.connect(self.on_play_toggle)
        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.clicked.connect(self.on_stop)
        self.loop_check = QCheckBox(tr("Loop Selection"))
        self.loop_check.setChecked(self.module.loop_selection)
        self.loop_check.toggled.connect(self.on_loop_changed)
        main_buttons.addWidget(self.load_btn)
        main_buttons.addWidget(self.play_btn)
        main_buttons.addWidget(self.stop_btn)
        main_buttons.addWidget(self.loop_check)
        controls_layout.addLayout(main_buttons)

        view_buttons = QHBoxLayout()
        self.zoom_selection_btn = QPushButton(tr("Zoom to Selection"))
        self.zoom_selection_btn.clicked.connect(self.on_zoom_to_selection)
        self.fit_btn = QPushButton(tr("Fit All"))
        self.fit_btn.clicked.connect(self.on_fit_all)
        view_buttons.addWidget(self.zoom_selection_btn)
        view_buttons.addWidget(self.fit_btn)
        controls_layout.addLayout(view_buttons)

        selection_layout = QHBoxLayout()
        selection_layout.addWidget(QLabel(tr("Start (s):")))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setDecimals(3)
        self.start_spin.setSingleStep(0.01)
        self.start_spin.valueChanged.connect(self.on_spinbox_changed)
        selection_layout.addWidget(self.start_spin)
        selection_layout.addWidget(QLabel(tr("End (s):")))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setDecimals(3)
        self.end_spin.setSingleStep(0.01)
        self.end_spin.valueChanged.connect(self.on_spinbox_changed)
        selection_layout.addWidget(self.end_spin)
        self.selection_label = QLabel(tr("Length: {0:.3f} s").format(0.0))
        selection_layout.addWidget(self.selection_label)
        controls_layout.addLayout(selection_layout)

        routing_layout = QHBoxLayout()
        routing_layout.addWidget(QLabel(tr("Output Mode:")))
        self.out_mode_combo = QComboBox()
        self.out_mode_combo.addItem(tr("Stereo"), "Stereo")
        self.out_mode_combo.addItem(tr("Left"), "Left")
        self.out_mode_combo.addItem(tr("Right"), "Right")
        self.out_mode_combo.addItem(tr("Mono"), "Mono")
        self.out_mode_combo.currentIndexChanged.connect(self.on_out_mode_changed)
        routing_layout.addWidget(self.out_mode_combo)
        controls_layout.addLayout(routing_layout)

        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel(tr("Playback Gain:")))
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-60, 12)
        self.gain_slider.setValue(0)
        self.gain_slider.setTickInterval(6)
        self.gain_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.gain_slider.valueChanged.connect(self.on_gain_changed)
        gain_layout.addWidget(self.gain_slider)
        self.gain_value_label = QLabel(tr("0 dB"))
        gain_layout.addWidget(self.gain_value_label)
        controls_layout.addLayout(gain_layout)

        self.position_label = QLabel(tr("Position: {0:.3f} / {1:.3f} s").format(0.0, 0.0))
        controls_layout.addWidget(self.position_label)

        controls.setLayout(controls_layout)
        layout.addWidget(controls)
        self.setLayout(layout)
        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool):
        self.play_btn.setEnabled(enabled)
        self.stop_btn.setEnabled(enabled)
        self.loop_check.setEnabled(enabled)
        self.zoom_selection_btn.setEnabled(enabled)
        self.fit_btn.setEnabled(enabled)
        self.start_spin.setEnabled(enabled)
        self.end_spin.setEnabled(enabled)
        self.out_mode_combo.setEnabled(enabled)
        self.gain_slider.setEnabled(enabled)

    def on_load(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("Open Audio File"), "", tr("Audio Files (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)")
        )
        if not file_path:
            return

        try:
            info = sf.info(file_path)
            file_sr = int(info.samplerate)
            engine_sr = self.module.sample_rate
            if file_sr != engine_sr:
                reply = QMessageBox.question(
                    self,
                    tr("Resample Required"),
                    tr(
                        "The file sample rate ({0} Hz) differs from the engine rate ({1} Hz).\n"
                        "Resampling is required to play correctly.\n\n"
                        "Do you want to proceed? (This may take a moment for large files)"
                    ).format(file_sr, engine_sr),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.No:
                    return

            self.load_worker = WaveformLoadWorker(file_path, engine_sr)
            self.load_worker.finished.connect(self.on_load_finished)
            self.progress_dialog = QProgressDialog(tr("Loading and processing audio..."), tr("Cancel"), 0, 0, self)
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.canceled.connect(self.on_load_cancel)
            self.progress_dialog.show()
            self.load_worker.start()
        except Exception as exc:
            QMessageBox.critical(self, tr("Error"), tr("Failed to read file info:\n{0}").format(exc))

    def on_load_finished(self, success, data, message, file_path):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        if success:
            self.module.set_playback_data(data, file_path)
            self.file_label.setText(message)
            self.update_waveform_display()
            self._set_controls_enabled(True)
            self.on_fit_all()
        else:
            if message != "Cancelled":
                QMessageBox.critical(self, tr("Error"), tr("Failed to load file:\n{0}").format(message))

        self.load_worker = None

    def on_load_cancel(self):
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.terminate()
            self.load_worker.wait()
            self.load_worker = None

    def update_waveform_display(self):
        data = self.module.playback_buffer
        duration = self.module.duration_seconds
        if data is None or len(data) == 0:
            self.waveform_curve.setData([], [])
            self._update_region_ui(0.0, 0.0)
            return

        x, y = make_waveform_display_data(data, self.module.sample_rate, MAX_WAVEFORM_POINTS)
        self.waveform_curve.setData(x, y)
        self.region.setBounds((0.0, duration))
        self._update_region_ui(0.0, duration)

    def _update_region_ui(self, start_s: float, end_s: float):
        duration = self.module.duration_seconds
        start_s = max(0.0, min(float(start_s), duration))
        end_s = max(0.0, min(float(end_s), duration))
        if duration > 0 and end_s <= start_s:
            end_s = min(duration, start_s + 1.0 / max(1, self.module.sample_rate))

        self._updating_region = True
        self.region.setRegion((start_s, end_s))
        self._updating_region = False

        self._updating_spinboxes = True
        self.start_spin.setRange(0.0, duration)
        self.end_spin.setRange(0.0, duration)
        self.start_spin.setValue(start_s)
        self.end_spin.setValue(end_s)
        self._updating_spinboxes = False

        self.module.set_selection_seconds(start_s, end_s)
        self._update_selection_label()

    def on_region_changed(self):
        if self._updating_region:
            return
        start_s, end_s = sorted(self.region.getRegion())
        self._update_region_ui(start_s, end_s)

    def on_spinbox_changed(self):
        if self._updating_spinboxes:
            return
        self._update_region_ui(self.start_spin.value(), self.end_spin.value())

    def on_plot_clicked(self, event):
        if self.module.playback_buffer is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if self.plot_widget.plotItem.sceneBoundingRect().contains(event.scenePos()):
            point = self.plot_widget.plotItem.vb.mapSceneToView(event.scenePos())
            self.module.seek_seconds(point.x())
            self.cursor_line.setPos(self.module.playback_pos / max(1, self.module.sample_rate))

    def on_play_toggle(self):
        if self.module.is_playing:
            self.module.pause_playback()
        else:
            self.module.start_playback()

    def on_stop(self):
        self.module.stop_playback(reset_to_region=True)
        self.update_ui()

    def on_loop_changed(self, checked: bool):
        self.module.loop_selection = bool(checked)

    def on_out_mode_changed(self):
        self.module.output_mode = self.out_mode_combo.currentData()

    def on_gain_changed(self, value: int):
        self.module.playback_gain_db = float(value)
        self.gain_value_label.setText(tr("{0} dB").format(value))

    def on_zoom_to_selection(self):
        start_s, end_s = self.module.get_selection_seconds()
        if end_s > start_s:
            padding = max(0.01, (end_s - start_s) * 0.08)
            self.plot_widget.setXRange(max(0.0, start_s - padding), min(self.module.duration_seconds, end_s + padding))

    def on_fit_all(self):
        duration = self.module.duration_seconds
        if duration > 0:
            self.plot_widget.setXRange(0.0, duration, padding=0.02)
            self.plot_widget.setYRange(-1.05, 1.05, padding=0.02)

    def _update_selection_label(self):
        start_s, end_s = self.module.get_selection_seconds()
        self.selection_label.setText(tr("Length: {0:.3f} s").format(max(0.0, end_s - start_s)))
        self.file_label.setToolTip(tr("Selection: {0:.3f} – {1:.3f} s").format(start_s, end_s))

    def update_ui(self):
        if self.module.is_playing:
            self.play_btn.setText(tr("Pause"))
        else:
            self.play_btn.setText(tr("Play"))

        duration = self.module.duration_seconds
        pos_s = self.module.playback_pos / max(1, self.module.sample_rate)
        self.cursor_line.setPos(pos_s)
        self.position_label.setText(tr("Position: {0:.3f} / {1:.3f} s").format(pos_s, duration))
        self._update_selection_label()


def make_waveform_display_data(
    data: np.ndarray, sample_rate: int, max_points: int = MAX_WAVEFORM_POINTS
) -> tuple[np.ndarray, np.ndarray]:
    """Build a compact min/max waveform suitable for interactive plotting."""
    if data.ndim > 1:
        channel_indices = np.argmax(np.abs(data), axis=1)
        waveform = data[np.arange(len(data)), channel_indices]
    else:
        waveform = data

    total = len(waveform)
    if total == 0:
        return np.array([], dtype=np.float32), np.array([], dtype=np.float32)

    if total <= max_points:
        x = np.arange(total, dtype=np.float32) / max(1, sample_rate)
        return x, waveform.astype(np.float32, copy=False)

    bins = max(1, max_points // 2)
    samples_per_bin = int(np.ceil(total / bins))
    padded = bins * samples_per_bin
    if padded > total:
        waveform = np.pad(waveform, (0, padded - total), mode="edge")

    blocks = waveform.reshape(bins, samples_per_bin)
    y_min = blocks.min(axis=1)
    y_max = blocks.max(axis=1)
    centers = (np.arange(bins, dtype=np.float32) * samples_per_bin) / max(1, sample_rate)

    x = np.repeat(centers, 2)
    y = np.empty(bins * 2, dtype=np.float32)
    y[0::2] = y_min
    y[1::2] = y_max
    return x, y

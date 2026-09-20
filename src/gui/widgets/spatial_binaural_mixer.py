"""Offline spatial mixing: source placement, render lifecycle and monitoring."""

from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.gui.styles import button_style
from src.gui.widgets.hrtf_player import HRTFData, SOFALoader
from src.gui.widgets.spatial_azimuth_view import AzimuthView
from src.gui.widgets.spatial_binaural_render import (
    RenderWorker,
    TrackConfig,
    interpolate_hrir as interpolate_hrir,  # Keep the existing public import available.
    validate_hrtf,
)
from src.measurement_modules.base import MeasurementModule


class FileLabel(QLabel):
    """Keep long paths available without letting them dictate layout width."""

    def __init__(self, text):
        super().__init__(text)
        self._filename = text
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(80)

    def set_file(self, path):
        self._filename = Path(path).name
        self._elide()
        self.setToolTip(str(path))
        self.setAccessibleDescription(str(path))

    def _elide(self):
        self.setText(
            self.fontMetrics().elidedText(self._filename, Qt.TextElideMode.ElideMiddle, self.contentsRect().width())
        )

    def resizeEvent(self, event):
        self._elide()
        super().resizeEvent(event)


class TrackControlUI(QFrame):
    removed = pyqtSignal(object)
    changed = pyqtSignal()
    selected = pyqtSignal(object)

    def __init__(self, number=1):
        super().__init__()
        self.number = number
        self.file_path = None
        self.setObjectName("spatialTrackCard")
        self.setStyleSheet(
            "QFrame#spatialTrackCard { border: 1px solid palette(mid); border-radius: 5px; }"
            "QFrame#spatialTrackCard[selected='true'] { border: 2px solid palette(highlight); }"
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.select_btn = QPushButton(str(number))
        self.select_btn.setCheckable(True)
        self.select_btn.setAccessibleName(tr("Track {0}").format(number))
        self.select_btn.setFixedWidth(36)
        self.select_btn.clicked.connect(lambda: self.selected.emit(self))
        self.name_label = FileLabel(tr("No file"))
        self.name_label.setAccessibleName(tr("Loaded audio file"))
        self.load_btn = QPushButton(tr("Load Audio"))
        self.load_btn.clicked.connect(self.on_load)
        self.remove_btn = QPushButton("×")
        self.remove_btn.setFixedWidth(30)
        self.remove_btn.setAccessibleName(tr("Remove Track"))
        self.remove_btn.setToolTip(tr("Remove Track"))
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
        header.addWidget(self.select_btn)
        header.addWidget(self.name_label, 1)
        header.addWidget(self.load_btn)
        header.addWidget(self.remove_btn)
        layout.addLayout(header)

        controls = QGridLayout()
        self.az_label = QLabel(tr("Azimuth:"))
        self.az_spin = QSpinBox()
        self.az_spin.setRange(-180, 180)
        self.az_spin.setSuffix("°")
        self.el_label = QLabel(tr("Elevation:"))
        self.el_spin = QSpinBox()
        self.el_spin.setRange(-90, 90)
        self.el_spin.setSuffix("°")
        self.gain_label = QLabel(tr("Gain:"))
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60, 12)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSingleStep(1)
        self.gain_spin.setSuffix(" dB")
        for column, (label, spin) in enumerate(
            ((self.az_label, self.az_spin), (self.el_label, self.el_spin), (self.gain_label, self.gain_spin))
        ):
            label.setBuddy(spin)
            spin.setAccessibleName(label.text())
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self.changed)
            controls.addWidget(label, 0, column)
            controls.addWidget(spin, 1, column)
            controls.setColumnStretch(column, 1)
        self.mute_btn = QPushButton(tr("Mute"))
        self.solo_btn = QPushButton(tr("Solo"))
        for column, button in enumerate((self.mute_btn, self.solo_btn), 3):
            button.setCheckable(True)
            button.toggled.connect(self.changed)
            controls.addWidget(button, 1, column)
        layout.addLayout(controls)
        order = [
            self.load_btn,
            self.select_btn,
            self.az_spin,
            self.el_spin,
            self.gain_spin,
            self.mute_btn,
            self.solo_btn,
            self.remove_btn,
        ]
        for before, after in zip(order, order[1:], strict=False):
            QWidget.setTabOrder(before, after)

    def set_selected(self, selected):
        self.select_btn.setChecked(selected)
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def load_file(self, path):
        # Validate before replacing an existing source.
        info = sf.info(path)
        if not info.frames:
            raise ValueError(tr("No audio in the selected range."))
        self.file_path = str(path)
        self.name_label.set_file(path)
        self.name_label.setToolTip(f"{path}\n{info.duration:.2f} s · {info.samplerate} Hz · {info.channels} ch")
        self.changed.emit()

    def on_load(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open Audio"), "", "Audio Files (*.wav *.mp3 *.flac *.ogg);;All Files (*)"
        )
        if path:
            try:
                self.load_file(path)
            except Exception as exc:
                QMessageBox.warning(self, tr("Error"), str(exc))

    def config(self):
        return TrackConfig(self.file_path, self.az_spin.value(), self.el_spin.value(), self.gain_spin.value())


class SpatialBinauralMixer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.hrtf_data: Optional[HRTFData] = None
        self.playback_buffer: Optional[np.ndarray] = None
        self.playback_cursor = 0
        self.playback_sample_rate = 0
        self.is_playing = False
        self.callback_id = None

    @property
    def name(self):
        return tr("Spatial Binaural Mixer")

    @property
    def description(self):
        return tr("Offline High-Quality HRTF Multitrack Spatial Renderer.")

    def get_widget(self):
        return SpatialBinauralMixerWidget(self)

    def play(self, result):
        self.stop()
        if self.audio_engine.sample_rate != result.sample_rate:
            raise ValueError(tr("Sample rate changed. Render again to monitor."))
        self.playback_buffer = result.audio
        self.playback_sample_rate = result.sample_rate
        self.playback_cursor = 0
        self.is_playing = True
        try:
            self.callback_id = self.audio_engine.register_callback(self._callback)
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.is_playing = False
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None
        self.playback_buffer = None

    def _callback(self, indata, outdata, frames, time_info, status):
        outdata.fill(0)
        buffer = self.playback_buffer
        if not self.is_playing or buffer is None:
            return
        if self.audio_engine.sample_rate != self.playback_sample_rate:
            self.is_playing = False
            return
        count = min(frames, len(buffer) - self.playback_cursor)
        chunk = buffer[self.playback_cursor : self.playback_cursor + count]
        if outdata.shape[1] >= 2:
            outdata[:count, :2] = chunk
        elif outdata.shape[1] == 1:
            outdata[:count, 0] = np.mean(chunk, axis=1)
        self.playback_cursor += count
        if self.playback_cursor >= len(buffer):
            self.is_playing = False


class SpatialBinauralMixerWidget(QWidget):
    def __init__(self, module):
        super().__init__()
        self.module = module
        self.tracks = []
        self.selected_track = None
        self._next_track_number = 1
        self.worker = None
        self._render_callback = None
        self.init_ui()
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(100)
        self.monitor_timer.timeout.connect(self._update_monitor)
        self.destroyed.connect(module.stop)
        self._scene_changed()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.sofa_group = QGroupBox(tr("Spatial Settings (SOFA)"))
        sofa_layout = QHBoxLayout(self.sofa_group)
        self.load_sofa_btn = QPushButton(tr("Load SOFA"))
        self.load_sofa_btn.clicked.connect(self.on_load_sofa)
        self.sofa_label = FileLabel(tr("No SOFA loaded"))
        sofa_layout.addWidget(self.load_sofa_btn)
        sofa_layout.addWidget(self.sofa_label, 1)
        layout.addWidget(self.sofa_group)

        self.editor = QWidget()
        editor_layout = QHBoxLayout(self.editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        scene_group = QGroupBox(tr("Source placement"))
        scene_layout = QVBoxLayout(scene_group)
        self.azimuth_view = AzimuthView()
        self.azimuth_view.selected.connect(self._select_number)
        self.azimuth_view.azimuth_changed.connect(self._set_azimuth)
        scene_layout.addWidget(self.azimuth_view, 1)
        hint = QLabel(tr("Drag to change azimuth. Arrow keys adjust the selected source."))
        hint.setWordWrap(True)
        scene_layout.addWidget(hint)
        note = QLabel(tr("Top view · direction only. Set elevation in the track card."))
        note.setWordWrap(True)
        scene_layout.addWidget(note)
        editor_layout.addWidget(scene_group, 2)

        tracks_group = QGroupBox(tr("Tracks"))
        tracks_layout = QVBoxLayout(tracks_group)
        toolbar = QHBoxLayout()
        self.add_track_btn = QPushButton(tr("Add Track"))
        self.add_track_btn.clicked.connect(self.add_track)
        self.add_files_btn = QPushButton(tr("Add Audio Files"))
        self.add_files_btn.clicked.connect(self.on_add_files)
        toolbar.addWidget(self.add_files_btn)
        toolbar.addWidget(self.add_track_btn)
        toolbar.addStretch()
        tracks_layout.addLayout(toolbar)
        self.empty_label = QLabel(tr("Add audio files, then place each source around the listener."))
        self.empty_label.setWordWrap(True)
        tracks_layout.addWidget(self.empty_label)
        self.tracks_area = QScrollArea()
        self.tracks_area.setObjectName("spatialMixerTracksScroll")
        self.tracks_area.setProperty("measurelabScrollRole", "dynamic-content")
        self.tracks_area.setWidgetResizable(True)
        self.tracks_area.setAccessibleName(tr("Tracks"))
        self.tracks_area.setMinimumWidth(480)
        self.tracks_container = QWidget()
        self.tracks_inner_layout = QVBoxLayout(self.tracks_container)
        self.tracks_inner_layout.setContentsMargins(4, 4, 4, 4)
        self.tracks_inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tracks_area.setWidget(self.tracks_container)
        tracks_layout.addWidget(self.tracks_area, 1)
        mono_note = QLabel(tr("Each file becomes one mono source. Mute takes priority over Solo."))
        mono_note.setWordWrap(True)
        tracks_layout.addWidget(mono_note)
        editor_layout.addWidget(tracks_group, 3)
        layout.addWidget(self.editor, 1)

        self.preview_group = QGroupBox(tr("Preview Settings"))
        preview_layout = QHBoxLayout(self.preview_group)
        self.preview_cb = QCheckBox(tr("Preview Mode"))
        self.preview_cb.toggled.connect(self.on_preview_cb_changed)
        preview_layout.addWidget(self.preview_cb)
        self.start_label = QLabel(tr("Start:"))
        self.start_sec_spin = QDoubleSpinBox()
        self.start_sec_spin.setRange(0, 86400)
        self.duration_label = QLabel(tr("Duration:"))
        self.duration_sec_spin = QDoubleSpinBox()
        self.duration_sec_spin.setRange(0.1, 600)
        self.duration_sec_spin.setValue(10)
        for label, spin in ((self.start_label, self.start_sec_spin), (self.duration_label, self.duration_sec_spin)):
            spin.setDecimals(1)
            spin.setSuffix(" s")
            spin.setKeyboardTracking(False)
            label.setBuddy(spin)
            spin.setAccessibleName(label.text())
            spin.valueChanged.connect(self._scene_changed)
        preview_layout.addWidget(self.start_label)
        preview_layout.addWidget(self.start_sec_spin)
        self.prev_btn = QPushButton("◀")
        self.next_btn = QPushButton("▶")
        for button, name, handler in (
            (self.prev_btn, tr("Previous Preview Segment"), self.on_prev_preview),
            (self.next_btn, tr("Next Preview Segment"), self.on_next_preview),
        ):
            button.setFixedWidth(32)
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.clicked.connect(handler)
            preview_layout.addWidget(button)
        preview_layout.addWidget(self.duration_label)
        preview_layout.addWidget(self.duration_sec_spin)
        preview_layout.addStretch()
        layout.addWidget(self.preview_group)

        self.range_label = QLabel()
        self.range_label.setWordWrap(True)
        layout.addWidget(self.range_label)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        layout.addWidget(self.result_label)
        actions = QHBoxLayout()
        self.play_btn = QPushButton(tr("▶ Render & Monitor"))
        self.play_btn.setAccessibleName(tr("Render & Monitor"))
        self.play_btn.setStyleSheet(button_style("primary"))
        self.play_btn.clicked.connect(self.on_render_play)
        self.stop_btn = QPushButton(tr("⏸ Stop Monitor"))
        self.stop_btn.setAccessibleName(tr("Stop Monitor"))
        self.stop_btn.setStyleSheet(button_style("stop"))
        self.stop_btn.clicked.connect(self.on_stop_play)
        self.export_btn = QPushButton(tr("Render to WAV"))
        self.export_btn.setAccessibleName(tr("Render to WAV"))
        self.export_btn.clicked.connect(self.on_export)
        for button in (self.play_btn, self.stop_btn, self.export_btn):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        status_row = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedWidth(130)
        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self.cancel_render)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress_bar)
        status_row.addWidget(self.cancel_btn)
        layout.addLayout(status_row)
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.on_preview_cb_changed()
        order = [
            self.load_sofa_btn,
            self.azimuth_view,
            self.add_files_btn,
            self.add_track_btn,
            self.preview_cb,
            self.start_sec_spin,
            self.prev_btn,
            self.next_btn,
            self.duration_sec_spin,
            self.play_btn,
            self.stop_btn,
            self.export_btn,
            self.cancel_btn,
        ]
        for before, after in zip(order, order[1:], strict=False):
            QWidget.setTabOrder(before, after)

    def _select_number(self, number):
        track = next((t for t in self.tracks if t.number == number), None)
        if track:
            self.select_track(track)

    def select_track(self, track):
        self.selected_track = track
        for item in self.tracks:
            item.set_selected(item is track)
        self.tracks_area.ensureWidgetVisible(track)
        self._update_map()

    def _set_azimuth(self, number, azimuth):
        track = next((t for t in self.tracks if t.number == number), None)
        if track:
            track.az_spin.setValue(azimuth)

    def _audible_tracks(self):
        loaded = [t for t in self.tracks if t.file_path]
        solo = any(t.solo_btn.isChecked() for t in loaded)
        return [t for t in loaded if not t.mute_btn.isChecked() and (not solo or t.solo_btn.isChecked())]

    def _update_map(self):
        audible = self._audible_tracks()
        self.azimuth_view.set_sources(
            [(t.number, t.az_spin.value(), t in audible) for t in self.tracks],
            self.selected_track.number if self.selected_track else None,
        )

    def _scene_changed(self):
        if self.module.callback_id is not None:
            self.on_stop_play()
        self.empty_label.setVisible(not self.tracks)
        self.result_label.hide()
        self._update_map()
        self._update_actions()
        rate = self.module.audio_engine.sample_rate if self.module.audio_engine else 48000
        if self.preview_cb.isChecked():
            self.range_label.setText(
                tr("Monitor / WAV: {0:.1f}–{1:.1f} s + filter tail · {2} Hz").format(
                    self.start_sec_spin.value(), self.start_sec_spin.value() + self.duration_sec_spin.value(), rate
                )
            )
        else:
            self.range_label.setText(tr("Monitor / WAV: full mix + filter tail · {0} Hz").format(rate))
        if self.module.hrtf_data is None:
            self.status_label.setText(tr("Please load a SOFA file first."))
        elif not self._audible_tracks():
            self.status_label.setText(tr("No valid tracks to render."))
        else:
            self.status_label.setText(tr("Ready · {0} audible tracks").format(len(self._audible_tracks())))

    def _update_actions(self):
        busy = self.worker is not None
        ready = self.module.hrtf_data is not None and bool(self._audible_tracks()) and not busy
        self.play_btn.setEnabled(ready and not self.module.is_playing)
        self.export_btn.setEnabled(ready and not self.module.is_playing)
        self.stop_btn.setEnabled(self.module.callback_id is not None)
        for control in (self.sofa_group, self.editor, self.preview_group):
            control.setEnabled(not busy)
        self.progress_bar.setVisible(busy or self.module.is_playing)
        self.cancel_btn.setVisible(busy)

    def on_preview_cb_changed(self, *_):
        for control in (self.start_sec_spin, self.duration_sec_spin, self.prev_btn, self.next_btn):
            control.setEnabled(self.preview_cb.isChecked())
        self._scene_changed()

    def on_prev_preview(self):
        self.start_sec_spin.setValue(max(0, self.start_sec_spin.value() - self.duration_sec_spin.value()))

    def on_next_preview(self):
        self.start_sec_spin.setValue(self.start_sec_spin.value() + self.duration_sec_spin.value())

    def on_load_sofa(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Open SOFA File"), "", "SOFA Files (*.sofa *.nc);;All Files (*)")
        if path:
            try:
                data = SOFALoader.load(path)
                if data is None:
                    raise ValueError(tr("Invalid stereo HRTF data."))
                validate_hrtf(data)
                self.module.hrtf_data = data
                self.sofa_label.set_file(path)
                self._scene_changed()
            except Exception as exc:
                QMessageBox.warning(self, tr("Error"), tr("Failed to load SOFA file: {0}").format(exc))

    def add_track(self):
        track = TrackControlUI(self._next_track_number)
        self._next_track_number += 1
        track.removed.connect(self.remove_track)
        track.selected.connect(self.select_track)
        track.changed.connect(self._scene_changed)
        self.tracks.append(track)
        self.tracks_inner_layout.addWidget(track)
        self.select_track(track)
        self._update_track_tab_order()
        self._scene_changed()
        return track

    def on_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Open Audio"), "", "Audio Files (*.wav *.mp3 *.flac *.ogg);;All Files (*)"
        )
        errors = []
        for path in paths:
            track = self.add_track()
            try:
                track.load_file(path)
            except Exception as exc:
                self.remove_track(track)
                errors.append(f"{Path(path).name}: {exc}")
        if errors:
            QMessageBox.warning(self, tr("Error"), "\n".join(errors))

    def remove_track(self, track):
        self.tracks.remove(track)
        self.tracks_inner_layout.removeWidget(track)
        if self.selected_track is track:
            self.selected_track = None
            if self.tracks:
                self.select_track(self.tracks[-1])
        track.deleteLater()
        self._update_track_tab_order()
        self._scene_changed()

    def _update_track_tab_order(self):
        previous = self.add_track_btn
        for track in self.tracks:
            QWidget.setTabOrder(previous, track.load_btn)
            previous = track.remove_btn
        QWidget.setTabOrder(previous, self.preview_cb)

    def _collect_track_configs(self):
        return [track.config() for track in self._audible_tracks()]

    def start_render(self, callback, *, output_path=None):
        if self.worker is not None:
            return
        if self.module.hrtf_data is None or not self._audible_tracks():
            self._scene_changed()
            return
        self.on_stop_play()
        self._scene_changed()
        self._render_callback = callback
        self.worker = RenderWorker(
            self._collect_track_configs(),
            self.module.hrtf_data,
            self.module.audio_engine.sample_rate,
            start_sec=self.start_sec_spin.value() if self.preview_cb.isChecked() else None,
            duration_sec=self.duration_sec_spin.value() if self.preview_cb.isChecked() else None,
            parent=QApplication.instance(),
            output_path=output_path,
        )
        # The application owns running threads even if a detached widget is deleted.
        # Shutdown joins only at application exit, never during interactive cancellation.
        self.destroyed.connect(self.worker.cancel)
        self.worker.progress.connect(self._render_progress)
        self.worker.finished.connect(self._render_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.progress_bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText(tr("Rendering Mix..."))
        self._update_actions()
        self.worker.start()

    def _render_progress(self, value, message):
        if self.worker is not None and not self.worker.cancelled.is_set():
            self.progress_bar.setValue(value)
            self.status_label.setText(message)

    def cancel_render(self):
        if self.worker is not None:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText(tr("Cancelling after the current processing step..."))

    def _render_finished(self):
        worker = self.worker
        callback = self._render_callback
        self.worker = None
        self._render_callback = None
        self._update_actions()
        if worker.cancelled.is_set() and not worker.output_saved:
            self.status_label.setText(tr("Cancelled"))
        elif worker.error is not None:
            self.status_label.setText(str(worker.error))
        elif worker.result is not None:
            result = worker.result
            self.result_label.setText(
                tr("Rendered {0:.1f} s · peak attenuation {1:.1f} dB").format(
                    len(result.audio) / result.sample_rate, result.attenuation_db
                )
            )
            self.result_label.show()
            try:
                callback(result)
            except Exception as exc:
                self.status_label.setText(str(exc))
            self._update_actions()

    def on_render_play(self):
        self.start_render(self._play_result)

    def _play_result(self, result):
        self.module.play(result)
        self.monitor_timer.start()
        self._update_monitor()

    def _update_monitor(self):
        module = self.module
        stream = getattr(module.audio_engine, "stream", None)
        if stream is None or not stream.active:
            self.on_stop_play()
            return
        if not module.is_playing:
            changed_rate = module.audio_engine.sample_rate != module.playback_sample_rate
            self.on_stop_play()
            self.status_label.setText(
                tr("Sample rate changed. Render again to monitor.") if changed_rate else tr("Done")
            )
            return
        total = len(module.playback_buffer)
        self.progress_bar.setValue(round(100 * module.playback_cursor / max(1, total)))
        self.status_label.setText(
            tr("Monitoring {0:.1f} / {1:.1f} s").format(
                module.playback_cursor / module.playback_sample_rate, total / module.playback_sample_rate
            )
        )
        self._update_actions()

    def on_stop_play(self):
        self.monitor_timer.stop()
        self.module.stop()
        self._update_actions()
        self.status_label.setText(tr("Stopped"))

    def on_export(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export WAV"), "mix.wav", "WAV Files (*.wav)")
        if not path:
            return

        def saved(result):
            self.status_label.setText(tr("WAV Export Successful") + " · " + Path(path).name)

        self.start_render(saved, output_path=path)

    def hideEvent(self, event):
        self.on_stop_play()
        self.cancel_render()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.on_stop_play()
        self.cancel_render()
        super().closeEvent(event)

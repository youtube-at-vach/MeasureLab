import atexit
from dataclasses import dataclass
import logging
import os
import queue
import tempfile
import threading
import weakref

import numpy as np
import soundfile as sf
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.analysis import AudioCalc
from src.core.localization import tr
from src.gui.styles import MONOSPACE_FONT_FAMILY
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.measurement_modules.base import MeasurementModule


logger = logging.getLogger(__name__)


WRITE_BLOCK_SIZE = 65536


@dataclass(frozen=True, slots=True)
class LoadedAudioInfo:
    """Structured file information used by normal and compact presentations."""

    path: str
    source_sample_rate: int
    playback_sample_rate: int
    channels: int
    duration_seconds: float

    @property
    def was_resampled(self) -> bool:
        return self.source_sample_rate != self.playback_sample_rate


class FileLoadWorker(QThread):
    finished = pyqtSignal(bool, object, object)  # success, data, LoadedAudioInfo/error

    def __init__(self, filepath, target_sr):
        super().__init__()
        self.filepath = filepath
        self.target_sr = target_sr

    def run(self):
        try:
            # Check file size first
            valid, msg = AudioCalc.validate_audio_file_size(self.filepath)
            if not valid:
                self.finished.emit(False, None, msg)
                return

            # First read basic info to check length/sr
            info = sf.info(self.filepath)
            file_sr = info.samplerate

            # Read data
            data, _ = sf.read(self.filepath, always_2d=True)
            if self.isInterruptionRequested():
                self.finished.emit(False, None, "Cancelled")
                return

            if file_sr != self.target_sr:
                # Resample using AudioCalc.resample (Polyphase filtering)
                data = AudioCalc.resample(data, file_sr, self.target_sr)
                if self.isInterruptionRequested():
                    self.finished.emit(False, None, "Cancelled")
                    return

            info = LoadedAudioInfo(
                path=self.filepath,
                source_sample_rate=int(file_sr),
                playback_sample_rate=int(self.target_sr),
                channels=int(data.shape[1]),
                duration_seconds=len(data) / self.target_sr,
            )
            self.finished.emit(True, data, info)

        except Exception as e:
            self.finished.emit(False, None, str(e))


class FileSaveWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, source_path, target_path, format=None, subtype=None):
        super().__init__()
        self.source_path = source_path
        self.target_path = target_path
        self.format = format
        self.subtype = subtype

    def run(self):
        if not self.source_path or not os.path.exists(self.source_path):
            self.finished.emit(False, "No recording data found")
            return

        try:
            # Use soundfile to copy/convert from source to target chunk by chunk
            # This handles format conversion (e.g. WAV to FLAC) automatically
            info = sf.info(self.source_path)
            samplerate = info.samplerate
            channels = info.channels

            with sf.SoundFile(self.source_path, "r") as f_in:
                with sf.SoundFile(
                    self.target_path,
                    "w",
                    samplerate=samplerate,
                    channels=channels,
                    format=self.format,
                    subtype=self.subtype,
                ) as f_out:
                    # Use sf.blocks for efficient chunked reading/writing
                    # 1MB blocks to maximize throughput
                    for block in f_in.blocks(blocksize=1048576):
                        f_out.write(block)

            self.finished.emit(True, f"Saved: {self.target_path}")
        except Exception as e:
            self.finished.emit(False, str(e))


class RecorderPlayer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

        # State
        self.is_playing = False
        self.is_recording = False
        self.loop_playback = False
        self.playback_gain_db = 0.0

        # Buffers
        self.playback_buffer = None  # numpy array (samples, channels)
        self.playback_pos = 0
        self.record_buffer = []  # Deprecated, kept empty to avoid immediate crashes
        self.recorded_samples = 0

        # Disk Streaming
        self._temp_record_file = None
        self._temp_record_obj = None
        self._write_queue = None
        self._writer_thread = None
        self.recording_error = ""

        # Cleanup on exit
        atexit.register(self.cleanup)

        # Settings
        self.input_mode = "Stereo"  # Stereo, Left, Right
        self.output_mode = "Stereo"  # Stereo, Left, Right, Mono

        self.callback_id = None
        self.widget = None

    @property
    def name(self) -> str:
        return "Recorder / Player"

    @property
    def description(self) -> str:
        return "Record and play audio files (WAV, MP3, FLAC, etc.)"

    def get_widget(self):
        if self.widget is None:
            self.widget = RecorderPlayerWidget(self)
        return self.widget

    def set_playback_data(self, data):
        self.playback_buffer = data
        self.playback_pos = 0

    # Deprecated synchronous load, kept for compatibility if needed, but UI should use worker
    def load_file(self, filepath):
        try:
            valid, msg = AudioCalc.validate_audio_file_size(filepath)
            if not valid:
                return False, msg

            data, file_sr = sf.read(filepath, always_2d=True)
            engine_sr = self.audio_engine.sample_rate

            msg_extra = ""

            # Resample if needed
            if file_sr != engine_sr:
                logger.debug(f"Resampling {os.path.basename(filepath)}: {file_sr}Hz -> {engine_sr}Hz")

                # Use efficient polyphase resampling
                data = AudioCalc.resample(data, file_sr, engine_sr)
                msg_extra = f" (Resampled from {file_sr}Hz)"

            self.playback_buffer = data
            self.playback_pos = 0
            return (
                True,
                f"Loaded: {os.path.basename(filepath)} ({engine_sr}Hz{msg_extra}, {data.shape[1]}ch, {len(data) / engine_sr:.2f}s)",
            )
        except Exception as e:
            return False, str(e)

    def save_recording(self, filepath, format=None, subtype=None):
        if not self._temp_record_file or not os.path.exists(self._temp_record_file):
            return False, "No recording data found"

        try:
            # Use soundfile to copy/convert from source to target
            info = sf.info(self._temp_record_file)
            samplerate = info.samplerate
            channels = info.channels

            with sf.SoundFile(self._temp_record_file, "r") as f_in:
                with sf.SoundFile(
                    filepath, "w", samplerate=samplerate, channels=channels, format=format, subtype=subtype
                ) as f_out:
                    # Use sf.blocks for efficient chunked reading/writing
                    # 1MB blocks to maximize throughput
                    for block in f_in.blocks(blocksize=1048576):
                        f_out.write(block)

            return True, f"Saved: {filepath}"
        except Exception as e:
            return False, str(e)

    def start_playback(self) -> tuple[bool, str]:
        """Start playback only after the shared audio callback is available."""
        if self.playback_buffer is None or len(self.playback_buffer) == 0:
            return False, "No audio file loaded"
        # If at the end, restart
        if self.playback_pos >= len(self.playback_buffer):
            self.playback_pos = 0
        self.is_playing = True
        try:
            self._ensure_callback()
        except Exception as exc:
            self.is_playing = False
            self._check_stop_callback()
            logger.error("Failed to start playback: %s", exc)
            return False, str(exc)
        return True, ""

    def stop_playback(self):
        self.is_playing = False
        self._check_stop_callback()

    def _remove_temp_file(self):
        if hasattr(self, "_temp_record_obj") and self._temp_record_obj is not None:
            try:
                self._temp_record_obj.close()
            except Exception as e:
                logger.debug(f"Failed to close temp record obj: {e}")
            self._temp_record_obj = None

        if self._temp_record_file and os.path.exists(self._temp_record_file):
            try:
                os.remove(self._temp_record_file)
            except OSError as e:
                logger.debug(f"Failed to remove temp record file: {e}")
        self._temp_record_file = None

    @staticmethod
    def _cleanup_temp_file(obj, filepath):
        if obj is not None:
            try:
                obj.close()
            except Exception as e:
                logger.debug(f"Failed to close temp obj: {e}")
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError as e:
                logger.debug(f"Failed to remove temp file: {e}")

    def cleanup(self):
        """
        Clean up temporary files and resources on shutdown.
        Registered with atexit to ensure execution on app termination.
        """
        if self.is_recording:
            # Try to stop cleanly
            self.stop_recording()

        self._remove_temp_file()

    def _file_writer(self, write_queue, temp_record_obj):
        """Background thread to write audio chunks to disk."""
        try:
            # Wait for first chunk to determine channels
            first_chunk = write_queue.get()
            if first_chunk is None:
                # If we exit before opening the file, ensure the object is closed
                if temp_record_obj is not None:
                    try:
                        temp_record_obj.close()
                    except Exception as e:
                        logger.debug(f"Failed to close temp record obj: {e}")
                return

            channels = first_chunk.shape[1] if first_chunk.ndim > 1 else 1
            samplerate = int(self.audio_engine.sample_rate)

            # Open file for writing. using 'FLOAT' subtype for high quality temp storage
            # Use the secure file descriptor instead of the filepath to prevent TOCTOU
            # We pass the file descriptor but set closefd=False, then explicitly close the object later
            with sf.SoundFile(
                temp_record_obj.fileno(),
                mode="w",
                samplerate=samplerate,
                channels=channels,
                subtype="FLOAT",
                format="WAV",
                closefd=False,
            ) as f:
                f.write(first_chunk)

                while True:
                    chunk = write_queue.get()
                    if chunk is None:
                        break
                    f.write(chunk)

            # Explicitly close the file object to release the lock on Windows
            # allowing the file to be read by name subsequently
            if temp_record_obj is not None:
                try:
                    temp_record_obj.close()
                except Exception as e:
                    logger.debug(f"Failed to close temp record obj: {e}")

        except Exception as e:
            self.recording_error = str(e)
            self.is_recording = False
            logger.error(f"Recorder writer error: {e}")

    def start_recording(self) -> tuple[bool, str]:
        """Start a disk-backed recording and roll back every resource on failure."""
        # Cleanup previous temp file
        self._remove_temp_file()
        self.recording_error = ""

        try:
            # Keep the secure file object alive while soundfile writes through its descriptor.
            self._temp_record_obj = tempfile.NamedTemporaryFile(
                suffix=".wav",
                delete=True,
                delete_on_close=False,
            )
            self._temp_record_file = self._temp_record_obj.name
            weakref.finalize(
                self,
                RecorderPlayer._cleanup_temp_file,
                self._temp_record_obj,
                self._temp_record_file,
            )

            self._write_queue = queue.Queue()
            self._writer_thread = threading.Thread(
                target=self._file_writer,
                args=(self._write_queue, self._temp_record_obj),
                daemon=True,
            )
            self._writer_thread.start()
            self.record_buffer = []  # Ensure empty
            self.recorded_samples = 0
            self.is_recording = True
            self._ensure_callback()
        except Exception as exc:
            self.is_recording = False
            self._stop_writer()
            self._remove_temp_file()
            self._check_stop_callback()
            logger.error("Failed to start recording: %s", exc)
            return False, str(exc)

        return True, ""

    def stop_recording(self):
        self.is_recording = False
        self._check_stop_callback()

        self._stop_writer()

    def _stop_writer(self):
        if self._writer_thread and self._writer_thread.is_alive():
            if self._write_queue is not None:
                self._write_queue.put(None)
            self._writer_thread.join()
        self._writer_thread = None
        self._write_queue = None

    def discard_recording(self):
        """Discard the current temporary recording after the UI confirms intent."""
        if self.is_recording:
            self.stop_recording()
        self._remove_temp_file()
        self.recorded_samples = 0
        self.recording_error = ""

    def _ensure_callback(self):
        if self.callback_id is None:
            self.callback_id = self.audio_engine.register_callback(self.audio_callback)

    def _check_stop_callback(self):
        if not self.is_playing and not self.is_recording:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def audio_callback(self, indata, outdata, frames, time_info, status):
        self._handle_recording(indata, frames)
        self._handle_playback(outdata, frames)

    def _handle_recording(self, indata, frames):
        if not self.is_recording:
            return

        # Select channels based on input_mode
        if self.input_mode == "Stereo":
            rec_data = indata.copy()
        elif self.input_mode == "Left":
            rec_data = indata[:, 0:1]  # Keep 2D
        elif self.input_mode == "Right":
            if indata.shape[1] > 1:
                rec_data = indata[:, 1:2]
            else:
                rec_data = np.zeros((frames, 1), dtype=indata.dtype)

        if self._write_queue:
            self._write_queue.put(rec_data)
        self.recorded_samples += frames

    def _handle_playback(self, outdata, frames):
        # Capture reference locally to ensure consistency during callback (avoid race if main thread swaps buffer)
        current_buffer = self.playback_buffer

        if self.is_playing and current_buffer is not None:
            pb_len = len(current_buffer)

            if pb_len == 0:
                self.is_playing = False
                outdata.fill(0)
                return

            current_idx = 0

            while current_idx < frames:
                # Snap current position to avoid race conditions with UI thread seeking
                pos = self.playback_pos

                # Sanity check for bounds or end of playback
                if pos >= pb_len:
                    if self.loop_playback:
                        pos = 0
                        self.playback_pos = 0
                    else:
                        self.is_playing = False
                        outdata[current_idx:] = 0
                        break

                remaining = frames - current_idx
                available = pb_len - pos

                to_copy = min(remaining, available)

                # Get chunk from buffer safely
                chunk = current_buffer[pos : pos + to_copy]

                # Apply digital gain/attenuation in linear domain
                if self.playback_gain_db != 0.0:
                    gain = 10 ** (self.playback_gain_db / 20.0)
                    chunk = chunk * gain

                # Target slice in outdata
                out_slice = outdata[current_idx : current_idx + to_copy]

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
                    if out_ch > 1:
                        out_slice[:, 1] = 0
                elif self.output_mode == "Right":
                    if out_ch > 1:
                        out_slice[:, 1] = chunk[:, 0] if file_ch == 1 else chunk[:, 1] if file_ch > 1 else 0
                        out_slice[:, 0] = 0
                elif self.output_mode == "Mono":
                    # Mix down to mono and send to all outputs
                    if file_ch > 1:
                        mono = np.mean(chunk, axis=1)
                    else:
                        mono = chunk[:, 0]

                    out_slice[:, 0] = mono
                    if out_ch > 1:
                        out_slice[:, 1] = mono

                # Avoid destructive read-modify-write if the UI thread mutated play position during this loop iteration
                if self.playback_pos == pos:
                    self.playback_pos = pos + to_copy

                current_idx += to_copy

                if self.playback_pos >= pb_len:
                    if self.loop_playback:
                        self.playback_pos = 0
                    else:
                        self.is_playing = False
                        if current_idx < frames:
                            outdata[current_idx:] = 0
                        break
        else:
            outdata.fill(0)


class RecorderPlayerWidget(QWidget, CompactableWidgetInterface):
    RESPONSIVE_BREAKPOINT = 760

    def __init__(self, module: RecorderPlayer):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        self.module = module

        self.load_worker = None
        self.save_worker = None
        self.progress_dialog = None
        self._loaded_info: LoadedAudioInfo | None = None
        self._save_target_path = ""
        self._playback_error = ""
        self._recording_error = ""
        self._has_unsaved_recording = False
        self._was_playing = False
        self._was_recording = False
        self._is_slider_dragging = False

        self.init_ui()
        self.update_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)

    @staticmethod
    def _emphasize(label: QLabel, *, larger: bool = False, monospace: bool = False):
        font = label.font()
        font.setBold(True)
        if larger:
            font.setPointSize(max(font.pointSize() + 3, 13))
        if monospace:
            font.setFamily(MONOSPACE_FONT_FAMILY.split(",", 1)[0])
        label.setFont(font)

    @staticmethod
    def _make_status_label(accessible_name: str) -> QLabel:
        label = QLabel()
        label.setFrameShape(QFrame.Shape.StyledPanel)
        label.setMargin(5)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        label.setAccessibleName(accessible_name)
        RecorderPlayerWidget._emphasize(label)
        return label

    @staticmethod
    def _configure_time_label(label: QLabel, accessible_name: str):
        label.setAccessibleName(accessible_name)
        RecorderPlayerWidget._emphasize(label, monospace=True)

    def init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 10, 12, 12)
        root_layout.setSpacing(10)

        self.full_container = QWidget()
        full_layout = QVBoxLayout(self.full_container)
        full_layout.setContentsMargins(0, 0, 0, 0)
        full_layout.setSpacing(10)

        self.cards_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.cards_layout.setSpacing(10)
        self.playback_group = self._build_playback_group()
        self.recording_group = self._build_recording_group()
        self.cards_layout.addWidget(self.playback_group, 1)
        self.cards_layout.addWidget(self.recording_group, 1)
        full_layout.addLayout(self.cards_layout)

        self.sync_frame = QFrame()
        self.sync_frame.setFrameShape(QFrame.Shape.StyledPanel)
        sync_layout = QHBoxLayout(self.sync_frame)
        self.sync_check = QCheckBox(tr("Sync Play/Record"))
        self.sync_check.setToolTip(tr("Synchronize starting and stopping of playback and recording"))
        self.sync_check.toggled.connect(self.on_sync_toggle)
        self.sync_help_label = QLabel(tr("Synchronize starting and stopping of playback and recording"))
        self.sync_help_label.setWordWrap(True)
        sync_layout.addWidget(self.sync_check)
        sync_layout.addWidget(self.sync_help_label, 1)
        full_layout.addWidget(self.sync_frame)
        full_layout.addStretch()

        self.compact_container = self._build_compact_container()
        self.compact_container.hide()

        root_layout.addWidget(self.full_container)
        root_layout.addWidget(self.compact_container)

        QWidget.setTabOrder(self.load_btn, self.out_mode_combo)
        QWidget.setTabOrder(self.out_mode_combo, self.gain_slider)
        QWidget.setTabOrder(self.gain_slider, self.gain_spin)
        QWidget.setTabOrder(self.gain_spin, self.loop_check)
        QWidget.setTabOrder(self.loop_check, self.play_btn)
        QWidget.setTabOrder(self.play_btn, self.pos_slider)
        QWidget.setTabOrder(self.pos_slider, self.in_mode_combo)
        QWidget.setTabOrder(self.in_mode_combo, self.sync_check)
        QWidget.setTabOrder(self.sync_check, self.rec_btn)
        QWidget.setTabOrder(self.rec_btn, self.save_btn)

    def _build_playback_group(self) -> QGroupBox:
        group = QGroupBox(tr("Playback"))
        layout = QVBoxLayout(group)
        layout.setSpacing(9)

        header = QHBoxLayout()
        self.playback_status_label = self._make_status_label(tr("Playback status"))
        self.file_label = QLabel(tr("No file loaded"))
        self.file_label.setWordWrap(False)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_label.setAccessibleName(tr("Loaded audio file"))
        self.load_btn = QPushButton(tr("Load File"))
        self.load_btn.clicked.connect(self.on_load)
        header.addWidget(self.playback_status_label)
        header.addWidget(self.file_label, 1)
        header.addWidget(self.load_btn)
        layout.addLayout(header)

        self.file_meta_label = QLabel(tr("Load an audio file to see its details."))
        self.file_meta_label.setWordWrap(True)
        self.file_meta_label.setAccessibleName(tr("Audio file details"))
        layout.addWidget(self.file_meta_label)

        timeline = QHBoxLayout()
        self.elapsed_label = QLabel("00:00.00")
        self.total_label = QLabel("00:00.00")
        self._configure_time_label(self.elapsed_label, tr("Playback elapsed time"))
        self._configure_time_label(self.total_label, tr("Playback duration"))
        self.time_label = self.elapsed_label
        self.pos_slider = self._create_position_slider()
        timeline.addWidget(self.elapsed_label)
        timeline.addWidget(self.pos_slider, 1)
        timeline.addWidget(self.total_label)
        layout.addLayout(timeline)

        transport = QHBoxLayout()
        self.play_btn = QPushButton(tr("Play"))
        self.play_btn.setCheckable(True)
        self.play_btn.clicked.connect(self.on_play_toggle)
        self.loop_check = QCheckBox(tr("Loop"))
        self.loop_check.toggled.connect(self.on_loop_toggle)
        transport.addWidget(self.play_btn, 1)
        transport.addWidget(self.loop_check)
        layout.addLayout(transport)

        settings = QGridLayout()
        self.out_mode_label = QLabel(tr("Output Mode:"))
        self.out_mode_combo = QComboBox()
        self.out_mode_combo.addItem(tr("Stereo"), "Stereo")
        self.out_mode_combo.addItem(tr("Left"), "Left")
        self.out_mode_combo.addItem(tr("Right"), "Right")
        self.out_mode_combo.addItem(tr("Mono"), "Mono")
        self.out_mode_combo.currentIndexChanged.connect(self.on_out_mode_changed)
        self.out_mode_label.setBuddy(self.out_mode_combo)
        settings.addWidget(self.out_mode_label, 0, 0)
        settings.addWidget(self.out_mode_combo, 0, 1, 1, 2)

        self.gain_label = QLabel(tr("Playback Gain:"))
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-120, 24)
        self.gain_slider.setValue(0)
        self.gain_slider.setTickInterval(12)
        self.gain_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.gain_slider.setAccessibleName(tr("Digital playback gain"))
        self.gain_slider.setToolTip(tr("Digital gain relative to the loaded audio level."))
        self.gain_slider.valueChanged.connect(self.on_gain_slider_changed)
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60.0, 12.0)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSingleStep(0.5)
        self.gain_spin.setSuffix(tr(" dB"))
        self.gain_spin.setAccessibleName(tr("Digital playback gain"))
        self.gain_spin.setToolTip(tr("Digital gain relative to the loaded audio level."))
        self.gain_spin.valueChanged.connect(self.on_gain_spin_changed)
        self.gain_value_label = self.gain_spin
        self.gain_label.setBuddy(self.gain_spin)
        settings.addWidget(self.gain_label, 1, 0)
        settings.addWidget(self.gain_slider, 1, 1)
        settings.addWidget(self.gain_spin, 1, 2)
        settings.setColumnStretch(1, 1)
        layout.addLayout(settings)
        return group

    def _build_recording_group(self) -> QGroupBox:
        group = QGroupBox(tr("Recording"))
        layout = QVBoxLayout(group)
        layout.setSpacing(9)

        header = QHBoxLayout()
        self.recording_status_label = self._make_status_label(tr("Recording status"))
        self.rec_info_label = QLabel("00:00.00")
        self._configure_time_label(self.rec_info_label, tr("Recording duration"))
        self._emphasize(self.rec_info_label, larger=True, monospace=True)
        header.addWidget(self.recording_status_label)
        header.addStretch()
        header.addWidget(self.rec_info_label)
        layout.addLayout(header)

        controls = QHBoxLayout()
        self.rec_btn = QPushButton(tr("Record"))
        self.rec_btn.setCheckable(True)
        self.rec_btn.clicked.connect(self.on_record_toggle)
        self.save_btn = QPushButton(tr("Save Recording"))
        self.save_btn.clicked.connect(self.on_save)
        controls.addWidget(self.rec_btn, 1)
        controls.addWidget(self.save_btn)
        layout.addLayout(controls)

        input_layout = QHBoxLayout()
        self.in_mode_label = QLabel(tr("Input Mode:"))
        self.in_mode_combo = QComboBox()
        self.in_mode_combo.addItem(tr("Stereo"), "Stereo")
        self.in_mode_combo.addItem(tr("Left"), "Left")
        self.in_mode_combo.addItem(tr("Right"), "Right")
        self.in_mode_combo.currentIndexChanged.connect(self.on_in_mode_changed)
        self.in_mode_label.setBuddy(self.in_mode_combo)
        input_layout.addWidget(self.in_mode_label)
        input_layout.addWidget(self.in_mode_combo, 1)
        layout.addLayout(input_layout)
        layout.addStretch()
        return group

    def _build_compact_container(self) -> QWidget:
        container = QFrame()
        container.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QGridLayout(container)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.compact_file_label = QLabel(tr("No file loaded"))
        self.compact_file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.compact_file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.compact_file_label.setAccessibleName(tr("Loaded audio file"))
        self.compact_playback_status_label = self._make_status_label(tr("Playback status"))
        self.compact_elapsed_label = QLabel("00:00.00")
        self.compact_total_label = QLabel("00:00.00")
        self._configure_time_label(self.compact_elapsed_label, tr("Playback elapsed time"))
        self._configure_time_label(self.compact_total_label, tr("Playback duration"))

        layout.addWidget(self.compact_file_label, 0, 0, 1, 2)
        layout.addWidget(self.compact_playback_status_label, 0, 2)
        layout.addWidget(self.compact_elapsed_label, 0, 3)
        layout.addWidget(QLabel("/"), 0, 4)
        layout.addWidget(self.compact_total_label, 0, 5)

        self.compact_pos_slider = self._create_position_slider()
        layout.addWidget(self.compact_pos_slider, 1, 0, 1, 6)

        self.compact_play_btn = QPushButton(tr("Play"))
        self.compact_play_btn.setCheckable(True)
        self.compact_play_btn.clicked.connect(self.on_play_toggle)
        self.compact_loop_check = QCheckBox(tr("Loop"))
        self.compact_loop_check.toggled.connect(self.on_loop_toggle)
        self.compact_rec_btn = QPushButton(tr("Record"))
        self.compact_rec_btn.setCheckable(True)
        self.compact_rec_btn.clicked.connect(self.on_record_toggle)
        self.compact_recording_status_label = self._make_status_label(tr("Recording status"))
        self.compact_rec_time_label = QLabel("00:00.00")
        self._configure_time_label(self.compact_rec_time_label, tr("Recording duration"))
        self.compact_save_btn = QPushButton(tr("Save Recording"))
        self.compact_save_btn.clicked.connect(self.on_save)

        layout.addWidget(self.compact_play_btn, 2, 0)
        layout.addWidget(self.compact_loop_check, 2, 1)
        layout.addWidget(self.compact_rec_btn, 2, 2)
        layout.addWidget(self.compact_recording_status_label, 2, 3)
        layout.addWidget(self.compact_rec_time_label, 2, 4)
        layout.addWidget(self.compact_save_btn, 2, 5)

        self.compact_conditions_label = QLabel()
        self.compact_conditions_label.setWordWrap(True)
        self.compact_conditions_label.setAccessibleName(tr("Audio routing summary"))
        self.compact_sync_check = QCheckBox(tr("Sync Play/Record"))
        self.compact_sync_check.setToolTip(tr("Synchronize starting and stopping of playback and recording"))
        self.compact_sync_check.toggled.connect(self.on_sync_toggle)
        layout.addWidget(self.compact_conditions_label, 3, 0, 1, 5)
        layout.addWidget(self.compact_sync_check, 3, 5)
        layout.setColumnStretch(0, 1)
        return container

    def _create_position_slider(self) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 1000)
        slider.setAccessibleName(tr("Playback position"))
        slider.sliderPressed.connect(self.on_slider_pressed)
        slider.sliderReleased.connect(self.on_slider_released)
        slider.sliderMoved.connect(self.on_slider_moved)
        slider.valueChanged.connect(self.on_slider_value_changed)
        return slider

    @staticmethod
    def _format_time(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        remaining = seconds % 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{remaining:05.2f}"
        return f"{minutes:02d}:{remaining:05.2f}"

    @staticmethod
    def _set_checked(widget, checked: bool):
        widget.blockSignals(True)
        widget.setChecked(checked)
        widget.blockSignals(False)

    @staticmethod
    def _set_slider_value(slider: QSlider, value: int):
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)

    def resizeEvent(self, event):
        direction = (
            QBoxLayout.Direction.TopToBottom
            if event.size().width() < self.RESPONSIVE_BREAKPOINT
            else QBoxLayout.Direction.LeftToRight
        )
        if self.cards_layout.direction() != direction:
            self.cards_layout.setDirection(direction)
        self._update_file_presentation()
        super().resizeEvent(event)

    def update_compact_layout(self) -> None:
        compact = self.is_compact_mode()
        self.full_container.setHidden(compact)
        self.compact_container.setVisible(compact)
        self.update_ui()
        self.updateGeometry()

    def on_slider_pressed(self):
        self._is_slider_dragging = True

    def on_slider_released(self):
        slider = self.sender()
        self._is_slider_dragging = False
        self._seek_to_slider(slider if isinstance(slider, QSlider) else None)

    def on_slider_moved(self, value):
        if self.module.playback_buffer is None:
            return
        total_samples = len(self.module.playback_buffer)
        target_pos = int((value / 1000.0) * total_samples)
        sr = max(1, self.module.audio_engine.sample_rate)
        elapsed = self._format_time(target_pos / sr)
        self.elapsed_label.setText(elapsed)
        self.compact_elapsed_label.setText(elapsed)

    def on_slider_value_changed(self, _value):
        if not self._is_slider_dragging:
            slider = self.sender()
            self._seek_to_slider(slider if isinstance(slider, QSlider) else None)

    def _seek_to_slider(self, slider: QSlider | None = None):
        if self.module.playback_buffer is None:
            return
        slider = slider or self.pos_slider
        total_samples = len(self.module.playback_buffer)
        target_pos = int((slider.value() / 1000.0) * total_samples)
        self.module.playback_pos = max(0, min(total_samples, target_pos))
        self.update_ui()

    def on_load(self):
        fname, _ = QFileDialog.getOpenFileName(
            self,
            tr("Open Audio File"),
            "",
            tr("Audio Files (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)"),
        )
        if not fname:
            return

        try:
            info = sf.info(fname)
            file_sr = info.samplerate
            engine_sr = self.module.audio_engine.sample_rate

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

            self._playback_error = ""
            self.load_worker = FileLoadWorker(fname, engine_sr)
            self.load_worker.finished.connect(self.on_load_finished)
            self.progress_dialog = QProgressDialog(
                tr("Loading and processing audio..."),
                tr("Cancel"),
                0,
                0,
                self,
            )
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.canceled.connect(self.on_load_cancel)
            self.progress_dialog.show()
            self.load_worker.start()
            self.update_ui()
        except Exception as exc:
            self._playback_error = str(exc)
            QMessageBox.critical(self, tr("Error"), tr("Failed to read file info:\n{0}").format(exc))
            self.update_ui()

    def on_load_finished(self, success, data, result):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        if success:
            self.module.set_playback_data(data)
            self._loaded_info = result if isinstance(result, LoadedAudioInfo) else None
            self._playback_error = ""
        elif result != "Cancelled":
            self._playback_error = str(result)
            QMessageBox.critical(self, tr("Error"), tr("Failed to load file:\n{0}").format(result))

        self.load_worker = None
        self.update_ui()

    def on_load_cancel(self):
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.requestInterruption()
            if self.progress_dialog:
                self.progress_dialog.setLabelText(tr("Stopping…"))
                self.progress_dialog.setCancelButton(None)

    def _confirm_replace_recording(self) -> bool:
        if not self._has_unsaved_recording:
            return True
        reply = QMessageBox.warning(
            self,
            tr("Unsaved recording"),
            tr("The previous recording has not been saved. Save it before starting a new recording?"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if reply == QMessageBox.StandardButton.Save:
            self.on_save()
            return False
        if reply != QMessageBox.StandardButton.Discard:
            return False
        self.module.discard_recording()
        self._has_unsaved_recording = False
        return True

    def _show_start_error(self, operation: str, message: str):
        QMessageBox.critical(
            self,
            tr("Error"),
            tr("Failed to start {0}:\n{1}").format(operation, message),
        )

    def on_play_toggle(self, _checked=False):
        if self.module.is_playing:
            self.module.stop_playback()
            if self.sync_check.isChecked() and self.module.is_recording:
                self.module.stop_recording()
                self._mark_recording_stopped()
            self.update_ui()
            return

        if self.sync_check.isChecked() and not self._confirm_replace_recording():
            self.update_ui()
            return

        success, message = self.module.start_playback()
        if not success:
            self._playback_error = message
            self._show_start_error(tr("playback"), message)
            self.update_ui()
            return

        self._playback_error = ""
        if self.sync_check.isChecked() and not self.module.is_recording:
            success, message = self.module.start_recording()
            if not success:
                self.module.stop_playback()
                self._recording_error = message
                self._show_start_error(tr("recording"), message)
            else:
                self._recording_error = ""
                self._has_unsaved_recording = False
        self.update_ui()

    def on_record_toggle(self, _checked=False):
        if self.module.is_recording:
            self.module.stop_recording()
            self._mark_recording_stopped()
            if self.sync_check.isChecked() and self.module.is_playing:
                self.module.stop_playback()
            self.update_ui()
            return

        if not self._confirm_replace_recording():
            self.update_ui()
            return

        success, message = self.module.start_recording()
        if not success:
            self._recording_error = message
            self._show_start_error(tr("recording"), message)
            self.update_ui()
            return

        self._recording_error = ""
        self._has_unsaved_recording = False
        if self.sync_check.isChecked() and not self.module.is_playing:
            success, message = self.module.start_playback()
            if not success:
                self.module.stop_recording()
                self.module.discard_recording()
                self._playback_error = message
                self._show_start_error(tr("playback"), message)
        self.update_ui()

    def _mark_recording_stopped(self):
        if self.module.recording_error:
            self._recording_error = self.module.recording_error
            return
        if self.module.recorded_samples > 0:
            self._has_unsaved_recording = True

    def on_loop_toggle(self, checked):
        self.module.loop_playback = bool(checked)
        self._set_checked(self.loop_check, self.module.loop_playback)
        self._set_checked(self.compact_loop_check, self.module.loop_playback)

    def on_sync_toggle(self, checked):
        self._set_checked(self.sync_check, bool(checked))
        self._set_checked(self.compact_sync_check, bool(checked))

    def on_out_mode_changed(self, _index):
        self.module.output_mode = self.out_mode_combo.currentData()
        self.update_ui()

    def on_in_mode_changed(self, _index):
        self.module.input_mode = self.in_mode_combo.currentData()
        self.update_ui()

    def on_gain_slider_changed(self, value):
        gain_db = value / 2.0
        self.module.playback_gain_db = gain_db
        self.gain_spin.blockSignals(True)
        self.gain_spin.setValue(gain_db)
        self.gain_spin.blockSignals(False)
        self.update_ui()

    def on_gain_spin_changed(self, value):
        gain_db = float(value)
        self.module.playback_gain_db = gain_db
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(round(gain_db * 2.0))
        self.gain_slider.blockSignals(False)
        self.update_ui()

    def on_save(self):
        if not self._has_unsaved_recording:
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save Recording"),
            "recording.wav",
            tr("WAV (*.wav);;FLAC (*.flac);;OGG (*.ogg)"),
        )
        if not fname:
            return

        self._save_target_path = fname
        self.save_worker = FileSaveWorker(self.module._temp_record_file, fname)
        self.save_worker.finished.connect(self.on_save_finished)
        self.progress_dialog = QProgressDialog(tr("Saving recording..."), None, 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()
        self.save_worker.start()
        self.update_ui()

    def on_save_finished(self, success, message):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.save_worker = None
        if success:
            self._has_unsaved_recording = False
            QMessageBox.information(
                self,
                tr("Success"),
                tr("Recording saved to:\n{0}").format(self._save_target_path),
            )
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to save:\n{0}").format(message))
        self.update_ui()

    def _update_file_presentation(self):
        if self._loaded_info is None:
            name = tr("No file loaded") if self.module.playback_buffer is None else tr("Ready")
            details = tr("Load an audio file to see its details.")
            tooltip = name
        else:
            info = self._loaded_info
            name = os.path.basename(info.path)
            duration = self._format_time(info.duration_seconds)
            details = tr("{0} Hz · {1} ch · {2}").format(
                info.playback_sample_rate,
                info.channels,
                duration,
            )
            if info.was_resampled:
                details += " · " + tr("Resampled from {0} Hz").format(info.source_sample_rate)
            tooltip = info.path

        file_text = self.file_label.fontMetrics().elidedText(
            name,
            Qt.TextElideMode.ElideMiddle,
            max(80, self.file_label.width()),
        )
        compact_file_text = self.compact_file_label.fontMetrics().elidedText(
            name,
            Qt.TextElideMode.ElideMiddle,
            max(80, self.compact_file_label.width()),
        )
        self.file_label.setText(file_text)
        self.file_label.setToolTip(tooltip)
        self.file_label.setAccessibleDescription(tooltip)
        self.compact_file_label.setText(compact_file_text)
        self.compact_file_label.setToolTip(tooltip)
        self.compact_file_label.setAccessibleDescription(tooltip)
        self.file_meta_label.setText(details)

    def _update_position(self):
        buffer = self.module.playback_buffer
        total = len(buffer) if buffer is not None else 0
        sr = max(1, self.module.audio_engine.sample_rate)
        pos = max(0, min(total, self.module.playback_pos))
        progress = int(1000 * pos / total) if total else 0
        if not self._is_slider_dragging:
            self._set_slider_value(self.pos_slider, progress)
            self._set_slider_value(self.compact_pos_slider, progress)
            elapsed = self._format_time(pos / sr)
            self.elapsed_label.setText(elapsed)
            self.compact_elapsed_label.setText(elapsed)
        total_text = self._format_time(total / sr)
        self.total_label.setText(total_text)
        self.compact_total_label.setText(total_text)

    def _update_playback_state(self, loading: bool, file_loaded: bool):
        playing = self.module.is_playing
        total = len(self.module.playback_buffer) if file_loaded else 0
        if loading:
            status = tr("Loading")
        elif self._playback_error:
            status = tr("Error")
        elif not file_loaded:
            status = tr("No file")
        elif playing:
            status = tr("Playing")
        elif total and self.module.playback_pos >= total:
            status = tr("Ended")
        elif self.module.playback_pos > 0:
            status = tr("Stopped")
        else:
            status = tr("Ready")

        self.playback_status_label.setText(status)
        self.compact_playback_status_label.setText(status)
        button_text = tr("Stop Playback") if playing else tr("Play")
        for button in (self.play_btn, self.compact_play_btn):
            button.setText(button_text)
            self._set_checked(button, playing)
            button.setEnabled(file_loaded and not loading)
            button.setToolTip(
                tr("Stop audio output.")
                if playing
                else tr("Start playback.")
                if file_loaded
                else tr("Load an audio file to enable playback.")
            )

        for slider in (self.pos_slider, self.compact_pos_slider):
            slider.setEnabled(file_loaded and not loading)
        for loop in (self.loop_check, self.compact_loop_check):
            loop.setEnabled(file_loaded and not loading)
        self.load_btn.setEnabled(not loading and not playing)

    def _update_recording_state(self, saving: bool):
        recording = self.module.is_recording
        duration = self.module.recorded_samples / max(1, self.module.audio_engine.sample_rate)
        duration_text = self._format_time(duration)
        self.rec_info_label.setText(duration_text)
        self.compact_rec_time_label.setText(duration_text)

        if saving:
            status = tr("Saving")
        elif self._recording_error or self.module.recording_error:
            status = tr("Error")
        elif recording:
            status = tr("Recording")
        elif self._has_unsaved_recording:
            status = tr("Unsaved")
        elif self.module.recorded_samples > 0:
            status = tr("Saved")
        else:
            status = tr("Ready")
        self.recording_status_label.setText(status)
        self.compact_recording_status_label.setText(status)

        rec_text = tr("Stop Recording") if recording else tr("Record")
        for button in (self.rec_btn, self.compact_rec_btn):
            button.setText(rec_text)
            self._set_checked(button, recording)
            button.setEnabled(not saving and self.load_worker is None)
        save_enabled = self._has_unsaved_recording and not recording and not saving
        for button in (self.save_btn, self.compact_save_btn):
            button.setEnabled(save_enabled)
            button.setToolTip(
                tr("Save the current recording.")
                if save_enabled
                else tr("Stop recording before saving.")
                if recording
                else tr("No recording available to save.")
            )
        self.compact_save_btn.setVisible(self._has_unsaved_recording or saving)
        self.in_mode_combo.setEnabled(not recording and not saving)

    def update_ui(self):
        if self._was_playing and not self.module.is_playing:
            self.module._check_stop_callback()
            if self.sync_check.isChecked() and self.module.is_recording:
                self.module.stop_recording()
                self._mark_recording_stopped()
        if self._was_recording and not self.module.is_recording:
            self.module.stop_recording()
            self._mark_recording_stopped()

        loading = self.load_worker is not None
        saving = self.save_worker is not None
        file_loaded = self.module.playback_buffer is not None and len(self.module.playback_buffer) > 0

        self._set_checked(self.loop_check, self.module.loop_playback)
        self._set_checked(self.compact_loop_check, self.module.loop_playback)
        sync_enabled = (
            file_loaded and not loading and not saving and not self.module.is_playing and not self.module.is_recording
        )
        for sync in (self.sync_check, self.compact_sync_check):
            sync.setEnabled(sync_enabled)
            sync.setToolTip(
                tr("Synchronize starting and stopping of playback and recording")
                if file_loaded
                else tr("Load an audio file to enable synchronized operation.")
            )

        self._update_file_presentation()
        self._update_position()
        self._update_playback_state(loading, file_loaded)
        self._update_recording_state(saving)
        self.compact_conditions_label.setText(
            tr("Out {0} · Gain {1:.1f} dB · In {2}").format(
                self.out_mode_combo.currentText(),
                self.module.playback_gain_db,
                self.in_mode_combo.currentText(),
            )
        )

        self._was_playing = self.module.is_playing
        self._was_recording = self.module.is_recording

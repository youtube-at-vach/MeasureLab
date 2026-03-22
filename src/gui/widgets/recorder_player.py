import atexit
import logging
import os
import queue
import tempfile
import threading

import numpy as np
import soundfile as sf
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.analysis import AudioCalc


logger = logging.getLogger(__name__)


WRITE_BLOCK_SIZE = 65536


class FileLoadWorker(QThread):
    finished = pyqtSignal(bool, object, str)  # success, data, message

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

            msg_extra = ""
            if file_sr != self.target_sr:
                # Resample using AudioCalc.resample (Polyphase filtering)
                data = AudioCalc.resample(data, file_sr, self.target_sr)
                msg_extra = f" (Resampled from {file_sr}Hz)"

            result_msg = f"Loaded: {os.path.basename(self.filepath)} ({self.target_sr}Hz{msg_extra}, {data.shape[1]}ch, {len(data) / self.target_sr:.2f}s)"
            self.finished.emit(True, data, result_msg)

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
        self._temp_record_fd = None
        self._write_queue = None
        self._writer_thread = None

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

    def start_playback(self):
        if self.playback_buffer is None:
            return
        # If at the end, restart
        if self.playback_pos >= len(self.playback_buffer):
            self.playback_pos = 0
        self.is_playing = True
        self._ensure_callback()

    def stop_playback(self):
        self.is_playing = False
        self._check_stop_callback()

    def _remove_temp_file(self):
        if self._temp_record_fd is not None:
            try:
                os.close(self._temp_record_fd)
            except OSError:
                pass
            self._temp_record_fd = None

        if self._temp_record_file and os.path.exists(self._temp_record_file):
            try:
                os.remove(self._temp_record_file)
            except OSError:
                pass

    def cleanup(self):
        """
        Clean up temporary files and resources on shutdown.
        Registered with atexit to ensure execution on app termination.
        """
        if self.is_recording:
            # Try to stop cleanly
            self.stop_recording()

        self._remove_temp_file()

    def _file_writer(self):
        """Background thread to write audio chunks to disk."""
        try:
            # Wait for first chunk to determine channels
            first_chunk = self._write_queue.get()
            if first_chunk is None:
                # If we exit before opening the file, ensure the fd is closed
                if self._temp_record_fd is not None:
                    try:
                        os.close(self._temp_record_fd)
                        self._temp_record_fd = None
                    except OSError:
                        pass
                return

            channels = first_chunk.shape[1] if first_chunk.ndim > 1 else 1
            samplerate = int(self.audio_engine.sample_rate)

            # Open file for writing. using 'FLOAT' subtype for high quality temp storage
            # Use the secure file descriptor instead of the filepath to prevent TOCTOU
            # The format argument is required when using a file descriptor
            with sf.SoundFile(
                self._temp_record_fd,
                mode="w",
                samplerate=samplerate,
                channels=channels,
                subtype="FLOAT",
                format="WAV",
                closefd=True,
            ) as f:
                # SoundFile now owns the fd and will close it
                self._temp_record_fd = None

                f.write(first_chunk)

                while True:
                    chunk = self._write_queue.get()
                    if chunk is None:
                        break
                    f.write(chunk)

        except Exception as e:
            logger.error(f"Recorder writer error: {e}")

    def start_recording(self):
        # Cleanup previous temp file
        self._remove_temp_file()

        # Create new temp file and store file descriptor to avoid TOCTOU vulnerability
        fd, self._temp_record_file = tempfile.mkstemp(suffix=".wav")
        # Keep the file descriptor open and store it for sf.SoundFile to use
        self._temp_record_fd = fd

        # Init queue and thread
        self._write_queue = queue.Queue()
        self._writer_thread = threading.Thread(target=self._file_writer, daemon=True)
        self._writer_thread.start()

        self.record_buffer = []  # Ensure empty
        self.recorded_samples = 0
        self.is_recording = True
        self._ensure_callback()

    def stop_recording(self):
        self.is_recording = False
        self._check_stop_callback()

        # Stop writer thread
        if self._writer_thread and self._writer_thread.is_alive():
            self._write_queue.put(None)
            self._writer_thread.join()
            self._writer_thread = None
            self._write_queue = None

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


class RecorderPlayerWidget(QWidget):
    def __init__(self, module: RecorderPlayer):
        super().__init__()
        self.module = module
        self.init_ui()

        self.load_worker = None
        self.save_worker = None
        self.progress_dialog = None

        self._was_playing = False

        # Update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.start(100)

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Playback Section ---
        pb_group = QGroupBox(tr("Playback"))
        pb_layout = QVBoxLayout()

        # File Info
        self.file_label = QLabel(tr("No file loaded"))
        self.file_label.setWordWrap(True)
        pb_layout.addWidget(self.file_label)

        # Controls
        ctrl_layout = QHBoxLayout()
        self.load_btn = QPushButton(tr("Load File"))
        self.load_btn.clicked.connect(self.on_load)
        self.play_btn = QPushButton(tr("Play"))
        self.play_btn.clicked.connect(self.on_play_toggle)
        self.loop_check = QCheckBox(tr("Loop"))
        self.loop_check.toggled.connect(self.on_loop_toggle)

        ctrl_layout.addWidget(self.load_btn)
        ctrl_layout.addWidget(self.play_btn)
        ctrl_layout.addWidget(self.loop_check)
        pb_layout.addLayout(ctrl_layout)

        # Position Slider
        pos_layout = QHBoxLayout()
        self.time_label = QLabel("0.00 / 0.00 s")
        pos_layout.addWidget(self.time_label)

        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 1000)
        self.pos_slider.setEnabled(False)
        self.pos_slider.sliderPressed.connect(self.on_slider_pressed)
        self.pos_slider.sliderReleased.connect(self.on_slider_released)
        self.pos_slider.sliderMoved.connect(self.on_slider_moved)
        self.pos_slider.valueChanged.connect(self.on_slider_value_changed)
        pos_layout.addWidget(self.pos_slider)
        pb_layout.addLayout(pos_layout)

        # Output Mode
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel(tr("Output Mode:")))
        self.out_mode_combo = QComboBox()
        self.out_mode_combo.addItem(tr("Stereo"), "Stereo")
        self.out_mode_combo.addItem(tr("Left"), "Left")
        self.out_mode_combo.addItem(tr("Right"), "Right")
        self.out_mode_combo.addItem(tr("Mono"), "Mono")
        self.out_mode_combo.currentTextChanged.connect(self.on_out_mode_changed)
        out_layout.addWidget(self.out_mode_combo)
        pb_layout.addLayout(out_layout)

        # Playback Gain (digital)
        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel(tr("Playback Gain:")))
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-60, 12)  # dB
        self.gain_slider.setValue(0)
        self.gain_slider.setTickInterval(6)
        self.gain_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.gain_slider.valueChanged.connect(self.on_gain_changed)
        gain_layout.addWidget(self.gain_slider)
        self.gain_value_label = QLabel(tr("0 dB"))
        gain_layout.addWidget(self.gain_value_label)
        pb_layout.addLayout(gain_layout)

        # Output Destination
        pb_group.setLayout(pb_layout)
        layout.addWidget(pb_group)

        # --- Recording Section ---
        rec_group = QGroupBox(tr("Recording"))
        rec_layout = QVBoxLayout()

        # Controls
        rec_ctrl_layout = QHBoxLayout()
        self.rec_btn = QPushButton(tr("Record"))
        self.rec_btn.setCheckable(True)
        self.rec_btn.clicked.connect(self.on_record_toggle)
        self.save_btn = QPushButton(tr("Save Recording"))
        self.save_btn.clicked.connect(self.on_save)
        self.save_btn.setEnabled(False)

        self.sync_check = QCheckBox(tr("Sync Play/Record"))
        self.sync_check.setToolTip(tr("Synchronize starting and stopping of playback and recording"))

        rec_ctrl_layout.addWidget(self.rec_btn)
        rec_ctrl_layout.addWidget(self.save_btn)
        rec_ctrl_layout.addWidget(self.sync_check)
        rec_layout.addLayout(rec_ctrl_layout)

        # Info
        self.rec_info_label = QLabel(tr("Recorded: 0.00s"))
        rec_layout.addWidget(self.rec_info_label)

        # Input Mode
        in_layout = QHBoxLayout()
        in_layout.addWidget(QLabel(tr("Input Mode:")))
        self.in_mode_combo = QComboBox()
        self.in_mode_combo.addItem(tr("Stereo"), "Stereo")
        self.in_mode_combo.addItem(tr("Left"), "Left")
        self.in_mode_combo.addItem(tr("Right"), "Right")
        self.in_mode_combo.currentTextChanged.connect(self.on_in_mode_changed)
        in_layout.addWidget(self.in_mode_combo)
        rec_layout.addLayout(in_layout)

        rec_group.setLayout(rec_layout)
        layout.addWidget(rec_group)

        layout.addStretch()
        self.setLayout(layout)

    def on_slider_pressed(self):
        self._is_slider_dragging = True

    def on_slider_released(self):
        self._is_slider_dragging = False
        self._seek_to_slider()

    def on_slider_moved(self, value):
        if self.module.playback_buffer is not None:
            total_samples = len(self.module.playback_buffer)
            target_pos = int((value / 1000.0) * total_samples)
            sr = self.module.audio_engine.sample_rate
            self.time_label.setText(f"{target_pos / sr:.2f} / {total_samples / sr:.2f} s")

    def on_slider_value_changed(self, value):
        if not getattr(self, "_is_slider_dragging", False):
            self._seek_to_slider()

    def _seek_to_slider(self):
        if self.module.playback_buffer is not None:
            total_samples = len(self.module.playback_buffer)
            target_pos = int((self.pos_slider.value() / 1000.0) * total_samples)
            target_pos = max(0, min(total_samples, target_pos))
            self.module.playback_pos = target_pos

            sr = self.module.audio_engine.sample_rate
            self.time_label.setText(f"{target_pos / sr:.2f} / {total_samples / sr:.2f} s")

    def on_load(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, tr("Open Audio File"), "", tr("Audio Files (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)")
        )
        if not fname:
            return

        try:
            # Check sample rate first
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

            # Start background loading
            self.load_worker = FileLoadWorker(fname, engine_sr)
            self.load_worker.finished.connect(self.on_load_finished)

            # Show progress dialog
            self.progress_dialog = QProgressDialog(tr("Loading and processing audio..."), tr("Cancel"), 0, 0, self)
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.canceled.connect(self.on_load_cancel)
            self.progress_dialog.show()

            self.load_worker.start()

        except Exception as e:
            QMessageBox.critical(self, tr("Error"), tr("Failed to read file info:\n{0}").format(e))

    def on_load_finished(self, success, data, msg):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        if success:
            self.module.set_playback_data(data)
            self.file_label.setText(msg)
            self.pos_slider.setEnabled(True)
            self.pos_slider.blockSignals(True)
            self.pos_slider.setValue(0)
            self.pos_slider.blockSignals(False)
            if self.module.playback_buffer is not None:
                sr = self.module.audio_engine.sample_rate
                total = len(self.module.playback_buffer)
                self.time_label.setText(f"0.00 / {total / sr:.2f} s")
        else:
            if msg != "Cancelled":  # Don't show error if user cancelled
                QMessageBox.critical(self, tr("Error"), tr("Failed to load file:\n{0}").format(msg))

        self.load_worker = None

    def on_load_cancel(self):
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.terminate()  # Terminate is harsh but effective for simple worker
            self.load_worker.wait()
            self.load_worker = None

    def on_play_toggle(self):
        if self.module.is_playing:
            self.module.stop_playback()

            if hasattr(self, "sync_check") and self.sync_check.isChecked() and self.module.is_recording:
                self.rec_btn.setChecked(False)
                self.module.stop_recording()
                self.rec_btn.setText(tr("Record"))
                self.rec_btn.setStyleSheet("")
                self.save_btn.setEnabled(True)
        else:
            self.module.start_playback()

            if hasattr(self, "sync_check") and self.sync_check.isChecked() and not self.module.is_recording:
                self.rec_btn.setChecked(True)
                self.module.start_recording()
                self.rec_btn.setText(tr("Stop Recording"))
                self.rec_btn.setStyleSheet("background-color: #ffcccc; color: red; font-weight: bold;")
                self.save_btn.setEnabled(False)

    def on_loop_toggle(self, checked):
        self.module.loop_playback = checked

    def on_out_mode_changed(self, text):
        self.module.output_mode = self.out_mode_combo.currentData()

    def on_gain_changed(self, value):
        self.module.playback_gain_db = float(value)
        self.gain_value_label.setText(tr("{0} dB").format(value))

    def on_record_toggle(self):
        if self.rec_btn.isChecked():
            self.module.start_recording()
            self.rec_btn.setText(tr("Stop Recording"))
            self.rec_btn.setStyleSheet("background-color: #ffcccc; color: red; font-weight: bold;")
            self.save_btn.setEnabled(False)

            if hasattr(self, "sync_check") and self.sync_check.isChecked() and not self.module.is_playing:
                self.module.start_playback()
        else:
            self.module.stop_recording()
            self.rec_btn.setText(tr("Record"))
            self.rec_btn.setStyleSheet("")
            self.save_btn.setEnabled(True)

            if hasattr(self, "sync_check") and self.sync_check.isChecked() and self.module.is_playing:
                self.module.stop_playback()

    def on_save(self):
        fname, selected_filter = QFileDialog.getSaveFileName(
            self, tr("Save Recording"), "recording.wav", tr("WAV (*.wav);;FLAC (*.flac);;OGG (*.ogg)")
        )
        if not fname:
            return

        # Disable UI to prevent concurrent actions
        self.rec_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

        # Start background saving
        self.save_worker = FileSaveWorker(self.module._temp_record_file, fname)
        self.save_worker.finished.connect(self.on_save_finished)

        # Show progress dialog
        self.progress_dialog = QProgressDialog(tr("Saving recording..."), None, 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        # Cannot cancel a save operation easily in the middle of sf.write, so no cancel button or handler for now.
        # If we wanted to cancel, we'd need to chunk the write or use a cancellable write loop.
        # For now, just indeterminate progress.
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()

        self.save_worker.start()

    def on_save_finished(self, success, msg):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.rec_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

        if success:
            QMessageBox.information(self, tr("Success"), msg)
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to save:\n{0}").format(msg))

        self.save_worker = None

    def on_in_mode_changed(self, text):
        self.module.input_mode = self.in_mode_combo.currentData()

    def update_ui(self):
        # Update Playback UI
        if self.module.is_playing:
            self.play_btn.setText(tr("Stop"))
        else:
            self.play_btn.setText(tr("Play"))

            if (
                getattr(self, "_was_playing", False)
                and hasattr(self, "sync_check")
                and self.sync_check.isChecked()
                and self.module.is_recording
            ):
                self.rec_btn.setChecked(False)
                self.module.stop_recording()
                self.rec_btn.setText(tr("Record"))
                self.rec_btn.setStyleSheet("")
                self.save_btn.setEnabled(True)

        self._was_playing = self.module.is_playing

        # Always update slider if file loaded and not dragging
        if self.module.playback_buffer is not None and not getattr(self, "_is_slider_dragging", False):
            total = len(self.module.playback_buffer)
            if total > 0:
                pos = self.module.playback_pos
                # Handle possible float division by zero just in case
                sr = max(1, self.module.audio_engine.sample_rate)
                progress = int(1000 * pos / total)

                self.pos_slider.blockSignals(True)
                self.pos_slider.setValue(progress)
                self.pos_slider.blockSignals(False)

                self.time_label.setText(f"{pos / sr:.2f} / {total / sr:.2f} s")

        # Update Recording UI
        if self.module.is_recording:
            duration = self.module.recorded_samples / self.module.audio_engine.sample_rate
            self.rec_info_label.setText(tr("Recorded: {0:.2f}s").format(duration))
        elif self.module.recorded_samples > 0:
            duration = self.module.recorded_samples / self.module.audio_engine.sample_rate
            self.rec_info_label.setText(tr("Recorded: {0:.2f}s (Stopped)").format(duration))

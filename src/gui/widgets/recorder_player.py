import os
import shutil
import tempfile
import math
import numpy as np
import soundfile as sf
import scipy.signal

from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
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

class TempFileRegistry:
    """
    Manages temporary files to ensure they are cleaned up.
    """
    _files = set()

    @classmethod
    def register(cls, path):
        cls._files.add(path)

    @classmethod
    def unregister(cls, path):
        if path in cls._files:
            cls._files.remove(path)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    @classmethod
    def cleanup_all(cls):
        for path in list(cls._files):
            cls.unregister(path)


class FileLoadWorker(QThread):
    finished = pyqtSignal(bool, object, str, object) # success, data, message, temp_file_path

    def __init__(self, filepath, target_sr):
        super().__init__()
        self.filepath = filepath
        self.target_sr = target_sr

    def run(self):
        temp_path = None
        try:
            # First read basic info to check length/sr
            info = sf.info(self.filepath)
            file_sr = info.samplerate
            channels = info.channels
            frames = info.frames

            # Determine if we need to stream/map
            # 1 minute of stereo float32 is ~20MB.
            # If file > 50MB, use memory mapping
            # 50MB ~= 50 * 1024*1024 / (4 * 2) = 6.5M samples

            # Use a conservative threshold to prefer memory mapping for safety
            LARGE_FILE_THRESHOLD_FRAMES = 5 * 1024 * 1024 # ~5 million frames

            is_large = frames > LARGE_FILE_THRESHOLD_FRAMES
            needs_resample = file_sr != self.target_sr

            msg_extra = ""
            final_data = None

            # Create a temporary file for the loaded/processed data
            # We use mkstemp to get a file path, then wrap in memmap
            fd, temp_path = tempfile.mkstemp(suffix='.dat')
            os.close(fd)
            TempFileRegistry.register(temp_path)

            if needs_resample:
                # We must resample.
                # To save memory, we decode to the temp file first (if large),
                # or just stream read -> resample -> write to output temp file.

                # Calculating output size
                gcd = math.gcd(int(file_sr), int(self.target_sr))
                up = int(self.target_sr // gcd)
                down = int(file_sr // gcd)

                # Calculate expected output frames
                # output_frames = ceil(input_frames * up / down)
                # But resample_poly might produce slightly different length depending on padding
                # Safe estimate:
                target_frames = int(math.ceil(frames * up / down))

                # Prepare output memmap
                shape = (target_frames, channels)
                # Ensure file size
                bytes_needed = target_frames * channels * 4 # float32
                with open(temp_path, 'wb') as f:
                    f.truncate(bytes_needed)

                output_mmap = np.memmap(temp_path, dtype='float32', mode='r+', shape=shape)

                # If we cannot implement artifact-free streaming resampling easily,
                # we have two choices:
                # 1. Load full input (if fits), resample to mmap (saves output RAM).
                # 2. Use a "good enough" blocked resampling (might have minor artifacts).
                #
                # Given the user wants "Safety" for large files, avoiding OOM is priority.
                # If we map the INPUT file (decoded), we save input RAM.
                # If we map the OUTPUT file, we save output RAM.
                #
                # Let's try to map the INPUT first.

                # Input Temp File
                fd_in, temp_in_path = tempfile.mkstemp(suffix='.dat')
                os.close(fd_in)
                try:
                    # Decode input to temp file
                    # We can use sf.read with blocks to avoid loading all at once
                    # Or sf.read directly to a memmap if it fits disk.

                    # Prepare input memmap
                    in_shape = (frames, channels)
                    in_bytes = frames * channels * 4
                    with open(temp_in_path, 'wb') as f:
                        f.truncate(in_bytes)

                    input_mmap = np.memmap(temp_in_path, dtype='float32', mode='r+', shape=in_shape)

                    # Read into input_mmap
                    # soundfile.read can write to array
                    sf.read(self.filepath, out=input_mmap, always_2d=True)
                    input_mmap.flush()

                    # Now resample from input_mmap to output_mmap?
                    # AudioCalc.resample returns a new array.
                    # We can't make it write to output_mmap.
                    # BUT, since input is on disk (mmap), we only pay RAM for output array if we use AudioCalc.resample.
                    # If output array is huge, we still OOM.

                    # If we use AudioCalc.resample(input_mmap, ...), it reads from disk.
                    # The result is in RAM.
                    # If result fits in RAM, we are good.
                    # If result doesn't fit, we crash.

                    # If we want to support HUGE files, we MUST stream resampling.
                    # But since we struggled with artifact-free streaming in POC,
                    # let's assume "Performance Improvement" here means "Avoiding double RAM usage".
                    # By mapping the input, we reduce peak RAM by size(Input).
                    # This allows processing files ~2x larger than before.

                    # Can we write result to output_mmap?
                    # No, unless we modify AudioCalc or use chunks.

                    # COMPROMISE:
                    # Load input to mmap (safe input).
                    # Resample to RAM (standard).
                    # Save RAM to output mmap (fast serialization).
                    # Return output mmap.

                    # Wait, if we resample to RAM, we allocate it.
                    # Then we copy to mmap.
                    # The peak is size(Output).
                    # Previous peak was size(Input) + size(Output).
                    # So we save size(Input). That is a significant win.

                    data_resampled = AudioCalc.resample(input_mmap, file_sr, self.target_sr)

                    # Write to the final output mmap
                    # Actually if data_resampled is already in RAM, we can just use it?
                    # The user wants "Streaming or memory mapping is safer".
                    # If we keep it in RAM, we are limited by RAM.
                    # If we write to mmap and delete RAM array, we free RAM.
                    # This allows the app to stay light after loading.

                    output_mmap[:] = data_resampled[:]
                    output_mmap.flush()
                    del data_resampled

                    msg_extra = f" (Resampled from {file_sr}Hz)"

                finally:
                    if os.path.exists(temp_in_path):
                        os.remove(temp_in_path)

            else:
                # No resampling needed.
                # Just decode to memmap.

                # Prepare memmap
                shape = (frames, channels)
                bytes_needed = frames * channels * 4
                with open(temp_path, 'wb') as f:
                    f.truncate(bytes_needed)

                output_mmap = np.memmap(temp_path, dtype='float32', mode='r+', shape=shape)

                # Stream read to mmap
                # sf.read directly to mmap
                sf.read(self.filepath, out=output_mmap, always_2d=True)
                output_mmap.flush()

            # Switch output_mmap to read-only mode for safety?
            # Creating a new memmap view is cheap
            final_data = np.memmap(temp_path, dtype='float32', mode='r', shape=output_mmap.shape)

            # Explicitly close the previous write-mode mmap
            del output_mmap

            result_msg = f"Loaded: {os.path.basename(self.filepath)} ({self.target_sr}Hz{msg_extra}, {final_data.shape[1]}ch, {len(final_data)/self.target_sr:.2f}s)"

            # Pass temp_path so receiver can own it
            self.finished.emit(True, final_data, result_msg, temp_path)

        except Exception as e:
            # Cleanup on failure
            if temp_path:
                TempFileRegistry.unregister(temp_path)
            self.finished.emit(False, None, str(e), None)


class RecorderPlayer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

        # State
        self.is_playing = False
        self.is_recording = False
        self.loop_playback = False
        self.playback_gain_db = 0.0

        # Buffers
        self.playback_buffer = None # numpy array (samples, channels) or memmap
        self.playback_pos = 0
        self.record_buffer = [] # List of numpy arrays
        self.recorded_samples = 0

        # Keep track of backing file for playback buffer
        self.playback_file_path = None

        # Settings
        self.input_mode = 'Stereo' # Stereo, Left, Right
        self.output_mode = 'Stereo' # Stereo, Left, Right, Mono

        self.callback_id = None
        self.widget = None

    @property
    def name(self) -> str:
        return "Recorder & Player"

    @property
    def description(self) -> str:
        return "Record and play audio files (WAV, MP3, FLAC, etc.)"

    def cleanup(self):
        # Called when module is destroyed or app closing (if hooked up)
        self.cleanup_playback_file()

    def cleanup_playback_file(self):
        if self.playback_buffer is not None:
            # Try to force release of memmap
            del self.playback_buffer
            self.playback_buffer = None

        if self.playback_file_path:
            TempFileRegistry.unregister(self.playback_file_path)
            self.playback_file_path = None

    def run(self, args):
        pass

    def get_widget(self):
        if self.widget is None:
            self.widget = RecorderPlayerWidget(self)
        return self.widget

    def set_playback_data(self, data, file_path=None):
        self.stop_playback()
        self.cleanup_playback_file()

        self.playback_buffer = data
        self.playback_file_path = file_path
        self.playback_pos = 0

    # Deprecated synchronous load
    def load_file(self, filepath):
        # Forward to async logic if possible?
        # But for backward compat, we keep simple logic but maybe add basic optimization?
        # Leaving as is for now to avoid breaking synchronous callers if any,
        # but User works with UI which uses Worker.
        try:
            data, file_sr = sf.read(filepath, always_2d=True)
            engine_sr = self.audio_engine.sample_rate

            msg_extra = ""

            # Resample if needed
            if file_sr != engine_sr:
                print(f"Resampling {os.path.basename(filepath)}: {file_sr}Hz -> {engine_sr}Hz")
                data = AudioCalc.resample(data, file_sr, engine_sr)
                msg_extra = f" (Resampled from {file_sr}Hz)"

            self.set_playback_data(data)
            return True, f"Loaded: {os.path.basename(filepath)} ({engine_sr}Hz{msg_extra}, {data.shape[1]}ch, {len(data)/engine_sr:.2f}s)"
        except Exception as e:
            return False, str(e)

    def save_recording(self, filepath, format=None, subtype=None):
        if not self.record_buffer:
            return False, "No recording data"

        try:
            data = np.concatenate(self.record_buffer, axis=0)
            sf.write(filepath, data, self.audio_engine.sample_rate, format=format, subtype=subtype)
            return True, f"Saved: {filepath}"
        except Exception as e:
            return False, str(e)

    def start_playback(self):
        if self.playback_buffer is None:
            return
        self.is_playing = True
        self._ensure_callback()

    def stop_playback(self):
        self.is_playing = False
        self._check_stop_callback()

    def start_recording(self):
        self.record_buffer = []
        self.recorded_samples = 0
        self.is_recording = True
        self._ensure_callback()

    def stop_recording(self):
        self.is_recording = False
        self._check_stop_callback()

    def _ensure_callback(self):
        if self.callback_id is None:
            self.callback_id = self.audio_engine.register_callback(self.audio_callback)

    def _check_stop_callback(self):
        if not self.is_playing and not self.is_recording:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def audio_callback(self, indata, outdata, frames, time_info, status):
        # Recording
        if self.is_recording:
            # Select channels based on input_mode
            if self.input_mode == 'Stereo':
                rec_data = indata.copy()
            elif self.input_mode == 'Left':
                rec_data = indata[:, 0:1] # Keep 2D
            elif self.input_mode == 'Right':
                if indata.shape[1] > 1:
                    rec_data = indata[:, 1:2]
                else:
                    rec_data = np.zeros((frames, 1), dtype=indata.dtype)

            self.record_buffer.append(rec_data)
            self.recorded_samples += frames

        # Playback
        if self.is_playing and self.playback_buffer is not None:
            pb_len = len(self.playback_buffer)
            current_idx = 0

            while current_idx < frames:
                remaining = frames - current_idx
                available = pb_len - self.playback_pos

                if available <= 0:
                    if self.loop_playback:
                        self.playback_pos = 0
                        available = pb_len
                    else:
                        self.is_playing = False
                        outdata[current_idx:] = 0
                        break

                to_copy = min(remaining, available)

                # Get chunk from buffer
                # If memmap, this reads from disk
                chunk = self.playback_buffer[self.playback_pos : self.playback_pos + to_copy]

                # Apply digital gain/attenuation in linear domain
                if self.playback_gain_db != 0.0:
                    gain = 10 ** (self.playback_gain_db / 20.0)
                    chunk = chunk * gain

                # Target slice in outdata
                out_slice = outdata[current_idx : current_idx + to_copy]

                file_ch = chunk.shape[1]
                out_ch = out_slice.shape[1]

                if self.output_mode == 'Stereo':
                    if file_ch == 1:
                        out_slice[:, 0] = chunk[:, 0]
                        if out_ch > 1: out_slice[:, 1] = chunk[:, 0]
                    else:
                        limit = min(file_ch, out_ch)
                        out_slice[:, :limit] = chunk[:, :limit]
                elif self.output_mode == 'Left':
                    out_slice[:, 0] = chunk[:, 0]
                    if out_ch > 1: out_slice[:, 1] = 0
                elif self.output_mode == 'Right':
                    if out_ch > 1:
                        out_slice[:, 1] = chunk[:, 0] if file_ch == 1 else chunk[:, 1] if file_ch > 1 else 0
                        out_slice[:, 0] = 0
                elif self.output_mode == 'Mono':
                    # Mix down to mono and send to all outputs
                    if file_ch > 1:
                        mono = np.mean(chunk, axis=1)
                    else:
                        mono = chunk[:, 0]

                    out_slice[:, 0] = mono
                    if out_ch > 1: out_slice[:, 1] = mono

                self.playback_pos += to_copy
                current_idx += to_copy

        else:
            outdata.fill(0)

class RecorderPlayerWidget(QWidget):
    def __init__(self, module: RecorderPlayer):
        super().__init__()
        self.module = module
        self.init_ui()

        self.load_worker = None
        self.progress_dialog = None

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

        # Progress
        self.pb_progress = QProgressBar()
        self.pb_progress.setTextVisible(True)
        pb_layout.addWidget(self.pb_progress)

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

        rec_ctrl_layout.addWidget(self.rec_btn)
        rec_ctrl_layout.addWidget(self.save_btn)
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

    def on_load(self):
        fname, _ = QFileDialog.getOpenFileName(self, tr("Open Audio File"), "", tr("Audio Files (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)"))
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
                    tr("The file sample rate ({0} Hz) differs from the engine rate ({1} Hz).\n"
                    "Resampling is required to play correctly.\n\n"
                    "Do you want to proceed? (This may take a moment for large files)").format(file_sr, engine_sr),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
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

    def on_load_finished(self, success, data, msg, temp_path):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        if success:
            self.module.set_playback_data(data, temp_path)
            self.file_label.setText(msg)
            self.pb_progress.setValue(0)
        else:
            if msg != "Cancelled": # Don't show error if user cancelled
                QMessageBox.critical(self, tr("Error"), tr("Failed to load file:\n{0}").format(msg))

        self.load_worker = None

    def on_load_cancel(self):
        if self.load_worker and self.load_worker.isRunning():
            self.load_worker.terminate() # Terminate is harsh but effective for simple worker
            self.load_worker.wait()
            self.load_worker = None

    def on_play_toggle(self):
        if self.module.is_playing:
            self.module.stop_playback()
        else:
            self.module.start_playback()

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
        else:
            self.module.stop_recording()
            self.rec_btn.setText(tr("Record"))
            self.rec_btn.setStyleSheet("")
            self.save_btn.setEnabled(True)

    def on_save(self):
        fname, selected_filter = QFileDialog.getSaveFileName(self, tr("Save Recording"), "recording.wav", tr("WAV (*.wav);;FLAC (*.flac);;OGG (*.ogg)"))
        if fname:
            # Determine format/subtype if needed, or let soundfile guess from extension
            success, msg = self.module.save_recording(fname)
            if success:
                QMessageBox.information(self, tr("Success"), msg)
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to save:\n{0}").format(msg))

    def on_in_mode_changed(self, text):
        self.module.input_mode = self.in_mode_combo.currentData()

    def update_ui(self):
        # Update Playback UI
        if self.module.is_playing:
            self.play_btn.setText(tr("Stop"))
            if self.module.playback_buffer is not None:
                total = len(self.module.playback_buffer)
                if total > 0:
                    progress = int(100 * self.module.playback_pos / total)
                    self.pb_progress.setValue(progress)
        else:
            self.play_btn.setText(tr("Play"))

        # Update Recording UI
        if self.module.is_recording:
            duration = self.module.recorded_samples / self.module.audio_engine.sample_rate
            self.rec_info_label.setText(tr("Recorded: {0:.2f}s").format(duration))
        elif self.module.recorded_samples > 0:
            duration = self.module.recorded_samples / self.module.audio_engine.sample_rate
            self.rec_info_label.setText(tr("Recorded: {0:.2f}s (Stopped)").format(duration))

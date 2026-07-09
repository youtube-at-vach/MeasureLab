import logging
import os
import json
import numpy as np
import soundfile as sf
import pyqtgraph as pg

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QGroupBox,
    QFormLayout,
    QDoubleSpinBox,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QProgressBar,
    QComboBox,
    QScrollArea,
    QFrame,
    QApplication,
)

from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.predistortion_applicator import PredistortionApplicator
from src.core.hammerstein_model import get_active_model, has_active_model

logger = logging.getLogger(__name__)


class OfflinePredistortionWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)

    def __init__(self, input_path: str, output_path: str, applicator: PredistortionApplicator):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.applicator = applicator
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        infile = None
        try:
            info = sf.info(self.input_path)
            file_sr = info.samplerate
            model_sr = self.applicator.sample_rate

            # If sample rate differs, read entire file and resample
            resample_msg = ""
            if abs(file_sr - model_sr) > 1.0:
                raw_data, _ = sf.read(self.input_path, always_2d=True)
                # Resample logic using scipy.signal
                from src.core.analysis import AudioCalc

                data = AudioCalc.resample(raw_data, file_sr, int(model_sr))
                resample_msg = "\n" + tr(" (Resampled from {0} Hz to {1} Hz)").format(int(file_sr), int(model_sr))
                M, channels = data.shape

                def get_chunk(start, end):
                    return data[start:end, :]
            else:
                infile = sf.SoundFile(self.input_path, "r")
                M = infile.frames
                channels = infile.channels

                def get_chunk(start, end):
                    infile.seek(start)
                    return infile.read(end - start, always_2d=True)

            out_data = np.zeros((M, channels), dtype=np.float32)
            block_size = 65536
            num_blocks = (M + block_size - 1) // block_size

            # Reset applicator states before processing
            self.applicator.reset_states()

            for b_idx in range(num_blocks):
                if self.is_cancelled:
                    raise InterruptedError("Cancelled")

                start = b_idx * block_size
                end = min(start + block_size, M)
                chunk = get_chunk(start, end)

                # Process channel by channel
                for ch in range(channels):
                    out_data[start:end, ch] = self.applicator.apply_predistortion_block(chunk[:, ch])

                pct = int(((b_idx + 1) / num_blocks) * 100)
                self.progress.emit(pct)

            # Prevent digital clipping at output
            peak_out = np.max(np.abs(out_data))
            clipping_msg = ""
            if peak_out > 1.0:
                clipping_msg = "\n" + tr(
                    "Warning: Output signal peaks at {0:.2f} dBFS. Output was normalized to avoid digital clipping."
                ).format(20 * np.log10(peak_out))
                out_data = out_data / peak_out

            sf.write(
                self.output_path,
                out_data,
                int(model_sr),
                subtype="PCM_24" if info.subtype == "PCM_24" else "PCM_16",
            )

            self.finished.emit(
                True,
                tr("Successfully exported to {0}").format(os.path.basename(self.output_path))
                + resample_msg
                + clipping_msg,
            )

        except InterruptedError:
            self.finished.emit(False, tr("Cancelled"))
        except Exception as e:
            logger.exception("Offline predistortion processing failed")
            self.finished.emit(False, str(e))
        finally:
            if infile is not None:
                infile.close()


class PredistortionProcessor(MeasurementModule):
    def __init__(self, audio_engine):
        self.audio_engine = audio_engine
        self.applicator = PredistortionApplicator()
        self.widget = None

        # Real-time state
        self.is_playing = False
        self.callback_id = None
        self.input_file = None
        self.play_index = 0
        self.tone_phase = 0.0

        # UI parameters
        self.source_mode = "tone"  # "tone" or "file"
        self.tone_freq = 1000.0
        self.tone_amp = 0.5
        self.tone_type = "sine"  # "sine", "pink", "white"
        self.pink_gen = None

    @property
    def name(self) -> str:
        return "Predistortion Processor"

    @property
    def description(self) -> str:
        return tr("Real-time non-linear predistortion processor using inverse Hammerstein kernels.")

    def get_widget(self):
        self.widget = PredistortionProcessorWidget(self)
        return self.widget

    def start_realtime(self):
        if self.is_playing:
            return
        self.is_playing = True
        self.play_index = 0
        self.tone_phase = 0.0

        if self.tone_type == "pink":
            from src.core.generators import PinkNoise

            self.pink_gen = PinkNoise()

        # Initialize stream reader for file input
        self.audio_file_reader = None
        if self.source_mode == "file" and getattr(self, "audio_file_path", None):
            try:
                self.audio_file_reader = sf.SoundFile(self.audio_file_path, "r")
            except Exception as e:
                logger.error("Failed to open audio file for playback: %s", e)
                self.is_playing = False
                raise

        # Reset filter states
        self.applicator.reset_states()

        fs = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time, status):
            if not self.is_playing:
                outdata.fill(0)
                return

            try:
                out_ch_count = outdata.shape[1]
                block_in = np.zeros(frames, dtype=np.float32)

                # Generate or load input block
                if self.source_mode == "tone":
                    if self.tone_type == "sine":
                        t = (self.play_index + np.arange(frames)) / fs
                        block_in = self.tone_amp * np.sin(2.0 * np.pi * self.tone_freq * t + self.tone_phase)
                    elif self.tone_type == "pink" and self.pink_gen:
                        block_in = self.tone_amp * self.pink_gen.generate(frames)
                    elif self.tone_type == "white":
                        block_in = self.tone_amp * np.random.randn(frames).astype(np.float32)

                    self.play_index += frames
                else:
                    # File Playback
                    if self.audio_file_reader:
                        chunk = self.audio_file_reader.read(frames, always_2d=True)
                        if len(chunk) < frames:
                            # Loop back
                            self.audio_file_reader.seek(0)
                            extra = self.audio_file_reader.read(frames - len(chunk), always_2d=True)
                            chunk = np.vstack([chunk, extra])
                        # Mix down to mono for predistortion processing
                        block_in = np.mean(chunk, axis=1).astype(np.float32)
                    else:
                        block_in.fill(0)

                # Apply Predistortion (mono filter)
                block_out = self.applicator.apply_predistortion_block(block_in)

                # Output mapping to all active channels
                for ch in range(out_ch_count):
                    outdata[:, ch] = block_out

            except Exception as e:
                logger.error("Error in predistortion callback: %s", e)
                outdata.fill(0)

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_realtime(self):
        self.is_playing = False
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None
        if getattr(self, "audio_file_reader", None):
            self.audio_file_reader.close()
            self.audio_file_reader = None


class PredistortionProcessorWidget(QWidget):
    def __init__(self, module: PredistortionProcessor):
        super().__init__()
        self.module = module
        self.model_data = None
        self.worker = None

        self.init_ui()
        self.setAcceptDrops(True)
        self.set_controls_enabled(False)
        self.check_active_model()

    def minimumSizeHint(self) -> QSize:
        return QSize(1000, 600)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # LEFT SIDEBAR (Scrollable Container)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setFixedWidth(360)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(4, 4, 8, 4)
        left_layout.setSpacing(8)

        # Group 1: Model Source
        model_group = QGroupBox(tr("Model Source"))
        model_form = QVBoxLayout(model_group)
        model_form.setSpacing(6)

        self.btn_load_model = QPushButton(tr("Load Inverse Model JSON..."))
        self.btn_load_model.setStyleSheet("background-color: #4ba3e3; color: white; font-weight: bold; padding: 5px;")
        self.btn_load_model.clicked.connect(self.on_load_model)
        model_form.addWidget(self.btn_load_model)

        self.btn_load_active = QPushButton(tr("Load Active Model from Cache"))
        self.btn_load_active.clicked.connect(self.on_load_active)
        model_form.addWidget(self.btn_load_active)

        self.lbl_status = QLabel(tr("No Inverse Model Loaded"))
        self.lbl_status.setStyleSheet("font-weight: bold; color: #d9534f;")
        self.lbl_sr = QLabel("-- Hz")
        self.lbl_order = QLabel("--")
        self.lbl_direction = QLabel("--")

        info_layout = QFormLayout()
        info_layout.setSpacing(4)
        info_layout.addRow(tr("Status:"), self.lbl_status)
        info_layout.addRow(tr("Rate:"), self.lbl_sr)
        info_layout.addRow(tr("Model Order:"), self.lbl_order)
        info_layout.addRow(tr("Direction:"), self.lbl_direction)
        model_form.addLayout(info_layout)
        left_layout.addWidget(model_group)

        # Group 2: Input Settings
        input_group = QGroupBox(tr("Input & Simulation Control"))
        input_form = QFormLayout(input_group)
        input_form.setSpacing(6)

        self.combo_source = QComboBox()
        self.combo_source.addItem(tr("Tone Generator"), "tone")
        self.combo_source.addItem(tr("Audio File"), "file")
        self.combo_source.currentIndexChanged.connect(self.on_source_changed)
        input_form.addRow(tr("Input Source:"), self.combo_source)

        # Tone Config Panel
        self.tone_widget = QWidget()
        tone_layout = QFormLayout(self.tone_widget)
        tone_layout.setContentsMargins(0, 0, 0, 0)
        tone_layout.setSpacing(6)

        self.combo_tone_type = QComboBox()
        self.combo_tone_type.addItem(tr("Sine Wave"), "sine")
        self.combo_tone_type.addItem(tr("Pink Noise"), "pink")
        self.combo_tone_type.addItem(tr("White Noise"), "white")
        self.combo_tone_type.currentIndexChanged.connect(self.on_tone_type_changed)
        tone_layout.addRow(tr("Tone Type:"), self.combo_tone_type)

        self.spin_freq = QDoubleSpinBox()
        self.spin_freq.setRange(20.0, 20000.0)
        self.spin_freq.setValue(1000.0)
        self.spin_freq.setSuffix(" Hz")
        self.spin_freq.valueChanged.connect(self.on_param_changed)
        tone_layout.addRow(tr("Tone Frequency:"), self.spin_freq)

        self.spin_amp = QDoubleSpinBox()
        self.spin_amp.setRange(-100.0, 0.0)
        self.spin_amp.setValue(-6.0)
        self.spin_amp.setSuffix(" dBFS")
        self.spin_amp.valueChanged.connect(self.on_param_changed)
        tone_layout.addRow(tr("Tone Amplitude:"), self.spin_amp)

        input_form.addRow(self.tone_widget)

        # File Config Panel
        self.file_widget = QWidget()
        file_layout = QVBoxLayout(self.file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)

        self.btn_select_file = QPushButton(tr("Select Audio File..."))
        self.btn_select_file.clicked.connect(self.on_select_file)
        file_layout.addWidget(self.btn_select_file)

        self.lbl_file_path = QLabel(tr("No File Selected"))
        self.lbl_file_path.setWordWrap(True)
        file_layout.addWidget(self.lbl_file_path)

        input_form.addRow(self.file_widget)
        self.file_widget.setVisible(False)

        # Settings
        self.combo_os = QComboBox()
        self.combo_os.addItem(tr("None (Bypass OS)"), 1)
        self.combo_os.addItem(tr("2x Over-sampling"), 2)
        self.combo_os.addItem(tr("4x Over-sampling"), 4)
        self.combo_os.addItem(tr("8x Over-sampling"), 8)
        self.combo_os.setCurrentIndex(2)  # Default 4x
        self.combo_os.currentIndexChanged.connect(self.on_param_changed)
        input_form.addRow(tr("Over-sampling:"), self.combo_os)

        left_layout.addWidget(input_group)

        # Group 3: Simulation & Playback Buttons
        ctrl_group = QGroupBox(tr("Action Panel"))
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setSpacing(6)

        self.btn_run_sim = QPushButton(tr("Run Simulation"))
        self.btn_run_sim.setStyleSheet("background-color: #2ca02c; color: white; font-weight: bold; padding: 6px;")
        self.btn_run_sim.clicked.connect(self.on_run_simulation)
        ctrl_layout.addWidget(self.btn_run_sim)

        self.btn_play_rt = QPushButton(tr("Play (Real-time Preview)"))
        self.btn_play_rt.setCheckable(True)
        self.btn_play_rt.clicked.connect(self.on_toggle_realtime)
        ctrl_layout.addWidget(self.btn_play_rt)

        self.btn_export_file = QPushButton(tr("Process and Export File..."))
        self.btn_export_file.clicked.connect(self.on_export_file)
        ctrl_layout.addWidget(self.btn_export_file)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        ctrl_layout.addWidget(self.progress_bar)

        left_layout.addWidget(ctrl_group)
        left_layout.addStretch()

        left_scroll.setWidget(left_container)
        main_layout.addWidget(left_scroll)

        # RIGHT PLOTS TAB
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(380)

        # Tab 1: Time Domain Plot
        self.tab_time = QWidget()
        time_layout = QVBoxLayout(self.tab_time)
        time_layout.setContentsMargins(4, 4, 4, 4)
        self.plot_time = pg.PlotWidget(title=tr("Time Domain Waveform"))
        self.plot_time.setLabel("bottom", tr("Time"), units="ms")
        self.plot_time.setLabel("left", tr("Amplitude"))
        self.plot_time.showGrid(x=True, y=True)
        self.plot_time.addLegend(offset=(10, 10))
        time_layout.addWidget(self.plot_time)
        self.plot_tabs.addTab(self.tab_time, tr("Time Waveform"))

        # Tab 2: Spectrum Plot
        self.tab_spec = QWidget()
        spec_layout = QVBoxLayout(self.tab_spec)
        spec_layout.setContentsMargins(4, 4, 4, 4)
        self.plot_spec = pg.PlotWidget(title=tr("Frequency Spectrum"))
        self.plot_spec.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_spec.setLabel("left", tr("Amplitude"), units="dBFS")
        self.plot_spec.showGrid(x=True, y=True)
        self.plot_spec.addLegend(offset=(10, 10))
        spec_layout.addWidget(self.plot_spec)
        self.plot_tabs.addTab(self.tab_spec, tr("Frequency Spectrum"))

        main_layout.addWidget(self.plot_tabs, 2)

        # Theme styling
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())

        # Plot curves colors
        # Input: White/Gray, Compensated: Light Blue
        self.curves = {
            "in_time": self.plot_time.plot(pen="#aaaaaa", name=tr("Input (Linear)")),
            "comp_time": self.plot_time.plot(pen="#4fc3f7", name=tr("Compensated Output")),
            "in_spec": self.plot_spec.plot(pen="#aaaaaa", name=tr("Input (Linear)")),
            "comp_spec": self.plot_spec.plot(pen="#4fc3f7", name=tr("Compensated Output")),
        }

    def set_controls_enabled(self, enabled):
        self.combo_source.setEnabled(enabled)
        self.combo_tone_type.setEnabled(enabled)
        self.spin_freq.setEnabled(enabled)
        self.spin_amp.setEnabled(enabled)
        self.btn_select_file.setEnabled(enabled)
        self.combo_os.setEnabled(enabled)
        self.btn_run_sim.setEnabled(enabled)
        self.btn_play_rt.setEnabled(enabled)
        self.btn_export_file.setEnabled(enabled and self.module.source_mode == "file")

    def apply_theme(self, theme=None):
        if not hasattr(self, "plot_time") or not hasattr(self, "plot_spec"):
            return

        theme_name = theme
        if not theme_name and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_current_theme()

        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        is_dark = theme_name == "dark"

        bg_color = "#121212" if is_dark else "#ffffff"
        text_color = "#ffffff" if is_dark else "#000000"

        self.plot_time.setBackground(bg_color)
        self.plot_spec.setBackground(bg_color)
        self.plot_time.getAxis("bottom").setPen(text_color)
        self.plot_time.getAxis("left").setPen(text_color)
        self.plot_spec.getAxis("bottom").setPen(text_color)
        self.plot_spec.getAxis("left").setPen(text_color)

    def check_active_model(self):
        """Checks if there's an active model in cache on widget initialization."""
        if has_active_model():
            self.on_load_active()

    def on_load_active(self):
        model = get_active_model()
        if model:
            try:
                self.module.applicator.load_model(model)
                self.model_data = model
                self.update_model_info()
                self.set_controls_enabled(True)
            except Exception as e:
                QMessageBox.critical(self, tr("Error"), tr("Failed to load model from cache:\n{0}").format(e))

    def on_load_model(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Load Inverse Model JSON"), "", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                model = json.load(f)
            self.module.applicator.load_model(model)
            self.model_data = model
            self.update_model_info()
            self.set_controls_enabled(True)
        except Exception as e:
            QMessageBox.critical(self, tr("Error"), tr("Failed to load model file:\n{0}").format(e))

    def update_model_info(self):
        if not self.model_data:
            return
        meta = self.model_data.get("metadata", {})
        self.lbl_status.setText(tr("Model Loaded Successfully"))
        self.lbl_status.setStyleSheet("font-weight: bold; color: #5cb85c;")
        self.lbl_sr.setText(f"{meta.get('sample_rate', 48000)} Hz")
        self.lbl_order.setText(f"{self.module.applicator.P} ({tr('Max Harmonic')})")
        dir_val = meta.get("model_direction", "forward")
        self.lbl_direction.setText(tr("Inverse") if dir_val == "inverse" else tr("Forward"))

    def on_source_changed(self, idx):
        source = self.combo_source.itemData(idx)
        self.module.source_mode = source
        self.tone_widget.setVisible(source == "tone")
        self.file_widget.setVisible(source == "file")
        self.btn_export_file.setEnabled(source == "file" and getattr(self.module, "audio_file_path", None) is not None)
        self.btn_play_rt.setEnabled(source == "tone" or getattr(self.module, "audio_file_path", None) is not None)

    def on_tone_type_changed(self, idx):
        self.module.tone_type = self.combo_tone_type.itemData(idx)
        self.spin_freq.setEnabled(self.module.tone_type == "sine")

    def on_param_changed(self):
        # Update settings to core module
        self.module.tone_freq = self.spin_freq.value()
        self.module.tone_amp = 10 ** (self.spin_amp.value() / 20.0)
        self.module.applicator.os_factor = self.combo_os.currentData()

    def on_select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Select Audio File"), "", "Audio Files (*.wav *.flac *.ogg)")
        if not path:
            return
        self.module.audio_file_path = path
        self.lbl_file_path.setText(os.path.basename(path))
        self.btn_export_file.setEnabled(True)
        self.btn_play_rt.setEnabled(True)

    def on_run_simulation(self):
        if not self.model_data:
            return

        self.on_param_changed()

        fs = self.module.applicator.sample_rate
        # Generate simulation input buffer (0.1 seconds base size)
        sim_samples = int(0.1 * fs)

        # Align to the nearest bin center frequency if it's a sine wave
        is_sine = (self.module.tone_type == "sine")
        if is_sine:
            df = fs / sim_samples
            k = max(1, round(self.module.tone_freq / df))
            sim_freq = k * df
        else:
            sim_freq = self.module.tone_freq

        # Generate a longer buffer (2x) to let filter transients settle
        total_samples = 2 * sim_samples
        t_full = np.arange(total_samples) / fs

        block_in_full = np.zeros(total_samples, dtype=np.float32)
        if is_sine:
            block_in_full = self.module.tone_amp * np.sin(2.0 * np.pi * sim_freq * t_full)
        elif self.module.tone_type == "pink":
            from src.core.generators import PinkNoise
            pink = PinkNoise()
            block_in_full = self.module.tone_amp * pink.generate(total_samples)
        elif self.module.tone_type == "white":
            block_in_full = self.module.tone_amp * np.random.randn(total_samples).astype(np.float32)

        # Run simulation over the full duration
        comp_sig_full, _, _ = self.module.applicator.run_simulation(block_in_full)

        # Extract the steady-state portion (the second half)
        t = np.arange(sim_samples) / fs
        block_in = block_in_full[sim_samples:]
        comp_sig = comp_sig_full[sim_samples:]

        # Plot Time Domain
        ms = t * 1000.0

        # Calculate pre-delay in milliseconds to adjust initial plot range
        delay_samples = 0
        if self.module.applicator.P > 0 and len(self.module.applicator.h_kernels) > 0:
            h1 = self.module.applicator.h_kernels[0]
            delay_samples = int(np.argmax(np.abs(h1)))
        delay_ms = (delay_samples / fs) * 1000.0

        # Set plot data (expose full 100ms steady-state so user can scroll/pan freely)
        self.curves["in_time"].setData(ms, block_in)
        self.curves["comp_time"].setData(ms, comp_sig)

        # Plot FFT Spectrum
        def get_fft(sig):
            n = len(sig)
            if is_sine:
                # Use rectangular window (no window) to achieve zero spectral leakage
                # because the frequency is aligned to a bin center.
                sig_w = sig
                fft_vals = np.fft.rfft(sig_w)
                mags = np.abs(fft_vals) / (n / 2.0)
                mags_db = 20 * np.log10(np.maximum(mags, 1e-10))
            else:
                # Hanning window to prevent leakage for non-periodic signals (e.g. noise)
                win = np.hanning(n)
                sig_w = sig * win
                fft_vals = np.fft.rfft(sig_w)
                mags = np.abs(fft_vals) / (n / 2.0)
                # Coherent gain compensation for Hanning
                mags *= 2.0
                mags_db = 20 * np.log10(np.maximum(mags, 1e-10))
            freqs = np.fft.rfftfreq(n, 1.0 / fs)
            return freqs, mags_db

        f_in, db_in = get_fft(block_in)
        f_comp, db_comp = get_fft(comp_sig)

        # Apply slight smoothing for visualization (same as in modeler)
        self.curves["in_spec"].setData(f_in, db_in)
        self.curves["comp_spec"].setData(f_comp, db_comp)

        # Auto range plots
        self.plot_time.autoRange()
        self.plot_spec.autoRange()

        # Focus time domain plot starting from twice the pre-delay for 10ms
        self.plot_time.setXRange(delay_ms * 2.0, delay_ms * 2.0 + 10.0, padding=0.0)

        self.plot_spec.setXRange(20, min(fs / 2, 22000.0))
        self.plot_spec.setYRange(-120, 10)

    def on_toggle_realtime(self, checked):
        if checked:
            self.on_param_changed()
            try:
                self.module.start_realtime()
                self.btn_play_rt.setText(tr("Stop (Playback Active)"))
                self.btn_play_rt.setStyleSheet("background-color: #d9534f; color: white;")
            except Exception as e:
                self.btn_play_rt.setChecked(False)
                QMessageBox.critical(self, tr("Error"), tr("Failed to start audio playback:\n{0}").format(e))
        else:
            self.module.stop_realtime()
            self.btn_play_rt.setText(tr("Play (Real-time Preview)"))
            self.btn_play_rt.setStyleSheet("")

    def on_export_file(self):
        if not getattr(self.module, "audio_file_path", None):
            return

        self.on_param_changed()

        out_path, _ = QFileDialog.getSaveFileName(self, tr("Save Predistorted Audio File"), "", "WAV Files (*.wav)")
        if not out_path:
            return

        self.btn_export_file.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = OfflinePredistortionWorker(
            input_path=self.module.audio_file_path,
            output_path=out_path,
            applicator=self.module.applicator,
        )
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self.on_export_finished)
        self.worker.start()

    def on_export_finished(self, success, message):
        self.btn_export_file.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.worker = None

        if success:
            QMessageBox.information(self, tr("Export Finished"), message)
        else:
            QMessageBox.critical(self, tr("Export Failed"), message)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            ext = os.path.splitext(path)[1].lower()
            if ext in {".json"}:
                # Load model
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        model = json.load(f)
                    self.module.applicator.load_model(model)
                    self.model_data = model
                    self.update_model_info()
                    self.set_controls_enabled(True)
                except Exception as e:
                    QMessageBox.critical(self, tr("Error"), tr("Failed to load model file:\n{0}").format(e))
            elif ext in {".wav", ".flac", ".ogg"}:
                # Select file
                self.module.audio_file_path = path
                self.lbl_file_path.setText(os.path.basename(path))
                self.btn_export_file.setEnabled(True)
                self.btn_play_rt.setEnabled(True)
                self.combo_source.setCurrentIndex(1)  # switch to file source

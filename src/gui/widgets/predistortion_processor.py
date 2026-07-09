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



class PreviewBufferWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, np.ndarray, str)

    def __init__(
        self,
        applicator: PredistortionApplicator,
        source_mode: str,
        tone_type: str,
        tone_freq: float,
        tone_amp: float,
        audio_file_path: str,
        sample_rate: float,
        sss_start_freq: float = 20.0,
        sss_end_freq: float = 20000.0,
        sss_duration: float = 20.0,
        sss_amp: float = 0.5,
    ):
        super().__init__()
        self.applicator = applicator
        self.source_mode = source_mode
        self.tone_type = tone_type
        self.tone_freq = tone_freq
        self.tone_amp = tone_amp
        self.audio_file_path = audio_file_path
        self.sample_rate = sample_rate
        self.sss_start_freq = sss_start_freq
        self.sss_end_freq = sss_end_freq
        self.sss_duration = sss_duration
        self.sss_amp = sss_amp
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def run(self):
        try:
            fs = self.sample_rate
            duration = 10.0  # 10 seconds preview limit

            # Generate or load input block
            if self.source_mode == "tone":
                total_samples = int(duration * fs)
                if self.tone_type == "sine":
                    t = np.arange(total_samples) / fs
                    block_in = self.tone_amp * np.sin(2.0 * np.pi * self.tone_freq * t)
                elif self.tone_type == "pink":
                    from src.core.generators import PinkNoise
                    pink = PinkNoise()
                    block_in = self.tone_amp * pink.generate(total_samples)
                elif self.tone_type == "white":
                    block_in = self.tone_amp * np.random.randn(total_samples).astype(np.float32)
                else:
                    block_in = np.zeros(total_samples, dtype=np.float32)
            elif self.source_mode == "sss":
                from src.core.realtime_sss_core import RealtimeSSSEngine
                engine = RealtimeSSSEngine(
                    sample_rate=fs,
                    sweep_duration=self.sss_duration,
                    start_freq=self.sss_start_freq,
                    end_freq=self.sss_end_freq,
                    output_amplitude=self.sss_amp,
                )
                engine.prepare_sweep()
                block_in = engine.out_sig
                if block_in is None:
                    raise ValueError(tr("Failed to generate SSS Sweep signal."))
            else:
                # File Playback (up to 10 seconds)
                if not self.audio_file_path or not os.path.exists(self.audio_file_path):
                    raise ValueError(tr("Audio file not found."))

                info = sf.info(self.audio_file_path)
                file_sr = info.samplerate
                frames_to_read = min(int(duration * file_sr), info.frames)

                with sf.SoundFile(self.audio_file_path, "r") as f:
                    chunk = f.read(frames_to_read, always_2d=True)

                # Resample if needed
                if abs(file_sr - fs) > 1.0:
                    from src.core.analysis import AudioCalc
                    chunk = AudioCalc.resample(chunk, file_sr, int(fs))

                block_in = np.mean(chunk, axis=1).astype(np.float32)

            if self.is_cancelled:
                raise InterruptedError("Cancelled")

            # Apply predistortion
            self.applicator.reset_states()

            M = len(block_in)
            block_size = 65536
            num_blocks = (M + block_size - 1) // block_size
            block_out = np.zeros(M, dtype=np.float32)

            for b_idx in range(num_blocks):
                if self.is_cancelled:
                    raise InterruptedError("Cancelled")

                start = b_idx * block_size
                end = min(start + block_size, M)
                chunk_in = block_in[start:end]

                # Apply predistortion
                chunk_out = self.applicator.apply_predistortion_block(chunk_in)
                block_out[start:end] = chunk_out

                pct = int(((b_idx + 1) / num_blocks) * 100)
                self.progress.emit(pct)

            # Prevent digital clipping at output
            peak_out = np.max(np.abs(block_out))
            if peak_out > 1.0:
                block_out = block_out / peak_out

            self.finished.emit(True, block_out, "")
        except InterruptedError:
            self.finished.emit(False, np.array([], dtype=np.float32), tr("Cancelled"))
        except Exception as e:
            logger.exception("Preview buffer generation failed")
            self.finished.emit(False, np.array([], dtype=np.float32), str(e))


class PredistortionProcessor(MeasurementModule):
    def __init__(self, audio_engine):
        self.audio_engine = audio_engine
        self.applicator = PredistortionApplicator()
        self.widget = None

        # Real-time state
        self.is_playing = False
        self.callback_id = None
        self.play_index = 0
        self.preview_buffer = None
        self.on_playback_finished_callback = None

        # UI parameters
        self.source_mode = "tone"  # "tone", "file", "sss"
        self.tone_freq = 1000.0
        self.tone_amp = 0.5
        self.tone_type = "sine"  # "sine", "pink", "white"

        # SSS parameters
        self.sss_start_freq = 20.0
        self.sss_end_freq = 20000.0
        self.sss_duration = 20.0
        self.sss_amp = 0.5

    @property
    def name(self) -> str:
        return "Predistortion Processor"

    @property
    def description(self) -> str:
        return tr("Real-time non-linear predistortion processor using inverse Hammerstein kernels.")

    def get_widget(self):
        self.widget = PredistortionProcessorWidget(self)
        return self.widget

    def start_realtime(self, preview_buffer: np.ndarray):
        if self.is_playing:
            return
        self.is_playing = True
        self.play_index = 0
        self.preview_buffer = preview_buffer

        total_frames = len(self.preview_buffer)

        def callback(indata, outdata, frames, time, status):
            if not self.is_playing:
                outdata.fill(0)
                return

            try:
                out_ch_count = outdata.shape[1]
                start = self.play_index
                end = start + frames

                if start >= total_frames:
                    outdata.fill(0)
                    self.is_playing = False
                    if self.on_playback_finished_callback:
                        self.on_playback_finished_callback()
                    return

                if end > total_frames:
                    chunk = self.preview_buffer[start:total_frames]
                    block_out = np.zeros(frames, dtype=np.float32)
                    block_out[:len(chunk)] = chunk
                    self.play_index = total_frames
                else:
                    block_out = self.preview_buffer[start:end]
                    self.play_index = end

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
        self.preview_buffer = None


class PredistortionProcessorWidget(QWidget):
    playback_finished = pyqtSignal()

    def __init__(self, module: PredistortionProcessor):
        super().__init__()
        self.module = module
        self.model_data = None
        self.worker = None
        self.preview_worker = None

        self.init_ui()
        self.playback_finished.connect(self.on_playback_finished)
        self.module.on_playback_finished_callback = lambda: self.playback_finished.emit()

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
        self.combo_source.addItem(tr("SSS Sweep"), "sss")
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

        # SSS Config Panel
        self.sss_widget = QWidget()
        sss_layout = QFormLayout(self.sss_widget)
        sss_layout.setContentsMargins(0, 0, 0, 0)
        sss_layout.setSpacing(6)

        self.spin_sss_start_freq = QDoubleSpinBox()
        self.spin_sss_start_freq.setRange(20.0, 20000.0)
        self.spin_sss_start_freq.setValue(20.0)
        self.spin_sss_start_freq.setSuffix(" Hz")
        self.spin_sss_start_freq.valueChanged.connect(self.on_param_changed)
        sss_layout.addRow(tr("Start Freq:"), self.spin_sss_start_freq)

        self.spin_sss_end_freq = QDoubleSpinBox()
        self.spin_sss_end_freq.setRange(20.0, 20000.0)
        self.spin_sss_end_freq.setValue(20000.0)
        self.spin_sss_end_freq.setSuffix(" Hz")
        self.spin_sss_end_freq.valueChanged.connect(self.on_param_changed)
        sss_layout.addRow(tr("End Freq:"), self.spin_sss_end_freq)

        self.spin_sss_duration = QDoubleSpinBox()
        self.spin_sss_duration.setRange(2.0, 60.0)
        self.spin_sss_duration.setValue(20.0)
        self.spin_sss_duration.setSuffix(" s")
        self.spin_sss_duration.valueChanged.connect(self.on_param_changed)
        sss_layout.addRow(tr("Duration:"), self.spin_sss_duration)

        self.spin_sss_amp = QDoubleSpinBox()
        self.spin_sss_amp.setRange(-100.0, 0.0)
        self.spin_sss_amp.setValue(-6.0)
        self.spin_sss_amp.setSuffix(" dBFS")
        self.spin_sss_amp.valueChanged.connect(self.on_param_changed)
        sss_layout.addRow(tr("Amplitude:"), self.spin_sss_amp)

        input_form.addRow(self.sss_widget)
        self.sss_widget.setVisible(False)

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

        # Tab 3: Parameter Details
        self.tab_params = QWidget()
        params_layout = QHBoxLayout(self.tab_params)
        params_layout.setContentsMargins(4, 4, 4, 4)
        params_layout.setSpacing(8)

        # Left control panel (Scrollable)
        params_left_scroll = QScrollArea()
        params_left_scroll.setWidgetResizable(True)
        params_left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        params_left_scroll.setFixedWidth(280)

        params_left_container = QWidget()
        params_left_layout = QVBoxLayout(params_left_container)
        params_left_layout.setContentsMargins(0, 0, 4, 0)
        params_left_layout.setSpacing(8)

        # Group A: Kernel Selection & Metrics
        kernel_metrics_group = QGroupBox(tr("Kernel Metrics"))
        kernel_metrics_form = QFormLayout(kernel_metrics_group)
        kernel_metrics_form.setSpacing(6)

        self.combo_kernel_select = QComboBox()
        self.combo_kernel_select.currentIndexChanged.connect(self.on_kernel_selection_changed)
        kernel_metrics_form.addRow(tr("Select Kernel:"), self.combo_kernel_select)

        self.lbl_kernel_taps = QLabel("--")
        self.lbl_kernel_peak = QLabel("--")
        self.lbl_kernel_delay = QLabel("--")
        self.lbl_kernel_rms = QLabel("--")

        kernel_metrics_form.addRow(tr("Taps (Length):"), self.lbl_kernel_taps)
        kernel_metrics_form.addRow(tr("Peak Value:"), self.lbl_kernel_peak)
        kernel_metrics_form.addRow(tr("Peak Delay:"), self.lbl_kernel_delay)
        kernel_metrics_form.addRow(tr("RMS Energy:"), self.lbl_kernel_rms)

        params_left_layout.addWidget(kernel_metrics_group)

        # Group B: Model Metadata (Detailed)
        metadata_group = QGroupBox(tr("Model Details"))
        metadata_form = QFormLayout(metadata_group)
        metadata_form.setSpacing(6)

        self.lbl_meta_direction = QLabel("--")
        self.lbl_meta_sr = QLabel("-- Hz")
        self.lbl_meta_order = QLabel("--")

        metadata_form.addRow(tr("Direction:"), self.lbl_meta_direction)
        metadata_form.addRow(tr("Sample Rate:"), self.lbl_meta_sr)
        metadata_form.addRow(tr("Max Order:"), self.lbl_meta_order)

        params_left_layout.addWidget(metadata_group)
        params_left_layout.addStretch()

        params_left_scroll.setWidget(params_left_container)
        params_layout.addWidget(params_left_scroll)

        # Right plots
        plots_right_container = QWidget()
        plots_right_layout = QVBoxLayout(plots_right_container)
        plots_right_layout.setContentsMargins(0, 0, 0, 0)
        plots_right_layout.setSpacing(6)

        self.plot_kernel_time = pg.PlotWidget(title=tr("Kernel Impulse Response (Time Domain)"))
        self.plot_kernel_time.setLabel("bottom", tr("Time"), units="ms")
        self.plot_kernel_time.setLabel("left", tr("Amplitude"))
        self.plot_kernel_time.showGrid(x=True, y=True)

        self.plot_kernel_freq = pg.PlotWidget(title=tr("Kernel Magnitude Response (Frequency Domain)"))
        self.plot_kernel_freq.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_kernel_freq.setLabel("left", tr("Magnitude"), units="dB")
        self.plot_kernel_freq.showGrid(x=True, y=True)

        plots_right_layout.addWidget(self.plot_kernel_time)
        plots_right_layout.addWidget(self.plot_kernel_freq)

        params_layout.addWidget(plots_right_container, 2)
        self.plot_tabs.addTab(self.tab_params, tr("Parameter Details"))

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
            "kernel_time": self.plot_kernel_time.plot(pen="#ff7f0e"),
            "kernel_freq": self.plot_kernel_freq.plot(pen="#ff7f0e"),
        }

    def set_controls_enabled(self, enabled, exclude_play_btn=False):
        self.combo_source.setEnabled(enabled)
        self.combo_tone_type.setEnabled(enabled)
        self.spin_freq.setEnabled(enabled)
        self.spin_amp.setEnabled(enabled)
        self.btn_select_file.setEnabled(enabled)
        self.spin_sss_start_freq.setEnabled(enabled)
        self.spin_sss_end_freq.setEnabled(enabled)
        self.spin_sss_duration.setEnabled(enabled)
        self.spin_sss_amp.setEnabled(enabled)
        self.combo_os.setEnabled(enabled)
        self.btn_run_sim.setEnabled(enabled and self.module.source_mode != "sss")
        if not exclude_play_btn:
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

        plots = [self.plot_time, self.plot_spec]
        if hasattr(self, "plot_kernel_time"):
            plots.append(self.plot_kernel_time)
        if hasattr(self, "plot_kernel_freq"):
            plots.append(self.plot_kernel_freq)

        for p in plots:
            p.setBackground(bg_color)
            p.getAxis("bottom").setPen(text_color)
            p.getAxis("left").setPen(text_color)

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
        sr_val = meta.get("sample_rate", 48000)
        self.lbl_sr.setText(f"{sr_val} Hz")
        self.lbl_order.setText(f"{self.module.applicator.P} ({tr('Max Harmonic')})")
        dir_val = meta.get("model_direction", "forward")
        self.lbl_direction.setText(tr("Inverse") if dir_val == "inverse" else tr("Forward"))

        # Update metadata details in Parameter Details Tab
        self.lbl_meta_direction.setText(tr("Inverse") if dir_val == "inverse" else tr("Forward"))
        self.lbl_meta_sr.setText(f"{sr_val} Hz")
        self.lbl_meta_order.setText(f"{self.module.applicator.P}")

        # Update kernel selection combo box
        self.combo_kernel_select.blockSignals(True)
        self.combo_kernel_select.clear()

        # Populate combo box with the original loaded kernels based on model direction
        if dir_val == "inverse":
            for i in range(len(self.module.applicator.g_kernels)):
                self.combo_kernel_select.addItem(
                    tr("Inverse Kernel g{0}").format(i + 1),
                    ("g", i)
                )
        else:
            for i in range(len(self.module.applicator.h_kernels)):
                self.combo_kernel_select.addItem(
                    tr("Forward Kernel h{0}").format(i + 1),
                    ("h", i)
                )

        self.combo_kernel_select.blockSignals(False)

        if self.combo_kernel_select.count() > 0:
            self.combo_kernel_select.setCurrentIndex(0)
            self.update_kernel_plots()

    def on_source_changed(self, idx):
        source = self.combo_source.itemData(idx)
        self.module.source_mode = source
        self.tone_widget.setVisible(source == "tone")
        self.file_widget.setVisible(source == "file")
        self.sss_widget.setVisible(source == "sss")
        self.btn_export_file.setEnabled(source == "file" and getattr(self.module, "audio_file_path", None) is not None)
        self.btn_play_rt.setEnabled(source == "tone" or source == "sss" or getattr(self.module, "audio_file_path", None) is not None)
        self.btn_run_sim.setEnabled(self.model_data is not None and source != "sss")

    def on_tone_type_changed(self, idx):
        self.module.tone_type = self.combo_tone_type.itemData(idx)
        self.spin_freq.setEnabled(self.module.tone_type == "sine")

    def on_param_changed(self):
        # Update settings to core module
        self.module.tone_freq = self.spin_freq.value()
        self.module.tone_amp = 10 ** (self.spin_amp.value() / 20.0)
        self.module.sss_start_freq = self.spin_sss_start_freq.value()
        self.module.sss_end_freq = self.spin_sss_end_freq.value()
        self.module.sss_duration = self.spin_sss_duration.value()
        self.module.sss_amp = 10 ** (self.spin_sss_amp.value() / 20.0)
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
        if not self.model_data or self.module.source_mode == "sss":
            return

        self.on_param_changed()

        fs = self.module.applicator.sample_rate

        # Generate simulation input buffer (0.1 seconds base size)
        sim_samples = int(0.1 * fs)

        # Align to the nearest bin center frequency if it's a sine wave
        is_sine = (self.module.tone_type == "sine" and self.module.source_mode == "tone")
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
        elif self.module.source_mode == "tone" and self.module.tone_type == "pink":
            from src.core.generators import PinkNoise
            pink = PinkNoise()
            block_in_full = self.module.tone_amp * pink.generate(total_samples)
        elif self.module.source_mode == "tone" and self.module.tone_type == "white":
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

        # Set plot data (expose full steady-state so user can scroll/pan freely)
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
                # Hanning window to prevent leakage for non-periodic signals (e.g. noise / sweeps)
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

            # Start preview buffer preparation worker
            self.btn_play_rt.setText(tr("Stop (Preparing...)"))
            self.btn_play_rt.setStyleSheet("background-color: #d9534f; color: white;")
            self.set_controls_enabled(False, exclude_play_btn=True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

            self.preview_worker = PreviewBufferWorker(
                applicator=self.module.applicator,
                source_mode=self.module.source_mode,
                tone_type=self.module.tone_type,
                tone_freq=self.module.tone_freq,
                tone_amp=self.module.tone_amp,
                audio_file_path=getattr(self.module, "audio_file_path", None),
                sample_rate=self.module.audio_engine.sample_rate,
                sss_start_freq=self.module.sss_start_freq,
                sss_end_freq=self.module.sss_end_freq,
                sss_duration=self.module.sss_duration,
                sss_amp=self.module.sss_amp,
            )
            self.preview_worker.progress.connect(self.progress_bar.setValue)
            self.preview_worker.finished.connect(self.on_preview_ready)
            self.preview_worker.start()
        else:
            # Cancellation or manual stop
            if self.preview_worker and self.preview_worker.isRunning():
                self.preview_worker.cancel()
                # UI state will be reverted in on_preview_ready
            else:
                self.module.stop_realtime()
                self.btn_play_rt.setText(tr("Play (Real-time Preview)"))
                self.btn_play_rt.setStyleSheet("")
                self.set_controls_enabled(True)
                self.progress_bar.setVisible(False)

    def on_preview_ready(self, success, buffer, message):
        self.progress_bar.setVisible(False)
        self.preview_worker = None

        if success:
            try:
                self.module.start_realtime(buffer)
                self.btn_play_rt.setText(tr("Stop (Playback Active)"))
                self.btn_play_rt.setStyleSheet("background-color: #d9534f; color: white;")
            except Exception as e:
                self.btn_play_rt.setChecked(False)
                QMessageBox.critical(self, tr("Error"), tr("Failed to start audio playback:\n{0}").format(e))
                self.on_playback_finished()
        else:
            self.btn_play_rt.setChecked(False)
            self.btn_play_rt.setText(tr("Play (Real-time Preview)"))
            self.btn_play_rt.setStyleSheet("")
            self.set_controls_enabled(True)
            if message and message != tr("Cancelled"):
                QMessageBox.critical(self, tr("Error"), tr("Failed to generate preview buffer:\n{0}").format(message))

    def on_playback_finished(self):
        # Stop button was not clicked, so we must uncheck it and clean up
        self.btn_play_rt.setChecked(False)
        self.on_toggle_realtime(False)

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

    def on_kernel_selection_changed(self, idx):
        self.update_kernel_plots()

    def update_kernel_plots(self):
        if not self.model_data:
            return

        idx = self.combo_kernel_select.currentIndex()
        if idx < 0:
            return

        kernel_info = self.combo_kernel_select.itemData(idx)
        if not kernel_info:
            return

        k_type, k_idx = kernel_info

        if k_type == "h":
            if k_idx >= len(self.module.applicator.h_kernels):
                return
            kernel = self.module.applicator.h_kernels[k_idx]
        else:
            if k_idx >= len(self.module.applicator.g_kernels):
                return
            kernel = self.module.applicator.g_kernels[k_idx]

        fs = self.module.applicator.sample_rate
        n = len(kernel)

        # Calculate statistics
        peak_val = np.max(np.abs(kernel))
        peak_pos = np.argmax(np.abs(kernel))
        peak_ms = (peak_pos / fs) * 1000.0
        rms_val = np.sqrt(np.mean(kernel**2))

        self.lbl_kernel_taps.setText(str(n))
        self.lbl_kernel_peak.setText(f"{peak_val:.6f}")
        self.lbl_kernel_delay.setText(f"{peak_pos} ({peak_ms:.3f} ms)")
        self.lbl_kernel_rms.setText(f"{rms_val:.6f}")

        # Update Time Domain Plot
        t = np.arange(n) / fs * 1000.0
        self.curves["kernel_time"].setData(t, kernel)
        self.plot_kernel_time.autoRange()

        # Update Frequency Domain Plot (Magnitude Response)
        n_fft = max(2048, int(2 ** np.ceil(np.log2(n * 2))))
        H = np.fft.rfft(kernel, n=n_fft)
        freqs = np.fft.rfftfreq(n_fft, 1.0 / fs)
        mags_db = 20 * np.log10(np.maximum(np.abs(H), 1e-10))

        self.curves["kernel_freq"].setData(freqs, mags_db)
        self.plot_kernel_freq.setXRange(20, min(fs / 2, 22000.0))

        # Range margin logic
        y_min = max(-100.0, np.min(mags_db) - 5)
        y_max = np.max(mags_db) + 5
        self.plot_kernel_freq.setYRange(y_min, y_max)


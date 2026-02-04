from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.core.localization import get_manager, tr
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper


def _load_signal_generator():
    from src.gui.widgets.signal_generator import SignalGenerator

    return SignalGenerator


def _load_spectrum_analyzer():
    from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer

    return SpectrumAnalyzer


def _load_sound_level_meter():
    from src.gui.widgets.sound_level_meter import SoundLevelMeter

    return SoundLevelMeter


def _load_lufs_meter():
    from src.gui.widgets.lufs_meter import LufsMeter

    return LufsMeter


def _load_loopback_finder():
    from src.gui.widgets.loopback_finder import LoopbackFinder

    return LoopbackFinder


def _load_distortion_analyzer():
    from src.gui.widgets.distortion_analyzer import DistortionAnalyzer

    return DistortionAnalyzer


def _load_advanced_distortion_meter():
    from src.gui.widgets.advanced_distortion_meter import AdvancedDistortionMeter

    return AdvancedDistortionMeter


def _load_network_analyzer():
    from src.gui.widgets.network_analyzer import NetworkAnalyzer

    return NetworkAnalyzer


def _load_oscilloscope():
    from src.gui.widgets.oscilloscope import Oscilloscope

    return Oscilloscope


def _load_raw_time_series():
    from src.gui.widgets.raw_time_series import RawTimeSeries

    return RawTimeSeries


def _load_lock_in_amplifier():
    from src.gui.widgets.lock_in_amplifier import LockInAmplifier

    return LockInAmplifier


def _load_lockin_thd_analyzer():
    from src.gui.widgets.lockin_thd_analyzer import LockInTHDAnalyzer

    return LockInTHDAnalyzer


def _load_frequency_counter():
    from src.gui.widgets.frequency_counter import FrequencyCounter

    return FrequencyCounter


def _load_lock_in_frequency_counter():
    from src.gui.widgets.lock_in_frequency_counter import LockInFrequencyCounter

    return LockInFrequencyCounter


def _load_spectrogram():
    from src.gui.widgets.spectrogram import Spectrogram

    return Spectrogram


def _load_boxcar_averager():
    from src.gui.widgets.boxcar_averager import BoxcarAverager

    return BoxcarAverager


def _load_goniometer():
    from src.gui.widgets.goniometer import Goniometer

    return Goniometer


def _load_impedance_analyzer():
    from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer

    return ImpedanceAnalyzer


def _load_noise_profiler():
    from src.gui.widgets.noise_profiler import NoiseProfiler

    return NoiseProfiler


def _load_recorder_player():
    from src.gui.widgets.recorder_player import RecorderPlayer

    return RecorderPlayer


def _load_inverse_filter():
    from src.gui.widgets.inverse_filter import InverseFilter

    return InverseFilter


def _load_transient_analyzer():
    from src.gui.widgets.transient_analyzer import TransientAnalyzer

    return TransientAnalyzer


def _load_sound_quality_analyzer():
    from src.gui.widgets.sound_quality_analyzer import SoundQualityAnalyzer

    return SoundQualityAnalyzer


def _load_timecode_monitor():
    from src.gui.widgets.timecode_monitor import TimecodeMonitor

    return TimecodeMonitor


def _load_bnim_meter():
    from src.gui.widgets.bnim_meter import BNIMMeter

    return BNIMMeter


def _load_hrtf_player():
    from src.gui.widgets.hrtf_player import HRTFPlayer

    return HRTFPlayer


def _load_ultrasound_modulator():
    from src.gui.widgets.ultrasound_modulator import UltrasoundModulator

    return UltrasoundModulator


def _load_linearity_analyzer():
    from src.gui.widgets.linearity_analyzer import LinearityAnalyzer

    return LinearityAnalyzer


_MODULE_LOADERS = {
    "Signal Generator": _load_signal_generator,
    "Spectrum Analyzer": _load_spectrum_analyzer,
    "Sound Level Meter": _load_sound_level_meter,
    "LUFS Meter": _load_lufs_meter,
    "Loopback Finder": _load_loopback_finder,
    "Distortion Analyzer": _load_distortion_analyzer,
    "Advanced Distortion Meter": _load_advanced_distortion_meter,
    "Network Analyzer": _load_network_analyzer,
    "Oscilloscope": _load_oscilloscope,
    "Raw Time Series": _load_raw_time_series,
    "Lock-in Amplifier": _load_lock_in_amplifier,
    "Lock-in THD Analyzer": _load_lockin_thd_analyzer,
    "Frequency Counter": _load_frequency_counter,
    "Lock-in Frequency Counter": _load_lock_in_frequency_counter,
    "Spectrogram": _load_spectrogram,
    "Boxcar Averager": _load_boxcar_averager,
    "Goniometer": _load_goniometer,
    "Impedance Analyzer": _load_impedance_analyzer,
    "Noise Profiler": _load_noise_profiler,
    "Recorder / Player": _load_recorder_player,
    "Inverse Filter": _load_inverse_filter,
    "Transient Analyzer": _load_transient_analyzer,
    "Sound Quality Analyzer": _load_sound_quality_analyzer,
    "Timecode Monitor & Generator": _load_timecode_monitor,
    "BNIM Meter": _load_bnim_meter,
    "HRTF Player": _load_hrtf_player,
    "Ultrasound AM Modulator": _load_ultrasound_modulator,
    "Linearity Analyzer": _load_linearity_analyzer,
}


def _load_module_class(module_key: str):
    """Return MeasurementModule class by key.

    Imports are intentionally delayed (via helper functions) to avoid importing
    all heavy GUI modules (pyqtgraph/scipy, etc.) at application startup.
    These imports remain explicit so PyInstaller can still discover them.
    """
    loader = _MODULE_LOADERS.get(module_key)
    if loader:
        return loader()

    raise KeyError(f"Unknown module key: {module_key}")


def _load_settings_widget_class():
    # Same reasoning as _load_module_class: delay heavy imports (scipy, etc.).
    from src.gui.widgets.settings import SettingsWidget

    return SettingsWidget


def _load_welcome_widget_class():
    from src.gui.widgets.welcome import WelcomeWidget

    return WelcomeWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MeasureLab")
        self.resize(1000, 700)

        # Initialize Core Components
        self.config_manager = ConfigManager()

        # Initialize Localization
        lang = self.config_manager.get_language()
        get_manager().load_language(lang)

        self.audio_engine = AudioEngine()

        # Initialize Theme Manager
        from src.core.theme_manager import ThemeManager

        self.theme_manager = ThemeManager(QApplication.instance())
        # Make it accessible from app instance for SettingsWidget
        QApplication.instance().theme_manager = self.theme_manager

        # Load and apply saved theme
        saved_theme = self.config_manager.get_theme()
        self.theme_manager.set_theme(saved_theme)

        # Load saved config
        audio_cfg = self.config_manager.get_audio_config()
        last_in = audio_cfg.get("input_device")
        last_in_hostapi = audio_cfg.get("input_hostapi")
        last_out = audio_cfg.get("output_device")
        last_out_hostapi = audio_cfg.get("output_hostapi")

        # Default IDs
        in_id, out_id = 3, 3  # Fallback

        if last_in or last_out:
            # Find IDs by name
            devices = self.audio_engine.list_devices()
            found_in = False
            found_out = False

            for i, dev in enumerate(devices):
                if not found_in and last_in and dev["name"] == last_in and dev["max_input_channels"] > 0:
                    # Check HostAPI if available
                    if last_in_hostapi:
                        if dev.get("hostapi_name") != last_in_hostapi:
                            continue
                    in_id = i
                    found_in = True

                if not found_out and last_out and dev["name"] == last_out and dev["max_output_channels"] > 0:
                    # Check HostAPI if available
                    if last_out_hostapi:
                        if dev.get("hostapi_name") != last_out_hostapi:
                            continue
                    out_id = i
                    found_out = True

            # Fallback: If strict match failed but we have a name, try loose match (name only)
            if last_in and not found_in:
                for i, dev in enumerate(devices):
                     if dev["name"] == last_in and dev["max_input_channels"] > 0:
                        in_id = i
                        found_in = True
                        break

            if last_out and not found_out:
                for i, dev in enumerate(devices):
                     if dev["name"] == last_out and dev["max_output_channels"] > 0:
                        out_id = i
                        found_out = True
                        break

            if not found_in and last_in:
                print(f"Saved input device '{last_in}' not found, using default.")
            if not found_out and last_out:
                print(f"Saved output device '{last_out}' not found, using default.")

        try:
            self.audio_engine.set_devices(in_id, out_id)

            # Apply other settings
            sr = audio_cfg.get("sample_rate", 48000)
            self.audio_engine.set_sample_rate(sr)

            bs = audio_cfg.get("block_size", 1024)
            self.audio_engine.set_block_size(bs)

            in_ch = audio_cfg.get("input_channels", "stereo")
            out_ch = audio_cfg.get("output_channels", "stereo")
            self.audio_engine.set_channel_mode(in_ch, out_ch)

            # Apply PipeWire/JACK resident mode after devices + format are configured.
            self.audio_engine.set_pipewire_jack_resident(self.config_manager.get_pipewire_jack_resident())

        except Exception as e:
            print(f"Failed to set devices/settings: {e}")
            # Try default if specific failed
            try:
                self.audio_engine.set_devices(None, None)
            except Exception:
                pass

            # Even if device selection failed, honor resident setting best-effort.
            try:
                self.audio_engine.set_pipewire_jack_resident(self.config_manager.get_pipewire_jack_resident())
            except Exception:
                pass

        # Module registry (keep keys identical to module.name strings)
        self._module_keys = [
            "Signal Generator",
            "Spectrum Analyzer",
            "Sound Level Meter",
            "LUFS Meter",
            "Loopback Finder",
            "Distortion Analyzer",
            "Advanced Distortion Meter",
            "Network Analyzer",
            "Oscilloscope",
            "Raw Time Series",
            "Lock-in Amplifier",
            "Lock-in THD Analyzer",
            "Frequency Counter",
            "Lock-in Frequency Counter",
            "Spectrogram",
            "Boxcar Averager",
            "Goniometer",
            "Impedance Analyzer",
            "Noise Profiler",
            "Recorder / Player",
            "Inverse Filter",
            "Transient Analyzer",
            "Sound Quality Analyzer",
            "Timecode Monitor & Generator",
            "BNIM Meter",
            "HRTF Player",
            "Ultrasound AM Modulator",
            "Linearity Analyzer",
        ]
        self.modules = [None] * len(self._module_keys)
        self.module_widgets = [None] * len(self._module_keys)

        # Main layout container
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Sidebar for tool selection
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.addItem(tr("Welcome"))
        self.sidebar.addItem(tr("Settings"))  # Add Settings item

        for key in self._module_keys:
            self.sidebar.addItem(tr(key))

        self.sidebar.currentRowChanged.connect(self.on_tool_selected)
        layout.addWidget(self.sidebar)

        # Main content area
        self.content_area = QStackedWidget()
        layout.addWidget(self.content_area)

        # Add initial welcome page (Index 0)
        WelcomeWidget = _load_welcome_widget_class()
        self.welcome_widget = WelcomeWidget()
        self.content_area.addWidget(self.welcome_widget)

        # Add Settings Page (Index 1) - lazy loaded to avoid importing scipy at startup
        self._settings_loaded = False
        self._settings_container = QWidget()
        settings_layout = QVBoxLayout(self._settings_container)
        settings_layout.setContentsMargins(12, 12, 12, 12)
        settings_layout.addWidget(QLabel(tr("Select Settings to load.")))
        self.content_area.addWidget(self._settings_container)

        # Add module pages (Index 2+) - lazy loaded per selection
        self._module_containers = []
        for _key in self._module_keys:
            container = QWidget()
            v = QVBoxLayout(container)
            v.setContentsMargins(12, 12, 12, 12)
            v.addWidget(QLabel(tr("Select a module from the sidebar.")))
            self._module_containers.append(container)
            self.content_area.addWidget(container)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Status Labels
        self.status_label = QLabel(tr("Idle"))
        self.io_label = QLabel(tr("In: - | Out: -"))
        self.sr_label = QLabel(tr("SR: -"))
        self.cpu_label = QLabel(tr("CPU: 0%"))
        self.clients_label = QLabel(tr("Clients: 0"))
        self.output_dest_label = QLabel(tr("Output:"))
        self.output_dest_combo = QComboBox()
        self.output_dest_combo.addItem(tr("Physical Output"), "physical")
        self.output_dest_combo.addItem(tr("Internal Loopback (Silent)"), "loopback_silent")
        self.output_dest_combo.addItem(tr("Loopback + Physical"), "loopback_mix")
        self.output_dest_combo.setToolTip(tr("Global output destination for all modules."))
        self.output_dest_combo.currentIndexChanged.connect(self.on_output_destination_changed)

        # Add labels to status bar
        self.status_bar.addPermanentWidget(self.status_label)
        self.status_bar.addPermanentWidget(self.io_label)
        self.status_bar.addPermanentWidget(self.sr_label)
        self.status_bar.addPermanentWidget(self.cpu_label)
        self.status_bar.addPermanentWidget(self.clients_label)
        self.status_bar.addPermanentWidget(self.output_dest_label)
        self.status_bar.addPermanentWidget(self.output_dest_combo)

        # Timer for status update
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(500)  # 500ms update rate

        # Sync output destination control with engine state on startup
        self._sync_output_destination_ui(self._get_engine_output_destination(), propagate=True)

    def _replace_container_contents(self, container: QWidget, widget: QWidget):
        layout = container.layout()
        if layout is None:
            layout = QVBoxLayout(container)
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        layout.addWidget(widget)

    def _ensure_settings_loaded(self):
        if self._settings_loaded:
            return
        try:
            SettingsWidget = _load_settings_widget_class()
            self.settings_widget = SettingsWidget(self.audio_engine, self.config_manager)
            self._replace_container_contents(self._settings_container, self.settings_widget)
            self._settings_loaded = True
        except Exception as e:
            self._replace_container_contents(
                self._settings_container,
                QLabel(tr("Failed to load Settings: {0}").format(str(e))),
            )

    def _ensure_module_loaded(self, module_index: int):
        if module_index < 0 or module_index >= len(self._module_keys):
            return
        if self.modules[module_index] is not None and self.module_widgets[module_index] is not None:
            return

        key = self._module_keys[module_index]
        container = self._module_containers[module_index]
        try:
            cls = _load_module_class(key)
            module = cls(self.audio_engine)
            self.modules[module_index] = module

            widget = module.get_widget()
            if widget:
                wrapper = DetachableWidgetWrapper(widget, tr(key), self.config_manager)
                self.module_widgets[module_index] = wrapper
                self._replace_container_contents(container, wrapper)

                # Sync global output destination into newly loaded widget
                self._propagate_output_destination(self._get_engine_output_destination())
            else:
                self._replace_container_contents(container, QLabel(tr("No GUI for {0}").format(key)))
        except Exception as e:
            self._replace_container_contents(
                container,
                QLabel(tr("Failed to load module {0}: {1}").format(tr(key), str(e))),
            )

    def preload_all_modules(self, progress_callback=None):
        """Preload Settings and all modules.

        Intended to be called while a splash screen is visible so the user sees
        progress while heavy imports/widgets are created.

        progress_callback: callable(str) -> None
        """

        def report(msg: str):
            if progress_callback is None:
                return
            try:
                progress_callback(msg)
            except Exception:
                pass

        report(tr("Loading Settings..."))
        QApplication.processEvents()
        self._ensure_settings_loaded()
        QApplication.processEvents()

        total = len(self._module_keys)
        for i, key in enumerate(self._module_keys, start=1):
            report(tr("Loading {0} ({1}/{2})...").format(tr(key), i, total))
            QApplication.processEvents()
            self._ensure_module_loaded(i - 1)
            QApplication.processEvents()

    def closeEvent(self, event):
        # Ensure PortAudio stream is closed (important in resident mode).
        try:
            self.audio_engine.stop_stream()
        except Exception:
            pass
        super().closeEvent(event)

    def update_status(self):
        status = self.audio_engine.get_status()

        # Keep global output selector in sync if a widget changed it
        current_mode = self._get_engine_output_destination()
        self._sync_output_destination_ui(current_mode, propagate=True)

        # Active State
        if status["active"]:
            self.status_label.setText(tr("ACTIVE"))
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText(tr("IDLE"))
            self.status_label.setStyleSheet("color: gray;")

        # I/O Mode
        in_mode = status["input_channels"].capitalize()
        out_mode = status["output_channels"].capitalize()
        self.io_label.setText(tr("In: {0} | Out: {1}").format(in_mode, out_mode))

        # Sample Rate
        self.sr_label.setText(tr("SR: {0}").format(status["sample_rate"]))

        # CPU Load
        cpu = status["cpu_load"] * 100
        flags = status.get("status_flags")

        if flags:
            self.cpu_label.setText(tr("CPU: {0:.1f}% [{1}]").format(cpu, flags))
            self.cpu_label.setStyleSheet("color: red; font-weight: bold;")
            self.cpu_label.setToolTip(tr("Audio Buffer Error: {0}").format(flags))
        else:
            self.cpu_label.setText(tr("CPU: {0:.1f}%").format(cpu))
            self.cpu_label.setStyleSheet("")
            self.cpu_label.setToolTip(tr("CPU Load of Audio Thread"))

        # Clients
        self.clients_label.setText(tr("Clients: {0}").format(status["active_clients"]))

    def _get_engine_output_destination(self):
        if self.audio_engine.loopback:
            return "loopback_silent" if self.audio_engine.mute_output else "loopback_mix"
        return "physical"

    def _sync_output_destination_ui(self, mode: str, propagate: bool = False):
        idx = self.output_dest_combo.findData(mode)
        if idx == -1:
            return
        if idx != self.output_dest_combo.currentIndex():
            self.output_dest_combo.blockSignals(True)
            self.output_dest_combo.setCurrentIndex(idx)
            self.output_dest_combo.blockSignals(False)
            if propagate:
                self._propagate_output_destination(mode)

    def _propagate_output_destination(self, mode: str):
        for widget in self.module_widgets:
            if widget:
                # If wrapped, get the inner content
                target = widget.content_widget if isinstance(widget, DetachableWidgetWrapper) else widget

                if hasattr(target, "set_output_destination"):
                    try:
                        target.set_output_destination(mode)
                    except Exception as e:
                        print(f"Failed to sync output destination: {e}")

    def on_output_destination_changed(self, index):
        data = self.output_dest_combo.currentData()
        if data == "physical":
            self.audio_engine.set_loopback(False)
            self.audio_engine.set_mute_output(False)
        elif data == "loopback_silent":
            self.audio_engine.set_loopback(True)
            self.audio_engine.set_mute_output(True)
        elif data == "loopback_mix":
            self.audio_engine.set_loopback(True)
            self.audio_engine.set_mute_output(False)

        # Mirror selection to widgets that expose destination controls
        self._propagate_output_destination(data)

    def on_tool_selected(self, index):
        if index == 1:
            self._ensure_settings_loaded()
        elif index >= 2:
            self._ensure_module_loaded(index - 2)
        self.content_area.setCurrentIndex(index)

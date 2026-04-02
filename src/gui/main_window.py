import importlib
import logging
import time
from typing import Optional

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
from src.core.module_constants import (
    ALL_MODULE_KEYS,
    MODULE_1PPS_MONITOR,
    MODULE_ADVANCED_DISTORTION_METER,
    MODULE_BNIM_METER,
    MODULE_BOXCAR_AVERAGER,
    MODULE_DISTORTION_ANALYZER,
    MODULE_FREQUENCY_COUNTER,
    MODULE_GONIOMETER,
    MODULE_HRTF_PLAYER,
    MODULE_IMPEDANCE_ANALYZER,
    MODULE_INVERSE_FILTER,
    MODULE_LINEARITY_ANALYZER,
    MODULE_LOCK_IN_AMPLIFIER,
    MODULE_LOCK_IN_FREQUENCY_COUNTER,
    MODULE_LOCK_IN_HARMONIC_ANALYZER,
    MODULE_LOCK_IN_THD_ANALYZER,
    MODULE_LOCKIN_SPECTRUM_FINDER,
    MODULE_LOOPBACK_FINDER,
    MODULE_LUFS_METER,
    MODULE_NETWORK_ANALYZER,
    MODULE_NOISE_PROFILER,
    MODULE_OSCILLOSCOPE,
    MODULE_RAW_TIME_SERIES,
    MODULE_RECORDER_PLAYER,
    MODULE_SIGNAL_GENERATOR,
    MODULE_SOUND_LEVEL_METER,
    MODULE_SOUND_QUALITY_ANALYZER,
    MODULE_SPECTROGRAM,
    MODULE_SPECTRUM_ANALYZER,
    MODULE_TIMECODE_MONITOR,
    MODULE_TRANSIENT_ANALYZER,
    MODULE_ULTRASOUND_MODULATOR,
    EXPERIMENTAL_MODULE_KEYS,
    MODULE_STEREO_ALIGNMENT_MONITOR,
    MODULE_PROCESSOR_BENCHMARK,
)
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper


# Registry mapping module key -> (module_path, class_name)
MODULE_REGISTRY = {
    MODULE_SIGNAL_GENERATOR: ("src.gui.widgets.signal_generator", "SignalGenerator"),
    MODULE_SPECTRUM_ANALYZER: ("src.gui.widgets.spectrum_analyzer", "SpectrumAnalyzer"),
    MODULE_SOUND_LEVEL_METER: ("src.gui.widgets.sound_level_meter", "SoundLevelMeter"),
    MODULE_LUFS_METER: ("src.gui.widgets.lufs_meter", "LufsMeter"),
    MODULE_LOOPBACK_FINDER: ("src.gui.widgets.loopback_finder", "LoopbackFinder"),
    MODULE_DISTORTION_ANALYZER: ("src.gui.widgets.distortion_analyzer", "DistortionAnalyzer"),
    MODULE_ADVANCED_DISTORTION_METER: ("src.gui.widgets.advanced_distortion_meter", "AdvancedDistortionMeter"),
    MODULE_NETWORK_ANALYZER: ("src.gui.widgets.network_analyzer", "NetworkAnalyzer"),
    MODULE_OSCILLOSCOPE: ("src.gui.widgets.oscilloscope", "Oscilloscope"),
    MODULE_RAW_TIME_SERIES: ("src.gui.widgets.raw_time_series", "RawTimeSeries"),
    MODULE_LOCK_IN_AMPLIFIER: ("src.gui.widgets.lock_in_amplifier", "LockInAmplifier"),
    MODULE_LOCK_IN_THD_ANALYZER: ("src.gui.widgets.lockin_thd_analyzer", "LockInTHDAnalyzer"),
    MODULE_LOCK_IN_HARMONIC_ANALYZER: ("src.gui.widgets.lockin_harmonic_analyzer", "LockInHarmonicAnalyzer"),
    MODULE_LOCKIN_SPECTRUM_FINDER: ("src.gui.widgets.lockin_spectrum_finder", "LockInSpectrumFinder"),
    MODULE_FREQUENCY_COUNTER: ("src.gui.widgets.frequency_counter", "FrequencyCounter"),
    MODULE_LOCK_IN_FREQUENCY_COUNTER: ("src.gui.widgets.lock_in_frequency_counter", "LockInFrequencyCounter"),
    MODULE_SPECTROGRAM: ("src.gui.widgets.spectrogram", "Spectrogram"),
    MODULE_BOXCAR_AVERAGER: ("src.gui.widgets.boxcar_averager", "BoxcarAverager"),
    MODULE_GONIOMETER: ("src.gui.widgets.goniometer", "Goniometer"),
    MODULE_IMPEDANCE_ANALYZER: ("src.gui.widgets.impedance_analyzer", "ImpedanceAnalyzer"),
    MODULE_NOISE_PROFILER: ("src.gui.widgets.noise_profiler", "NoiseProfiler"),
    MODULE_RECORDER_PLAYER: ("src.gui.widgets.recorder_player", "RecorderPlayer"),
    MODULE_INVERSE_FILTER: ("src.gui.widgets.inverse_filter", "InverseFilter"),
    MODULE_TRANSIENT_ANALYZER: ("src.gui.widgets.transient_analyzer", "TransientAnalyzer"),
    MODULE_SOUND_QUALITY_ANALYZER: ("src.gui.widgets.sound_quality_analyzer", "SoundQualityAnalyzer"),
    MODULE_TIMECODE_MONITOR: ("src.gui.widgets.timecode_monitor", "TimecodeMonitor"),
    MODULE_BNIM_METER: ("src.gui.widgets.bnim_meter", "BNIMMeter"),
    MODULE_HRTF_PLAYER: ("src.gui.widgets.hrtf_player", "HRTFPlayer"),
    MODULE_ULTRASOUND_MODULATOR: ("src.gui.widgets.ultrasound_modulator", "UltrasoundModulator"),
    MODULE_LINEARITY_ANALYZER: ("src.gui.widgets.linearity_analyzer", "LinearityAnalyzer"),
    MODULE_1PPS_MONITOR: ("src.gui.widgets.one_pps_monitor", "OnePPSMonitor"),
    MODULE_STEREO_ALIGNMENT_MONITOR: ("src.gui.widgets.stereo_alignment_monitor", "StereoAlignmentMonitor"),
    MODULE_PROCESSOR_BENCHMARK: ("src.gui.widgets.processor_benchmark", "ProcessorBenchmark"),
}


def _load_class(module_path: str, class_name: str):
    """Dynamically load a class from a module."""
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _load_module_class(module_key: str):
    """Return MeasurementModule class by key.

    Uses _load_class to avoid importing heavy GUI modules at application startup.
    Explicit imports for PyInstaller discovery are handled in src.gui.pyinstaller_imports.
    """
    if module_key not in MODULE_REGISTRY:
        raise KeyError(f"Unknown module key: {module_key}")

    return _load_class(*MODULE_REGISTRY[module_key])


if False:
    # Explicit imports via src.gui.pyinstaller_imports so PyInstaller can discover dynamically loaded modules.
    from . import pyinstaller_imports  # noqa: F401


def _load_settings_widget_class():
    # Same reasoning as _load_module_class: delay heavy imports (scipy, etc.).
    return _load_class("src.gui.widgets.settings", "SettingsWidget")


def _load_welcome_widget_class():
    return _load_class("src.gui.widgets.welcome", "WelcomeWidget")


class MainWindow(QMainWindow):
    def __init__(self, enable_experimental: bool = False):
        super().__init__()
        self.enable_experimental = enable_experimental
        self.logger = logging.getLogger(__name__)
        self.setWindowTitle("MeasureLab")
        self.resize(1000, 700)

        self._init_core()
        self._init_audio()
        self._init_ui()
        self._init_state()

    def _init_core(self):
        """Initialize core components (config, localization, audio engine, theme)."""
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

    def _init_audio(self):
        """Configure AudioEngine with saved settings."""
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

            # Find Input Device
            if last_in:
                found_in_id = self._find_device_id(devices, last_in, last_in_hostapi, is_input=True)
                if found_in_id is not None:
                    in_id = found_in_id
                else:
                    self.logger.info(f"Saved input device '{last_in}' not found, using default.")

            # Find Output Device
            if last_out:
                found_out_id = self._find_device_id(devices, last_out, last_out_hostapi, is_input=False)
                if found_out_id is not None:
                    out_id = found_out_id
                else:
                    self.logger.info(f"Saved output device '{last_out}' not found, using default.")

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

            # Apply virtual/offline mode
            is_offline = self.config_manager.is_offline_mode()
            self.audio_engine.set_offline_mode(is_offline)

            # Apply dithering settings
            self.audio_engine.dithering_enabled = self.config_manager.is_dithering_enabled()
            self.audio_engine.dithering_bit_depth = self.config_manager.get_dithering_bit_depth()

            # Apply 64-bit engine mode
            is_64bit = audio_cfg.get("audio_engine_64bit", False)
            self.audio_engine.set_audio_engine_64bit(is_64bit)

        except Exception as e:
            self.logger.error(f"Failed to set devices/settings: {e}")
            # Try default if specific failed
            try:
                self.audio_engine.set_devices(None, None)
            except Exception as e:
                self.logger.error(f"Failed to set default devices: {e}")

            # Even if device selection failed, honor resident setting best-effort.
            try:
                self.audio_engine.set_pipewire_jack_resident(self.config_manager.get_pipewire_jack_resident())
            except Exception as e:
                self.logger.warning(f"Failed to set resident mode: {e}")

    def _init_ui(self):
        """Initialize UI components (Layouts, Sidebar, StackedWidget, Status Bar)."""
        self._init_module_registry()

        main_layout = self._init_main_layout()
        self._init_sidebar(main_layout)
        self._init_content_area(main_layout)
        self._init_status_bar()

    def _init_module_registry(self):
        """Initialize module registry arrays."""
        # Module registry (keep keys identical to module.name strings)
        self._module_keys = [
            k for k in ALL_MODULE_KEYS if self.enable_experimental or k not in EXPERIMENTAL_MODULE_KEYS
        ]
        self.modules = [None] * len(self._module_keys)
        self.module_widgets = [None] * len(self._module_keys)

    def _init_main_layout(self):
        """Initialize the main widget and layout."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        return layout

    def _init_sidebar(self, layout):
        """Initialize the sidebar with navigation items."""
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(200)
        self.sidebar.addItem(tr("Welcome"))
        self.sidebar.addItem(tr("Settings"))  # Add Settings item

        for key in self._module_keys:
            self.sidebar.addItem(tr(key))

        self.sidebar.currentRowChanged.connect(self.on_tool_selected)
        layout.addWidget(self.sidebar)

    def _init_content_area(self, layout):
        """Initialize the central stacked widget content area."""
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

    def _init_status_bar(self):
        """Initialize the status bar and its indicators."""
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

    def _init_state(self):
        """Initial state synchronization (output destination, offline mode)."""
        # Sync output destination control with engine state on startup
        self._sync_output_destination_ui(self._get_engine_output_destination(), propagate=True)

        # Track offline mode state to update UI dynamically
        self._last_offline_mode = False
        # Initial check
        self._update_output_destination_ui_for_mode(self.audio_engine.offline_mode)
        self._last_offline_mode = self.audio_engine.offline_mode

    def _find_device_id(self, devices: list, name: str, hostapi: str, is_input: bool) -> Optional[int]:
        """Find device ID by name and hostapi, with fallback to name only."""
        if not name:
            return None

        def is_valid_device(dev):
            if is_input:
                return dev["max_input_channels"] > 0
            return dev["max_output_channels"] > 0

        # Pass 1: Strict match
        strict = next(
            (
                i
                for i, d in enumerate(devices)
                if is_valid_device(d) and d["name"] == name and (not hostapi or d.get("hostapi_name") == hostapi)
            ),
            None,
        )

        if strict is not None:
            return strict

        # Pass 2: Loose match
        if hostapi:
            return next(
                (i for i, d in enumerate(devices) if is_valid_device(d) and d["name"] == name),
                None,
            )

        return None

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
                # Only set it for this specific widget, not all of them
                if hasattr(widget, "set_output_destination"):
                    try:
                        widget.set_output_destination(self._get_engine_output_destination())
                    except Exception as e:
                        self.logger.warning(f"Failed to sync output destination for {key}: {e}")
            else:
                self._replace_container_contents(container, QLabel(tr("No GUI for {0}").format(key)))
        except (ImportError, AttributeError, RuntimeError, ValueError, KeyError) as e:
            self._replace_container_contents(
                container,
                QLabel(tr("Error loading {0}: {1}").format(key, e)),
            )
            self.logger.error(f"Failed to load module {key}: {e}", exc_info=True)

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
            except Exception as e:
                self.logger.warning(f"Progress callback failed: {e}")

        report(tr("Loading Settings..."))
        QApplication.processEvents()
        self._ensure_settings_loaded()
        QApplication.processEvents()

        total = len(self._module_keys)
        last_event_time = time.monotonic()
        for i, key in enumerate(self._module_keys, start=1):
            report(tr("Loading {0} ({1}/{2})...").format(tr(key), i, total))

            current_time = time.monotonic()
            if current_time - last_event_time > 0.05:
                QApplication.processEvents()
                last_event_time = current_time

            self._ensure_module_loaded(i - 1)

            current_time = time.monotonic()
            if current_time - last_event_time > 0.05:
                QApplication.processEvents()
                last_event_time = current_time

    def closeEvent(self, event):
        # Ensure PortAudio stream is closed (important in resident mode).
        try:
            self.audio_engine.stop_stream()
        except Exception:
            self.logger.exception("Failed to stop audio stream on close")
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

        # Check for Offline Mode change
        is_offline = status["offline_mode"]
        if is_offline != self._last_offline_mode:
            self._update_output_destination_ui_for_mode(is_offline)
            self._last_offline_mode = is_offline

    def _get_engine_output_destination(self):
        if self.audio_engine.loopback:
            return "loopback_silent" if self.audio_engine.mute_output else "loopback_mix"
        return "physical"

    def _update_output_destination_ui_for_mode(self, is_offline: bool):
        """Update the output destination combobox based on offline/online mode."""
        self.output_dest_combo.blockSignals(True)
        self.output_dest_combo.clear()

        if is_offline:
            # unique item for offline mode
            self.output_dest_combo.addItem(tr("Virtual Loopback (Always On)"), "virtual_loopback")
            self.output_dest_combo.setCurrentIndex(0)
            self.output_dest_combo.setEnabled(False)
            self.output_dest_combo.setToolTip(tr("In Virtual Mode, audio is always looped back."))
        else:
            # Restore standard items
            self.output_dest_combo.addItem(tr("Physical Output"), "physical")
            self.output_dest_combo.addItem(tr("Internal Loopback (Silent)"), "loopback_silent")
            self.output_dest_combo.addItem(tr("Loopback + Physical"), "loopback_mix")
            self.output_dest_combo.setEnabled(True)
            self.output_dest_combo.setToolTip(tr("Global output destination for all modules."))

            # Resync selection with engine state
            current_mode = self._get_engine_output_destination()
            idx = self.output_dest_combo.findData(current_mode)
            if idx != -1:
                self.output_dest_combo.setCurrentIndex(idx)

        self.output_dest_combo.blockSignals(False)

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
                        self.logger.warning(f"Failed to sync output destination: {e}")

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

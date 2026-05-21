import importlib
import logging
import time
from typing import Any, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSizePolicy,
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
    EXPERIMENTAL_MODULE_KEYS,
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
    MODULE_ARBITRARY_HARMONIC_GENERATOR,
    MODULE_LOCKIN_SPECTRUM_FINDER,
    MODULE_LOOPBACK_FINDER,
    MODULE_LUFS_METER,
    MODULE_NETWORK_ANALYZER,
    MODULE_NOISE_PROFILER,
    MODULE_OSCILLOSCOPE,
    MODULE_PROCESSOR_BENCHMARK,
    MODULE_RAW_TIME_SERIES,
    MODULE_RECORDER_PLAYER,
    MODULE_SIGNAL_GENERATOR,
    MODULE_SOUND_LEVEL_METER,
    MODULE_SOUND_QUALITY_ANALYZER,
    MODULE_SPATIAL_BINAURAL_MIXER,
    MODULE_SPECTROGRAM,
    MODULE_SPECTRUM_ANALYZER,
    MODULE_STEREO_ALIGNMENT_MONITOR,
    MODULE_TIMECODE_MONITOR,
    MODULE_TRANSIENT_ANALYZER,
    MODULE_ULTRASOUND_MODULATOR,
    MODULE_WAVEFORM_LOOP_PLAYER,
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
    MODULE_LOCK_IN_HARMONIC_ANALYZER: ("src.gui.widgets.lockin_harmonic_analyzer", "LockInHarmonicAnalyzer"),
    MODULE_ARBITRARY_HARMONIC_GENERATOR: ("src.gui.widgets.arbitrary_harmonic_generator", "ArbitraryHarmonicGenerator"),
    MODULE_LOCKIN_SPECTRUM_FINDER: ("src.gui.widgets.lockin_spectrum_finder", "LockInSpectrumFinder"),
    MODULE_FREQUENCY_COUNTER: ("src.gui.widgets.frequency_counter", "FrequencyCounter"),
    MODULE_LOCK_IN_FREQUENCY_COUNTER: ("src.gui.widgets.lock_in_frequency_counter", "LockInFrequencyCounter"),
    MODULE_SPECTROGRAM: ("src.gui.widgets.spectrogram", "Spectrogram"),
    MODULE_BOXCAR_AVERAGER: ("src.gui.widgets.boxcar_averager", "BoxcarAverager"),
    MODULE_GONIOMETER: ("src.gui.widgets.goniometer", "Goniometer"),
    MODULE_IMPEDANCE_ANALYZER: ("src.gui.widgets.impedance_analyzer", "ImpedanceAnalyzer"),
    MODULE_NOISE_PROFILER: ("src.gui.widgets.noise_profiler", "NoiseProfiler"),
    MODULE_RECORDER_PLAYER: ("src.gui.widgets.recorder_player", "RecorderPlayer"),
    MODULE_WAVEFORM_LOOP_PLAYER: ("src.gui.widgets.waveform_loop_player", "WaveformLoopPlayer"),
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
    MODULE_SPATIAL_BINAURAL_MIXER: ("src.gui.widgets.spatial_binaural_mixer", "SpatialBinauralMixer"),
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
    _ACTIVE_STATE_ATTRS = (
        "is_running",
        "is_playing",
        "is_recording",
        "rotation_active",
        "analysis_active",
        "capture_active",
        "_play_active",
        "_cal_active",
    )

    def __init__(self, enable_experimental: bool = False):
        super().__init__()
        self.enable_experimental = enable_experimental
        self.logger = logging.getLogger(__name__)
        self.setWindowTitle("MeasureLab")
        self.resize(1000, 700)
        self._menu_only_mode = False
        self._normal_geometry = None
        self._normal_min_width = self.minimumWidth()
        self._normal_max_width = self.maximumWidth()

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

            # Apply Core Audio settings
            self.audio_engine.set_coreaudio_fail_if_conversion_required(
                self.config_manager.is_coreaudio_fail_if_conversion_required()
            )
            self.audio_engine.set_coreaudio_change_device_parameters(
                self.config_manager.is_coreaudio_change_device_parameters()
            )
            self.audio_engine.set_coreaudio_conversion_quality(self.config_manager.get_coreaudio_conversion_quality())

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
        self.modules: list[Any | None] = [None] * len(self._module_keys)
        self.module_widgets: list[DetachableWidgetWrapper | None] = [None] * len(self._module_keys)

    def _init_main_layout(self):
        """Initialize the main widget and layout."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        return layout

    def _init_sidebar(self, layout):
        """Initialize the sidebar with navigation items."""
        self.sidebar_panel = QWidget()
        self.sidebar_panel.setFixedWidth(220)
        sidebar_layout = QVBoxLayout(self.sidebar_panel)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)

        self.menu_only_btn = QPushButton(tr("Menu Only"))
        self.menu_only_btn.setCheckable(True)
        self.menu_only_btn.setToolTip(tr("Toggle menu-only mode."))
        self.menu_only_btn.toggled.connect(self.set_menu_only_mode)
        sidebar_layout.addWidget(self.menu_only_btn)

        self.sidebar = QListWidget()
        self.sidebar.addItem(tr("Welcome"))
        self.sidebar.addItem(tr("Settings"))  # Add Settings item

        for key in self._module_keys:
            self.sidebar.addItem(tr(key))

        self.sidebar.currentRowChanged.connect(self.on_tool_selected)
        self.sidebar.itemDoubleClicked.connect(self.on_sidebar_item_double_clicked)
        sidebar_layout.addWidget(self.sidebar, stretch=1)

        self.sidebar_footer = QWidget()
        self.sidebar_footer_layout = QVBoxLayout(self.sidebar_footer)
        self.sidebar_footer_layout.setContentsMargins(0, 8, 0, 0)
        self.sidebar_footer_layout.setSpacing(4)
        self.sidebar_footer.hide()
        sidebar_layout.addWidget(self.sidebar_footer)

        layout.addWidget(self.sidebar_panel)
        self._refresh_sidebar_activity_indicators()

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
        self._module_containers: list[QWidget] = []
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
        self.compact_status_label = QLabel(tr("Idle") + " • -")
        self.compact_status_label.setStyleSheet("color: gray;")
        self.compact_status_label.setToolTip(tr("Audio status summary."))
        self.output_dest_label = QLabel(tr("Output:"))
        self.output_dest_combo = QComboBox()
        self.output_dest_combo.addItem(tr("Physical Output"), "physical")
        self.output_dest_combo.addItem(tr("Internal Loopback (Silent)"), "loopback_silent")
        self.output_dest_combo.addItem(tr("Loopback + Physical"), "loopback_mix")
        self.output_dest_combo.setToolTip(tr("Global output destination for all modules."))
        self.output_dest_combo.currentIndexChanged.connect(self.on_output_destination_changed)
        self.output_dest_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._status_widgets = [
            self.status_label,
            self.io_label,
            self.sr_label,
            self.cpu_label,
            self.clients_label,
            self.output_dest_label,
            self.output_dest_combo,
        ]

        # Add labels to status bar
        self._move_status_widgets_to_status_bar()

        # Timer for status update
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(500)  # 500ms update rate

    def _clear_sidebar_footer(self):
        while self.sidebar_footer_layout.count():
            item = self.sidebar_footer_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _move_status_widgets_to_sidebar_footer(self):
        """Show compact status plus routing controls below the menu."""
        self._clear_sidebar_footer()
        for widget in self._status_widgets:
            self.status_bar.removeWidget(widget)
            widget.hide()

        self.sidebar_footer_layout.addWidget(self.compact_status_label)
        self.sidebar_footer_layout.addWidget(self.output_dest_combo)
        self.compact_status_label.show()
        self.output_dest_combo.show()

    def _move_status_widgets_to_status_bar(self):
        """Move status/routing controls back to the QStatusBar."""
        if hasattr(self, "sidebar_footer_layout"):
            self._clear_sidebar_footer()
        self.compact_status_label.hide()
        for widget in self._status_widgets:
            self.status_bar.addPermanentWidget(widget)
            widget.show()

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
            if item is None:
                continue
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

    def _format_compact_sample_rate(self, sample_rate) -> str:
        try:
            sr = float(sample_rate)
        except (TypeError, ValueError):
            return str(sample_rate)

        if sr >= 1000 and sr % 1000 == 0:
            return tr("{0:g} kHz").format(sr / 1000)
        if sr >= 1000:
            return tr("{0:.1f} kHz").format(sr / 1000)
        return tr("{0:g} Hz").format(sr)

    def update_status(self):
        status = self.audio_engine.get_status()

        # Keep global output selector in sync if a widget changed it
        current_mode = self._get_engine_output_destination()
        self._sync_output_destination_ui(current_mode, propagate=True)

        # Active State
        if status["active"]:
            state_text = tr("ACTIVE").capitalize()
            status_style = "color: green; font-weight: bold;"
            self.status_label.setText(tr("ACTIVE"))
            self.status_label.setStyleSheet(status_style)
        else:
            state_text = tr("IDLE").capitalize()
            status_style = "color: gray;"
            self.status_label.setText(tr("IDLE"))
            self.status_label.setStyleSheet(status_style)

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

        compact_sr = self._format_compact_sample_rate(status["sample_rate"])
        self.compact_status_label.setText(f"{state_text} • {compact_sr}")
        self.compact_status_label.setStyleSheet(status_style)
        self.compact_status_label.setToolTip(
            tr("In: {0} | Out: {1}\nCPU: {2:.1f}%\nClients: {3}").format(
                in_mode,
                out_mode,
                cpu,
                status["active_clients"],
            )
        )
        self._refresh_sidebar_activity_indicators()

        # Check for Offline Mode change
        is_offline = status["offline_mode"]
        if is_offline != self._last_offline_mode:
            self._update_output_destination_ui_for_mode(is_offline)
            self._last_offline_mode = is_offline

    def _module_is_active(self, module) -> bool:
        if module is None:
            return False

        for attr_name in self._ACTIVE_STATE_ATTRS:
            if bool(getattr(module, attr_name, False)):
                return True

        return False

    def _build_module_activity_tooltip(self, module_index: int) -> str:
        key = self._module_keys[module_index]
        parts = [tr(key)]

        if self._module_is_active(self.modules[module_index]):
            parts.append(tr("ACTIVE"))

        wrapper = self.module_widgets[module_index]
        if wrapper is not None and getattr(wrapper, "is_detached", False):
            parts.append(tr("Widget is detached in a separate window."))

        return "\n".join(parts)

    def _refresh_sidebar_activity_indicators(self):
        if not hasattr(self, "sidebar"):
            return

        default_brush = self.sidebar.palette().brush(QPalette.ColorRole.Text)
        active_brush = self.sidebar.palette().brush(QPalette.ColorRole.Highlight)

        for module_index, key in enumerate(self._module_keys):
            item = self.sidebar.item(module_index + 2)
            if item is None:
                continue

            is_active = self._module_is_active(self.modules[module_index])
            font = item.font()
            font.setBold(is_active)
            item.setFont(font)
            item.setForeground(active_brush if is_active else default_brush)
            item.setToolTip(self._build_module_activity_tooltip(module_index))
            item.setText(tr(key))

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

    def set_menu_only_mode(self, enabled: bool):
        """Toggle between the full main window and a compact menu-only window."""
        enabled = bool(enabled)
        if self._menu_only_mode == enabled:
            return

        self._menu_only_mode = enabled
        if self.menu_only_btn.isChecked() != enabled:
            self.menu_only_btn.blockSignals(True)
            self.menu_only_btn.setChecked(enabled)
            self.menu_only_btn.blockSignals(False)

        if enabled:
            self._normal_geometry = self.saveGeometry()
            self._normal_min_width = self.minimumWidth()
            self._normal_max_width = self.maximumWidth()

            self.content_area.hide()
            self._move_status_widgets_to_sidebar_footer()
            self.sidebar_footer.show()
            self.status_bar.hide()
            self.menu_only_btn.setText(tr("Normal View"))
            self.sidebar.setToolTip(tr("Double-click a menu item to open it."))
            self.setFixedWidth(self.sidebar_panel.width())
            return

        self.setMinimumWidth(self._normal_min_width)
        self.setMaximumWidth(self._normal_max_width)
        self.content_area.show()
        self.sidebar_footer.hide()
        self._move_status_widgets_to_status_bar()
        self.status_bar.show()
        self.menu_only_btn.setText(tr("Menu Only"))
        self.sidebar.setToolTip("")

        if self._normal_geometry is not None:
            self.restoreGeometry(self._normal_geometry)

        current_index = self.sidebar.currentRow()
        if current_index >= 0:
            self.on_tool_selected(current_index)

    def on_sidebar_item_double_clicked(self, item):
        """Open selected content on double-click while in menu-only mode."""
        index = self.sidebar.row(item)
        if not self._menu_only_mode:
            self.on_tool_selected(index)
            return

        if index >= 2:
            module_index = index - 2
            self._ensure_module_loaded(module_index)
            wrapper = self.module_widgets[module_index]
            if isinstance(wrapper, DetachableWidgetWrapper):
                if wrapper.is_detached:
                    window = wrapper.independent_window
                    if window is not None:
                        window.show()
                        window.raise_()
                        window.activateWindow()
                else:
                    wrapper.detach()
                return

        self.set_menu_only_mode(False)
        self.on_tool_selected(index)

    def on_tool_selected(self, index):
        if index < 0:
            return
        if self._menu_only_mode:
            return
        if index == 1:
            self._ensure_settings_loaded()
        elif index >= 2:
            self._ensure_module_loaded(index - 2)
        self.content_area.setCurrentIndex(index)

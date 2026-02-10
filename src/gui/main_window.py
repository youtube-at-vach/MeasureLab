import logging
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
from src.core.module_constants import ALL_MODULE_KEYS
from src.gui.module_loader import load_module_class
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper


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
        self.logger = logging.getLogger(__name__)
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

            # Find Input Device
            if last_in:
                found_in_id = self._find_device_id(devices, last_in, last_in_hostapi, is_input=True)
                if found_in_id is not None:
                    in_id = found_in_id
                else:
                    self.logger.warning(f"Saved input device '{last_in}' not found, using default.")

            # Find Output Device
            if last_out:
                found_out_id = self._find_device_id(devices, last_out, last_out_hostapi, is_input=False)
                if found_out_id is not None:
                    out_id = found_out_id
                else:
                    self.logger.warning(f"Saved output device '{last_out}' not found, using default.")

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
            self.logger.error(f"Failed to set devices/settings: {e}")
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
        self._module_keys = list(ALL_MODULE_KEYS)
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

        # Track offline mode state to update UI dynamically
        self._last_offline_mode = False
        # Initial check
        self._update_output_destination_ui_for_mode(self.audio_engine.offline_mode)
        self._last_offline_mode = self.audio_engine.offline_mode

    def _find_device_id(self, devices: list, name: str, hostapi: str, is_input: bool) -> Optional[int]:
        """Find device ID by name and hostapi, with fallback to name only."""
        if not name:
            return None

        # 1. Strict match (Name + HostAPI)
        for i, dev in enumerate(devices):
            # Check capabilities
            if is_input and dev["max_input_channels"] <= 0:
                continue
            if not is_input and dev["max_output_channels"] <= 0:
                continue

            if dev["name"] == name:
                # If hostapi is specified, strict match is required.
                if hostapi:
                    if dev.get("hostapi_name") == hostapi:
                        return i
                else:
                    # If hostapi is not specified, just match name
                    return i

        # 2. Loose match (Name only) - only needed if hostapi was specified
        if hostapi:
            for i, dev in enumerate(devices):
                if is_input and dev["max_input_channels"] <= 0:
                    continue
                if not is_input and dev["max_output_channels"] <= 0:
                    continue

                if dev["name"] == name:
                    return i

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
            cls = load_module_class(key)
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

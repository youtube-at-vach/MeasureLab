"""Simple VST3 launcher with native editor access and optional routing."""

from collections import Counter
from importlib.util import find_spec
import threading

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.localization import tr
from src.core.vst_discovery import VstScanResult, discover_vst3, vst3_search_paths


class _Scanner(threading.Thread):
    def __init__(self):
        # A slow/unavailable network folder must not hold up application exit.
        # Only the GUI timer reads the result, after this thread has finished.
        super().__init__(daemon=True)
        self.cancelled = threading.Event()
        self.result = VstScanResult()

    def run(self):
        self.result = discover_vst3(cancelled=self.cancelled.is_set)


class _Loader(QThread):
    failed = pyqtSignal(str)

    def __init__(self, dut, path, name, parent):
        super().__init__(parent)
        self.dut, self.path, self.name = dut, path, name
        self.succeeded = False

    def run(self):
        try:
            self.dut.load(self.path, self.name or None)
            self.succeeded = True
        except Exception as exc:
            self.failed.emit(str(exc))


class VstDutDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.dut = engine.vst_dut
        self.loader = None
        self.scanner = None
        self.discovered_paths = []
        self.setWindowTitle(tr("VST3 DUT"))
        self.resize(660, 380)
        self.host_available = find_spec("pedalboard") is not None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        status_font = self.status.font()
        status_font.setBold(True)
        self.status.setFont(status_font)
        layout.addWidget(self.status)
        info = QLabel(tr("Virtual output → VST3 → measurement input (one block later)."))
        info.setWordWrap(True)
        layout.addWidget(info)
        self.controls = QWidget()
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(12)
        plugin_group = QGroupBox(tr("VST3 plugin"))
        form = QFormLayout(plugin_group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setSpacing(8)
        controls_layout.addWidget(plugin_group)
        search_row = QHBoxLayout()
        self.plugin_search = QLineEdit()
        self.plugin_search.setClearButtonEnabled(True)
        self.plugin_search.setAccessibleName(tr("Search installed VST3 plugins"))
        self.plugin_search.setPlaceholderText(tr("Search installed VST3 plugins"))
        self.plugin_search.textChanged.connect(self._filter_plugins)
        search_row.addWidget(self.plugin_search)
        self.rescan_button = QPushButton(tr("Rescan"))
        self.rescan_button.clicked.connect(self._scan_plugins)
        search_row.addWidget(self.rescan_button)
        form.addRow(search_row)
        self.plugins = QComboBox()
        self.plugins.setMinimumWidth(0)
        self.plugins.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.plugins.activated.connect(self._select_plugin)
        form.addRow(tr("Installed VST3 plugins"), self.plugins)
        self.scan_status = QLabel()
        self.scan_status.setWordWrap(True)
        form.addRow(self.scan_status)
        self.advanced = QCheckBox(tr("Manual plugin selection"))
        form.addRow(self.advanced)
        self.manual = QWidget()
        manual_form = QFormLayout(self.manual)
        manual_form.setContentsMargins(0, 0, 0, 0)
        self.advanced.toggled.connect(self.manual.setVisible)
        self.manual.hide()
        form.addRow(self.manual)
        self.path = QLineEdit(self.dut.path)
        self.path.setAccessibleName(tr("Path to .vst3 file or bundle"))
        self.path.setPlaceholderText(tr("Path to .vst3 file or bundle"))
        browse = QPushButton(tr("Browse..."))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path)
        path_row.addWidget(browse)
        manual_form.addRow(path_row)
        self.plugin_name = QLineEdit()
        self.plugin_name.setPlaceholderText(tr("Plugin name inside bundle (optional)"))
        self.plugin_name.setAccessibleName(tr("Plugin name inside bundle (optional)"))
        manual_form.addRow(self.plugin_name)
        self.path.textChanged.connect(self._path_changed)
        buttons = QHBoxLayout()
        self.load_button = QPushButton(tr("Load VST3"))
        self.load_button.clicked.connect(self._load)
        buttons.addWidget(self.load_button)
        self.unload_button = QPushButton(tr("Unload"))
        self.unload_button.clicked.connect(self._unload)
        buttons.addWidget(self.unload_button)
        self.editor_button = QPushButton(tr("Open plugin editor"))
        self.editor_button.clicked.connect(self._toggle_editor)
        buttons.addWidget(self.editor_button)
        self.bypass = QCheckBox(tr("Bypass"))
        self.bypass.setChecked(self.dut.bypassed)
        self.bypass.toggled.connect(lambda value: self._edit(lambda: self.dut.set_bypassed(value)))
        buttons.addStretch()
        buttons.addWidget(self.bypass)
        form.addRow(buttons)

        self.routing_toggle = QCheckBox(tr("Routing"))
        controls_layout.addWidget(self.routing_toggle)
        self.routing = QWidget()
        self.routing_toggle.toggled.connect(self.routing.setVisible)
        self.routing.hide()
        controls_layout.addWidget(self.routing)
        route_layout = QHBoxLayout(self.routing)
        route_layout.setContentsMargins(0, 0, 0, 0)
        input_group = QGroupBox(tr("DUT inputs"))
        input_form = QFormLayout(input_group)
        input_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return_group = QGroupBox(tr("Measurement inputs"))
        return_form = QFormLayout(return_group)
        return_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        route_layout.addWidget(input_group, 1)
        route_layout.addWidget(return_group, 1)
        self.channels = QComboBox()
        self.channels.addItem(tr("Mono"), 1)
        self.channels.addItem(tr("Stereo"), 2)
        self.channels.setCurrentIndex(len(self.dut.input_routes) - 1)
        input_form.addRow(tr("DUT channels"), self.channels)
        self.inputs = []
        for index in range(2):
            combo = QComboBox()
            combo.addItem(tr("Output L"), 0)
            combo.addItem(tr("Output R"), 1)
            combo.addItem(tr("Silence"), -1)
            route = self.dut.input_routes[index] if index < len(self.dut.input_routes) else 1
            combo.setCurrentIndex(combo.findData(route))
            input_form.addRow(tr("DUT input {0}").format(index + 1), combo)
            self.inputs.append(combo)
        self.returns = []
        for index in range(2):
            combo = QComboBox()
            combo.addItem(tr("DUT output 1"), "wet1")
            combo.addItem(tr("DUT output 2"), "wet2")
            combo.addItem(tr("Output L (reference)"), "dry1")
            combo.addItem(tr("Output R (reference)"), "dry2")
            combo.addItem(tr("Silence"), "silence")
            combo.setCurrentIndex(combo.findData(self.dut.return_routes[index]))
            return_form.addRow(tr("Measurement input {0}").format("L" if index == 0 else "R"), combo)
            self.returns.append(combo)
        for combo in [self.channels, *self.inputs, *self.returns]:
            combo.currentIndexChanged.connect(self._routes_changed)
        self._update_mono_controls()

        layout.addWidget(self.controls)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("Close"))
        self.close_buttons.rejected.connect(self.reject)
        layout.addWidget(self.close_buttons)
        # Enter in a search/path field must never activate Load or Unload.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.plugin_search.setFocus()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(250)
        self._refresh()
        self._scan_plugins()

    def _scan_plugins(self):
        if self.scanner is not None:
            return
        self.scanner = _Scanner()
        self.rescan_button.setEnabled(False)
        self.scan_status.setText(tr("Scanning VST3 folders…"))
        self.scan_status.setToolTip("\n".join(str(path) for path in vst3_search_paths()))
        self.scanner.start()

    def _scanned(self):
        result = self.scanner.result
        self.scanner = None
        self.discovered_paths = result.paths
        self.rescan_button.setEnabled(True)
        self._filter_plugins()
        message = tr("Found {0} VST3 bundles. Compatibility is checked on load.").format(len(result.paths))
        if result.errors:
            message += "\n" + tr("Some folders could not be scanned. See tooltip for details.")
            self.scan_status.setToolTip(self.scan_status.toolTip() + "\n\n" + "\n".join(result.errors))
        self.scan_status.setText(message)

    def _filter_plugins(self):
        selected = self.path.text()
        query = self.plugin_search.text().strip().casefold()
        counts = Counter(path.stem.casefold() for path in self.discovered_paths)
        self.plugins.clear()
        self.plugins.addItem(tr("Select a VST3 plugin…"), None)
        for path in self.discovered_paths:
            if query and query not in str(path).casefold():
                continue
            label = path.stem
            if counts[label.casefold()] > 1:
                label += f" — {path.parent}"
            self.plugins.addItem(label, str(path))
            self.plugins.setItemData(self.plugins.count() - 1, str(path), Qt.ItemDataRole.ToolTipRole)
        if self.plugins.count() == 1:
            self.plugins.setItemText(0, tr("No matching plugins") if query else tr("No VST3 plugins found"))
        self.plugins.setEnabled(self.plugins.count() > 1)
        self.plugins.setCurrentIndex(max(0, self.plugins.findData(selected)))

    def _select_plugin(self, index):
        path = self.plugins.itemData(index)
        if path:
            if path != self.path.text():
                self.plugin_name.clear()
            self.path.setText(path)

    def _path_changed(self):
        self.plugin_name.clear()
        self.plugins.setCurrentIndex(max(0, self.plugins.findData(self.path.text())))
        self.path.setToolTip(self.path.text())
        self._refresh()

    def _browse(self):
        # macOS bundles can be selected as files using the native file dialog.
        path, _ = QFileDialog.getOpenFileName(self, tr("VST3 DUT"), self.path.text(), "VST3 (*.vst3)")
        if path:
            self.path.setText(path)

    def _load(self):
        if not self.controls.isEnabled() or not self.path.text().strip():
            return
        name = self.plugin_name.text().strip() if self.advanced.isChecked() else ""
        self.loader = _Loader(self.dut, self.path.text().strip(), name, self)
        self.loader.failed.connect(self._error)
        self.loader.finished.connect(self._loaded)
        self.loader.start()
        self._refresh()

    def _unload(self):
        self._edit(self.dut.close)
        self._refresh()

    def _toggle_editor(self):
        if not self.controls.isEnabled() or not self.dut.loaded or self.dut.error:
            return
        try:
            if self.dut.editor_open:
                self.dut.close_editor()
            else:
                self.dut.open_editor()
            self.engine.last_output_buffer = None
        except Exception as exc:
            self._error(tr("Could not open or close the plugin editor.") + "\n" + str(exc))
        self._refresh()

    def _close_editor(self):
        try:
            self.dut.close_editor()
        except Exception as exc:
            self._error(str(exc))

    def _loaded(self):
        succeeded = self.loader.succeeded
        self.loader.deleteLater()
        self.loader = None
        self.bypass.blockSignals(True)
        self.bypass.setChecked(self.dut.bypassed)
        self.bypass.blockSignals(False)
        self.engine.last_output_buffer = None
        self._refresh()
        if succeeded:
            self._toggle_editor()

    def _error(self, message):
        QMessageBox.warning(self, tr("VST3 DUT"), message)

    def _edit(self, action):
        try:
            action()
            self.engine.last_output_buffer = None
        except Exception as exc:
            self._error(str(exc))
        self._refresh()

    def _update_mono_controls(self):
        stereo = self.channels.currentData() == 2
        self.inputs[1].setEnabled(stereo)
        for combo in self.returns:
            combo.model().item(1).setEnabled(stereo)
            if not stereo and combo.currentData() == "wet2":
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)

    def _routes_changed(self):
        self._update_mono_controls()
        inputs = tuple(combo.currentData() for combo in self.inputs[: self.channels.currentData()])
        returns = tuple(combo.currentData() for combo in self.returns)
        self._edit(lambda: self.dut.set_routes(inputs, returns))

    def _refresh(self):
        if self.scanner is not None and not self.scanner.is_alive():
            self._scanned()
        loading = self.loader is not None
        available = self.engine.offline_mode and not self.engine.network_mode and not self.engine.is_audio_reserved()
        # Loading/routing/control changes are between measurement runs. This
        # prevents an unmarked discontinuity inside an FFT or swept capture.
        editable = available and not self.engine.callbacks and not loading
        try:
            if self.dut.poll_editor():
                self.engine.last_output_buffer = None
                if self.dut.editor_error:
                    self._error(tr("Could not open or close the plugin editor.") + "\n" + self.dut.editor_error)
            if self.dut.editor_open and not editable:
                self.dut.close_editor()
        except Exception as exc:
            self._error(str(exc))
        self.controls.setEnabled(editable)
        self.editor_button.setEnabled(self.dut.loaded and not self.dut.error)
        self.editor_button.setText(tr("Close plugin editor") if self.dut.editor_open else tr("Open plugin editor"))
        self.routing.setEnabled(not self.dut.editor_open)
        self.unload_button.setEnabled(self.dut.loaded)
        self.bypass.setEnabled(self.dut.loaded)
        self.load_button.setEnabled(bool(self.path.text().strip()))
        self.close_buttons.setEnabled(not loading)
        self.bypass.blockSignals(True)
        self.bypass.setChecked(self.dut.bypassed)
        self.bypass.blockSignals(False)
        if loading:
            self.status.setText(tr("Loading VST3…"))
        elif self.dut.error:
            self.status.setText(tr("DUT error; input is silent. Reload the plugin.") + "\n" + self.dut.error)
        elif self.dut.loaded:
            self.status.setText(
                self.dut.name
                + " — "
                + (tr("Bypass") if self.dut.bypassed else tr("Ready"))
                + "\n"
                + tr("Host startup padding: {0} samples").format(self.dut.padded_samples)
            )
        else:
            self.status.setText(tr("No DUT loaded. Select a plugin and click Load VST3."))
        if not available:
            self.notice.setText(tr("Enable Virtual Audio to use the DUT."))
        elif not editable and not loading:
            self.notice.setText(tr("Stop measurements before changing the DUT."))
        elif not self.host_available:
            self.notice.setText(tr("No DUT loaded. Install requirements-vst.txt to enable VST3 hosting."))
        elif self.dut.editor_open:
            self.notice.setText(tr("Edit the plugin in its own window, then close it before measuring."))
        else:
            self.notice.setText("")
        self.notice.setVisible(bool(self.notice.text()))

    def reject(self):
        if self.loader is None:
            self._close_editor()
            if self.scanner is not None:
                self.scanner.cancelled.set()
            super().reject()

    def closeEvent(self, event):
        if self.loader is not None:
            event.ignore()
        else:
            self._close_editor()
            if self.scanner is not None:
                self.scanner.cancelled.set()
            super().closeEvent(event)

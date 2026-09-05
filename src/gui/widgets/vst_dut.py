"""Small, generic VST3 DUT editor; does not embed a native plugin window."""

from collections import Counter
from importlib.util import find_spec
import threading

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QDialogButtonBox,
    QGroupBox,
    QSlider,
    QTabWidget,
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

    def run(self):
        try:
            self.dut.load(self.path, self.name or None)
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
        self.resize(720, 580)
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
        self.path = QLineEdit(self.dut.path)
        self.path.setAccessibleName(tr("Path to .vst3 file or bundle"))
        self.path.setPlaceholderText(tr("Path to .vst3 file or bundle"))
        browse = QPushButton(tr("Browse..."))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path)
        path_row.addWidget(browse)
        form.addRow(path_row)
        self.plugin_name = QLineEdit()
        self.plugin_name.setPlaceholderText(tr("Plugin name inside bundle (optional)"))
        self.plugin_name.setAccessibleName(tr("Plugin name inside bundle (optional)"))
        self.advanced = QCheckBox(tr("Plugin name inside bundle (optional)"))
        self.advanced.toggled.connect(self.plugin_name.setVisible)
        form.addRow(self.advanced)
        self.plugin_name.hide()
        form.addRow(self.plugin_name)
        self.path.textChanged.connect(self._path_changed)
        buttons = QHBoxLayout()
        self.load_button = QPushButton(tr("Load VST3"))
        self.load_button.clicked.connect(self._load)
        buttons.addWidget(self.load_button)
        self.unload_button = QPushButton(tr("Unload"))
        self.unload_button.clicked.connect(self._unload)
        buttons.addWidget(self.unload_button)
        self.bypass = QCheckBox(tr("Bypass"))
        self.bypass.setChecked(self.dut.bypassed)
        self.bypass.toggled.connect(lambda value: self._edit(lambda: self.dut.set_bypassed(value)))
        buttons.addStretch()
        buttons.addWidget(self.bypass)
        form.addRow(buttons)

        self.tabs = QTabWidget()
        controls_layout.addWidget(self.tabs)
        routing = QWidget()
        route_layout = QHBoxLayout(routing)
        input_group = QGroupBox(tr("DUT inputs"))
        input_form = QFormLayout(input_group)
        input_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return_group = QGroupBox(tr("Measurement inputs"))
        return_form = QFormLayout(return_group)
        return_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        route_layout.addWidget(input_group, 1)
        route_layout.addWidget(return_group, 1)
        self.tabs.addTab(routing, tr("Routing"))
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

        parameter_page = QWidget()
        parameter_form = QFormLayout(parameter_page)
        parameter_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        parameter_form.setSpacing(8)
        self.tabs.addTab(parameter_page, tr("Parameters"))
        self.parameter_search = QLineEdit()
        self.parameter_search.setPlaceholderText(tr("Search parameters"))
        self.parameter_search.setAccessibleName(tr("Search parameters"))
        self.parameter_search.setClearButtonEnabled(True)
        self.parameter_search.textChanged.connect(self._refresh_parameters)
        parameter_form.addRow(self.parameter_search)
        self.parameter = QComboBox()
        self.parameter.setMinimumWidth(0)
        self.parameter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.parameter.currentIndexChanged.connect(self._parameter_selected)
        parameter_form.addRow(tr("Parameter"), self.parameter)
        parameter_row = QHBoxLayout()
        self.value = QDoubleSpinBox()
        self.value.setRange(0, 1)
        self.value.setDecimals(6)
        self.value.setSingleStep(0.01)
        self.value.setKeyboardTracking(False)
        self.value.setAccessibleName(tr("Normalized value (0–1)"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setAccessibleName(tr("Normalized value (0–1)"))
        self.slider.valueChanged.connect(lambda value: self.value.setValue(value / 1000))
        self.value.valueChanged.connect(self._value_changed)
        parameter_row.addWidget(self.slider, 1)
        parameter_row.addWidget(self.value)
        self.apply = QPushButton(tr("Apply"))
        self.apply.clicked.connect(self._apply_parameter)
        parameter_row.addWidget(self.apply)
        parameter_form.addRow(tr("Normalized value (0–1)"), parameter_row)
        layout.addWidget(self.controls)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("Close"))
        self.close_buttons.rejected.connect(self.reject)
        layout.addWidget(self.close_buttons)
        # Enter in a search/value field must never activate Load or Unload.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.plugin_search.setFocus()
        self._refresh_parameters()
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
        self._refresh_parameters()
        self._refresh()

    def _loaded(self):
        self.loader.deleteLater()
        self.loader = None
        self.bypass.blockSignals(True)
        self.bypass.setChecked(self.dut.bypassed)
        self.bypass.blockSignals(False)
        self.engine.last_output_buffer = None
        self._refresh_parameters()
        self._refresh()

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

    def _refresh_parameters(self):
        selected = self.parameter.currentText()
        query = self.parameter_search.text().strip().casefold()
        names = [name for name in self.dut.parameters if query in name.casefold()]
        self.parameter.blockSignals(True)
        self.parameter.clear()
        self.parameter.addItems(names)
        self.parameter.setCurrentIndex(max(0, self.parameter.findText(selected)))
        self.parameter.blockSignals(False)
        self.parameter.setPlaceholderText(tr("No matching parameters") if query else tr("No parameters available"))
        self._parameter_selected()

    def _parameter_selected(self):
        self.parameter.setToolTip(self.parameter.currentText())
        self.value.setValue(self.dut.parameters.get(self.parameter.currentText(), 0))
        self._value_changed()

    def _value_changed(self):
        self.slider.blockSignals(True)
        self.slider.setValue(round(self.value.value() * 1000))
        self.slider.blockSignals(False)
        selected = self.parameter.currentText() in self.dut.parameters
        self.parameter.setEnabled(self.parameter.count() > 0)
        self.value.setEnabled(selected and not self.dut.error)
        self.slider.setEnabled(selected and not self.dut.error)
        self.apply.setEnabled(
            selected
            and not self.dut.error
            and self.value.value() != round(self.dut.parameters.get(self.parameter.currentText(), 0), 6)
        )

    def _apply_parameter(self):
        self._edit(lambda: self.dut.set_parameter(self.parameter.currentText(), self.value.value()))
        self._parameter_selected()

    def _refresh(self):
        if self.scanner is not None and not self.scanner.is_alive():
            self._scanned()
        loading = self.loader is not None
        available = self.engine.offline_mode and not self.engine.network_mode and not self.engine.is_audio_reserved()
        # Loading/routing/control changes are between measurement runs. This
        # prevents an unmarked discontinuity inside an FFT or swept capture.
        editable = available and not self.engine.callbacks and not loading
        self.controls.setEnabled(editable)
        self.unload_button.setEnabled(self.dut.loaded)
        self.bypass.setEnabled(self.dut.loaded)
        self.load_button.setEnabled(bool(self.path.text().strip()))
        self.close_buttons.setEnabled(not loading)
        self.bypass.blockSignals(True)
        self.bypass.setChecked(self.dut.bypassed)
        self.bypass.blockSignals(False)
        self._value_changed()
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
        else:
            self.notice.setText("")
        self.notice.setVisible(bool(self.notice.text()))

    def reject(self):
        if self.loader is None:
            if self.scanner is not None:
                self.scanner.cancelled.set()
            super().reject()

    def closeEvent(self, event):
        if self.loader is not None:
            event.ignore()
        else:
            if self.scanner is not None:
                self.scanner.cancelled.set()
            super().closeEvent(event)

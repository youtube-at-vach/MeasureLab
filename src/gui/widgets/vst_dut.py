"""Small, generic VST3 DUT editor; does not embed a native plugin window."""

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
        self.setWindowTitle(tr("VST3 DUT"))
        self.resize(620, 530)
        layout = QVBoxLayout(self)
        info = QLabel(tr("Virtual output → VST3 → measurement input (one block later)."))
        info.setWordWrap(True)
        layout.addWidget(info)
        self.controls = QWidget()
        form = QFormLayout(self.controls)
        self.path = QLineEdit(self.dut.path)
        self.path.setPlaceholderText(tr("Path to .vst3 file or bundle"))
        browse = QPushButton(tr("Browse..."))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path)
        path_row.addWidget(browse)
        form.addRow(path_row)
        self.plugin_name = QLineEdit()
        self.plugin_name.setPlaceholderText(tr("Plugin name inside bundle (optional)"))
        form.addRow(self.plugin_name)
        buttons = QHBoxLayout()
        self.load_button = QPushButton(tr("Load"))
        self.load_button.clicked.connect(self._load)
        buttons.addWidget(self.load_button)
        self.unload_button = QPushButton(tr("Unload"))
        self.unload_button.clicked.connect(lambda: self._edit(self.dut.close))
        buttons.addWidget(self.unload_button)
        self.bypass = QCheckBox(tr("Bypass"))
        self.bypass.setChecked(self.dut.bypassed)
        self.bypass.toggled.connect(lambda value: self._edit(lambda: self.dut.set_bypassed(value)))
        buttons.addWidget(self.bypass)
        form.addRow(buttons)

        self.channels = QComboBox()
        self.channels.addItem(tr("Mono"), 1)
        self.channels.addItem(tr("Stereo"), 2)
        self.channels.setCurrentIndex(len(self.dut.input_routes) - 1)
        form.addRow(tr("DUT channels"), self.channels)
        self.inputs = []
        for index in range(2):
            combo = QComboBox()
            combo.addItem(tr("Output L"), 0)
            combo.addItem(tr("Output R"), 1)
            combo.addItem(tr("Silence"), -1)
            route = self.dut.input_routes[index] if index < len(self.dut.input_routes) else 1
            combo.setCurrentIndex(combo.findData(route))
            form.addRow(tr("DUT input {0}").format(index + 1), combo)
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
            form.addRow(tr("Measurement input {0}").format("L" if index == 0 else "R"), combo)
            self.returns.append(combo)
        for combo in [self.channels, *self.inputs, *self.returns]:
            combo.currentIndexChanged.connect(self._routes_changed)
        self._update_mono_controls()

        self.parameter = QComboBox()
        self.parameter.setMinimumWidth(0)
        self.parameter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.parameter.currentIndexChanged.connect(self._parameter_selected)
        form.addRow(tr("Parameter"), self.parameter)
        parameter_row = QHBoxLayout()
        self.value = QDoubleSpinBox()
        self.value.setRange(0, 1)
        self.value.setDecimals(6)
        self.value.setSingleStep(0.01)
        parameter_row.addWidget(self.value)
        self.apply = QPushButton(tr("Apply"))
        self.apply.clicked.connect(self._apply_parameter)
        parameter_row.addWidget(self.apply)
        form.addRow(tr("Normalized value (0–1)"), parameter_row)
        layout.addWidget(self.controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self._refresh_parameters()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(250)
        self._refresh()

    def _browse(self):
        # macOS bundles can be selected as files using the native file dialog.
        path, _ = QFileDialog.getOpenFileName(self, tr("VST3 DUT"), self.path.text(), "VST3 (*.vst3)")
        if path:
            self.path.setText(path)

    def _load(self):
        self.loader = _Loader(self.dut, self.path.text(), self.plugin_name.text().strip(), self)
        self.loader.failed.connect(self._error)
        self.loader.finished.connect(self._loaded)
        self.loader.start()
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
        self.parameter.clear()
        self.parameter.addItems(list(self.dut.parameters))
        self._parameter_selected()

    def _parameter_selected(self):
        self.value.setValue(self.dut.parameters.get(self.parameter.currentText(), 0))

    def _apply_parameter(self):
        self._edit(lambda: self.dut.set_parameter(self.parameter.currentText(), self.value.value()))
        self._parameter_selected()

    def _refresh(self):
        loading = self.loader is not None
        available = self.engine.offline_mode and not self.engine.network_mode and not self.engine.is_audio_reserved()
        # Loading/routing/control changes are between measurement runs. This
        # prevents an unmarked discontinuity inside an FFT or swept capture.
        editable = available and not self.engine.callbacks and not loading
        self.controls.setEnabled(editable)
        self.unload_button.setEnabled(self.dut.loaded)
        self.bypass.setEnabled(self.dut.loaded)
        self.apply.setEnabled(bool(self.dut.parameters) and not self.dut.error)
        if loading:
            self.status.setText(tr("Loading VST3…"))
        elif self.dut.error:
            self.status.setText(tr("DUT error; input is silent. Reload the plugin.") + "\n" + self.dut.error)
        elif not available:
            self.status.setText(tr("Enable Virtual Audio to use the DUT."))
        elif not editable:
            self.status.setText(tr("Stop measurements before changing the DUT."))
        elif self.dut.loaded:
            self.status.setText(
                self.dut.name + "\n" + tr("Host startup padding: {0} samples").format(self.dut.padded_samples)
            )
        else:
            self.status.setText(tr("No DUT loaded. Install requirements-vst.txt to enable VST3 hosting."))

    def reject(self):
        if self.loader is None:
            super().reject()

    def closeEvent(self, event):
        if self.loader is not None:
            event.ignore()
        else:
            super().closeEvent(event)

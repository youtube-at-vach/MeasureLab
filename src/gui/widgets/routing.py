"""Infrastructure page for current connections and independent audition."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.localization import tr


def route_labels():
    return {
        "output_mix": tr("Output mix"),
        "dut_output": tr("DUT output"),
        "measurement_return": tr("Measurement return"),
        "measurement_input": tr("Measurement input"),
        "physical_input": tr("Physical input"),
        "physical_output": tr("Physical Output"),
        "physical_monitor": tr("Physical monitor"),
        "remote_input": tr("Remote input"),
        "remote_output": tr("Remote I/O Output"),
        "remote_client": tr("Remote client"),
        "silence": tr("Silence"),
        "vst_dut": tr("VST3 DUT"),
        "bypass": tr("Bypass"),
        "dut_input_mapping": tr("DUT inputs"),
        "return_mapping": tr("Measurement inputs"),
        "dry_reference": tr("Dry reference"),
        "one_block_delay": tr("One block delay"),
        "input_channels": tr("Input channels"),
        "output_channels": tr("Output channels"),
        "monitor_buffer": tr("Monitor buffer"),
        "monitor_gain": tr("Monitor volume"),
    }


def monitor_reason(reason):
    # Runtime driver/plugin errors remain verbatim. Engine-owned explanations
    # use literal translation keys so the key checker can verify every locale.
    return {
        "Physical monitoring requires virtual audio.": tr("Physical monitoring requires virtual audio."),
        "Load a DUT to monitor its output.": tr("Load a DUT to monitor its output."),
        "DUT error; reload the plugin.": tr("DUT error; reload the plugin."),
        "Select a physical output device.": tr("Select a physical output device."),
    }.get(reason, reason)


def state_labels():
    return {
        "off": tr("Off"),
        "waiting": tr("Waiting"),
        "playing": tr("Playing"),
        "dropout": tr("Audio dropout"),
        "unavailable": tr("Unavailable"),
        "error": tr("Error"),
    }


class RoutingWidget(QWidget):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.connections = QTableWidget(0, 4)
        self.connections.setHorizontalHeaderLabels([tr("Source"), tr("Processing"), tr("Destination"), tr("Status")])
        self.connections.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.connections.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.connections.verticalHeader().hide()
        self.connections.setAccessibleName(tr("Current audio connections"))
        layout.addWidget(self.connections, 1)

        self.output = QComboBox()
        self.output.setAccessibleName(tr("Output destination"))
        self.output.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.output.activated.connect(self._set_output)
        layout.addWidget(self.output)

        self.details_toggle = QCheckBox(tr("DUT routing details"))
        layout.addWidget(self.details_toggle)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.hide()
        self.details_toggle.toggled.connect(self.details.setVisible)
        layout.addWidget(self.details)

        group = QGroupBox(tr("Monitor Out"))
        form = QFormLayout(group)
        self.source = QComboBox()
        for source in ("dut_output", "measurement_return", "output_mix"):
            self.source.addItem(route_labels()[source], source)
        self.source.activated.connect(lambda: self._configure(source=self.source.currentData()))
        form.addRow(tr("Source"), self.source)
        device_row = QHBoxLayout()
        self.device = QComboBox()
        self.device.setMinimumWidth(0)
        self.device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.device.setAccessibleName(tr("Physical monitor device"))
        self.device.activated.connect(self._select_device)
        device_row.addWidget(self.device, 1)
        self.refresh_button = QPushButton(tr("Refresh"))
        self.refresh_button.clicked.connect(self.refresh_devices)
        device_row.addWidget(self.refresh_button)
        form.addRow(tr("Destination"), device_row)
        self.volume = QDoubleSpinBox()
        self.volume.setRange(-60, 0)
        self.volume.setDecimals(1)
        self.volume.setSuffix(" dB")
        self.volume.setValue(-20)
        self.volume.setAccessibleName(tr("Monitor volume"))
        self.volume.valueChanged.connect(lambda value: self._configure(gain_db=value))
        form.addRow(tr("Monitor volume"), self.volume)
        self.enabled = QCheckBox(tr("Monitor Out"))
        self.enabled.toggled.connect(self._toggle)
        form.addRow(self.enabled)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        form.addRow(self.status)
        note = QLabel(tr("Audition only: buffering and dropouts do not change measurement samples."))
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(group)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self._last_connections = None
        self._last_output_choices = None
        self.refresh_devices()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        self.refresh()

    def refresh_devices(self):
        selected = self.engine.monitor.route.device
        self.device.clear()
        self.device.addItem(tr("Select a physical output device."), None)
        try:
            for index, info in enumerate(self.engine.list_devices()):
                if info["max_output_channels"] > 0:
                    name = str(info["name"])
                    api = info.get("hostapi_name", "")
                    self.device.addItem(f"{name} ({api})" if api else name, index)
            self.device.setCurrentIndex(max(0, self.device.findData(selected)))
        except Exception as exc:
            self.error.setText(str(exc))

    def _select_device(self):
        if self.device.currentData() is not None:
            self._configure(device=self.device.currentData())

    def _configure(self, **settings):
        try:
            self.engine.configure_monitor(**settings)
            self.error.clear()
        except Exception as exc:
            self.error.setText(monitor_reason(str(exc)))
        self.refresh()

    def _toggle(self, enabled):
        try:
            self.engine.set_monitor_enabled(enabled)
            self.error.clear()
        except Exception as exc:
            self.error.setText(monitor_reason(str(exc)))
        self.refresh()

    def _set_output(self):
        try:
            self.engine.set_output_destination(self.output.currentData())
            self.error.clear()
        except Exception as exc:
            self.error.setText(str(exc))
        self.refresh()

    def refresh(self):
        snapshot = self.engine.routing_snapshot()
        labels, states = route_labels(), state_labels()
        backend = {
            "virtual": tr("Virtual Audio"),
            "local": tr("Physical I/O"),
            "remote_client": tr("Remote client"),
            "remote_provider": tr("Remote Audio I/O"),
        }.get(snapshot.backend, snapshot.backend)
        clock = {
            "virtual_timer": tr("Virtual timer"),
            "physical_device": tr("Physical device clock"),
            "remote_device": tr("Remote device clock"),
        }[snapshot.clock]
        devices = " → ".join(filter(None, (snapshot.input_device, snapshot.output_device)))
        if snapshot.backend == "virtual":
            devices = snapshot.dut_name
        modes = {"stereo": tr("Stereo"), "left": tr("Left"), "right": tr("Right")}
        channel_details = (
            (
                f"{tr('Input channels')}: {modes[snapshot.input_mode]} · "
                f"{tr('Output channels')}: {modes[snapshot.output_mode]}"
            )
            if snapshot.backend != "virtual"
            else ""
        )
        self.summary.setText(
            "\n".join(filter(None, (f"{backend} · {snapshot.sample_rate:g} Hz · {clock}", devices, channel_details)))
        )
        if snapshot.connections != self._last_connections:
            self.connections.setRowCount(len(snapshot.connections))
            for row, connection in enumerate(snapshot.connections):
                values = (
                    labels[connection.source],
                    " → ".join(labels[p] for p in connection.processors),
                    labels[connection.destination],
                    states[connection.state],
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(monitor_reason(connection.reason) or value)
                    self.connections.setItem(row, column, item)
            self.connections.resizeRowsToContents()
            self._last_connections = snapshot.connections
        network = snapshot.backend == "remote_client"
        output_name = tr("Remote I/O Output") if network else tr("Physical Output")
        input_only = any(c.destination == "remote_output" and c.state == "unavailable" for c in snapshot.connections)
        if input_only:
            output_name = tr("No Remote Output (Input Only)")
        combined = (
            tr("Internal Loopback (Remote Output Unavailable)")
            if input_only
            else tr("Loopback + Remote I/O Output")
            if network
            else tr("Loopback + Physical")
        )
        choices = (output_name, tr("Internal Loopback (Silent)"), combined)
        if choices != self._last_output_choices:
            self.output.clear()
            for name, value in zip(choices, ("physical", "loopback_silent", "loopback_mix"), strict=True):
                self.output.addItem(name, value)
            self._last_output_choices = choices
        self.output.setCurrentIndex(self.output.findData(snapshot.output_destination))
        self.output.setVisible(snapshot.output_editable)
        self.details_toggle.setVisible(bool(snapshot.dut_inputs))
        if snapshot.dut_inputs:
            inputs = {0: tr("Output L"), 1: tr("Output R"), -1: tr("Silence")}
            returns = {
                "wet1": tr("DUT output 1"),
                "wet2": tr("DUT output 2"),
                "dry1": tr("Output L (reference)"),
                "dry2": tr("Output R (reference)"),
                "silence": tr("Silence"),
            }
            lines = [
                f"{inputs[route]} → {tr('DUT input {0}').format(i + 1)}" for i, route in enumerate(snapshot.dut_inputs)
            ]
            lines += [
                f"{returns[route]} → {tr('Measurement input {0}').format(ch)}"
                for ch, route in zip(("L", "R"), snapshot.dut_returns, strict=True)
            ]
            self.details.setText("\n".join(lines))
        self.details.setVisible(bool(snapshot.dut_inputs) and self.details_toggle.isChecked())
        monitor = snapshot.monitor
        route = monitor.route
        self.enabled.blockSignals(True)
        self.enabled.setChecked(route.enabled)
        self.enabled.blockSignals(False)
        reason = self.engine.monitor_unavailable_reason()
        self.enabled.setEnabled(route.enabled or not reason)
        self.enabled.setToolTip(monitor_reason(reason))
        editable = snapshot.backend == "virtual" and not route.enabled
        self.source.setEnabled(editable)
        self.device.setEnabled(editable)
        self.refresh_button.setEnabled(editable)
        self.source.setCurrentIndex(self.source.findData(route.source))
        self.device.setCurrentIndex(max(0, self.device.findData(route.device)))
        self.volume.blockSignals(True)
        self.volume.setValue(route.gain_db)
        self.volume.blockSignals(False)
        self.status.setText(states[monitor.state] + (" — " + monitor_reason(monitor.reason) if monitor.reason else ""))
        self.status.setToolTip(
            tr("Dropped: {0} frames · Missing: {1} frames · Buffered: {2} frames").format(
                monitor.dropped_frames, monitor.missing_frames, monitor.buffered_frames
            )
        )

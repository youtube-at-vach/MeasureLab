"""Infrastructure page for current connections and independent audition."""

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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


def _label(text="", *, bold=False):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    font = label.font()
    font.setBold(bold)
    label.setFont(font)
    return label


class ConnectionView(QScrollArea):
    """Read-only signal paths, aligned from source to destination."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setProperty("measurelabScrollRole", "dynamic-content")
        self.setAccessibleName(tr("Current audio connections"))
        self.setMinimumHeight(100)
        self._connections = None

    def sizeHint(self):
        height = self.widget().sizeHint().height() + 4 if self.widget() is not None else 100
        return QSize(720, min(280, height))

    def set_connections(self, connections):
        if connections == self._connections:
            return
        self._connections = connections
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        labels, states = route_labels(), state_labels()
        for column, title in ((0, tr("Source")), (2, tr("Processing")), (4, tr("Destination")), (5, tr("Status"))):
            grid.addWidget(_label(title), 0, column)
        for column, stretch in ((0, 2), (2, 3), (4, 2), (5, 1)):
            grid.setColumnStretch(column, stretch)
        row = 1
        for connection in connections:
            for column, text in ((0, labels[connection.source]), (4, labels[connection.destination])):
                endpoint = _label(text, bold=True)
                endpoint.setMargin(10)
                endpoint.setStyleSheet(
                    "background: palette(base); color: palette(text);"
                    "border: 1px solid palette(mid); border-radius: 5px;"
                )
                grid.addWidget(endpoint, row, column)
            for column in (1, 3):
                arrow = _label("→")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(arrow, row, column)
            processing = _label(" → ".join(labels[p] for p in connection.processors) or "—")
            grid.addWidget(processing, row, 2)
            status = _label(states[connection.state], bold=True)
            reason = monitor_reason(connection.reason)
            status.setToolTip(reason or status.text())
            grid.addWidget(status, row, 5)
            row += 1
            if reason:
                grid.addWidget(_label(reason), row, 0, 1, 6)
                row += 1
        grid.setRowStretch(row, 1)
        old = self.takeWidget()
        if old is not None:
            old.deleteLater()
        self.setWidget(content)
        self.updateGeometry()


class RoutingWidget(QWidget):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        title = _label(tr("Routing"), bold=True)
        font = title.font()
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() + 5)
        else:
            font.setPixelSize(font.pixelSize() + 5)
        title.setFont(font)
        heading.addWidget(title)
        heading.addStretch()
        self.backend_label = _label(bold=True)
        heading.addWidget(self.backend_label)
        layout.addLayout(heading)
        self.summary = _label()
        layout.addWidget(self.summary)

        flow_group = QGroupBox(tr("Signal flow"))
        flow_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        flow_layout = QVBoxLayout(flow_group)
        flow_layout.setSpacing(8)
        self.device_summary = _label()
        flow_layout.addWidget(self.device_summary)
        self.connections = ConnectionView()
        flow_layout.addWidget(self.connections, 1)

        self.output_row = QWidget()
        output_layout = QFormLayout(self.output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.output = QComboBox()
        self.output.setAccessibleName(tr("Output destination"))
        self.output.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.output.activated.connect(self._set_output)
        output_layout.addRow(tr("Output destination"), self.output)
        flow_layout.addWidget(self.output_row)

        self.details_toggle = QCheckBox(tr("DUT routing details"))
        self.details_toggle.setProperty("measurelabLayoutAuditExpand", True)
        flow_layout.addWidget(self.details_toggle)
        self.details = _label()
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.hide()
        self.details_toggle.toggled.connect(self.details.setVisible)
        flow_layout.addWidget(self.details)
        layout.addWidget(flow_group)

        group = QGroupBox(tr("Monitor Out"))
        monitor_layout = QVBoxLayout(group)
        monitor_layout.setSpacing(10)
        self.monitor_path = _label(bold=True)
        monitor_layout.addWidget(self.monitor_path)
        controls = QGridLayout()
        controls.setHorizontalSpacing(16)
        controls.setVerticalSpacing(6)
        self.source = QComboBox()
        self.source.setAccessibleName(tr("Source"))
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for source in ("dut_output", "measurement_return", "output_mix"):
            self.source.addItem(route_labels()[source], source)
        self.source.activated.connect(lambda: self._configure(source=self.source.currentData()))
        source_label = _label(tr("Source"))
        source_label.setBuddy(self.source)
        controls.addWidget(source_label, 0, 0)
        controls.addWidget(self.source, 1, 0)
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
        device_label = _label(tr("Physical monitor device"))
        device_label.setBuddy(self.device)
        controls.addWidget(device_label, 0, 1)
        controls.addLayout(device_row, 1, 1)
        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(1, 2)
        monitor_layout.addLayout(controls)

        action_row = QHBoxLayout()
        self.volume = QDoubleSpinBox()
        self.volume.setRange(-60, 0)
        self.volume.setDecimals(1)
        self.volume.setSuffix(" dB")
        self.volume.setValue(-20)
        self.volume.setAccessibleName(tr("Monitor volume"))
        self.volume.valueChanged.connect(lambda value: self._configure(gain_db=value))
        volume_label = _label(tr("Monitor volume"))
        volume_label.setBuddy(self.volume)
        action_row.addWidget(volume_label)
        action_row.addWidget(self.volume)
        action_row.addSpacing(16)
        self.enabled = QCheckBox(tr("Enable monitoring"))
        self.enabled.toggled.connect(self._toggle)
        action_row.addWidget(self.enabled)
        action_row.addStretch()
        monitor_layout.addLayout(action_row)
        self.status = _label(bold=True)
        self.status.setAccessibleName(tr("Status"))
        monitor_layout.addWidget(self.status)
        self.monitor_hint = _label()
        monitor_layout.addWidget(self.monitor_hint)
        note = _label(tr("Audition only: buffering and dropouts do not change measurement samples."))
        monitor_layout.addWidget(note)
        layout.addWidget(group)
        self.error = _label(bold=True)
        self.error.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addStretch()
        self._last_output_choices = None
        self.refresh_devices()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        self.refresh()

    def _set_error(self, message):
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def refresh_devices(self):
        selected = self.engine.monitor.route.device
        self._set_error("")
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
            self._set_error(str(exc))

    def _select_device(self):
        if self.device.currentData() is not None:
            self._configure(device=self.device.currentData())

    def _configure(self, **settings):
        try:
            self.engine.configure_monitor(**settings)
            self._set_error("")
        except Exception as exc:
            self._set_error(monitor_reason(str(exc)))
        self.refresh()

    def _toggle(self, enabled):
        try:
            self.engine.set_monitor_enabled(enabled)
            self._set_error("")
        except Exception as exc:
            self._set_error(monitor_reason(str(exc)))
        self.refresh()

    def _set_output(self):
        try:
            self.engine.set_output_destination(self.output.currentData())
            self._set_error("")
        except Exception as exc:
            self._set_error(str(exc))
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
        self.backend_label.setText(backend)
        self.summary.setText(f"{snapshot.sample_rate:g} Hz · {clock}")
        modes = {"stereo": tr("Stereo"), "left": tr("Left"), "right": tr("Right")}
        if snapshot.backend == "virtual":
            device_text = f"{tr('VST3 DUT')}: {snapshot.dut_name}" if snapshot.dut_name else ""
        else:
            device_text = (
                f"{tr('Physical input') if snapshot.backend != 'remote_client' else tr('Remote input')}: "
                f"{snapshot.input_device or '—'} · {modes[snapshot.input_mode]}\n"
                f"{tr('Physical Output') if snapshot.backend != 'remote_client' else tr('Remote I/O Output')}: "
                f"{snapshot.output_device or '—'} · {modes[snapshot.output_mode]}"
            )
        self.device_summary.setText(device_text)
        self.device_summary.setVisible(bool(device_text))
        self.connections.set_connections(tuple(c for c in snapshot.connections if c.destination != "physical_monitor"))
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
        self.output_row.setVisible(snapshot.output_editable)
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
        self.monitor_path.setText(
            f"{labels[route.source]} → {tr('Monitor buffer')} → {tr('Monitor volume')} → {tr('Physical monitor')}"
        )
        self.monitor_path.setVisible(snapshot.backend == "virtual")
        self.enabled.blockSignals(True)
        self.enabled.setChecked(route.enabled)
        self.enabled.blockSignals(False)
        reason = self.engine.monitor_unavailable_reason()
        self.enabled.setEnabled(route.enabled or not reason)
        self.enabled.setToolTip(monitor_reason(reason))
        editable = snapshot.backend == "virtual" and not route.enabled
        hint = (
            monitor_reason(reason)
            if reason and not route.enabled and reason != monitor.reason
            else tr("Turn monitoring off to change source or device.")
            if route.enabled
            else ""
        )
        if monitor.state == "waiting" and route.enabled:
            hint = tr("Monitoring waits for a generator or measurement to start.") + " " + hint
        self.monitor_hint.setText(hint)
        self.monitor_hint.setVisible(bool(hint))
        self.source.setToolTip(hint if not editable else "")
        self.volume.setEnabled(snapshot.backend == "virtual")
        self.source.setEnabled(editable)
        self.device.setEnabled(editable)
        self.refresh_button.setEnabled(editable)
        self.source.setCurrentIndex(self.source.findData(route.source))
        self.device.setCurrentIndex(max(0, self.device.findData(route.device)))
        self.device.setToolTip(hint if not editable else self.device.currentText())
        self.volume.blockSignals(True)
        self.volume.setValue(route.gain_db)
        self.volume.blockSignals(False)
        self.status.setText(states[monitor.state] + (" — " + monitor_reason(monitor.reason) if monitor.reason else ""))
        self.status.setToolTip(
            tr("Dropped: {0} frames · Missing: {1} frames · Buffered: {2} frames").format(
                monitor.dropped_frames, monitor.missing_frames, monitor.buffered_frames
            )
        )

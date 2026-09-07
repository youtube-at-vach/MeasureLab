"""Infrastructure page for current connections and independent audition."""

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
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
    QToolButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.localization import tr


def route_labels():
    return {
        "output_mix": tr("Output mix"),
        "dut_output": tr("DUT output"),
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
    """Display fixed engine paths, with explicit access to their channel mapping."""

    edit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setProperty("measurelabScrollRole", "dynamic-content")
        self.setAccessibleName(tr("Current audio connections"))
        self.setMinimumHeight(115)
        self._connections = None

    def sizeHint(self):
        height = self.widget().sizeHint().height() + 4 if self.widget() is not None else 115
        return QSize(760, min(330, height))

    def set_snapshot(self, snapshot):
        connections = tuple(c for c in snapshot.connections if c.destination != "physical_monitor")
        identity = (
            connections,
            snapshot.dut_name,
            snapshot.dut_returns,
            snapshot.input_mode,
            snapshot.output_mode,
            snapshot.monitor.state,
        )
        if identity == self._connections:
            return
        self._connections = identity
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        labels, states = route_labels(), state_labels()
        for column, title in ((0, tr("Source")), (2, tr("Processing")), (4, tr("Destination"))):
            grid.addWidget(_label(title), 0, column)
            grid.setColumnStretch(column, 1)
        # Join the DUT bus and its wet return into one readable path. Dry
        # references stay separate: they never pass through the plugin.
        dut_feed = next((c for c in connections if c.destination == "dut_output"), None)
        wet_return = next((c for c in connections if c.source == "dut_output"), None)
        row = 1
        monitor_tap_shown = False
        for connection in connections:
            if connection is dut_feed and wet_return is not None:
                continue
            source = connection.source
            processors = connection.processors
            if connection is wet_return and dut_feed is not None:
                source = dut_feed.source
                processors = dut_feed.processors + processors
            for column in (0, 2, 4):
                card = QFrame()
                card.setObjectName("routingNode")
                card.setStyleSheet(
                    "QFrame#routingNode {background: palette(base); border: 1px solid palette(mid);border-radius: 8px;}"
                )
                box = QVBoxLayout(card)
                box.setContentsMargins(12, 8, 12, 8)
                box.setSpacing(4)
                if column == 0:
                    box.addWidget(_label(labels[source], bold=True))
                    if source == "output_mix":
                        box.addWidget(
                            _label(
                                tr("Same generator signal")
                                if "dry_reference" in processors
                                else tr("MeasureLab generators")
                            )
                        )
                elif column == 2:
                    has_dut = "vst_dut" in processors or "bypass" in processors
                    title = (
                        tr("Bypass")
                        if "bypass" in processors
                        else tr("VST3 DUT")
                        if has_dut
                        else tr("Dry reference")
                        if "dry_reference" in processors
                        else tr("Internal loopback")
                        if "one_block_delay" in processors
                        else labels[processors[0]]
                        if processors
                        else tr("Direct")
                    )
                    box.addWidget(_label(title, bold=True))
                    if has_dut:
                        name = _label(snapshot.dut_name)
                        name.setMaximumHeight(name.fontMetrics().lineSpacing() * 2 + 4)
                        name.setToolTip(snapshot.dut_name)
                        box.addWidget(name)
                    if "one_block_delay" in processors:
                        box.addWidget(_label(tr("One block delay")))
                    modes = {"stereo": tr("Stereo"), "left": tr("Left"), "right": tr("Right")}
                    if "input_channels" in processors:
                        box.addWidget(_label(modes[snapshot.input_mode]))
                    if "output_channels" in processors:
                        box.addWidget(_label(modes[snapshot.output_mode]))
                    if has_dut:
                        edit = QPushButton(tr("Edit channel routing…"))
                        edit.clicked.connect(self.edit_requested)
                        box.addWidget(edit)
                else:
                    if connection.destination == "measurement_input":
                        box.addWidget(_label(tr("MeasureLab analysis"), bold=True))
                        if snapshot.dut_returns:
                            returns = {
                                "wet1": tr("DUT output 1"),
                                "wet2": tr("DUT output 2"),
                                "dry1": tr("Output L (reference)"),
                                "dry2": tr("Output R (reference)"),
                                "silence": tr("Silence"),
                            }
                            for channel, route in zip(("L", "R"), snapshot.dut_returns, strict=True):
                                belongs = (
                                    route.startswith("wet")
                                    if connection.source == "dut_output"
                                    else route.startswith("dry")
                                    if "dry_reference" in processors
                                    else route == "silence"
                                )
                                # A mixed wet/dry + silence return has no separate
                                # engine connection; show its silent channel here.
                                if route == "silence" and (connection is wet_return or wet_return is None):
                                    belongs = True
                                if belongs:
                                    box.addWidget(
                                        _label(f"{returns[route]} → {tr('Measurement input {0}').format(channel)}")
                                    )
                        else:
                            box.addWidget(_label(labels[connection.destination]))
                    else:
                        box.addWidget(_label(labels[connection.destination], bold=True))
                    box.addWidget(
                        _label(tr("Waiting for audio") if connection.state == "waiting" else states[connection.state])
                    )
                if (
                    snapshot.backend == "virtual"
                    and column == 4
                    and connection.destination == "measurement_input"
                    and not monitor_tap_shown
                ):
                    monitor_tap_shown = True
                    outlet = _label(
                        f"↓ {tr('Monitor Out')} · {tr('Measurement input {0}').format('L / R')} · {states[snapshot.monitor.state]}",
                        bold=True,
                    )
                    outlet.setStyleSheet("border-top: 1px solid palette(mid); padding-top: 5px;")
                    box.addWidget(outlet)
                box.addStretch()
                grid.addWidget(card, row, column)
            for column in (1, 3):
                arrow = _label("→", bold=True)
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setFixedWidth(24)
                font = arrow.font()
                font.setPixelSize(22)
                arrow.setFont(font)
                grid.addWidget(arrow, row, column)
            row += 1
            if connection.reason:
                reason = _label(monitor_reason(connection.reason))
                reason.setMaximumHeight(reason.fontMetrics().lineSpacing() * 2 + 4)
                reason.setToolTip(reason.text())
                grid.addWidget(reason, row, 0, 1, 5)
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

        self.details_toggle = QToolButton()
        self.details_toggle.setText(tr("Show channel settings"))
        self.details_toggle.setCheckable(True)
        self.details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.details_toggle.toggled.connect(
            lambda checked: self.details_toggle.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
            )
        )
        self.details_toggle.setToolTip(tr("DUT routing details"))
        self.details_toggle.setProperty("measurelabLayoutAuditExpand", True)
        flow_layout.addWidget(self.details_toggle)
        self.details = self._create_dut_routes()
        self.details.hide()
        self.details_toggle.toggled.connect(self.details.setVisible)
        flow_layout.addWidget(self.details)
        self.connections.edit_requested.connect(lambda: self.details_toggle.setChecked(True))
        plugin_row = QHBoxLayout()
        self.flow_hint = _label()
        plugin_row.addWidget(self.flow_hint, 1)
        self.plugin_button = QPushButton(tr("VST3 plugin"))
        self.plugin_button.clicked.connect(self._open_plugin)
        plugin_row.addWidget(self.plugin_button)
        flow_layout.addLayout(plugin_row)
        layout.addWidget(flow_group)

        group = QGroupBox(tr("Monitor Out"))
        monitor_layout = QVBoxLayout(group)
        monitor_layout.setSpacing(10)
        self.monitor_path = _label(bold=True)
        monitor_layout.addWidget(self.monitor_path)
        controls = QGridLayout()
        controls.setHorizontalSpacing(16)
        controls.setVerticalSpacing(6)
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
        controls.addWidget(device_label, 0, 0)
        controls.addLayout(device_row, 1, 0)
        controls.setColumnStretch(0, 1)
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
        self.enabled.setStyleSheet(
            "QCheckBox::indicator {width: 14px; height: 14px;}"
            "QCheckBox::indicator:unchecked {border: 1px solid palette(text);"
            "background: palette(base); border-radius: 2px;}"
        )
        self.enabled.toggled.connect(self._toggle)
        action_row.addWidget(self.enabled)
        action_row.addStretch()
        self.status = _label(bold=True)
        self.status.setAccessibleName(tr("Status"))
        action_row.addWidget(self.status, 1)
        monitor_layout.addLayout(action_row)
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

    def _create_dut_routes(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.route_controls = QWidget()
        groups = QHBoxLayout(self.route_controls)
        groups.setContentsMargins(0, 0, 0, 0)
        input_group = QGroupBox(tr("DUT inputs"))
        input_form = QFormLayout(input_group)
        return_group = QGroupBox(tr("Measurement inputs"))
        return_form = QFormLayout(return_group)
        for form in (input_form, return_form):
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        groups.addWidget(input_group, 1)
        groups.addWidget(return_group, 1)
        self.channels = QComboBox()
        self.channels.addItem(tr("Mono"), 1)
        self.channels.addItem(tr("Stereo"), 2)
        self.channels.setAccessibleName(tr("DUT channels"))
        input_form.addRow(tr("DUT channels"), self.channels)
        self.inputs = []
        for index in range(2):
            combo = QComboBox()
            for name, value in ((tr("Output L"), 0), (tr("Output R"), 1), (tr("Silence"), -1)):
                combo.addItem(name, value)
            name = tr("DUT input {0}").format(index + 1)
            combo.setAccessibleName(name)
            input_form.addRow(name, combo)
            self.inputs.append(combo)
        self.returns = []
        for index in range(2):
            combo = QComboBox()
            for name, value in (
                (tr("DUT output 1"), "wet1"),
                (tr("DUT output 2"), "wet2"),
                (tr("Output L (reference)"), "dry1"),
                (tr("Output R (reference)"), "dry2"),
                (tr("Silence"), "silence"),
            ):
                combo.addItem(name, value)
            name = tr("Measurement input {0}").format("L" if index == 0 else "R")
            combo.setAccessibleName(name)
            return_form.addRow(name, combo)
            self.returns.append(combo)
        for combo in (self.channels, *self.inputs, *self.returns):
            combo.setMinimumWidth(0)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.activated.connect(self._routes_changed)
        layout.addWidget(self.route_controls)
        self.route_notice = _label()
        layout.addWidget(self.route_notice)
        return panel

    def _routes_editable(self):
        return (
            self.engine.offline_mode
            and not self.engine.network_mode
            and not self.engine.is_audio_reserved()
            and not self.engine.callbacks
        )

    def _refresh_dut_routes(self):
        dut = self.engine.vst_dut
        values = (
            len(dut.input_routes),
            *dut.input_routes,
            *(() if len(dut.input_routes) == 2 else (1,)),
            *dut.return_routes,
        )
        for combo, value in zip((self.channels, *self.inputs, *self.returns), values, strict=True):
            # Never rebuild options on the refresh timer: open menus and keyboard
            # focus must survive status updates. Only user activation writes routes.
            combo.setCurrentIndex(combo.findData(value))
        stereo = len(dut.input_routes) == 2
        self.inputs[1].setEnabled(stereo)
        for combo in self.returns:
            combo.model().item(1).setEnabled(stereo)
        editable = self._routes_editable()
        self.route_controls.setEnabled(editable)
        self.route_notice.setText(
            tr("Stop measurements before loading or routing the DUT.")
            if not editable
            else tr("No DUT loaded. Select a plugin and click Load VST3.")
            if not dut.loaded
            else ""
        )
        self.route_notice.setVisible(bool(self.route_notice.text()))

    def _routes_changed(self):
        # Check at activation too: measurement ownership can change between ticks.
        if not self._routes_editable():
            self.refresh()
            return
        count = self.channels.currentData()
        inputs = tuple(combo.currentData() for combo in self.inputs[:count])
        returns = tuple(
            "wet1" if count == 1 and combo.currentData() == "wet2" else combo.currentData() for combo in self.returns
        )
        try:
            self.engine.vst_dut.set_routes(inputs, returns)
            self.engine.last_output_buffer = None
            self._set_error("")
        except Exception as exc:
            self._set_error(str(exc))
        self.refresh()

    def _open_plugin(self):
        from src.gui.widgets.vst_dut import VstDutDialog

        dialog = VstDutDialog(self.engine, self)
        dialog.exec()
        if dialog.scanner is not None:
            dialog.scanner.cancelled.set()
        dialog.deleteLater()
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
        states = state_labels()
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
            device_text = ""
        else:
            device_text = (
                f"{tr('Physical input') if snapshot.backend != 'remote_client' else tr('Remote input')}: "
                f"{snapshot.input_device or '—'} · {modes[snapshot.input_mode]}\n"
                f"{tr('Physical Output') if snapshot.backend != 'remote_client' else tr('Remote I/O Output')}: "
                f"{snapshot.output_device or '—'} · {modes[snapshot.output_mode]}"
            )
        self.device_summary.setText(device_text)
        self.device_summary.setVisible(bool(device_text))
        self.connections.set_snapshot(snapshot)
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
        virtual = snapshot.backend == "virtual"
        self.details_toggle.setVisible(virtual)
        self.details.setVisible(virtual and self.details_toggle.isChecked())
        self.plugin_button.setVisible(virtual)
        self.flow_hint.setText(
            tr("VST3 processes the generator signal in Virtual Audio.")
            if virtual
            else tr("Input goes to analysis. Generators feed the output independently.")
            if snapshot.backend != "remote_provider"
            else tr("Remote Audio I/O")
        )
        self._refresh_dut_routes()
        monitor = snapshot.monitor
        route = monitor.route
        self.monitor_path.setText(
            f"↳ {tr('Monitor Out')} · {states[monitor.state]}: {tr('Measurement input {0}').format('L / R')} → {tr('Physical monitor')}: "
            f"{route.device_name or tr('Select a physical output device.')}"
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
            else tr("Turn monitoring off to change the device.")
            if route.enabled
            else ""
        )
        if monitor.state == "waiting" and route.enabled:
            hint = tr("Monitoring waits for a generator or measurement to start.") + " " + hint
        self.monitor_hint.setText(hint)
        self.monitor_hint.setVisible(bool(hint))
        self.volume.setEnabled(snapshot.backend == "virtual")
        self.device.setEnabled(editable)
        self.refresh_button.setEnabled(editable)
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

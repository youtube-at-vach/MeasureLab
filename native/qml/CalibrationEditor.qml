import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: editor
    required property var source
    required property var messages
    property string encoded: source ? source.calibration : ""
    readonly property var configuration: encoded ? JSON.parse(encoded) : null
    property double draftGeneration: 0
    property bool invalidDraft: false
    property alias channel: channelBox.currentIndex
    property alias factorText: factor.text
    property alias profileRevision: revision.text
    property alias calibrated: calibratedBox.checked
    readonly property bool canApply: source && source.state === 2 && configuration
        && configuration.generation === draftGeneration && configuration.status !== "queued"
    function labelsFit() { return !bindingLabel.truncated && applyButton.width >= applyButton.implicitWidth
        && closeButton.width >= closeButton.implicitWidth; }
    readonly property var displayedText: ({title: title, channel: channelLabel.text, factor: factorLabel.text,
        revision: revisionLabel.text, calibrated: calibratedBox.text, apply: applyButton.text, close: closeButton.text,
        note: note.text, status: statusLabel.text})
    modal: true
    title: tr("migration.display.calibration_edit")
    width: Math.max(480, form.implicitWidth + 48)
    height: implicitHeight
    function tr(key) { return messages[key] || ""; }
    onSourceChanged: close()
    onConfigurationChanged: {
        if (visible && (!configuration || configuration.generation !== draftGeneration))
            close();
    }
    onOpened: {
        draftGeneration = configuration ? configuration.generation : 0;
        channel = 0;
        loadChannel();
    }
    function loadChannel() {
        if (!configuration || !configuration.channels[channel])
            return;
        const id = configuration.channels[channel].channel_id;
        const profile = configuration.profiles.find(p => p.channel_id === id);
        factor.text = profile ? profile.v_per_fs.toString() : "1";
        revision.text = profile ? profile.revision : "qt.profile.1";
        calibratedBox.checked = profile ? profile.is_calibrated : false;
        invalidDraft = false;
    }
    function submission() {
        if (!canApply || !configuration.channels[channel])
            return null;
        const value = Number(factor.text);
        if (!factor.text.trim() || !Number.isFinite(value) || value <= 0 || !revision.text.trim())
            return null;
        const selected = configuration.channels[channel];
        const profiles = configuration.profiles.filter(p => p.channel_id !== selected.channel_id);
        profiles.push({channel_id: selected.channel_id, revision: revision.text,
            device_binding: selected.device_binding, is_calibrated: calibratedBox.checked, v_per_fs: value});
        return {generation: draftGeneration, revision: configuration.revision + 1, profiles: profiles};
    }
    function applyDraft() {
        const request = submission();
        invalidDraft = !request || !source.apply_calibration(JSON.stringify(request));
        return !invalidDraft;
    }
    contentItem: Rectangle {
        implicitWidth: form.implicitWidth
        implicitHeight: form.implicitHeight
        color: "#f3f6fa"
        ColumnLayout {
            id: form
            anchors.fill: parent
            spacing: 12
            GridLayout {
                columns: 2
                Label { id: channelLabel; text: editor.tr("migration.display.calibration_channel") }
                ComboBox {
                    id: channelBox
                    Layout.fillWidth: true
                    model: editor.configuration ? editor.configuration.channels.map(c => c.channel_id) : []
                    onActivated: editor.loadChannel()
                }
                Label { id: factorLabel; text: editor.tr("migration.display.calibration_factor") }
                TextField { id: factor; Layout.fillWidth: true; Layout.preferredWidth: 240; selectByMouse: true }
                Label { id: revisionLabel; text: editor.tr("migration.display.calibration_revision") }
                TextField { id: revision; Layout.fillWidth: true; selectByMouse: true }
            }
            Label {
                id: bindingLabel
                Layout.fillWidth: true
                elide: Text.ElideRight
                text: editor.configuration && editor.configuration.channels[editor.channel]
                    ? editor.tr("migration.display.calibration_binding")
                        .arg(editor.configuration.channels[editor.channel].device_binding.device)
                        .arg(editor.configuration.channels[editor.channel].device_binding.port) : ""
                ToolTip.visible: bindingHover.hovered
                ToolTip.text: text
                HoverHandler { id: bindingHover }
            }
            CheckBox { id: calibratedBox; text: editor.tr("migration.display.calibration_enabled") }
            Label {
                id: note
                text: editor.tr("migration.display.calibration_note")
                Layout.fillWidth: true
                Layout.preferredWidth: 430
                wrapMode: Text.WordWrap
            }
            Label {
                id: statusLabel
                Layout.fillWidth: true
                Layout.preferredWidth: 430
                wrapMode: Text.WordWrap
                text: editor.invalidDraft || (editor.configuration && editor.configuration.status === "rejected")
                    ? editor.tr("migration.display.calibration_rejected")
                    : !editor.configuration ? ""
                    : editor.configuration.status === "queued" ? editor.tr("migration.display.calibration_queued")
                    : editor.configuration.status === "applied" ? editor.tr("migration.display.calibration_applied")
                    : editor.configuration.status === "cancelled" ? editor.tr("migration.display.calibration_cancelled") : ""
            }
        }
    }
    footer: DialogButtonBox {
        Button { id: applyButton; text: editor.tr("migration.display.calibration_apply"); enabled: editor.canApply; onClicked: editor.applyDraft() }
        Button { id: closeButton; text: editor.tr("migration.display.calibration_close"); onClicked: editor.close() }
    }
}

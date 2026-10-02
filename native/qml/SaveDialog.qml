import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    required property var source
    required property var messages
    property var selected: null
    property alias destination: path.text
    property alias formatIndex: format.currentIndex
    property string encoded: source ? source.saves : ""
    property double selectedOperation: 0
    property double lastOperation: 0
    readonly property var report: encoded ? JSON.parse(encoded) : ({receipts: [], closed: false, rejection: null})
    readonly property var receipt: report.receipts.find(r => r.operation_id === selectedOperation) || null
    readonly property bool canSave: source && selected && !report.closed && !!destination.trim()
    readonly property var displayedText: ({title: title, path: pathLabel.text, format: formatLabel.text,
        note: note.text, save: saveButton.text, cancel: cancelButton.text, finish: finishButton.text,
        close: closeButton.text, status: statusLabel.text})
    modal: true
    title: tr("migration.display.save_measurement")
    width: Math.max(560, form.implicitWidth + 48)
    height: implicitHeight
    function tr(key) { return messages[key] || ""; }
    function status(value) {
        switch (value) {
        case "queued": return tr("migration.display.save_queued");
        case "writing": return tr("migration.display.save_writing");
        case "saved": return tr("migration.display.save_saved");
        case "failed": return tr("migration.display.save_failed");
        case "cancelled": return tr("migration.display.save_cancelled");
        }
        return "";
    }
    function labelsFit() { return [saveButton, cancelButton, finishButton, closeButton].every(b => b.width >= b.implicitWidth)
        && form.width >= pathLabel.implicitWidth + path.implicitWidth + 12; }
    function selectResult(frame) {
        if (!source || !frame || !source.pin_result(frame.source.generation, frame.result_id))
            return false;
        selected = frame;
        source.poll_saves();
        open();
        return true;
    }
    function submit() {
        if (!canSave)
            return false;
        return source.save_result(JSON.stringify({generation: selected.source.generation,
            result_id: selected.result_id, destination: destination, format: formatIndex === 0 ? "json" : "csv"}));
    }
    function cancelSelected() { return source && receipt ? source.cancel_save(receipt.operation_id) : false; }
    onSourceChanged: close()
    onReportChanged: {
        const newest = report.receipts.length ? report.receipts[report.receipts.length - 1].operation_id : 0;
        if (lastOperation !== newest) {
            lastOperation = newest;
            selectedOperation = newest;
        }
        // Replacing a JS array resets ComboBox selection. Preserve operation identity.
        Qt.callLater(() => operations.currentIndex = report.receipts.findIndex(r => r.operation_id === selectedOperation));
    }
    onClosed: {
        if (source)
            source.release_save_result();
        selected = null;
    }
    Timer { interval: 30; repeat: true; running: !!dialog.source; onTriggered: dialog.source.poll_saves() }
    contentItem: Rectangle {
        color: "#f3f6fa"
        implicitWidth: form.implicitWidth
        implicitHeight: form.implicitHeight
        ColumnLayout {
            id: form
            anchors.fill: parent
            spacing: 12
            Label {
                Layout.fillWidth: true
                elide: Text.ElideMiddle
                text: dialog.selected ? dialog.tr("migration.display.save_selected").arg(dialog.selected.result_id)
                    .arg(dialog.selected.interval[0]).arg(dialog.selected.interval[1]) : ""
                ToolTip.visible: selectedHover.hovered
                ToolTip.text: text
                HoverHandler { id: selectedHover }
            }
            GridLayout {
                columns: 2
                columnSpacing: 12
                Label { id: pathLabel; text: dialog.tr("migration.display.save_path") }
                TextField { id: path; Layout.fillWidth: true; Layout.preferredWidth: 280; selectByMouse: true;
                    ToolTip.visible: pathHover.hovered; ToolTip.text: text; HoverHandler { id: pathHover } }
                Label { id: formatLabel; text: dialog.tr("migration.display.save_format") }
                ComboBox { id: format; model: ["JSON", "CSV"]; Layout.fillWidth: true }
            }
            Label { id: note; text: dialog.tr("migration.display.save_note") + "\n" + dialog.tr("migration.display.save_finish_note"); Layout.fillWidth: true;
                Layout.preferredWidth: 480; wrapMode: Text.WordWrap }
            ComboBox {
                id: operations
                Layout.fillWidth: true
                model: dialog.report.receipts.map(r => r.operation_id + ": " + dialog.status(r.status.state))
                onActivated: index => dialog.selectedOperation = dialog.report.receipts[index].operation_id
            }
            Label {
                id: statusLabel
                Layout.fillWidth: true
                Layout.preferredWidth: 480
                wrapMode: Text.WordWrap
                text: dialog.report.rejection === "busy" ? dialog.tr("migration.display.save_busy")
                    : dialog.report.rejection ? dialog.tr("migration.display.save_rejected")
                    : dialog.receipt ? dialog.status(dialog.receipt.status.state)
                    : dialog.report.closed ? dialog.tr("migration.display.save_closed") : ""
            }
            Label {
                Layout.fillWidth: true
                Layout.preferredWidth: 480
                wrapMode: Text.WrapAnywhere
                text: dialog.receipt && dialog.receipt.status.state === "failed" ? dialog.receipt.status.message : ""
                color: "#9b2335"
            }
        }
    }
    footer: ColumnLayout {
        RowLayout {
            Button { id: saveButton; text: dialog.tr("migration.display.save_measurement"); enabled: dialog.canSave; onClicked: dialog.submit() }
            Button { id: cancelButton; text: dialog.tr("migration.display.save_cancel");
                enabled: dialog.receipt && dialog.receipt.status.state === "queued"; onClicked: dialog.cancelSelected() }
        }
        RowLayout {
            Button { id: finishButton; text: dialog.tr("migration.display.save_finish"); enabled: dialog.source && !dialog.report.closed;
                onClicked: dialog.source.close_saves() }
            Button { id: closeButton; text: dialog.tr("migration.display.calibration_close"); onClicked: dialog.close() }
        }
    }
}

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    required property var source
    required property var messages
    property alias path: filePath.text
    property alias spec: specPath.text
    property alias formatIndex: format.currentIndex
    readonly property var formats: ["product_json", "product_csv", "csv_spec"]
    property string encoded: source ? source.imports : ""
    readonly property var report: encoded ? JSON.parse(encoded) : ({receipts: [], latest: 0, preview: null, closed: false})
    readonly property var preview: report.preview ? JSON.parse(report.preview) : null
    readonly property var receipt: report.receipts.find(r => r.operation_id === report.latest) || null
    property int traceIndex: 0
    readonly property var trace: preview && preview.traces[traceIndex] || null
    readonly property var displayedText: ({title: title, path: pathLabel.text, spec: specLabel.text,
        trace: traceLabel.text, note: note.text, read: readButton.text, cancel: cancelButton.text,
        close: closeButton.text, status: stateLabel.text, provenance: provenance.text, relation: relation.text})
    title: tr("migration.display.import_open")
    modal: false
    width: 720
    height: 610
    function tr(key) { return messages[key] || ""; }
    function axisText(axis) {
        return axis ? tr("migration.display.import_axis").arg(axis.dimension).arg(axis.base_unit).arg(axis.display_unit) : "—";
    }
    function submit() {
        if (!source || report.closed || !path.trim() || formatIndex < 0 || formatIndex > 2 || formatIndex === 2 && !spec.trim())
            return false;
        const request = {path: path, format: formats[formatIndex]};
        if (formatIndex === 2)
            request.spec = spec;
        return source.import_product(JSON.stringify(request));
    }
    function status(value) {
        if (value === "reading") return tr("migration.display.import_reading");
        if (value === "loaded") return tr("migration.display.import_loaded");
        if (value === "failed") return tr("migration.display.import_failed");
        if (value === "queued") return tr("migration.display.save_queued");
        if (value === "cancelled") return tr("migration.display.save_cancelled");
        return "";
    }
    function labelsFit() { return contentItem.implicitHeight <= contentItem.height + 1 && [readButton, cancelButton, closeButton].every(b => b.contentItem.implicitWidth <= b.availableWidth + 1); }
    onSourceChanged: { traceIndex = 0; close(); }
    onPreviewChanged: traceIndex = 0
    Timer { interval: 30; repeat: true; running: !!dialog.source; onTriggered: dialog.source.poll_imports() }
    contentItem: Rectangle {
        color: "#f3f6fa"
        implicitWidth: form.implicitWidth
        implicitHeight: form.implicitHeight
        ColumnLayout {
            id: form
            anchors.fill: parent
            spacing: 8
            GridLayout {
                columns: 2
                Layout.fillWidth: true
                Label { id: pathLabel; text: dialog.tr("migration.display.import_path") }
                TextField { id: filePath; Layout.fillWidth: true; selectByMouse: true }
                Label { text: dialog.tr("migration.display.save_format") }
                ComboBox {
                    id: format
                    Layout.fillWidth: true
                    model: [dialog.tr("migration.display.save_product_json"), dialog.tr("migration.display.save_product_csv"), dialog.tr("migration.display.import_spec")]
                    implicitContentWidthPolicy: ComboBox.WidestText
                }
                Label { id: specLabel; visible: dialog.formatIndex === 2; text: dialog.tr("migration.display.import_spec") }
                TextField { id: specPath; visible: dialog.formatIndex === 2; Layout.fillWidth: true; selectByMouse: true }
            }
            Label { id: stateLabel; Layout.fillWidth: true; wrapMode: Text.WrapAnywhere;
                text: dialog.report.closed ? dialog.tr("migration.display.import_closed")
                    : dialog.report.rejection ? (dialog.report.rejection === "busy" ? dialog.tr("migration.display.import_busy") : dialog.tr("migration.display.import_rejected"))
                    : dialog.receipt ? dialog.status(dialog.receipt.status.state) : "" }
            Label { Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; color: "#9b2335";
                text: dialog.receipt && dialog.receipt.status.state === "failed" ? dialog.receipt.status.message : "" }
            Label { id: note; text: dialog.tr("migration.display.import_note"); Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Label { id: provenance; Layout.fillWidth: true; wrapMode: Text.WordWrap;
                text: dialog.preview ? (dialog.preview.has_snapshot ? dialog.tr("migration.display.import_snapshot") : dialog.tr("migration.display.import_unknown")) : "" }
            Label { id: relation; Layout.fillWidth: true; wrapMode: Text.WordWrap;
                text: dialog.preview ? (dialog.preview.sample_relation === "original_trace_arrays" ? dialog.tr("migration.display.import_original") : dialog.tr("migration.display.import_merged")) : "" }
            Label { visible: dialog.preview && dialog.preview.has_snapshot; Layout.fillWidth: true; wrapMode: Text.WrapAnywhere;
                text: dialog.preview ? dialog.tr("migration.display.import_quality").arg(dialog.preview.invalid_spans).arg(dialog.preview.error || "—") : "" }
            RowLayout {
                Label { id: traceLabel; text: dialog.tr("migration.display.import_trace") }
                ComboBox {
                    id: traces
                    Layout.fillWidth: true
                    model: dialog.preview ? dialog.preview.traces.map(t => t.name || t.id) : []
                    onActivated: index => dialog.traceIndex = index
                }
            }
            Label { Layout.fillWidth: true; elide: Text.ElideRight;
                text: dialog.trace ? dialog.trace.source_module + " · " + dialog.trace.timestamp : "" }
            Label { Layout.fillWidth: true; text: dialog.trace ? dialog.tr("migration.display.import_calibration").arg(
                (dialog.trace.is_calibrated ? dialog.tr("migration.display.import_calibrated") : dialog.tr("migration.display.import_uncalibrated"))) : "" }
            Label { text: dialog.trace ? dialog.axisText(dialog.trace.x_axis) : ""; Layout.fillWidth: true; elide: Text.ElideRight }
            Label { text: dialog.trace ? dialog.axisText(dialog.trace.y_axis) : ""; Layout.fillWidth: true; elide: Text.ElideRight }
            Label { visible: dialog.trace && !!dialog.trace.y2_axis; text: dialog.trace ? dialog.axisText(dialog.trace.y2_axis) : "";
                Layout.fillWidth: true; elide: Text.ElideRight }
            Label { visible: dialog.trace && !dialog.trace.rows.length; text: dialog.tr("migration.display.import_empty") }
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 80
                clip: true
                model: dialog.trace ? dialog.trace.rows : []
                ScrollBar.vertical: ScrollBar {}
                delegate: RowLayout {
                    required property var modelData
                    width: ListView.view.width
                    Label { text: modelData.index; Layout.preferredWidth: 60 }
                    Label { text: "X: " + modelData.x; Layout.fillWidth: true }
                    Label { text: "Y: " + modelData.y; Layout.fillWidth: true }
                    Label { text: modelData.y2 === null ? "—" : "Y2: " + modelData.y2; Layout.fillWidth: true }
                }
            }
        }
    }
    footer: Flow {
        spacing: 8
        Button { id: readButton; text: dialog.tr("migration.display.import_open"); enabled: dialog.source && !dialog.report.closed; onClicked: dialog.submit() }
        Button { id: cancelButton; text: dialog.tr("migration.display.import_cancel"); enabled: dialog.receipt && dialog.receipt.status.state === "queued";
            onClicked: dialog.source.cancel_import(dialog.report.latest) }
        Button { id: closeButton; text: dialog.tr("migration.display.calibration_close"); onClicked: dialog.close() }
    }
}

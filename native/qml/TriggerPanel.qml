import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: panel
    required property var source
    required property var current
    required property var response
    required property var messages
    property double revision: 0
    property alias sampleText: samplePosition.text
    readonly property bool buttonsFit: captureButton.width >= captureButton.implicitWidth && retryButton.width >= retryButton.implicitWidth && releaseButton.width >= releaseButton.implicitWidth
    readonly property var displayedText: ({capture: captureButton.text, retry: retryButton.text, release: releaseButton.text, sample: sampleLabel.text, status: statusLabel.text})
    function tr(key) { return messages[key] || ""; }
    onSourceChanged: revision = 0
    function requestAt(start, nextRevision) {
        if (!source || !current)
            return null;
        const n = current.interval[1] - current.interval[0];
        const pre = Math.floor(n / 2);
        return {
            revision: nextRevision,
            request: {
                request_id: "qt.manual." + nextRevision,
                pre: pre, post: n - pre,
                event: {
                    id: "qt.event." + nextRevision,
                    stream_id: current.source.stream_id,
                    generation: source.generation,
                    timebase_id: current.source.timebase.id,
                    sample: {numerator: 2 * (start + pre) + 1, denominator: 2},
                    source: "qt.manual", kind: "manual", polarity: "none",
                    condition_revision: "manual.v1", validity: [], received_host_seconds: null
                }
            }
        };
    }
    function submit(request) {
        if (!request)
            return false;
        const accepted = source.request_trigger(JSON.stringify(request));
        if (accepted)
            revision = request.revision;
        return accepted;
    }
    function retry() {
        return response && source.retry_trigger(response.request.event.generation, response.revision);
    }
    function release() {
        return response && source.release_trigger(response.request.event.generation, response.revision);
    }
    function capture() {
        if (!current || !samplePosition.text.trim())
            return false;
        const sample = Number(samplePosition.text);
        if (!Number.isSafeInteger(2 * sample))
            return false;
        const n = current.interval[1] - current.interval[0];
        const request = requestAt(Math.floor(sample) - Math.floor(n / 2), revision + 1);
        request.request.event.sample.numerator = 2 * sample;
        return submit(request);
    }
    function statusText() {
        if (!response || response.status === "released")
            return "";
        switch (response.status) {
        case "queued": return tr("migration.display.trigger_queued");
        case "pending": return tr("migration.display.trigger_pending");
        case "complete": return tr("migration.display.trigger_complete");
        case "gap": return tr("migration.display.trigger_gap");
        case "cancelled": return tr("migration.display.trigger_cancelled");
        case "error": return tr("migration.display.trigger_error").arg(response.reason);
        }
        return "";
    }
    RowLayout {
        Label { id: sampleLabel; text: panel.tr("migration.display.trigger_sample") }
        TextField {
            id: samplePosition
            Layout.preferredWidth: 100
            text: panel.current ? (Math.floor((panel.current.interval[0] + panel.current.interval[1]) / 2) + 0.5).toString() : "0"
        }
        Button {
            id: captureButton
            text: panel.tr("migration.display.trigger_capture")
            enabled: panel.source && panel.source.state === 2 && !!panel.current
            onClicked: panel.capture()
        }
        Button {
            id: retryButton
            text: panel.tr("migration.display.trigger_retry")
            enabled: panel.source && panel.source.state === 2 && panel.response && ["pending", "gap"].indexOf(panel.response.status) >= 0
            onClicked: panel.retry()
        }
        Button {
            id: releaseButton
            text: panel.tr("migration.display.trigger_release")
            enabled: panel.response && ["released", "cancelled"].indexOf(panel.response.status) < 0
            onClicked: panel.release()
        }
        Item { Layout.fillWidth: true }
    }
    Label {
        id: statusLabel
        text: panel.statusText()
        Layout.fillWidth: true
        elide: Text.ElideRight
    }
}

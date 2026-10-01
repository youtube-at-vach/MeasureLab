import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "../qml"

Window {
    id: window
    width: 1088
    height: 352
    visible: true
    color: "#101b2b"
    title: qsTr("Plot renderer feasibility spike")
    property real viewLow: 0
    property real viewHigh: 1
    property bool loaded: true
    property bool baselineReady: false
    onLoadedChanged: { if (!loaded) baselineReady = false; }
    property string cursorText: ""
    property real cursorFraction: 0.5
    readonly property int paints: baseline.item ? baseline.item.paints : 0
    readonly property real dataWidth: baseline.item ? baseline.item.children[1].width - 64 : 1024
    readonly property real dataHeight: baseline.item ? baseline.item.children[1].height - 40 : 256
    function zoomIn() {
        const center = (viewLow + viewHigh) / 2;
        const span = (viewHigh - viewLow) / 2;
        viewLow = center - span / 2;
        viewHigh = center + span / 2;
    }
    function panRight() {
        const shift = Math.min(0.125, 1 - viewHigh);
        viewLow += shift;
        viewHigh += shift;
    }
    function reset() { viewLow = 0; viewHigh = 1; }
    function readCursor() {
        if (baseline.item) {
            baseline.item.cursorAt(window.cursorFraction);
            backend.recordCursor(baseline.item.cursorBin, baseline.item.cursorHz, baseline.item.cursorValue);
        } else {
            backend.pick(viewLow + (viewHigh - viewLow) * cursorFraction);
        }
    }
    QtObject {
        id: sourceAdapter
        property double nextToken: 0
        function subscribe() { backend.subscribe(); nextToken += 1; return nextToken; }
        function unsubscribe(token) { backend.unsubscribe(token); }
    }
    Row {
        height: 32
        Button { text: qsTr("Zoom"); onClicked: window.zoomIn(); }
        Button { text: qsTr("Pan"); onClicked: window.panRight(); }
        Button { text: qsTr("Reset"); onClicked: window.reset(); }
        Label { text: window.cursorText; color: "#b9cbe3"; }
    }
    Loader {
        id: baseline
        active: backend.mode === "baseline" && window.loaded
        x: 0; y: 32; width: 1088; height: window.height - 32
        onLoaded: Qt.callLater(() => window.baselineReady = true)
        sourceComponent: SpectrumView {
            source: sourceAdapter
            messages: displayTranslations
            frame: window.baselineReady && backend.payload ? JSON.parse(backend.payload) : null
            heatmap: backend.kind === "spectrogram"
            lowHz: window.viewLow * 24000
            highHz: window.viewHigh * 24000
        }
    }
    Loader {
        active: backend.mode === "wgpu" && window.loaded
        x: 52; y: 46; width: 1024; height: 256
        sourceComponent: Item {
            Image {
                anchors.fill: parent
                cache: false
                asynchronous: false
                source: backend.serial > 0 ? "image://spike/" + backend.serial : ""
            }
            Rectangle {
                x: parent.width * window.cursorFraction
                width: 1; height: parent.height
                color: "#f3bc68"
            }
            MouseArea {
                anchors.fill: parent
                onClicked: mouse => {
                    window.cursorFraction = Math.max(0, Math.min(1, mouse.x / width));
                    window.readCursor();
                }
                onWheel: wheel => { window.zoomIn(); wheel.accepted = true; }
            }
        }
    }
}

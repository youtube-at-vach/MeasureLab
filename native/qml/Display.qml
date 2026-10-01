import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import DisplayProbe 1.0

ApplicationWindow {
    id: window
    visible: true
    width: 1000
    height: 640
    minimumWidth: Math.max(640, content.implicitWidth + 32)
    minimumHeight: Math.max(540, content.implicitHeight + 32)
    title: qsTr("MeasureLab · shared FFT display evaluation")
    property var backend: null
    property var frame: null
    property bool holding: false
    onHoldingChanged: {
        if (!holding)
            acceptPayload();
    }
    property string encoded: backend ? backend.payload : ""
    onEncodedChanged: acceptPayload()
    property int phase: 0
    property double oldGeneration: 0
    property double session: 0
    property double baseline: 0
    property var held: null
    property string heldText: ""
    property double deadline: Date.now() + 20000
    property bool saved: false
    property bool savePending: false
    property bool failed: false
    property bool liveInput: Qt.application.arguments.indexOf("--live-input") >= 0
    property string imageStatus: ""
    function check(ok, message) {
        if (!ok && !failed) {
            failed = true;
            console.error("DISPLAY_FAIL " + message);
            Qt.exit(1);
        }
        return ok;
    }
    function argument(name) {
        const i = Qt.application.arguments.indexOf(name);
        return i >= 0 ? Qt.application.arguments[i + 1] : "";
    }
    function acceptPayload() {
        if (holding)
            return;
        if (!backend || !backend.payload) {
            frame = null;
            return;
        }
        const next = JSON.parse(backend.payload);
        if (frame && frame.result_id === next.result_id)
            return;
        function freeze(value) {
            if (value && typeof value === "object" && !Object.isFrozen(value)) {
                Object.keys(value).forEach(key => freeze(value[key]));
                Object.freeze(value);
            }
            return value;
        }
        frame = freeze(next);
    }
    function stateLabel() {
        if (!backend)
            return qsTr("Recreating");
        switch (backend.state) {
        case 0:
            return qsTr("Idle");
        case 1:
            return qsTr("Preparing");
        case 2:
            return liveInput ? qsTr("Acquiring live input") : qsTr("Replaying saved input");
        case 3:
            return qsTr("Stopping");
        case 4:
            return qsTr("Failed: %1").arg(backend.error);
        }
        return qsTr("Unknown");
    }
    function recreate() {
        holding = false;
        line.active = false;
        map.active = false;
        frame = null;
        if (backend)
            backend.destroy();
        backend = factory.createObject(window);
        line.active = true;
        map.active = true;
        gc();
    }
    function saveImage(path) {
        const wasHolding = holding;
        holding = true;
        savePending = true;
        if (!canvas.grabToImage(function (result) {
            saved = result.saveToFile(path);
            savePending = false;
            holding = wasHolding;
            imageStatus = saved ? qsTr("Image saved") : qsTr("Image save failed");
            console.log(saved ? "DISPLAY_IMAGE_OK" : "DISPLAY_IMAGE_FAILED");
        })) {
            savePending = false;
            holding = wasHolding;
            imageStatus = qsTr("Image capture failed");
        }
    }
    Component {
        id: factory
        DisplayBackend {}
    }
    Component.onCompleted: {
        recreate();
        console.log("DISPLAY_READY");
        if (backend.testing)
            exercise.start();
    }
    Rectangle {
        id: canvas
        anchors.fill: parent
        color: "#f3f6fa"
        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: 16
            spacing: 8
            Label {
                text: liveInput ? qsTr("Live input · shared FFT · uncalibrated FS · clock origin unknown") : qsTr("Saved input · shared FFT · uncalibrated FS · clock origin unknown")
                Layout.fillWidth: true
                elide: Text.ElideRight
                font.bold: true
            }
            RowLayout {
                Button {
                    text: liveInput ? qsTr("Start input") : qsTr("Start replay")
                    enabled: backend && (backend.state === 0 || backend.state === 4)
                    onClicked: backend.start(false)
                }
                Button {
                    text: qsTr("Stop")
                    enabled: backend && (backend.state === 1 || backend.state === 2)
                    onClicked: backend.stop()
                }
                Button {
                    text: qsTr("Recreate")
                    onClicked: recreate()
                }
                Button {
                    text: qsTr("Save image")
                    enabled: !!frame && !savePending
                    onClicked: saveImage(imagePath.text)
                }
                Label {
                    text: stateLabel()
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
            RowLayout {
                Label {
                    text: qsTr("PNG path")
                }
                TextField {
                    id: imagePath
                    text: argument("--snapshot")
                    placeholderText: qsTr("Absolute output path.png")
                    Layout.fillWidth: true
                }
                Label {
                    text: imageStatus
                }
            }
            Label {
                text: frame ? qsTr("Result %1 · samples [%2, %3) · %4").arg(frame.result_id).arg(frame.interval[0]).arg(frame.interval[1]).arg(frame.source.timebase.id) : qsTr("No result")
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 16
                Loader {
                    id: line
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    active: false
                    sourceComponent: SpectrumView {
                        source: window.backend
                        frame: window.frame
                    }
                }
                Loader {
                    id: map
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    active: false
                    sourceComponent: SpectrumView {
                        source: window.backend
                        frame: window.frame
                        heatmap: true
                    }
                }
            }
            Label {
                text: qsTr("Spectrogram shows retained display frames (up to 32); omitted updates leave empty time rows.")
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            Label {
                text: qsTr("FFT evaluations: %1 · display updates omitted: %2").arg(backend ? backend.produced : 0).arg(backend ? backend.coalesced : 0)
            }
        }
    }
    Timer {
        id: exercise
        interval: 40
        repeat: true
        onTriggered: {
            if (!check(Date.now() < deadline, "timeout phase " + phase))
                return;
            switch (phase) {
            case 0:
                check(backend.subscribers() === 2, "two actual view tokens");
                check(backend.start(false), "start");
                check(!backend.start(false), "duplicate start");
                backend.stop();
                backend.stop();
                phase = 1;
                break;
            case 1:
                if (backend.state !== 0 || backend.workers())
                    return;
                check(backend.outcome === 2 && backend.reclaimed, "preparing cancel");
                if (backend.start(true))
                    phase = 2;
                break;
            case 2:
                if (backend.state !== 4 || backend.workers())
                    return;
                check(backend.outcome === 3, "injected failure");
                backend.stop();
                check(backend.state === 4, "failure retained");
                if (backend.start(false))
                    phase = 3;
                break;
            case 3:
                if (!frame || backend.produced < 3 || line.item.paints === 0 || map.item.paints === 0)
                    return;
                check(backend.shared && line.item.frame === map.item.frame, "one immutable result for both views");
                check(Object.isFrozen(frame) && Object.isFrozen(frame.peak_fs.values), "projection frozen");
                check(line.item.resultId === map.item.resultId, "same result ID");
                check(frame.source.timebase.origin_seconds === null && frame.source.timebase.uncertainty_seconds === null, "unknown clock");
                check(frame.peak_fs.shape[0] === frame.frequency_hz.length, "bin shape");
                held = frame;
                heldText = JSON.stringify(held);
                oldGeneration = backend.generation;
                const ch = frame.source.channel_ids.length - 1;
                line.item.channel = ch;
                map.item.channel = ch;
                const bin = [37, 71, 113, 173, 251, 331, 419, 509][ch];
                line.item.cursorBin = bin;
                map.item.cursorBin = bin;
                check(line.item.cursorValue === frame.peak_fs.values[bin * frame.source.channel_ids.length + ch], "full precision cursor");
                check(Math.abs(line.item.cursorValue - (ch + 1) / (liveInput ? 512 : 32)) < 0.000001, "input tone cursor");
                line.item.zoom(line.item.cursorHz, 0.5);
                check(line.item.highHz - line.item.lowHz === 12000 && map.item.highHz === 24000, "independent zoom");
                line.item.resetZoom();
                check(backend.stall() >= 2, "FFT advances during blocked GUI");
                phase = 4;
                break;
            case 4:
                check(backend.coalesced > 0, "coalesced GUI updates");
                check(JSON.stringify(held) === heldText, "old result immutable");
                session = backend.subscribe();
                map.active = false;
                baseline = backend.produced;
                phase = 5;
                break;
            case 5:
                if (backend.produced <= baseline || backend.subscribers() !== 2)
                    return;
                line.active = false;
                baseline = backend.produced;
                phase = 6;
                break;
            case 6:
                if (backend.produced <= baseline || backend.subscribers() !== 1)
                    return;
                check(backend.unsubscribe(session), "session release");
                check(!backend.unsubscribe(session), "duplicate release");
                phase = 7;
                break;
            case 7:
                if (backend.state !== 0 || backend.workers())
                    return;
                check(backend.reclaimed, "graph reclaimed");
                line.active = true;
                map.active = true;
                if (backend.start(false))
                    phase = 8;
                break;
            case 8:
                if (!frame || backend.state !== 2)
                    return;
                check(backend.generation > oldGeneration, "restart generation");
                const id = frame.result_id;
                backend.deliver(oldGeneration);
                check(frame.result_id === id, "stale delivery fenced");
                recreate();
                phase = 9;
                break;
            case 9:
                if (backend.workers())
                    return;
                check(backend.state === 0 && frame === null, "recreate idle");
                if (backend.start(false))
                    phase = 10;
                break;
            case 10:
                if (!frame || backend.produced < 6 || line.item.paints === 0 || map.item.paints === 0)
                    return;
                check(window.minimumWidth <= 1180 && window.minimumHeight <= 690, "evaluation size limit");
                console.log("DISPLAY_SIZE " + window.minimumWidth + " " + window.minimumHeight);
                saveImage(argument("--snapshot"));
                phase = 11;
                break;
            case 11:
                if (savePending)
                    return;
                if (!check(saved, "image saved"))
                    return;
                console.log("DISPLAY_PASS shared cursor zoom immutable slow_gui cancel failure stale views session recreate image shutdown");
                Qt.quit();
                break;
            }
        }
    }
}

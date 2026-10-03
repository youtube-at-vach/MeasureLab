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
    title: tr("migration.display.title")
    property var backend: null
    readonly property var messages: backend ? JSON.parse(backend.translations) : ({})
    function tr(key) {
        return messages[key] || "";
    }
    property var latestFrame: null
    property string captureEncoded: backend ? backend.capture : ""
    readonly property var trigger: captureEncoded ? freeze(JSON.parse(captureEncoded)) : null
    readonly property var frame: trigger && ["queued", "pending", "gap", "complete", "error"].indexOf(trigger.status) >= 0 ? trigger.frame : latestFrame
    function freeze(value) {
        if (value && typeof value === "object" && !Object.isFrozen(value)) {
            Object.keys(value).forEach(key => freeze(value[key]));
            Object.freeze(value);
        }
        return value;
    }
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
    property bool workspaceTesting: Qt.application.arguments.indexOf("--workspace-test") >= 0
    property bool triggerTesting: Qt.application.arguments.indexOf("--trigger-test") >= 0
    property bool filterTesting: Qt.application.arguments.indexOf("--filter-test") >= 0
    property bool calibrationEditingTest: Qt.application.arguments.indexOf("--calibration-edit-test") >= 0
    property bool savingTest: Qt.application.arguments.indexOf("--save-test") >= 0
    property bool importingTest: Qt.application.arguments.indexOf("--import-test") >= 0
    property var workspaceEvidence: ({})
    property var lineBefore: null
    property var mapBefore: null
    property var tokensBefore: []
    property int detachedSaves: 0
    property bool detachedSaveFailed: false
    function paneEvidence(pane) {
        return {
            minimum: [pane.floating.minimumWidth, pane.floating.minimumHeight],
            size: [pane.floating.width, pane.floating.height],
            title: pane.floating.title,
            labels: pane.item.displayedText,
            regions: {spectrum: pane.item.plotRegion(pane.floating.contentItem), spectrogram: pane.item.plotRegion(pane.floating.contentItem)},
            buttons_fit: pane.item.buttonsFit
        };
    }
    function saveDetached() {
        holding = true;
        detachedSaves = 0;
        function capture(pane, suffix) {
            if (!pane.floating.contentItem.grabToImage(result => {
                if (!result.saveToFile(argument("--snapshot") + suffix))
                    detachedSaveFailed = true;
                detachedSaves += 1;
                if (detachedSaves === 2)
                    holding = false;
            })) {
                detachedSaveFailed = true;
                detachedSaves += 1;
            }
        }
        capture(line, ".spectrum.png");
        capture(map, ".spectrogram.png");
    }
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
            latestFrame = null;
            return;
        }
        const next = JSON.parse(backend.payload);
        if (latestFrame && latestFrame.result_id === next.result_id)
            return;
        latestFrame = freeze(next);
    }
    function stateLabel() {
        if (!backend)
            return tr("migration.display.recreating");
        switch (backend.state) {
        case 0:
            return tr("migration.display.idle");
        case 1:
            return tr("migration.display.preparing");
        case 2:
            return liveInput ? tr("migration.display.live") : tr("migration.display.replay");
        case 3:
            return tr("migration.display.stopping");
        case 4:
            return tr("migration.display.failed").arg(backend.error);
        }
        return tr("migration.display.unknown");
    }
    function recreate() {
        holding = false;
        line.active = false;
        map.active = false;
        latestFrame = null;
        if (backend)
            backend.destroy();
        backend = factory.createObject(window);
        line.active = true;
        map.active = true;
        gc();
    }
    function saveImage(path, target) {
        const wasHolding = holding;
        holding = true;
        savePending = true;
        if (!(target || canvas).grabToImage(function (result) {
            saved = result.saveToFile(path);
            savePending = false;
            holding = wasHolding;
            imageStatus = saved ? tr("migration.display.image_saved") : tr("migration.display.image_failed");
            console.log(saved ? "DISPLAY_IMAGE_OK" : "DISPLAY_IMAGE_FAILED");
        })) {
            savePending = false;
            holding = wasHolding;
            imageStatus = tr("migration.display.capture_failed");
        }
    }
    Component {
        id: factory
        DisplayBackend {}
    }
    Component.onCompleted: {
        recreate();
        console.log("DISPLAY_READY");
        if (backend.testing && !triggerTesting && !filterTesting && !calibrationEditingTest && !savingTest && !importingTest)
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
                text: liveInput ? tr("migration.display.live_description") : tr("migration.display.saved_description")
                Layout.fillWidth: true
                elide: Text.ElideRight
                font.bold: true
            }
            RowLayout {
                Button {
                    text: liveInput ? tr("migration.display.start_input") : tr("migration.display.start_replay")
                    enabled: backend && (backend.state === 0 || backend.state === 4)
                    onClicked: backend.start(false)
                }
                Button {
                    text: tr("migration.display.stop")
                    enabled: backend && (backend.state === 1 || backend.state === 2)
                    onClicked: backend.stop()
                }
                Button {
                    text: tr("migration.display.recreate")
                    enabled: !savePending
                    onClicked: recreate()
                }
                Button {
                    text: tr("migration.display.save_image")
                    enabled: !!frame && !savePending
                    onClicked: saveImage(imagePath.text)
                }
                Button {
                    text: tr("migration.display.calibration_edit")
                    enabled: backend && backend.state === 2 && !!backend.calibration
                    onClicked: calibrationEditor.open()
                }
                Label {
                    text: stateLabel()
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
            RowLayout {
                Button {
                    text: tr("migration.display.save_measurement")
                    enabled: backend && !!frame
                    onClicked: measurementSave.selectResult(frame)
                }
                Button {
                    text: tr("migration.display.import_open")
                    enabled: !!backend
                    onClicked: productImport.open()
                }
                Label {
                    text: tr("migration.display.png_path")
                }
                TextField {
                    id: imagePath
                    text: argument("--snapshot")
                    placeholderText: tr("migration.display.png_placeholder")
                    Layout.fillWidth: true
                }
                Label {
                    text: imageStatus
                }
            }
            Label {
                text: frame ? tr("migration.display.result").arg(frame.result_id).arg(frame.interval[0]).arg(frame.interval[1]).arg(frame.source.timebase.id) : tr("migration.display.no_result")
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            TriggerPanel {
                id: triggerPanel
                Layout.fillWidth: true
                source: window.backend
                current: window.latestFrame
                response: window.trigger
                messages: window.messages
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 16
                PlotPane {
                    id: line
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    active: false
                    source: window.backend
                    frame: window.frame
                    messages: window.messages
                    capturePending: window.savePending
                    onSaveRequested: target => saveImage(imagePath.text, target)
                }
                PlotPane {
                    id: map
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    active: false
                    source: window.backend
                    frame: window.frame
                    messages: window.messages
                    capturePending: window.savePending
                    heatmap: true
                    onSaveRequested: target => saveImage(imagePath.text, target)
                }
            }
            Label {
                text: tr("migration.display.history_note")
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            Label {
                text: backend && messages["migration.display.counters"] ? tr("migration.display.counters").arg(backend.produced).arg(backend.coalesced) : ""
            }
        }
    }
    TriggerExercise {
        enabled: window.triggerTesting
        host: window
        panel: triggerPanel
        line: line
        map: map
    }
    FilterExercise {
        enabled: window.filterTesting
        host: window
        panel: triggerPanel
        line: line
        map: map
        dialog: measurementSave
    }
    CalibrationEditor {
        id: calibrationEditor
        source: window.backend
        messages: window.messages
        x: (window.width - width) / 2
        y: (window.height - height) / 2
    }
    CalibrationEditExercise {
        enabled: window.calibrationEditingTest
        host: window
        editor: calibrationEditor
        triggerPanel: triggerPanel
        line: line
        map: map
    }
    SaveDialog {
        id: measurementSave
        source: window.backend
        messages: window.messages
        x: (window.width - width) / 2
        y: (window.height - height) / 2
    }
    SaveExercise {
        enabled: window.savingTest
        host: window
        dialog: measurementSave
        triggerPanel: triggerPanel
        line: line
        map: map
    }
    ImportDialog {
        id: productImport
        source: window.backend
        messages: window.messages
        x: (window.width - width) / 2
        y: (window.height - height) / 2
    }
    ImportExercise {
        enabled: window.importingTest
        host: window
        dialog: productImport
        line: line
        map: map
    }
    Timer {
        id: exercise
        interval: 40
        repeat: true
        onTriggered: {
            if (!check(Date.now() < deadline, "timeout phase " + phase))
                return;
            if (backend && backend.state === 4 && phase !== 2) {
                check(false, "unexpected worker failure: " + backend.error);
                return;
            }
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
                phase = workspaceTesting ? 30 : 4;
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
                if (workspaceTesting) {
                    line.detach();
                    map.detach();
                    check(line.floating.visible && map.floating.visible, "detached before backend recreation");
                    workspaceEvidence.recreated_detached = true;
                }
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
                console.log("DISPLAY_PLOT_REGIONS " + JSON.stringify({spectrum: line.item.plotRegion(canvas), spectrogram: map.item.plotRegion(canvas)}));
                saveImage(argument("--snapshot"));
                phase = 11;
                break;
            case 11:
                if (savePending)
                    return;
                if (!check(saved, "image saved"))
                    return;
                if (workspaceTesting) {
                    workspaceEvidence.main = {
                        minimum: [window.minimumWidth, window.minimumHeight],
                        size: [window.width, window.height],
                        title: window.title,
                        regions: {spectrum: line.item.plotRegion(canvas), spectrogram: map.item.plotRegion(canvas)}
                    };
                    line.detach();
                    map.detach();
                    phase = 37;
                } else {
                    console.log("DISPLAY_PASS shared cursor zoom immutable slow_gui cancel failure stale views session recreate image shutdown");
                    exercise.stop();
                    Qt.quit();
                }
                break;
            case 30:
                lineBefore = line.item;
                mapBefore = map.item;
                tokensBefore = [line.item.token, map.item.token];
                line.item.zoom(line.item.cursorHz, 0.5);
                line.detach();
                map.detach();
                baseline = backend.produced;
                phase = 31;
                break;
            case 31:
                if (backend.produced <= baseline + 1 || !line.floating.visible || !map.floating.visible)
                    return;
                check(line.item === lineBefore && map.item === mapBefore, "detachment keeps view objects");
                check(line.item.token === tokensBefore[0] && map.item.token === tokensBefore[1] && backend.subscribers() === 2, "detachment keeps actual subscriptions");
                check(line.item.frame === map.item.frame && line.item.resultId === frame.result_id, "detached views share current frame");
                check(line.item.highHz - line.item.lowHz === 12000 && map.item.highHz === 24000, "detachment preserves independent zoom");
                workspaceEvidence.spectrum = paneEvidence(line);
                workspaceEvidence.spectrogram = paneEvidence(map);
                workspaceEvidence.views_preserved = true;
                workspaceEvidence.tokens_preserved = true;
                saveDetached();
                phase = 32;
                break;
            case 32:
                if (detachedSaves !== 2)
                    return;
                check(!detachedSaveFailed, "both detached plot images saved");
                line.dock();
                map.floating.close();
                baseline = backend.produced;
                phase = 33;
                break;
            case 33:
                if (backend.subscribers() !== 1 || backend.produced <= baseline)
                    return;
                check(!map.item && !map.active && !map.floating.visible, "native close releases view demand");
                check(line.item === lineBefore && line.item.token === tokensBefore[0] && !line.detached, "dock preserves view and token");
                check(line.item.highHz - line.item.lowHz === 12000, "dock preserves zoom");
                workspaceEvidence.close_released = true;
                workspaceEvidence.other_continued = true;
                map.reopen();
                line.item.resetZoom();
                phase = 34;
                break;
            case 34:
                if (!map.item || backend.subscribers() !== 2 || map.item.paints === 0)
                    return;
                check(!map.detached && map.item.token !== tokensBefore[1] && map.item.frame === line.item.frame, "reopen in dock with new demand");
                workspaceEvidence.reopened_docked = true;
                line.detach();
                map.detach();
                line.floating.close();
                map.floating.close();
                phase = 35;
                break;
            case 35:
                if (backend.state !== 0 || backend.workers())
                    return;
                check(backend.subscribers() === 0 && backend.reclaimed && !line.item && !map.item, "last floating close stops and reclaims worker");
                workspaceEvidence.last_close_stopped = true;
                line.reopen();
                map.reopen();
                check(backend.start(false), "restart after last floating close");
                phase = 36;
                break;
            case 36:
                if (!frame || backend.state !== 2 || backend.produced < 3)
                    return;
                check(frame.source.generation > oldGeneration && JSON.stringify(held) === heldText, "restart preserves held old result");
                check(backend.stall() >= 2, "restarted FFT advances during blocked GUI");
                phase = 4;
                break;
            case 37:
                if (!line.floating.visible || !map.floating.visible || backend.state !== 2)
                    return;
                check(line.item.buttonsFit && map.item.buttonsFit, "translated controls fit");
                workspaceEvidence.shutdown_detached = true;
                workspaceEvidence.catalog = window.messages;
                workspaceEvidence.language = argument("--language") || "en";
                console.log("DISPLAY_WORKSPACE " + JSON.stringify(workspaceEvidence));
                console.log("DISPLAY_PASS shared cursor zoom immutable slow_gui cancel failure stale views session recreate image shutdown");
                exercise.stop();
                Qt.quit();
                break;
            }
        }
    }
}

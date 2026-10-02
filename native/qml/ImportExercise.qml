import QtQuick

Timer {
    id: test
    required property var host
    required property var dialog
    required property var line
    required property var map
    property bool enabled: false
    interval: 40
    repeat: true
    running: enabled
    property int phase: 0
    property var checks: ({imports: []})
    property bool imageSaved: false
    property double generation: 0
    Component.onCompleted: { if (enabled) host.deadline = Date.now() + 120000; }
    function check(ok, message) { return host.check(ok, "product import: " + message); }
    function path(name) { return host.argument("--import-directory") + "/" + name; }
    function submit(name, format, spec) {
        dialog.path = path(name);
        dialog.formatIndex = format;
        dialog.spec = spec ? path(spec) : "";
        return dialog.submit();
    }
    function completed() { return dialog.receipt && ["loaded", "failed", "cancelled"].indexOf(dialog.receipt.status.state) >= 0; }
    function capture() {
        check(completed() && dialog.receipt.status.state === "loaded" && !!dialog.preview, "loaded preview");
        checks.imports.push({receipt: dialog.receipt, preview: dialog.preview});
    }
    onTriggered: {
        if (!check(Date.now() < host.deadline, "timeout phase " + phase)) return;
        const backend = host.backend;
        if (!check(backend && backend.state !== 4, "acquisition failure")) return;
        switch (phase) {
        case 0:
            check(backend.start(false), "start replay");
            generation = backend.generation;
            phase = 1;
            break;
        case 1:
            if (!host.frame || backend.produced < 3 || !line.item.paints || !map.item.paints) return;
            checks.normal = host.frame;
            checks.calibration = JSON.parse(backend.calibration);
            check(backend.pin_result(generation, host.frame.result_id), "pin actual acquisition result");
            for (const name of ["snapshot.json", "snapshot.csv"])
                check(backend.save_result(JSON.stringify({generation: generation, result_id: host.frame.result_id,
                    destination: path(name), format: name.endsWith("json") ? "product_json" : "product_csv"})), "save full snapshot for import");
            dialog.open();
            check(submit("legacy.json", 0), "admit legacy JSON");
            phase = 2;
            break;
        case 2:
            if (!completed()) return;
            capture();
            check(!dialog.preview.has_snapshot && dialog.trace.rows[1].y === "-3.5" && dialog.trace.rows[1].y2 === "0.0", "legacy values not recalibrated");
            checks.dialog = {labels: dialog.displayedText, size: [dialog.width, dialog.height], labels_fit: dialog.labelsFit()};
            check(dialog.contentItem.grabToImage(result => {
                check(result.saveToFile(host.argument("--snapshot") + ".import.png"), "import image saved");
                imageSaved = true;
            }), "import image requested");
            phase = 3;
            break;
        case 3:
            if (!imageSaved) return;
            check(submit("legacy.csv", 1), "admit legacy CSV pair");
            phase = 4;
            break;
        case 4:
            if (!completed()) return;
            capture();
            check(submit("merged.csv", 2, "merged.spec.json"), "admit explicit merged CSV");
            phase = 5;
            break;
        case 5:
            if (!completed()) return;
            capture();
            check(dialog.preview.sample_relation === "merged_grid_may_be_interpolated", "merged grid remains unknown");
            check(submit("broken.json", 0), "admit malformed file");
            phase = 6;
            break;
        case 6:
            if (!completed()) return;
            check(dialog.receipt.status.state === "failed" && !dialog.preview, "failure hides old result");
            checks.failure = dialog.receipt;
            checks.states = {failed: dialog.displayedText.status};
            backend.poll_saves();
            const saves = JSON.parse(backend.saves).receipts;
            if (!saves.every(r => r.status.state === "saved")) return;
            checks.saves = saves;
            check(submit("snapshot.json", 0), "recover with full JSON");
            phase = 7;
            break;
        case 7:
            if (!completed()) return;
            capture();
            check(dialog.preview.has_snapshot, "full JSON snapshot");
            check(submit("snapshot.csv", 1), "full CSV pair");
            phase = 8;
            break;
        case 8:
            if (!completed()) return;
            capture();
            check(dialog.preview.has_snapshot, "full CSV snapshot");
            checks.blocked_gui_fft = backend.stall();
            check(checks.blocked_gui_fft >= 2, "import independent of acquisition");
            check(JSON.stringify(JSON.parse(backend.calibration)) === JSON.stringify(checks.calibration), "saved profiles never apply to current session");
            check(!backend.import_product("{}"), "malformed request rejected");
            checks.states.rejected = dialog.displayedText.status;
            check(!backend.cancel_import(dialog.report.latest), "completed import cannot cancel");
            dialog.close();
            backend.stop();
            phase = 9;
            break;
        case 9:
            if (backend.state !== 0 || backend.workers()) return;
            check(backend.start(false), "restart acquisition");
            phase = 10;
            break;
        case 10:
            if (!host.frame || backend.produced < 3) return;
            check(backend.generation !== generation && !!dialog.preview, "import survives acquisition restart");
            check(submit("legacy.json", 0), "submit before close");
            backend.close_imports();
            phase = 11;
            break;
        case 11:
            if (!dialog.report.receipts.every(r => ["loaded", "failed", "cancelled"].indexOf(r.status.state) >= 0)) return;
            check(dialog.report.closed && !dialog.preview && !dialog.submit(), "close fences outstanding result");
            checks.states.closed = dialog.displayedText.status;
            checks.retiring = dialog.report;
            host.recreate();
            phase = 12;
            break;
        case 12:
            if (backend.workers()) return;
            check(!dialog.preview && !dialog.report.receipts.length, "recreated backend has no old imported result");
            check(backend.start(false), "recreated acquisition start");
            phase = 13;
            break;
        case 13:
            if (!host.frame || backend.produced < 3 || !line.item.paints || !map.item.paints) return;
            checks.minimum = [host.minimumWidth, host.minimumHeight];
            checks.size = [host.width, host.height];
            check(host.minimumWidth <= 1180 && host.minimumHeight <= 690 && dialog.labelsFit(), "UI fits");
            console.log("DISPLAY_PLOT_REGIONS " + JSON.stringify({spectrum: line.item.plotRegion(host.contentItem), spectrogram: map.item.plotRegion(host.contentItem)}));
            host.saveImage(host.argument("--snapshot"));
            phase = 14;
            break;
        case 14:
            if (host.savePending) return;
            check(host.saved, "main image saved");
            check(submit("legacy.json", 0), "admit import before QObject teardown");
            checks.teardown = dialog.report;
            checks.lifecycle = true;
            console.log("DISPLAY_IMPORT " + JSON.stringify(checks));
            console.log("DISPLAY_IMPORT_PASS legacy snapshot failure recovery restart close recreate teardown");
            test.stop();
            Qt.quit();
            break;
        }
    }
}

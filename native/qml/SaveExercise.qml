import QtQuick

Timer {
    id: test
    required property var host
    required property var dialog
    required property var triggerPanel
    required property var line
    required property var map
    property bool enabled: false
    running: enabled
    interval: 10
    repeat: true
    property int phase: 0
    property var checks: ({})
    property double baseline: 0
    property double generation: 0
    property bool dialogSaved: false
    readonly property bool product: host.argument("--save-format") === "product"
    readonly property int extra: product ? 1 : 0
    readonly property bool loadTest: host.argument("--save-load-test") === "1"
    readonly property int loadExtra: loadTest ? 2 : 0
    property bool pairChecked: false
    function check(ok, message) { return host.check(ok, "measurement save: " + message); }
    function path(name) { return host.argument("--save-directory") + "/" + name; }
    function submit(name, format) {
        dialog.destination = path(name);
        dialog.formatIndex = format + (product ? 2 : 0);
        return dialog.submit();
    }
    function complete(count) { return dialog.report.receipts.length === count
        && dialog.report.receipts.every(r => ["saved", "failed", "cancelled"].indexOf(r.status.state) >= 0); }
    onTriggered: {
        if (!check(Date.now() < host.deadline, "timeout phase " + phase))
            return;
        const backend = host.backend;
        if (!check(backend && backend.state !== 4, "worker failure: " + (backend ? backend.error : "missing backend")))
            return;
        switch (phase) {
        case 0:
            check(backend.start(false), "start");
            generation = backend.generation;
            phase = 1;
            break;
        case 1:
            if (!host.frame || backend.produced < 3 || !line.item.paints || !map.item.paints)
                return;
            checks.normal = host.frame;
            check(dialog.selectResult(host.frame), "pin presented normal result");
            check(submit("normal.json", 0), "admit normal JSON");
            check(submit("normal.csv", 1), "admit normal CSV");
            const configuration = JSON.parse(backend.calibration);
            const channel = configuration.channels[0];
            const profiles = configuration.profiles.filter(p => p.channel_id !== channel.channel_id);
            profiles.push({channel_id: channel.channel_id, revision: "edited.c0", v_per_fs: 3.5,
                is_calibrated: true, device_binding: channel.device_binding});
            check(backend.apply_calibration(JSON.stringify({generation: generation, revision: 1, profiles: profiles})), "edit after pin");
            baseline = backend.produced;
            phase = 2;
            break;
        case 2:
            if (!complete(2) || backend.produced <= baseline + 2)
                return;
            const edited = JSON.parse(backend.calibration);
            if (edited.status !== "applied" || !host.latestFrame.channel_calibration[0].profile
                    || host.latestFrame.channel_calibration[0].profile.revision !== "edited.c0")
                return;
            checks.calibration = edited;
            check(dialog.report.receipts.every(r => r.status.state === "saved"), "actual normal completion");
            check(dialog.selected === checks.normal && host.latestFrame.result_id !== checks.normal.result_id, "dialog holds original result while graph advances");
            check(submit("normal.json", 0), "admit existing destination");
            phase = 3;
            break;
        case 3:
            if (!complete(3))
                return;
            check(dialog.report.receipts[2].status.state === "failed", "no clobber failure");
            check(submit("missing/result.json", 0), "admit missing parent");
            phase = 4;
            break;
        case 4:
            if (!complete(4 + (pairChecked ? extra : 0)))
                return;
            check(dialog.report.receipts[3].status.state === "failed", "missing parent fails");
            if (product && !pairChecked) {
                check(submit("partial.csv", 1), "admit CSV with existing sidecar");
                phase = 14;
                break;
            }
            checks.dialog = {labels: dialog.displayedText, size: [dialog.width, dialog.height],
                image_size: [dialog.contentItem.width, dialog.contentItem.height], labels_fit: dialog.labelsFit()};
            check(dialog.labelsFit() && dialog.width <= 1180 && dialog.height <= 690, "dialog fits");
            check(dialog.contentItem.grabToImage(result => {
                check(result.saveToFile(host.argument("--snapshot") + ".save.png"), "dialog image");
                dialogSaved = true;
            }), "dialog image request");
            // Keep the selected CSV/companion explanation until the actual image is captured.
            phase = 15;
            break;
        case 5:
            if (!complete(5 + extra) || !dialogSaved)
                return;
            check(dialog.report.receipts[4 + extra].status.state === "saved", "save recovered");
            if (loadTest) {
                checks.load = {before: backend.produced};
                check(submit("slow.json", 0), "admit slow writer");
                check(submit("cancelled.csv", 1), "admit queued writer");
                checks.load.busy = !submit("busy.json", 0);
                check(checks.load.busy && dialog.report.rejection === "busy", "shared queue busy");
                backend.poll_saves();
                checks.load.outstanding = dialog.report.receipts.slice(5 + extra);
                check(checks.load.outstanding[0].status.state === "writing" && checks.load.outstanding[1].status.state === "queued", "slow writer and queued operation observed");
                checks.load.cancelled = backend.cancel_save(checks.load.outstanding[1].operation_id);
                check(checks.load.cancelled, "cancel only queued operation");
                checks.load.blocked_gui_fft = backend.stall();
                check(checks.load.blocked_gui_fft >= 2, "graph continues with writer and stalled GUI");
                phase = 17;
                break;
            }
            phase = 18;
            break;
        case 18:
            checks.before_stall_result = host.latestFrame.result_id;
            checks.blocked_gui_fft = backend.stall();
            check(checks.blocked_gui_fft >= 2, "acquisition advances with blocked GUI");
            dialog.close();
            // Let Qt consume the coalesced notification before choosing a live interval.
            phase = 19;
            break;
        case 19:
            if (host.latestFrame.result_id === checks.before_stall_result)
                return;
            check(triggerPanel.submit(triggerPanel.requestAt(host.latestFrame.interval[0], 1)), "trigger request");
            phase = 6;
            break;
        case 6:
            if (!host.trigger || host.trigger.status !== "complete")
                return;
            checks.trigger = host.trigger;
            check(dialog.selectResult(host.frame), "pin held trigger result");
            line.detach();
            map.detach();
            check(line.item.frame === host.frame && map.item.frame === host.frame, "detached views share held result");
            check(submit("trigger.json", 0), "admit trigger JSON");
            check(submit("trigger.csv", 1), "admit trigger CSV");
            phase = 7;
            break;
        case 7:
            if (!complete(7 + extra + loadExtra))
                return;
            check(dialog.report.receipts.slice(5 + extra + loadExtra).every(r => r.status.state === "saved"), "actual trigger completion");
            const stale = {generation: generation - 1, result_id: host.frame.result_id, destination: path("stale.json"), format: product ? "product_json" : "json"};
            check(!backend.save_result(JSON.stringify(stale)), "stale pinned identity rejected");
            check(!backend.save_result("{}"), "malformed request rejected");
            check(!backend.cancel_save(dialog.report.receipts[0].operation_id), "completed save cannot be cancelled");
            check(submit("stop.json", 0), "admit at acquisition stop");
            check(submit("stop.csv", 1), "admit second at stop");
            backend.stop();
            backend.close_saves();
            phase = 8;
            break;
        case 8:
            if (!complete(9 + extra + loadExtra) || backend.state !== 0 || backend.workers())
                return;
            check(backend.reclaimed, "acquisition reclaimed independently");
            check(!dialog.submit(), "closed admission rejected");
            checks.receipts = dialog.report.receipts;
            checks.closed = dialog.report.closed;
            checks.detached_hold = line.item.frame === checks.trigger.frame && map.item.frame === checks.trigger.frame;
            dialog.close();
            line.dock();
            map.dock();
            check(backend.start(false), "restart");
            phase = 9;
            break;
        case 9:
            if (!host.latestFrame || backend.produced < 2)
                return;
            check(host.latestFrame.source.generation !== generation, "new generation");
            check(!backend.pin_result(generation, checks.normal.result_id), "old presentation fenced");
            checks.restart = true;
            host.recreate();
            phase = 10;
            break;
        case 10:
            if (backend.workers())
                return;
            check(backend.start(false), "start recreated backend");
            phase = 11;
            break;
        case 11:
            if (!host.frame || backend.produced < 3 || !line.item.paints || !map.item.paints)
                return;
            check(host.minimumWidth <= 1180 && host.minimumHeight <= 690, "main size");
            checks.minimum = [host.minimumWidth, host.minimumHeight];
            checks.size = [host.width, host.height];
            checks.recreate = true;
            console.log("DISPLAY_PLOT_REGIONS " + JSON.stringify({spectrum: line.item.plotRegion(host.contentItem), spectrogram: map.item.plotRegion(host.contentItem)}));
            host.saveImage(host.argument("--snapshot"));
            phase = 12;
            break;
        case 12:
            if (host.savePending)
                return;
            check(host.saved, "main image saved");
            checks.teardown = host.frame;
            check(dialog.selectResult(host.frame), "pin before QObject teardown");
            check(submit("teardown.json", 0), "admit teardown JSON");
            check(submit("teardown.csv", 1), "admit teardown CSV");
            console.log("DISPLAY_SAVE " + JSON.stringify(checks));
            console.log("DISPLAY_SAVE_PASS pin normal trigger immutable failure recovery stop restart recreate teardown");
            test.stop();
            Qt.quit();
            break;
        case 14:
            if (!complete(5))
                return;
            check(dialog.report.receipts[4].status.state === "failed", "CSV sidecar publication failed");
            pairChecked = true;
            phase = 4;
            break;
        case 15:
            if (!dialogSaved)
                return;
            check(submit("recovery.json", 0), "recovery after I/O failure");
            phase = 5;
            break;
        case 17:
            if (!complete(7 + extra))
                return;
            checks.load.after = backend.produced;
            check(checks.load.after >= checks.load.before + 2, "acquisition advances across slow save");
            check(dialog.report.receipts[5 + extra].status.state === "saved" && dialog.report.receipts[6 + extra].status.state === "cancelled", "slow save completes and queued cancel creates no file");
            phase = 18;
            break;
        }
    }
}

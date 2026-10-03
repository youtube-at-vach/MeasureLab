import QtQuick

Timer {
    required property var host
    required property var panel
    required property var line
    required property var map
    required property var dialog
    property bool enabled: false
    running: enabled
    interval: 10
    repeat: true
    property int phase: 0
    property int submitted: 0
    property double generation: 0
    property var firstRequest: null
    property var held: null
    property string heldText: ""
    property var checks: ({})
    function check(ok, message) { return host.check(ok, "filter: " + message); }
    function saveNext(prefix, offset) {
        const receipts = dialog.report.receipts;
        if (receipts.length !== submitted || receipts.some(r => r.status.state !== "saved"))
            return false;
        if (submitted === offset + 4)
            return true;
        const format = submitted - offset;
        dialog.destination = host.argument("--save-directory") + "/" + prefix + [".json", ".csv", ".product.json", ".product.csv"][format];
        dialog.formatIndex = format;
        check(dialog.submit(), "admit immutable snapshot format " + format);
        submitted++;
        return false;
    }
    onTriggered: {
        if (!check(Date.now() < host.deadline, "timeout phase " + phase))
            return;
        const backend = host.backend;
        const response = host.trigger;
        if (!check(backend && backend.state !== 4, "worker failed: " + (backend ? backend.error : "missing")))
            return;
        switch (phase) {
        case 0:
            check(backend.subscribers() === 2 && backend.start(false), "two views start");
            generation = backend.generation;
            phase = 1;
            break;
        case 1:
            if (!host.latestFrame || backend.produced < 3 || !line.item.paints || !map.item.paints)
                return;
            check(host.latestFrame.source.precision === "F64" && host.latestFrame.source.timebase.rate.numerator === 24000, "derived precision and rate");
            checks.normal = host.latestFrame;
            check(dialog.selectResult(host.latestFrame), "pin normal");
            phase = 2;
            break;
        case 2:
            if (!saveNext("normal", 0))
                return;
            checks.normal_saved = true;
            dialog.close();
            const n = host.latestFrame.interval[1] - host.latestFrame.interval[0];
            firstRequest = panel.requestAt(host.latestFrame.interval[1] + 2 * n, 1);
            check(panel.submit(firstRequest), "future derived event");
            phase = 3;
            break;
        case 3:
            if (!response || response.status !== "pending")
                return;
            check(host.frame === null && response.frame === null, "pending contains no numbers");
            checks.pending = true;
            phase = 4;
            break;
        case 4:
            const end = Math.floor(firstRequest.request.event.sample.numerator / 2) + firstRequest.request.post;
            if (host.latestFrame.interval[1] < end)
                return;
            check(response.status === "pending" && panel.retry(), "explicit retry");
            phase = 5;
            break;
        case 5:
            if (!response || response.status !== "complete")
                return;
            check(line.item.frame === map.item.frame && line.item.frame === response.frame, "shared derived trigger");
            held = response.frame;
            check(panel.submit(panel.requestAt(response.history.interval[0], 2)), "same derived interval");
            phase = 6;
            break;
        case 6:
            if (!response || response.revision !== 2 || response.status !== "complete")
                return;
            check(JSON.stringify(held.raw_result_id) === JSON.stringify(response.frame.raw_result_id), "shared FFT identity");
            check(["continuous-cache", "trigger-cache"].indexOf(response.fft_origin) >= 0, "reuse FFT");
            held = response.frame;
            heldText = JSON.stringify(held);
            checks.trigger = response;
            line.detach();
            map.detach();
            line.item.zoom(1000, 0.5);
            checks.blocked_gui_fft = backend.stall() + backend.stall();
            check(checks.blocked_gui_fft >= 2, "analysis continues with blocked GUI");
            check(line.item.highHz - line.item.lowHz === 6000 && map.item.highHz === 12000, "derived axes independent");
            check(JSON.stringify(held) === heldText, "held immutable");
            line.dock();
            map.dock();
            line.item.resetZoom();
            checks.shared_hold = true;
            phase = 7;
            break;
        case 7:
            if (Math.abs(line.item.width - line.width) > 0.5 || Math.abs(map.item.width - map.width) > 0.5)
                return;
            console.log("DISPLAY_PLOT_REGIONS " + JSON.stringify({spectrum: line.item.plotRegion(host.contentItem), spectrogram: map.item.plotRegion(host.contentItem)}));
            host.saveImage(host.argument("--snapshot"));
            phase = 8;
            break;
        case 8:
            if (host.savePending)
                return;
            check(host.saved && panel.buttonsFit && host.minimumWidth <= 1180 && host.minimumHeight <= 690, "image and controls fit");
            checks.minimum = [host.minimumWidth, host.minimumHeight];
            checks.buttons_fit = panel.buttonsFit;
            check(dialog.selectResult(held), "pin held trigger");
            phase = 9;
            break;
        case 9:
            if (!saveNext("trigger", 4))
                return;
            checks.trigger_saved = true;
            dialog.close();
            check(panel.submit(panel.requestAt(0, 3)), "expired derived interval");
            phase = 10;
            break;
        case 10:
            if (!response || response.status !== "gap")
                return;
            check(response.frame === null && host.frame === null, "expired has no numbers");
            checks.gap = true;
            check(panel.release(), "release");
            backend.stop();
            phase = 11;
            break;
        case 11:
            if (backend.state !== 0 || backend.workers())
                return;
            check(backend.reclaimed && JSON.stringify(held) === heldText, "stop releases graph and retains snapshot");
            check(backend.start(false), "restart");
            check(!panel.submit(firstRequest), "old generation rejected");
            phase = 12;
            break;
        case 12:
            if (!host.latestFrame || host.latestFrame.source.generation === generation || backend.produced < 2)
                return;
            check(host.latestFrame.source.stream_id === held.source.stream_id && host.latestFrame.source.generation > generation, "derived restart generation");
            backend.deliver(generation);
            check(host.latestFrame.source.generation > generation, "stale Qt notification rejected");
            backend.stop();
            phase = 13;
            break;
        case 13:
            if (backend.state !== 0 || backend.workers())
                return;
            check(backend.reclaimed && JSON.stringify(held) === heldText, "restart ownership");
            checks.restart = true;
            checks.receipts = dialog.report.receipts;
            host.recreate();
            phase = 14;
            break;
        case 14:
            check(host.frame === null && backend.subscribers() === 2 && JSON.stringify(held) === heldText, "recreate");
            checks.recreate = true;
            console.log("FILTER_DISPLAY " + JSON.stringify(checks));
            console.log("FILTER_DISPLAY_PASS");
            stop();
            Qt.quit();
            break;
        }
    }
}

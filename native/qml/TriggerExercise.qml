import QtQuick

Timer {
    id: test
    required property var host
    required property var panel
    required property var line
    required property var map
    property bool enabled: false
    running: enabled
    interval: 10
    repeat: true
    property int phase: 0
    property var firstRequest: null
    property var held: null
    property string heldText: ""
    property double baseline: 0
    property double generation: 0
    property var checks: ({})
    function check(ok, message) { return host.check(ok, "trigger: " + message); }
    onTriggered: {
        if (!check(Date.now() < host.deadline, "timeout phase " + phase))
            return;
        const backend = host.backend;
        const response = host.trigger;
        if (!check(backend.state !== 4, "worker failed: " + backend.error))
            return;
        switch (phase) {
        case 0:
            check(backend.subscribers() === 2, "two actual view tokens");
            check(backend.start(false), "start");
            generation = backend.generation;
            phase = 1;
            break;
        case 1:
            if (!host.latestFrame || backend.produced < 3)
                return;
            const n = host.latestFrame.interval[1] - host.latestFrame.interval[0];
            firstRequest = panel.requestAt(host.latestFrame.interval[1] + 2 * n, 1);
            panel.sampleText = "bad sample";
            check(!panel.capture(), "invalid manual sample rejected");
            panel.sampleText = (firstRequest.request.event.sample.numerator / 2).toString();
            check(panel.capture(), "queue future request from manual control");
            check(!panel.submit(firstRequest), "duplicate revision rejected");
            phase = 2;
            break;
        case 2:
            if (!response || response.status !== "pending")
                return;
            check(response.frame === null && host.frame === null, "pending has no numeric frame");
            check(response.history.pending.length > 0, "pending interval retained");
            check(response.fractional_residual.numerator === 1 && response.fractional_residual.denominator === 2, "fractional sample retained");
            checks.pending = true;
            phase = 3;
            break;
        case 3:
            const end = Math.floor(firstRequest.request.event.sample.numerator / 2) + firstRequest.request.post;
            if (host.latestFrame.interval[1] < end)
                return;
            check(response.status === "pending", "no implicit retry");
            check(panel.retry(), "explicit retry queued");
            phase = 4;
            break;
        case 4:
            if (!response || response.status !== "complete")
                return;
            check(line.item.frame === map.item.frame && line.item.frame === response.frame, "two views share trigger projection");
            check(Object.isFrozen(response.frame.peak_fs.values), "trigger projection frozen");
            held = response.frame;
            heldText = JSON.stringify(held);
            const same = panel.requestAt(response.history.interval[0], 2);
            check(panel.submit(same), "second reader same interval");
            phase = 5;
            break;
        case 5:
            if (!response || response.revision !== 2 || response.status !== "complete")
                return;
            check(JSON.stringify(response.frame.raw_result_id) === JSON.stringify(held.raw_result_id), "same raw FFT shared");
            check(response.frame.result_id !== held.result_id, "distinct capture metadata ID");
            check(["continuous-cache", "trigger-cache"].indexOf(response.fft_origin) >= 0, "no second FFT");
            checks.shared_raw = true;
            checks.retry = true;
            held = response.frame;
            heldText = JSON.stringify(held);
            baseline = backend.produced;
            if (host.argument("--calibration-test")) {
                line.item.channel = 0;
                map.item.channel = held.source.channel_ids.length - 1;
                check(held.calibration === "partial" && Object.isFrozen(held.channel_calibration), "immutable partial calibration");
                check(line.item.voltageValue !== null && map.item.voltageValue === null, "calibrated and missing profile voltage");
            }
            line.detach();
            map.detach();
            line.item.zoom(1000, 0.5);
            // Correctness probe, not a throughput budget: keep Qt blocked for 640 ms.
            const advanced = backend.stall() + backend.stall();
            checks.blocked_gui_fft = advanced;
            check(advanced >= 2, "acquisition advances with held result and blocked GUI: " + advanced);
            phase = 6;
            break;
        case 6:
            if (backend.produced <= baseline + 1)
                return;
            check(line.item.frame === held && map.item.frame === held && JSON.stringify(held) === heldText, "hold immutable during acquisition");
            check(line.item.highHz - line.item.lowHz === 12000 && map.item.highHz === 24000, "independent trigger zoom");
            check(backend.subscribers() === 2 && line.detached && map.detached, "detach preserves demand and hold");
            line.dock();
            map.dock();
            line.item.resetZoom();
            checks.hold_continued = true;
            checks.detached_hold = true;
            phase = 14;
            break;
        case 14:
            // Reparenting schedules a layout polish. Record the docked geometry only
            // after the loaded views have actually resized to their normal panes.
            if (Math.abs(line.item.width - line.width) > 0.5 || Math.abs(map.item.width - map.width) > 0.5
                || Math.abs(line.item.height - line.height) > 0.5 || Math.abs(map.item.height - map.height) > 0.5)
                return;
            console.log("DISPLAY_PLOT_REGIONS " + JSON.stringify({spectrum: line.item.plotRegion(host.contentItem), spectrogram: map.item.plotRegion(host.contentItem)}));
            host.saveImage(host.argument("--snapshot"));
            phase = 7;
            break;
        case 7:
            if (host.savePending)
                return;
            check(host.saved, "trigger image saved");
            check(panel.buttonsFit, "translated trigger controls fit");
            check(host.minimumWidth <= 1180 && host.minimumHeight <= 690, "trigger UI size limit");
            checks.labels = panel.displayedText;
            checks.buttons_fit = panel.buttonsFit;
            checks.minimum = [host.minimumWidth, host.minimumHeight];
            checks.size = [host.width, host.height];
            if (host.argument("--calibration-test")) {
                checks.calibration = {
                    result_id: held.result_id,
                    spectrum: {channel: line.item.channel, voltage: line.item.voltageText, profile: line.item.profileText},
                    spectrogram: {channel: map.item.channel, voltage: map.item.voltageText, profile: map.item.profileText},
                    labels_fit: line.item.calibrationLabelsFit && map.item.calibrationLabelsFit
                };
                check(line.item.frame === held && map.item.frame === held, "calibration uses held result");
                check(checks.calibration.labels_fit, "calibration labels fit");
            }
            check(panel.submit(panel.requestAt(0, 3)), "expired request");
            phase = 8;
            break;
        case 8:
            if (!response || response.status !== "gap")
                return;
            check(response.frame === null && response.history.missing.length > 0 && host.frame === null, "gap has missing interval and no numeric frame");
            check(JSON.stringify(held) === heldText, "external held frame survives history eviction");
            check(!backend.retry_trigger(generation - 1, 3), "stale retry rejected");
            check(!backend.release_trigger(generation, 2), "old release rejected");
            const stale = panel.requestAt(0, 4);
            stale.request.event.generation = generation - 1;
            check(!panel.submit(stale), "stale request rejected");
            check(panel.release(), "release active capture");
            check(!panel.release(), "duplicate release rejected");
            checks.gap = true;
            checks.stale = true;
            phase = 9;
            break;
        case 9:
            if (!host.frame || host.trigger.status !== "released")
                return;
            check(line.item.frame === map.item.frame && host.frame === host.latestFrame, "release returns both views to continuous result");
            checks.release = true;
            const size = host.latestFrame.interval[1] - host.latestFrame.interval[0];
            // Release is immediately fenced; its cache cleanup is owner-acknowledged later.
            if (!panel.submit(panel.requestAt(host.latestFrame.interval[1] + 100 * size, 4)))
                return;
            backend.stop();
            backend.stop();
            phase = 10;
            break;
        case 10:
            if (backend.state !== 0 || backend.workers())
                return;
            check(backend.reclaimed && host.trigger.status === "cancelled" && host.trigger.frame === null, "stop cancels pending and reclaims");
            checks.cancelled = true;
            check(backend.start(false), "restart");
            check(host.trigger === null, "restart resets mailbox");
            phase = 11;
            break;
        case 11:
            if (!host.latestFrame || host.latestFrame.source.generation === generation)
                return;
            check(!panel.submit(firstRequest), "old generation after restart rejected");
            check(JSON.stringify(held) === heldText, "held result survives restart");
            backend.deliver(generation);
            check(host.latestFrame.source.generation > generation, "stale Qt notification fenced");
            backend.stop();
            phase = 12;
            break;
        case 12:
            if (backend.state !== 0 || backend.workers())
                return;
            check(backend.reclaimed, "restart graph reclaimed");
            checks.restart = true;
            host.recreate();
            phase = 13;
            break;
        case 13:
            check(host.frame === null && host.trigger === null && backend.subscribers() === 2, "backend recreation clears internal capture");
            check(JSON.stringify(held) === heldText, "external capture survives backend destruction");
            checks.recreate = true;
            console.log("DISPLAY_TRIGGER " + JSON.stringify(checks));
            console.log("DISPLAY_TRIGGER_PASS");
            test.stop();
            Qt.quit();
            break;
        }
    }
}

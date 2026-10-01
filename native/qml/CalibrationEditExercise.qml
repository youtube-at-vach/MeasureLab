import QtQuick

Timer {
    id: test
    required property var host
    required property var editor
    required property var triggerPanel
    required property var line
    required property var map
    property bool enabled: false
    running: enabled
    interval: 10
    repeat: true
    property int phase: 0
    property var held: null
    property string heldText: ""
    property var first: null
    property var updated: null
    property var checks: ({})
    property double generation: 0
    property double baseline: 0
    property bool dialogSaved: false
    function check(ok, message) { return host.check(ok, "calibration edit: " + message); }
    function status(revision, value) {
        const receipt = editor.configuration;
        return receipt && receipt.revision === revision && receipt.status === value;
    }
    function capture(revision, start) {
        return triggerPanel.submit(triggerPanel.requestAt(start, revision));
    }
    function editChannel(index, value, revision, calibrated) {
        editor.channel = index;
        editor.loadChannel();
        editor.factorText = value.toString();
        editor.profileRevision = revision;
        editor.calibrated = calibrated;
        return editor.applyDraft();
    }
    onTriggered: {
        if (!check(Date.now() < host.deadline, "timeout phase " + phase))
            return;
        const backend = host.backend;
        const response = host.trigger;
        if (!check(backend.state !== 4, "worker failed: " + backend.error))
            return;
        switch (phase) {
        case 0:
            check(backend.start(false), "start");
            generation = backend.generation;
            phase = 1;
            break;
        case 1:
            if (!host.latestFrame || backend.produced < 3 || !editor.configuration)
                return;
            checks.initial = editor.configuration;
            check(capture(1, host.latestFrame.interval[0]), "capture before edit");
            phase = 2;
            break;
        case 2:
            if (!response || response.status !== "complete")
                return;
            first = response;
            held = response.frame;
            heldText = JSON.stringify(held);
            line.item.channel = 0;
            map.item.channel = held.source.channel_ids.length - 1;
            editor.open();
            editor.factorText = "bad";
            check(!editor.applyDraft(), "bad numeric draft rejected");
            check(editChannel(0, 3.5, "edited.c0", true), "apply edited coefficient from dialog");
            phase = 3;
            break;
        case 3:
            if (!status(1, "applied") || host.latestFrame.channel_calibration[0].profile.revision !== "edited.c0")
                return;
            checks.edited = editor.configuration;
            check(line.item.frame === held && map.item.frame === held && JSON.stringify(held) === heldText, "edit leaves both held views unchanged");
            check(capture(2, first.history.interval[0]), "capture same raw interval after edit");
            phase = 4;
            break;
        case 4:
            if (!response || response.revision !== 2 || response.status !== "complete")
                return;
            updated = response;
            check(JSON.stringify(response.frame.raw_result_id) === JSON.stringify(held.raw_result_id), "edit preserves shared raw FFT identity");
            check(response.trigger_evaluations === first.trigger_evaluations, "calibration does not evaluate another FFT");
            check(response.frame.channel_calibration[0].profile.revision === "edited.c0", "new trigger uses edited profile");
            checks.shared_raw = true;
            checks.hold_immutable = true;
            checks.first = first;
            checks.updated = response;
            check(!backend.apply_calibration("{}"), "malformed submission rejected");
            const stale = editor.submission();
            stale.generation -= 1;
            check(!backend.apply_calibration(JSON.stringify(stale)), "old generation rejected");
            const bad = JSON.parse(JSON.stringify(editor.submission()));
            bad.profiles[0].device_binding = {device: "wrong device", port: 99};
            check(backend.apply_calibration(JSON.stringify(bad)), "enqueue misbound profile");
            phase = 5;
            break;
        case 5:
            if (!status(2, "rejected"))
                return;
            checks.rejected = editor.configuration;
            check(JSON.stringify(checks.rejected.profiles) === JSON.stringify(checks.edited.profiles), "invalid replacement is atomic");
            check(editor.labelsFit() && editor.width <= 1180 && editor.height <= 690, "editor labels and size fit");
            checks.editor = {labels: editor.displayedText, labels_fit: editor.labelsFit(), size: [editor.width, editor.height]};
            // Capture the QML-owned dialog content independently of the native root item.
            if (!editor.contentItem.grabToImage(result => {
                check(result.saveToFile(host.argument("--snapshot") + ".editor.png"), "dialog image saved");
                dialogSaved = true;
            }))
                check(false, "dialog capture requested");
            phase = 6;
            break;
        case 6:
            if (!dialogSaved)
                return;
            check(editChannel(0, 3.5, "disabled.c0", false), "disable calibration from dialog");
            phase = 7;
            break;
        case 7:
            if (!status(3, "applied") || host.latestFrame.channel_calibration[0].profile.revision !== "disabled.c0")
                return;
            checks.disabled = editor.configuration;
            check(host.latestFrame.rms_v.values[0] === null && host.latestFrame.rms_v.reasons[0] === "uncalibrated", "disabled normal voltage has reason");
            check(capture(3, host.latestFrame.interval[0]), "capture disabled profile");
            phase = 8;
            break;
        case 8:
            if (!response || response.revision !== 3 || response.status !== "complete")
                return;
            checks.disabled_capture = response;
            check(response.frame.rms_v.values[0] === null, "disabled trigger voltage stays null");
            const index = response.frame.source.channel_ids.length - 1;
            check(editChannel(index, 5, "added.last", true), "create profile for previously missing ChannelId");
            phase = 9;
            break;
        case 9:
            const last = host.latestFrame.source.channel_ids.length - 1;
            if (!status(4, "applied") || !host.latestFrame.channel_calibration[last].profile)
                return;
            checks.added = editor.configuration;
            check(capture(4, host.latestFrame.interval[0]), "capture added profile");
            phase = 10;
            break;
        case 10:
            if (!response || response.revision !== 4 || response.status !== "complete")
                return;
            checks.added_capture = response;
            check(response.frame.channel_calibration[map.item.channel].profile.revision === "added.last", "explicit channel binding of new profile");
            editor.close();
            line.detach();
            map.detach();
            const advanced = backend.stall();
            check(advanced >= 2, "acquisition continues during blocked GUI");
            check(JSON.stringify(held) === heldText && line.item.frame === response.frame && map.item.frame === response.frame, "all held results survive edit and detachment");
            checks.blocked_gui_fft = advanced;
            checks.detached_hold = true;
            line.dock();
            map.dock();
            phase = 11;
            break;
        case 11:
            if (Math.abs(line.item.width - line.width) > 0.5 || Math.abs(map.item.width - map.width) > 0.5)
                return;
            checks.minimum = [host.minimumWidth, host.minimumHeight];
            checks.size = [host.width, host.height];
            check(host.minimumWidth <= 1180 && host.minimumHeight <= 690, "main UI size");
            console.log("DISPLAY_PLOT_REGIONS " + JSON.stringify({spectrum: line.item.plotRegion(host.contentItem), spectrogram: map.item.plotRegion(host.contentItem)}));
            host.saveImage(host.argument("--snapshot"));
            phase = 12;
            break;
        case 12:
            if (host.savePending)
                return;
            check(host.saved && JSON.stringify(held) === heldText, "image saved without mutating old result");
            backend.stop();
            phase = 13;
            break;
        case 13:
            if (backend.state !== 0 || backend.workers())
                return;
            check(backend.reclaimed, "stopped graph reclaimed");
            check(!backend.apply_calibration(JSON.stringify({generation: generation, revision: 5, profiles: checks.added.profiles})), "stopped edit rejected");
            check(backend.start(false), "restart");
            phase = 14;
            break;
        case 14:
            if (!host.latestFrame || host.latestFrame.source.generation === generation)
                return;
            check(editor.configuration.revision === 0 && JSON.stringify(editor.configuration.profiles) === JSON.stringify(checks.initial.profiles), "restart uses initial session configuration");
            check(JSON.stringify(held) === heldText, "old result survives restart");
            checks.restart = true;
            host.recreate();
            phase = 15;
            break;
        case 15:
            check(JSON.stringify(held) === heldText && host.frame === null && backend.workers() === 0, "backend destruction retains external result and reclaims worker");
            checks.recreate = true;
            console.log("DISPLAY_CALIBRATION_EDIT " + JSON.stringify(checks));
            console.log("DISPLAY_CALIBRATION_EDIT_PASS");
            test.stop();
            Qt.quit();
            break;
        }
    }
}

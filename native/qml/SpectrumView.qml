import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: view
    required property var source
    required property var frame
    required property var messages
    property bool detached: false
    property bool workspaceControls: false
    property bool capturePending: false
    property var subscribedSource: null
    property bool heatmap: false
    property double token: 0
    property int channel: 0
    property real lowHz: 0
    property real highHz: 24000
    property int cursorBin: 0
    property var rows: []
    property string lastId: ""
    property int paints: 0
    readonly property string resultId: frame ? frame.result_id : ""
    readonly property real cursorHz: frame ? frame.frequency_hz[cursorBin] : 0
    readonly property var cursorValue: frame ? frame.peak_fs.values[cursorBin * frame.source.channel_ids.length + channel] : null
    readonly property string cursorReason: frame ? (frame.peak_fs.reasons[cursorBin * frame.source.channel_ids.length + channel] || "") : ""
    readonly property var displayedText: ({
        heading: heading.text,
        reset: resetButton.text,
        detach: detachButton.text,
        save: saveButton.text
    })
    readonly property bool buttonsFit: resetButton.width >= resetButton.implicitWidth && detachButton.width >= detachButton.implicitWidth && saveButton.width >= saveButton.implicitWidth

    signal detachRequested()
    signal saveRequested()
    function tr(key) {
        return messages[key];
    }
    function plotRegion(target) {
        const point = plot.mapToItem(target, 52, 14);
        return [Math.floor(point.x), Math.floor(point.y), Math.ceil(plot.width - 64), Math.ceil(plot.height - 40)];
    }
    Component.onCompleted: {
        subscribedSource = source;
        token = subscribedSource.subscribe();
    }
    Component.onDestruction: {
        if (subscribedSource)
            subscribedSource.unsubscribe(token);
    }
    onFrameChanged: {
        if (!frame) {
            rows = [];
            lastId = "";
        } else if (lastId !== frame.result_id) {
            if (rows.length && rows[rows.length - 1].source.generation !== frame.source.generation)
                rows = [];
            rows = rows.concat([frame]).slice(-32);
            lastId = frame.result_id;
        }
        plot.requestPaint();
    }
    onChannelChanged: plot.requestPaint()
    onLowHzChanged: plot.requestPaint()
    onHighHzChanged: plot.requestPaint()
    onCursorBinChanged: plot.requestPaint()
    function db(value) {
        return value === null ? null : (value === 0 ? -120 : Math.max(-120, 20 * Math.log(value) / Math.LN10));
    }
    function resetZoom() {
        lowHz = 0;
        highHz = frame ? frame.frequency_hz[frame.frequency_hz.length - 1] : 24000;
    }
    function zoom(center, factor) {
        const maxHz = frame ? frame.frequency_hz[frame.frequency_hz.length - 1] : 24000;
        const span = Math.min(maxHz, Math.max(maxHz / 128, (highHz - lowHz) * factor));
        lowHz = Math.min(maxHz - span, Math.max(0, center - span / 2));
        highHz = lowHz + span;
    }
    function cursorAt(fraction) {
        if (!frame)
            return;
        const hz = lowHz + Math.max(0, Math.min(1, fraction)) * (highHz - lowHz);
        const step = frame.frequency_hz[1] - frame.frequency_hz[0];
        cursorBin = Math.max(0, Math.min(frame.frequency_hz.length - 1, Math.round(hz / step)));
    }
    RowLayout {
        Label {
            id: heading
            text: view.heatmap ? tr("migration.display.spectrogram") : tr("migration.display.spectrum")
            font.bold: true
        }
        ComboBox {
            Layout.fillWidth: true
            model: view.frame ? view.frame.source.channel_ids : []
            currentIndex: view.channel
            onActivated: view.channel = currentIndex
        }
        Button {
            id: resetButton
            text: tr("migration.display.reset_zoom")
            onClicked: view.resetZoom()
        }
    }
    Canvas {
        id: plot
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 140
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            ctx.fillStyle = "#101b2b";
            ctx.fillRect(0, 0, width, height);
            const left = 52, top = 14, w = width - 64, h = height - 40;
            if (w <= 0 || h <= 0)
                return;
            ctx.font = "11px sans-serif";
            ctx.fillStyle = "#b9cbe3";
            ctx.fillText(view.lowHz.toFixed(0) + " Hz", left, height - 8);
            ctx.fillText(view.highHz.toFixed(0) + " Hz", width - 76, height - 8);
            const current = view.frame;
            if (!current)
                return;
            const channels = current.source.channel_ids.length;
            // Raster reduction preserves maxima; cursor always reads the original bin.
            function buckets(row) {
                const output = new Array(Math.ceil(w)).fill(null);
                const invalid = new Array(output.length).fill(false);
                for (let k = 0; k < row.frequency_hz.length; ++k) {
                    const hz = row.frequency_hz[k];
                    if (hz < view.lowHz || hz > view.highHz)
                        continue;
                    const x = Math.min(output.length - 1, Math.floor((hz - view.lowHz) / (view.highHz - view.lowHz) * w));
                    const value = view.db(row.peak_fs.values[k * channels + view.channel]);
                    if (value !== null)
                        output[x] = output[x] === null ? value : Math.max(output[x], value);
                    else
                        invalid[x] = true;
                }
                return {
                    values: output,
                    invalid: invalid
                };
            }
            if (view.heatmap) {
                const first = view.rows[0], last = view.rows[view.rows.length - 1];
                if (!first || !last)
                    return;
                const start = first.interval[0], end = last.interval[1], span = end - start;
                for (let r = 0; r < view.rows.length; ++r) {
                    const row = view.rows[r], values = buckets(row).values;
                    const y = top + (end - row.interval[1]) / span * h;
                    const rh = (row.interval[1] - row.interval[0]) / span * h;
                    for (let x = 0; x < values.length; ++x) {
                        if (values[x] === null)
                            continue;
                        const level = Math.max(0, Math.min(1, (values[x] + 100) / 100));
                        ctx.fillStyle = Qt.hsla(0.64 - 0.5 * level, 0.85, 0.12 + 0.5 * level, 1);
                        ctx.fillRect(left + x, y, 1.1, rh);
                    }
                }
                const rate = current.source.timebase.rate;
                ctx.fillStyle = "#b9cbe3";
                ctx.fillText("0 s", 4, top + 10);
                ctx.fillText(((end - start) * rate.denominator / rate.numerator).toFixed(2) + " s", 4, top + h);
            } else {
                for (let db = 0; db >= -120; db -= 30) {
                    const y = top - db / 120 * h;
                    ctx.strokeStyle = "#27364d";
                    ctx.beginPath();
                    ctx.moveTo(left, y);
                    ctx.lineTo(left + w, y);
                    ctx.stroke();
                    ctx.fillStyle = "#b9cbe3";
                    ctx.fillText(db.toString(), 8, y + 4);
                }
                ctx.strokeStyle = "#62d8e9";
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                const raster = buckets(current), values = raster.values;
                let drawing = false;
                for (let x = 0; x < values.length; ++x) {
                    if (values[x] === null) {
                        if (raster.invalid[x])
                            drawing = false;
                        continue;
                    }
                    const y = top + Math.max(0, Math.min(1, -values[x] / 120)) * h;
                    if (drawing)
                        ctx.lineTo(left + x, y);
                    else
                        ctx.moveTo(left + x, y);
                    drawing = true;
                }
                ctx.stroke();
                ctx.fillStyle = "#b9cbe3";
                ctx.fillText("dBFS peak", left + 8, top + 14);
            }
            const cx = left + (view.cursorHz - view.lowHz) / (view.highHz - view.lowHz) * w;
            if (cx >= left && cx <= left + w) {
                ctx.strokeStyle = "#f3bc68";
                ctx.beginPath();
                ctx.moveTo(cx, top);
                ctx.lineTo(cx, top + h);
                ctx.stroke();
            }
            view.paints += 1;
        }
        MouseArea {
            anchors.fill: parent
            onClicked: mouse => view.cursorAt((mouse.x - 52) / (width - 64))
            onWheel: wheel => {
                view.zoom(view.lowHz + (wheel.x - 52) / (width - 64) * (view.highHz - view.lowHz), wheel.angleDelta.y > 0 ? 0.5 : 2);
                wheel.accepted = true;
            }
        }
    }
    Label {
        Layout.fillWidth: true
        elide: Text.ElideRight
        text: !view.frame ? tr("migration.display.waiting") : (view.cursorValue === null ? tr("migration.display.invalid").arg(view.cursorReason) : tr("migration.display.cursor").arg(view.cursorHz.toFixed(2)).arg(view.cursorValue.toPrecision(8)))
    }
    RowLayout {
        visible: view.workspaceControls
        Button {
            id: detachButton
            text: view.detached ? tr("migration.display.dock") : tr("migration.display.detach")
            onClicked: view.detachRequested()
        }
        Button {
            id: saveButton
            text: tr("migration.display.save_image")
            enabled: !!view.frame && !view.capturePending
            onClicked: view.saveRequested()
        }
    }
}

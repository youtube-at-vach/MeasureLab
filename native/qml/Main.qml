import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import BridgeProbe 1.0

ApplicationWindow {
    id: window
    visible: true
    width: 560
    height: 360
    minimumWidth: 440
    minimumHeight: 300
    title: qsTr("MeasureLab — Qt boundary evaluation")
    property var backend: null
    property bool testing: false
    property int phase: 0
    property double oldGeneration: 0
    property double viewToken: 0
    property double sessionToken: 0
    property double baseline: 0
    property var secondWindow: null
    property double deadline: Date.now() + 10000

    function stateLabel(state) {
        switch (state) {
        case 0:
            return qsTr("Idle");
        case 1:
            return qsTr("Preparing");
        case 2:
            return qsTr("Running");
        case 3:
            return qsTr("Stopping");
        case 4:
            return qsTr("Failed: simulated start failure");
        }
        return qsTr("Unknown");
    }

    function check(condition, message) {
        if (!condition) {
            console.error("PROBE_FAIL " + message);
            Qt.exit(1);
        }
        return condition;
    }

    Component {
        id: factory
        Backend {}
    }
    Component {
        id: viewFactory
        Window {
            id: view
            required property var source
            property double token: source.subscribe()
            visible: true
            width: 360
            height: 220
            title: qsTr("Shared result view")
            Component.onDestruction: source.unsubscribe(token)
            ListView {
                anchors.fill: parent
                anchors.margins: 20
                model: view.source
                delegate: Label {
                    required property string value
                    text: value
                    height: implicitHeight + 6
                }
            }
        }
    }
    Component.onCompleted: {
        backend = factory.createObject(window);
        viewToken = backend.subscribe();
        testing = backend.testing;
        console.log("PROBE_READY");
        if (testing)
            exercise.start();
    }

    Rectangle {
        id: canvas
        anchors.fill: parent
        color: window.palette.window
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            Label {
                text: qsTr("Synthetic worker · no audio device")
                font.bold: true
            }
            Label {
                text: backend ? stateLabel(backend.state) : qsTr("Recreating")
            }
            RowLayout {
                Button {
                    text: qsTr("Start")
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
                    onClicked: {
                        backend.destroy();
                        backend = factory.createObject(window);
                        viewToken = backend.subscribe();
                        gc();
                    }
                }
            }
            Label {
                text: qsTr("Generation / latest result")
            }
            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: viewToken ? backend : null
                delegate: Label {
                    required property string value
                    text: value
                    width: ListView.view.width
                    height: implicitHeight + 6
                }
            }
            Label {
                text: qsTr("Display updates coalesced: %1").arg(backend ? backend.coalesced : 0)
            }
        }
    }

    Timer {
        interval: 500
        running: Qt.application.arguments.indexOf("--snapshot") >= 0
        onTriggered: {
            const index = Qt.application.arguments.indexOf("--snapshot");
            const requested = canvas.grabToImage(function (result) {
                check(result.saveToFile(Qt.application.arguments[index + 1]), "snapshot save");
                Qt.quit();
            });
            check(requested, "snapshot request");
        }
    }

    Timer {
        id: exercise
        interval: 20
        repeat: true
        onTriggered: {
            if (!check(Date.now() < deadline, "timeout at phase " + phase))
                return;
            switch (phase) {
            case 0:
                if (!check(backend.start(false), "start accepted"))
                    return;
                check(backend.state === 1, "preparing before worker ack");
                check(!backend.start(false), "duplicate start rejected");
                backend.stop();
                backend.stop();
                phase = 1;
                break;
            case 1:
                if (backend.state !== 0)
                    return;
                check(backend.outcome === 2, "preparation cancelled");
                if (backend.start(true))
                    phase = 2;
                break;
            case 2:
                if (backend.state !== 4)
                    return;
                check(backend.outcome === 3, "failure retained");
                backend.stop();
                check(backend.state === 4, "stop must not turn failure into success");
                if (backend.start(false))
                    phase = 3;
                break;
            case 3:
                if (backend.state !== 2 || backend.produced < 4)
                    return;
                list.forceLayout();
                check(list.count === 2, "list model has two rows");
                check(list.itemAtIndex(1) !== null, "delegate instantiated");
                check(Number(list.itemAtIndex(1).value) === backend.produced, "list model value notified");
                oldGeneration = backend.generation;
                check(backend.stall() >= 8, "producer advances during blocked GUI");
                phase = 4;
                break;
            case 4:
                check(backend.coalesced >= 7, "display queue coalesced");
                backend.stop();
                backend.stop();
                phase = 5;
                break;
            case 5:
                if (backend.state !== 0)
                    return;
                check(backend.outcome === 1, "running stopped");
                if (backend.start(false))
                    phase = 6;
                break;
            case 6:
                if (backend.state !== 2)
                    return;
                check(backend.generation > oldGeneration, "new generation");
                const current = backend.generation;
                const produced = backend.produced;
                backend.deliver(oldGeneration);
                check(backend.generation === current && backend.produced === produced, "stale notification ignored");
                // Drop a running object. Its destructor must cancel and join.
                backend.destroy();
                backend = null;
                viewToken = 0;
                gc();
                phase = 7;
                break;
            case 7:
                gc();
                backend = factory.createObject(window);
                viewToken = backend.subscribe();
                phase = 8;
                break;
            case 8:
                check(backend.workers() === 0, "destroyed worker reclaimed");
                check(backend.state === 0 && backend.produced === 0, "new view starts idle");
                if (backend.start(false))
                    phase = 9;
                break;
            case 9:
                if (backend.state !== 2)
                    return;
                secondWindow = viewFactory.createObject(window, {
                    source: backend
                });
                sessionToken = backend.subscribe();
                check(backend.subscribers() === 3, "two views and saving session");
                secondWindow.destroy();
                secondWindow = null;
                phase = 10;
                break;
            case 10:
                if (backend.subscribers() !== 2)
                    return;
                baseline = backend.produced;
                phase = 11;
                break;
            case 11:
                if (backend.produced <= baseline)
                    return;
                check(backend.state === 2, "one view closed, worker continues");
                backend.unsubscribe(viewToken);
                viewToken = 0;
                check(backend.subscribers() === 1, "saving session is sole owner");
                baseline = backend.produced;
                phase = 12;
                break;
            case 12:
                if (backend.produced <= baseline)
                    return;
                check(backend.state === 2, "all views closed, saving session continues");
                backend.unsubscribe(sessionToken);
                check(!backend.unsubscribe(sessionToken), "duplicate token release rejected");
                sessionToken = 0;
                phase = 13;
                break;
            case 13:
                if (backend.state !== 0 || backend.workers() !== 0)
                    return;
                if (secondWindow === null) {
                    check(backend.subscribers() === 0, "last subscriber released");
                    secondWindow = viewFactory.createObject(window, {
                        source: backend
                    });
                }
                if (backend.start(false))
                    phase = 14;
                break;
            case 14:
                if (backend.state !== 2)
                    return;
                secondWindow.destroy();
                secondWindow = null;
                phase = 15;
                break;
            case 15:
                if (backend.state !== 0 || backend.workers() !== 0)
                    return;
                if (secondWindow === null)
                    secondWindow = viewFactory.createObject(window, {
                        source: backend
                    });
                if (backend.start(false))
                    phase = 16;
                break;
            case 16:
                if (backend.state !== 2)
                    return;
                console.log("PROBE_PASS cancel failure stop model slow_gui stale recreate subscriptions window_recreate shutdown");
                // Exit while running; native main checks workers and models after engine drop.
                Qt.quit();
                break;
            }
        }
    }
}

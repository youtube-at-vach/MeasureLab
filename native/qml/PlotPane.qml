import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Evaluation wrapper: the same loaded view moves between two visual parents.
// Closing a floating window destroys that view and releases its actual demand.
Item {
    id: pane
    required property var source
    required property var frame
    required property var messages
    property bool heatmap: false
    property bool active: false
    property bool detached: false
    property bool capturePending: false
    readonly property var item: loader.item
    readonly property var floating: floatingWindow
    implicitWidth: item ? item.implicitWidth : 260
    implicitHeight: item ? item.implicitHeight : 220
    signal saveRequested(var target)
    function tr(key) {
        return messages[key];
    }
    function detach() {
        if (!active)
            return;
        detached = true;
        loader.parent = floatingWindow.contentItem;
        floatingWindow.show();
    }
    function dock() {
        detached = false;
        loader.parent = pane;
        floatingWindow.hide();
    }
    function closeView() {
        // Hide/restore the parent before releasing the loaded QObject.
        dock();
        active = false;
    }
    function reopen() {
        dock();
        active = true;
    }
    onActiveChanged: {
        if (!active)
            dock();
    }
    Rectangle {
        anchors.fill: parent
        color: "#f3f6fa"
        z: -1
    }
    ColumnLayout {
        anchors.centerIn: parent
        width: parent.width
        visible: pane.detached || !pane.active
        Label {
            text: pane.detached ? floatingWindow.title : pane.tr("migration.display.closed")
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }
        Button {
            Layout.alignment: Qt.AlignHCenter
            text: pane.detached ? pane.tr("migration.display.dock") : pane.tr("migration.display.reopen")
            onClicked: pane.detached ? pane.dock() : pane.reopen()
        }
    }
    Loader {
        id: loader
        anchors.fill: parent
        active: pane.active
        sourceComponent: SpectrumView {
            source: pane.source
            frame: pane.frame
            messages: pane.messages
            heatmap: pane.heatmap
            detached: pane.detached
            workspaceControls: true
            capturePending: pane.capturePending
            onDetachRequested: pane.detached ? pane.dock() : pane.detach()
            onSaveRequested: pane.saveRequested(pane.detached ? floatingWindow.contentItem : pane)
        }
    }
    Window {
        id: floatingWindow
        visible: false
        width: 600
        height: 450
        minimumWidth: Math.max(320, pane.implicitWidth + 16)
        minimumHeight: Math.max(280, pane.implicitHeight + 16)
        title: pane.heatmap ? pane.tr("migration.display.spectrogram") : pane.tr("migration.display.spectrum")
        color: "#f3f6fa"
        Rectangle {
            anchors.fill: parent
            color: "#f3f6fa"
            z: -1
        }
        onClosing: close => {
            close.accepted = true;
            pane.closeView();
        }
    }
}

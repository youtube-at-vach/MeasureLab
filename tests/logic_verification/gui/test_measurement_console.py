from __future__ import annotations

import base64

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.module_constants import (
    MODULE_GONIOMETER,
    MODULE_OSCILLOSCOPE,
    MODULE_SPECTROGRAM,
    MODULE_SPECTRUM_ANALYZER,
)
from src.gui.main_window import MainWindow
from src.gui.measurement_console import DEFAULT_CONSOLE_MODULES, MeasurementConsoleWindow
from src.gui.module_registry import NO_INDEPENDENT_DISPLAY, WidgetCapabilities
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper


NO_CAPABILITIES = WidgetCapabilities(
    split_window=NO_INDEPENDENT_DISPLAY,
    compact_mode=NO_INDEPENDENT_DISPLAY,
    comparison=NO_INDEPENDENT_DISPLAY,
)


def test_default_console_uses_goniometer() -> None:
    assert DEFAULT_CONSOLE_MODULES == (
        MODULE_OSCILLOSCOPE,
        MODULE_SPECTRUM_ANALYZER,
        MODULE_SPECTROGRAM,
        MODULE_GONIOMETER,
    )


class _DummyWrapper(QWidget):
    def __init__(self, *, compactable: bool = True):
        super().__init__()
        self.is_compactable = compactable
        self.is_split = False
        self.is_detached = False
        self.console_hosted = False
        self.compact = False
        self.content_widget = self

    def set_console_hosted(self, hosted: bool) -> None:
        self.console_hosted = hosted
        if not hosted:
            self.compact = False

    def toggle_compact(self, compact: bool) -> None:
        self.compact = compact

    def is_compact_mode(self) -> bool:
        return self.compact

    def reattach(self) -> None:
        self.is_detached = False

    def reattach_all(self) -> None:
        self.is_split = False


class _PrimaryActionContent(QWidget):
    def __init__(self):
        super().__init__()
        self.toggle_btn = QPushButton("Start", self)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._update_label)

    def _update_label(self, running: bool) -> None:
        self.toggle_btn.setText("Stop" if running else "Start")


class _ConfigStub:
    def __init__(self):
        self.console_config = {"version": 0}

    def get_measurement_console_config(self):
        return self.console_config

    def set_measurement_console_config(self, config) -> None:
        self.console_config = config


class _ConsoleHostStub(QWidget):
    def __init__(self, wrappers: list[_DummyWrapper]):
        super().__init__()
        self._module_keys = [f"Instrument {index}" for index in range(len(wrappers))]
        self.wrappers = wrappers
        self.module_widgets = wrappers
        self.config_manager = _ConfigStub()
        self.returned: list[int] = []

    def move_module_to_console(self, module_index: int, console):
        return self.wrappers[module_index]

    def return_module_from_console(self, module_index: int, console) -> None:
        self.returned.append(module_index)
        self.wrappers[module_index].set_console_hosted(False)


def test_console_hosts_compact_widgets_in_two_columns(qtbot):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(4)])
    console = MeasurementConsoleWindow(host)

    for index in range(4):
        console.add_module(index, arrange=False)
    console.arrange_two_by_two()
    console.show()
    qtbot.wait(10)

    assert console.module_indices == (0, 1, 2, 3)
    assert all(wrapper.console_hosted and wrapper.compact for wrapper in host.wrappers)
    assert len({dock.objectName() for dock in console._docks.values()}) == 4
    assert console.dockWidgetArea(console._docks[0]) is Qt.DockWidgetArea.LeftDockWidgetArea
    assert console.dockWidgetArea(console._docks[1]) is Qt.DockWidgetArea.RightDockWidgetArea

    console.close()
    assert sorted(host.returned) == [0, 1, 2, 3]


def test_console_lock_disables_mutating_dock_features(qtbot):
    host = _ConsoleHostStub([_DummyWrapper()])
    console = MeasurementConsoleWindow(host)
    console.add_module(0)
    dock = console._docks[0]

    console.set_layout_locked(True)

    assert dock.features() == QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
    assert not console.add_button.isEnabled()
    assert not console.layout_button.isEnabled()

    console.set_layout_locked(False)
    assert dock.features() & QDockWidget.DockWidgetFeature.DockWidgetMovable
    assert not dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    console.close()


def test_dock_close_returns_instrument_to_host(qtbot):
    host = _ConsoleHostStub([_DummyWrapper()])
    console = MeasurementConsoleWindow(host)
    console.add_module(0)
    console.show()

    console._docks[0].close()
    qtbot.waitUntil(lambda: not console.module_indices)

    assert host.returned == [0]
    assert not host.wrappers[0].console_hosted
    console.close()


def test_console_merges_wrapper_header_and_dock_controls(qtbot):
    content = _PrimaryActionContent()
    wrapper = DetachableWidgetWrapper(
        content,
        "Instrument 0",
        capabilities=NO_CAPABILITIES,
    )
    host = _ConsoleHostStub([wrapper])
    console = MeasurementConsoleWindow(host)

    console.add_module(0)
    dock = console._docks[0]

    assert dock.titleBarWidget() is wrapper.header
    assert wrapper.layout.indexOf(wrapper.header) == -1
    assert dock._primary_button is not None
    assert dock._close_button is not None
    assert dock._primary_button.parent() is wrapper.header
    assert dock._close_button.parent() is wrapper.header
    assert wrapper.detach_btn.isHidden()
    assert wrapper.more_btn.isHidden()
    assert wrapper.header.layout().contentsMargins().top() == 1
    assert wrapper.screenshot_btn.height() == 22
    assert not dock.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable

    dock._primary_button.click()
    qtbot.waitUntil(lambda: content.toggle_btn.isChecked())
    qtbot.waitUntil(lambda: dock._primary_button.toolTip() == "Stop")

    console.set_layout_locked(True)
    assert dock._close_button.isHidden()
    assert not dock._primary_button.isHidden()

    console.set_layout_locked(False)
    dock._close_button.click()
    qtbot.waitUntil(lambda: not console.module_indices)

    assert wrapper.layout.indexOf(wrapper.header) == 0
    assert wrapper.header.parent() is wrapper
    assert not wrapper.more_btn.isHidden()
    assert wrapper.header.layout().contentsMargins().top() == 5
    assert wrapper.screenshot_btn.height() == 28
    assert host.returned == [0]
    console.close()


def test_console_workspace_round_trip_restores_modules_compact_mode_and_lock(qtbot):
    first_host = _ConsoleHostStub([_DummyWrapper() for _ in range(2)])
    first = MeasurementConsoleWindow(first_host)
    first.add_module(0, arrange=False)
    first.add_module(1, arrange=False)
    first_host.wrappers[1].toggle_compact(False)
    first.set_layout_locked(True)
    first.show()
    qtbot.waitUntil(lambda: all(dock.isVisible() for dock in first._docks.values()))
    first.close()

    second_host = _ConsoleHostStub([_DummyWrapper() for _ in range(2)])
    second_host.config_manager = first_host.config_manager
    second = MeasurementConsoleWindow(second_host)

    assert second.restore_workspace()
    second.show()
    qtbot.waitUntil(lambda: all(dock.isVisible() for dock in second._docks.values()))
    assert second.module_indices == (0, 1)
    assert second_host.wrappers[0].compact
    assert not second_host.wrappers[1].compact
    assert second.lock_action.isChecked()
    assert second._layout_locked
    second.close()


def test_console_recovers_hidden_docks_and_tiny_saved_geometry(qtbot):
    first_host = _ConsoleHostStub([_DummyWrapper() for _ in range(6)])
    first = MeasurementConsoleWindow(first_host)
    for index in range(6):
        first.add_module(index, arrange=False)
    first.arrange_two_by_two()
    first.show()
    qtbot.waitUntil(lambda: first.isVisible())

    for dock in first._docks.values():
        dock.hide()
    first.resize(254, 100)
    first_host.config_manager.console_config = {
        "version": 1,
        "module_keys": list(first_host._module_keys),
        "compact_module_keys": list(first_host._module_keys),
        "geometry": base64.b64encode(bytes(first.saveGeometry())).decode("ascii"),
        "dock_state": base64.b64encode(bytes(first.saveState(1))).decode("ascii"),
        "layout_locked": False,
    }
    damaged_config = first_host.config_manager.console_config
    first.close()
    first_host.config_manager.console_config = damaged_config

    second_host = _ConsoleHostStub([_DummyWrapper() for _ in range(6)])
    second_host.config_manager = first_host.config_manager
    second = MeasurementConsoleWindow(second_host)

    assert second.restore_workspace()
    assert second.module_indices == (0, 1, 2, 3, 4, 5)

    second.show()
    qtbot.waitUntil(lambda: all(dock.toggleViewAction().isChecked() for dock in second._docks.values()))
    available = QApplication.primaryScreen().availableGeometry()
    qtbot.waitUntil(
        lambda: (
            second.width() >= min(second.RECOVERY_MIN_WIDTH, available.width())
            and second.height() >= min(second.RECOVERY_MIN_HEIGHT, available.height())
        )
    )
    assert second.tabifiedDockWidgets(second._docks[0]) == [second._docks[4]]
    assert second.tabifiedDockWidgets(second._docks[1]) == [second._docks[5]]
    second.close()


def test_console_ignores_corrupt_saved_qt_state(qapp):
    host = _ConsoleHostStub([_DummyWrapper()])
    host.config_manager.console_config = {
        "version": 1,
        "module_keys": ["Instrument 0"],
        "compact_module_keys": [],
        "geometry": "not base64!",
        "dock_state": "also not base64!",
        "layout_locked": False,
    }
    console = MeasurementConsoleWindow(host)

    assert not console.restore_workspace()
    assert console.module_indices == (0,)
    console.close()


class _ActivationStub:
    def __init__(self):
        self.activated: list[int] = []

    def activate_module(self, module_index: int) -> None:
        self.activated.append(module_index)


def test_main_window_transfer_round_trip_preserves_wrapper(qtbot):
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    qtbot.addWidget(window)

    container = QWidget(window)
    QVBoxLayout(container)
    wrapper = _DummyWrapper()
    container.layout().addWidget(wrapper)
    window._module_keys = ["Instrument 0"]
    window._module_containers = [container]
    window.module_widgets = [wrapper]
    window._module_console_hosts = {}
    window._ensure_module_loaded = lambda _index: None
    console = _ActivationStub()

    moved = MainWindow.move_module_to_console(window, 0, console)

    assert moved is wrapper
    assert wrapper.parent() is None
    assert window._module_console_hosts[0] is console
    assert container.layout().count() == 1

    MainWindow.return_module_from_console(window, 0, console)

    assert wrapper.parent() is container
    assert container.layout().indexOf(wrapper) == 0
    assert not window._module_console_hosts

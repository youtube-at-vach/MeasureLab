from __future__ import annotations

import base64

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QPalette
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
from src.gui.module_registry import NO_INDEPENDENT_DISPLAY, WidgetCapabilities, console_action
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper


NO_CAPABILITIES = WidgetCapabilities(
    split_window=NO_INDEPENDENT_DISPLAY,
    compact_mode=NO_INDEPENDENT_DISPLAY,
    comparison=NO_INDEPENDENT_DISPLAY,
)
PRIMARY_ACTION_CAPABILITIES = WidgetCapabilities(
    split_window=NO_INDEPENDENT_DISPLAY,
    compact_mode=NO_INDEPENDENT_DISPLAY,
    comparison=NO_INDEPENDENT_DISPLAY,
    console_primary_action=console_action("toggle_btn"),
)


def _icon_contains_color(icon, color: QColor) -> bool:
    image = icon.pixmap(QSize(16, 16)).toImage()
    return any(image.pixelColor(x, y) == color for y in range(image.height()) for x in range(image.width()))


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
    if console._requires_compact_screen_layout(QApplication.primaryScreen().availableGeometry()):
        qtbot.waitUntil(lambda: bool(console.tabifiedDockWidgets(console._docks[0])))
        assert console.tabifiedDockWidgets(console._docks[0]) == [
            console._docks[1],
            console._docks[2],
            console._docks[3],
        ]
    else:
        assert console.dockWidgetArea(console._docks[1]) is Qt.DockWidgetArea.RightDockWidgetArea

    console.close()
    assert sorted(host.returned) == [0, 1, 2, 3]


def test_side_by_side_uses_two_tabbed_columns_for_four_instruments(qtbot):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(4)])
    console = MeasurementConsoleWindow(host)
    for index in range(4):
        console.add_module(index, arrange=False)

    console.arrange_side_by_side()
    console.show()
    qtbot.waitUntil(lambda: all(dock.isVisible() for dock in console._docks.values()))

    assert console.dockWidgetArea(console._docks[0]) is Qt.DockWidgetArea.LeftDockWidgetArea
    assert console.dockWidgetArea(console._docks[1]) is Qt.DockWidgetArea.RightDockWidgetArea
    assert console.tabifiedDockWidgets(console._docks[0]) == [console._docks[2]]
    assert console.tabifiedDockWidgets(console._docks[1]) == [console._docks[3]]
    console.close()


def test_single_pane_tabs_all_instruments_for_constrained_screens(qtbot):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(4)])
    console = MeasurementConsoleWindow(host)
    for index in range(4):
        console.add_module(index, arrange=False)

    console.arrange_single_pane()
    console.show()
    qtbot.waitUntil(lambda: all(dock.isVisible() for dock in console._docks.values()))

    assert console.tabifiedDockWidgets(console._docks[0]) == [
        console._docks[1],
        console._docks[2],
        console._docks[3],
    ]
    assert console.dockWidgetArea(console._docks[0]) is Qt.DockWidgetArea.LeftDockWidgetArea
    console.close()


def test_responsive_layout_uses_single_pane_below_grid_size(qtbot):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(4)])
    console = MeasurementConsoleWindow(host)
    for index in range(4):
        console.add_module(index, arrange=False)
    console.arrange_two_by_two()
    console.show()

    console._apply_responsive_layout(QSize(console.GRID_MIN_WIDTH - 1, console.GRID_MIN_HEIGHT))
    qtbot.waitUntil(lambda: bool(console.tabifiedDockWidgets(console._docks[0])))

    assert console._compact_screen_layout_active
    assert console.tabifiedDockWidgets(console._docks[0]) == [
        console._docks[1],
        console._docks[2],
        console._docks[3],
    ]
    console.close()


def test_responsive_layout_restores_previous_layout_after_returning_to_large_screen(qtbot):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(4)])
    console = MeasurementConsoleWindow(host)
    for index in range(4):
        console.add_module(index, arrange=False)
    console.arrange_two_by_two()
    console.show()

    console._apply_responsive_layout(QSize(800, 700))
    qtbot.waitUntil(lambda: console._compact_screen_layout_active)
    console._apply_responsive_layout(QSize(console.GRID_MIN_WIDTH, console.GRID_MIN_HEIGHT))
    qtbot.waitUntil(lambda: not console._compact_screen_layout_active)

    assert console.dockWidgetArea(console._docks[0]) is Qt.DockWidgetArea.LeftDockWidgetArea
    assert console.dockWidgetArea(console._docks[1]) is Qt.DockWidgetArea.RightDockWidgetArea
    console.close()


def test_console_clamps_an_oversized_window_to_the_available_screen(qtbot):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(4)])
    console = MeasurementConsoleWindow(host)
    for index in range(4):
        console.add_module(index, arrange=False)
    console.show()
    qtbot.waitUntil(console.isVisible)

    available = QApplication.primaryScreen().availableGeometry()
    console.resize(available.width() * 2, available.height() * 2)
    console._ensure_visible_on_screen()

    frame = console.frameGeometry()
    assert frame.width() <= available.width()
    assert frame.height() <= available.height()
    console.close()


def test_layout_menu_replaces_single_row_with_side_by_side(qapp):
    host = _ConsoleHostStub([_DummyWrapper()])
    console = MeasurementConsoleWindow(host)

    action_labels = [action.text() for action in console.layout_button.menu().actions()]

    assert "Side by Side" in action_labels
    assert "Single Row" not in action_labels
    console.close()


def test_adding_fifth_instrument_preserves_grid_and_tabs_from_left(qtbot, monkeypatch):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(5)])
    console = MeasurementConsoleWindow(host)
    for index in range(4):
        console.add_module(index, arrange=False)
    console.arrange_two_by_two()
    console.show()
    qtbot.waitUntil(lambda: all(dock.isVisible() for dock in console._docks.values()))

    unaffected_geometry = {index: console._docks[index].geometry() for index in (1, 2, 3)}
    preset_calls = 0

    def record_preset_call() -> None:
        nonlocal preset_calls
        preset_calls += 1

    monkeypatch.setattr(console, "arrange_two_by_two", record_preset_call)

    console.add_module(4)
    qtbot.waitUntil(lambda: console.tabifiedDockWidgets(console._docks[0]) == [console._docks[4]])
    qtbot.waitUntil(
        lambda: all(console._docks[index].geometry() == geometry for index, geometry in unaffected_geometry.items())
    )

    assert preset_calls == 0
    assert console.tabifiedDockWidgets(console._docks[0]) == [console._docks[4]]
    assert console._docks[4].isVisible()
    console.close()


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
        capabilities=PRIMARY_ACTION_CAPABILITIES,
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


def test_console_primary_action_tracks_source_enabled_state(qtbot):
    content = _PrimaryActionContent()
    content.toggle_btn.setEnabled(False)
    wrapper = DetachableWidgetWrapper(
        content,
        "Instrument 0",
        capabilities=PRIMARY_ACTION_CAPABILITIES,
    )
    host = _ConsoleHostStub([wrapper])
    console = MeasurementConsoleWindow(host)
    console.add_module(0)

    dock = console._docks[0]
    assert dock._primary_button is not None
    assert not dock._primary_button.isEnabled()

    content.toggle_btn.setEnabled(True)
    qtbot.waitUntil(dock._primary_button.isEnabled)

    content.toggle_btn.setEnabled(False)
    qtbot.waitUntil(lambda: not dock._primary_button.isEnabled())
    console.close()


def test_console_media_icons_follow_button_text_palette(qtbot):
    content = _PrimaryActionContent()
    wrapper = DetachableWidgetWrapper(
        content,
        "Instrument 0",
        capabilities=PRIMARY_ACTION_CAPABILITIES,
    )
    host = _ConsoleHostStub([wrapper])
    console = MeasurementConsoleWindow(host)
    console.add_module(0)
    console.show()
    qtbot.waitUntil(console.isVisible)
    dock = console._docks[0]
    assert dock._primary_button is not None

    app = QApplication.instance()
    original_palette = QPalette(app.palette())
    expected_color = QColor(245, 235, 225)
    test_palette = QPalette(original_palette)
    test_palette.setColor(QPalette.ColorRole.ButtonText, expected_color)

    try:
        app.setPalette(test_palette)
        QApplication.processEvents()
        qtbot.waitUntil(lambda: _icon_contains_color(dock._primary_button.icon(), expected_color))

        assert _icon_contains_color(console.stop_all_action.icon(), expected_color)

        content.toggle_btn.click()
        qtbot.waitUntil(lambda: dock._primary_button.property("headerIcon") == "stop")
        assert _icon_contains_color(dock._primary_button.icon(), expected_color)
    finally:
        app.setPalette(original_palette)

    console.close()


def test_console_stop_all_stops_every_running_primary_action(qtbot):
    contents = [_PrimaryActionContent() for _ in range(3)]
    wrappers = [
        DetachableWidgetWrapper(
            content,
            f"Instrument {index}",
            capabilities=PRIMARY_ACTION_CAPABILITIES,
        )
        for index, content in enumerate(contents)
    ]
    host = _ConsoleHostStub(wrappers)
    console = MeasurementConsoleWindow(host)
    for index in range(3):
        console.add_module(index, arrange=False)

    contents[0].toggle_btn.click()
    contents[2].toggle_btn.click()
    qtbot.waitUntil(console.stop_all_action.isEnabled)

    console.stop_all_action.trigger()
    qtbot.waitUntil(lambda: not console._stop_all_active)

    assert not contents[0].toggle_btn.isChecked()
    assert not contents[1].toggle_btn.isChecked()
    assert not contents[2].toggle_btn.isChecked()
    assert "2" in console.statusBar().currentMessage()
    assert not console.stop_all_action.isEnabled()
    console.close()


def test_console_stop_all_reports_running_actions_that_are_disabled(qtbot):
    content = _PrimaryActionContent()
    wrapper = DetachableWidgetWrapper(
        content,
        "Instrument 0",
        capabilities=PRIMARY_ACTION_CAPABILITIES,
    )
    host = _ConsoleHostStub([wrapper])
    console = MeasurementConsoleWindow(host)
    console.add_module(0)

    content.toggle_btn.click()
    content.toggle_btn.setEnabled(False)
    qtbot.waitUntil(console.stop_all_action.isEnabled)

    console.stop_all_action.trigger()
    qtbot.waitUntil(lambda: not console._stop_all_active)

    assert content.toggle_btn.isChecked()
    assert "1" in console.statusBar().currentMessage()
    assert console.stop_all_action.isEnabled()
    console.close()


def test_console_close_cancels_pending_stop_all_actions(qtbot):
    contents = [_PrimaryActionContent() for _ in range(2)]
    wrappers = [
        DetachableWidgetWrapper(
            content,
            f"Instrument {index}",
            capabilities=PRIMARY_ACTION_CAPABILITIES,
        )
        for index, content in enumerate(contents)
    ]
    host = _ConsoleHostStub(wrappers)
    console = MeasurementConsoleWindow(host)
    for index in range(2):
        console.add_module(index, arrange=False)
        contents[index].toggle_btn.click()

    console.stop_all_instruments()
    assert not contents[0].toggle_btn.isChecked()
    assert contents[1].toggle_btn.isChecked()

    console.close()
    qtbot.wait(10)

    assert contents[1].toggle_btn.isChecked()


def test_console_layout_lock_does_not_disable_stop_all(qtbot):
    content = _PrimaryActionContent()
    wrapper = DetachableWidgetWrapper(
        content,
        "Instrument 0",
        capabilities=PRIMARY_ACTION_CAPABILITIES,
    )
    host = _ConsoleHostStub([wrapper])
    console = MeasurementConsoleWindow(host)
    console.add_module(0)
    content.toggle_btn.click()
    console.set_layout_locked(True)

    qtbot.waitUntil(console.stop_all_action.isEnabled)
    console.stop_all_action.trigger()
    qtbot.waitUntil(lambda: not content.toggle_btn.isChecked())

    assert console._layout_locked
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


def test_console_close_preserves_last_usable_geometry_during_transient_shrink(qtbot):
    first_host = _ConsoleHostStub([_DummyWrapper() for _ in range(6)])
    first = MeasurementConsoleWindow(first_host)
    for index in range(6):
        first.add_module(index, arrange=False)
    first.arrange_two_by_two()
    first.resize(1200, 800)
    first.show()
    qtbot.waitUntil(lambda: first._last_usable_geometry is not None)

    # Reproduce the native close sequence: the top-level window is resized to
    # its tiny dock-layout minimum and closes before the queued resize snapshot.
    first.resize(254, 100)
    first.close()

    second_host = _ConsoleHostStub([_DummyWrapper() for _ in range(6)])
    second_host.config_manager = first_host.config_manager
    second = MeasurementConsoleWindow(second_host)

    assert second.restore_workspace()
    assert second.width() > 254
    assert second.height() > 100
    second.show()
    qtbot.waitUntil(second._has_usable_window_size)
    second.close()


def test_console_ignores_delayed_auto_fit_from_hosted_compact_widget(qtbot):
    host = _ConsoleHostStub([_DummyWrapper() for _ in range(4)])
    console = MeasurementConsoleWindow(host)
    for index in range(4):
        console.add_module(index, arrange=False)
    console.arrange_two_by_two()
    console.resize(1200, 800)
    console.show()
    qtbot.waitUntil(lambda: console.isVisible())
    qtbot.wait(100)
    expected_size = QSize(console.size())

    # Some compact widgets defer ``self.window().adjustSize()``. During
    # workspace restoration self.window() is the console, so that legacy
    # callback must not collapse the user-managed dock workspace.
    QTimer.singleShot(0, console.adjustSize)
    qtbot.wait(10)

    assert console.size() == expected_size
    console.close()


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
            second._has_usable_window_size()
            and second.frameGeometry().width() <= available.width()
            and second.frameGeometry().height() <= available.height()
        )
    )
    if second._requires_compact_screen_layout(available):
        assert second.tabifiedDockWidgets(second._docks[0]) == [
            second._docks[1],
            second._docks[2],
            second._docks[3],
            second._docks[4],
            second._docks[5],
        ]
    else:
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

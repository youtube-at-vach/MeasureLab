"""Experimental multi-instrument measurement console.

The console deliberately hosts the existing module wrappers instead of creating
second module instances.  This keeps the proof of concept compatible with the
current singleton-per-module MainWindow model and, more importantly, avoids
duplicating real-time audio callbacks behind the user's back.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from enum import Enum
from typing import TYPE_CHECKING

from PyQt6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QMoveEvent, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDockWidget,
    QMainWindow,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from src.core.localization import tr
from src.core.module_constants import (
    MODULE_GONIOMETER,
    MODULE_OSCILLOSCOPE,
    MODULE_SPECTROGRAM,
    MODULE_SPECTRUM_ANALYZER,
)
from src.gui.console_layouts import CONSOLE_LAYOUTS, LayoutSplit, layout_cells, make_layout_icon
from src.gui.widgets.detachable_wrapper import HeaderIcon, application_button_text_color, make_header_icon

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow


logger = logging.getLogger(__name__)


DEFAULT_CONSOLE_MODULES = (
    MODULE_OSCILLOSCOPE,
    MODULE_SPECTRUM_ANALYZER,
    MODULE_SPECTROGRAM,
    MODULE_GONIOMETER,
)


def _safe_object_name(module_key: str) -> str:
    """Return a stable ASCII object name required by QMainWindow.saveState()."""
    slug = re.sub(r"[^a-z0-9]+", "_", module_key.lower()).strip("_")
    return f"measurement_console_dock_{slug}"


class InstrumentDockWidget(QDockWidget):
    """A dock whose close button returns the instrument to its normal page."""

    remove_requested = pyqtSignal(int)
    primary_action_state_changed = pyqtSignal()

    def __init__(
        self,
        title: str,
        module_index: int,
        stable_module_key: str,
        parent: QWidget | None = None,
    ):
        super().__init__(title, parent)
        self.module_index = module_index
        self._allow_close = False
        self._instrument_title_bar: QWidget | None = None
        self._primary_action: QAbstractButton | None = None
        self._primary_button: QToolButton | None = None
        self._close_button: QToolButton | None = None
        self._scroll_area = QScrollArea(self)
        self._scroll_area.setObjectName(f"{_safe_object_name(stable_module_key)}_viewport")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setMinimumSize(0, 0)
        self._scroll_area.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setWidget(self._scroll_area)
        self.setObjectName(_safe_object_name(stable_module_key))
        self.setMinimumSize(0, 0)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.featuresChanged.connect(self._sync_title_bar_controls)

    def set_instrument_widget(self, widget: QWidget) -> None:
        """Host an instrument without propagating its minimum size to the console."""
        self._scroll_area.setWidget(widget)
        self._install_integrated_title_bar(widget)

    def take_instrument_widget(self) -> QWidget | None:
        """Release the instrument so MainWindow can return it to its normal page."""
        widget = self._scroll_area.takeWidget()
        if widget is not None:
            self._restore_instrument_title_bar(widget)
        return widget

    def _create_title_bar_button(self, tooltip: str) -> QToolButton:
        button = QToolButton(self._instrument_title_bar)
        button.setText(tooltip)
        button.setAccessibleName(tooltip)
        button.setToolTip(tooltip)
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(QSize(26, 22))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setStyleSheet(
            "QToolButton { border: 1px solid transparent; border-radius: 5px; padding: 2px; }"
            "QToolButton:hover { border-color: palette(mid); background: palette(midlight); }"
            "QToolButton:pressed { background: palette(mid); }"
        )
        return button

    def _install_integrated_title_bar(self, widget: QWidget) -> None:
        take_title_bar = getattr(widget, "take_hosted_title_bar", None)
        restore_title_bar = getattr(widget, "restore_hosted_title_bar", None)
        if not callable(take_title_bar) or not callable(restore_title_bar):
            return

        title_bar = take_title_bar()
        title_bar_layout = title_bar.layout()
        if title_bar_layout is None:
            restore_title_bar(title_bar)
            return

        self._instrument_title_bar = title_bar
        self.setTitleBarWidget(title_bar)

        primary_action_getter = getattr(widget, "console_primary_action", None)
        if callable(primary_action_getter):
            primary_action = primary_action_getter()
            if isinstance(primary_action, QAbstractButton):
                self._primary_action = primary_action
                self._primary_button = self._create_title_bar_button(primary_action.text())
                self._primary_button.clicked.connect(self._trigger_primary_action)
                self._primary_action.toggled.connect(self._schedule_primary_action_sync)
                self._primary_action.installEventFilter(self)
                title_bar_layout.addWidget(self._primary_button)

        self._close_button = self._create_title_bar_button(tr("Close"))
        self._close_button.clicked.connect(self.close)
        title_bar_layout.addWidget(self._close_button)
        self._sync_title_bar_controls()

    def _restore_instrument_title_bar(self, widget: QWidget) -> None:
        title_bar = self._instrument_title_bar
        if title_bar is None:
            return

        title_bar_layout = title_bar.layout()
        if self._primary_action is not None:
            try:
                self._primary_action.toggled.disconnect(self._schedule_primary_action_sync)
            except (RuntimeError, TypeError):
                pass
            self._primary_action.removeEventFilter(self)

        for button in (self._primary_button, self._close_button):
            if button is None:
                continue
            if title_bar_layout is not None:
                title_bar_layout.removeWidget(button)
            button.deleteLater()

        self.setTitleBarWidget(None)
        title_bar.setParent(None)
        restore_title_bar = getattr(widget, "restore_hosted_title_bar", None)
        if callable(restore_title_bar):
            restore_title_bar(title_bar)

        self._instrument_title_bar = None
        self._primary_action = None
        self._primary_button = None
        self._close_button = None

    def _trigger_primary_action(self) -> None:
        if self._primary_action is None or not self._primary_action.isEnabled():
            return
        self._primary_action.click()
        self._schedule_primary_action_sync()

    def primary_action_is_running(self) -> bool:
        """Return whether this instrument exposes a checked primary action."""
        return self._primary_action is not None and self._primary_action.isChecked()

    def stop_primary_action(self) -> PrimaryActionStopResult:
        """Request a normal button-driven stop without bypassing widget cleanup."""
        action = self._primary_action
        if action is None:
            return PrimaryActionStopResult.UNAVAILABLE
        if not action.isChecked():
            return PrimaryActionStopResult.ALREADY_STOPPED
        if not action.isEnabled():
            return PrimaryActionStopResult.BLOCKED

        try:
            action.click()
        except RuntimeError:
            logger.exception("Failed to stop console primary action")
            return PrimaryActionStopResult.FAILED

        self._schedule_primary_action_sync()
        return PrimaryActionStopResult.STOPPED if not action.isChecked() else PrimaryActionStopResult.FAILED

    def _schedule_primary_action_sync(self, *_args) -> None:
        QTimer.singleShot(0, self._sync_primary_action)

    def eventFilter(self, watched, event) -> bool:
        """Keep the title-bar proxy usable when the source action is enabled later."""
        if watched is self._primary_action and event.type() == QEvent.Type.EnabledChange:
            self._schedule_primary_action_sync()
        return super().eventFilter(watched, event)

    def _sync_primary_action(self) -> None:
        if self._primary_action is None or self._primary_button is None:
            self.primary_action_state_changed.emit()
            return
        running = self._primary_action.isChecked()
        label = self._primary_action.text() or (tr("Stop") if running else tr("Start"))
        icon = HeaderIcon.STOP if running else HeaderIcon.PLAY
        self._primary_button.setText(label)
        self._primary_button.setAccessibleName(label)
        self._primary_button.setToolTip(label)
        self._primary_button.setEnabled(self._primary_action.isEnabled())
        self._primary_button.setProperty("headerIcon", icon.value)
        self._primary_button.setIcon(make_header_icon(icon, application_button_text_color()))
        self.primary_action_state_changed.emit()

    def changeEvent(self, event) -> None:
        """Recolor console controls whenever the application palette changes."""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self._sync_title_bar_controls()

    def _sync_title_bar_controls(self, *_args) -> None:
        if self._close_button is None:
            return

        features = self.features()
        can_close = bool(features & QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self._close_button.setVisible(can_close)
        self._close_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton))
        self._sync_primary_action()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return

        # Avoid mutating QMainWindow's dock layout while Qt is dispatching the
        # native close-button event.
        event.ignore()
        QTimer.singleShot(0, lambda: self.remove_requested.emit(self.module_index))


class PrimaryActionStopResult(Enum):
    """Outcome of requesting a stop through one instrument's primary action."""

    STOPPED = "stopped"
    ALREADY_STOPPED = "already_stopped"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    FAILED = "failed"


class MeasurementConsoleWindow(QMainWindow):
    """A dockable, multi-monitor host for completed measurement widgets."""

    closed = pyqtSignal()

    DEFAULT_WIDTH = 1400
    DEFAULT_HEIGHT = 900
    RECOVERY_MIN_WIDTH = 900
    RECOVERY_MIN_HEIGHT = 650
    GRID_MIN_WIDTH = 1400
    GRID_MIN_HEIGHT = 740

    _UNLOCKED_FEATURES = (
        QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable
    )

    def __init__(self, main_window: "MainWindow"):
        super().__init__(main_window)
        self.main_window = main_window
        self._docks: dict[int, InstrumentDockWidget] = {}
        self._closing = False
        self._layout_locked = False
        self._last_visible_dock_state: bytes | None = None
        self._last_usable_geometry: bytes | None = None
        self._validate_docks_after_show = False
        self._compact_screen_layout_active = False
        self._pre_compact_screen_dock_state: bytes | None = None
        self._screen_change_connected = False
        self._preset_layout_generation = 0
        self._layout_preset = "grid_2x2"
        self._main_module_index: int | None = None
        self._undo_layout: tuple[bytes, str, int | None, bytes | None] | None = None
        self._stop_all_generation = 0
        self._stop_all_queue: list[int] = []
        self._stop_all_active = False
        self._stop_all_stopped_count = 0
        self._stop_all_failed_count = 0

        self.setWindowTitle(tr("Measurement Console"))
        self.setObjectName("measurement_console_window")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self.setDockNestingEnabled(True)
        self.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)

        # QMainWindow requires a central widget, but the console wants docks to
        # consume effectively all available space.  A one-pixel ignored widget
        # keeps the left/right dock areas distinct without taking useful room.
        center = QWidget(self)
        center.setObjectName("measurement_console_center")
        center.setFixedSize(1, 1)
        center.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setCentralWidget(center)

        self._init_toolbar()
        self.statusBar().showMessage(tr("No instruments in the console."))

    @property
    def module_indices(self) -> tuple[int, ...]:
        return tuple(self._docks)

    def _init_toolbar(self) -> None:
        toolbar = QToolBar(tr("Measurement Console"), self)
        toolbar.setObjectName("measurement_console_toolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        self.add_button = QToolButton(toolbar)
        self.add_button.setText(tr("Add Instrument"))
        self.add_button.setToolTip(tr("Add Instrument"))
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_menu = QMenu(self.add_button)
        self.add_button.setMenu(self.add_menu)
        toolbar.addWidget(self.add_button)

        self.layout_button = QToolButton(toolbar)
        self.layout_button.setText(tr("Layout"))
        self.layout_button.setToolTip(tr("Extra instruments share panes as tabs."))
        self.layout_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout_menu = QMenu(self.layout_button)

        self._preset_labels = {
            "tabs": tr("Tabbed View"),
            "columns": tr("Side by Side"),
            "grid_2x2": tr("2 x 2 Grid"),
            "grid_2x3": tr("2 Columns x 3 Rows"),
            "grid_3x2": tr("3 Columns x 2 Rows"),
            "main_right": tr("Main + 3 Right"),
            "main_bottom": tr("Main + 3 Below"),
        }
        self._preset_actions: dict[str, QAction] = {}
        self._preset_group = QActionGroup(self)
        self._preset_group.setExclusive(True)
        self.layout_button.setMenu(layout_menu)
        toolbar.addWidget(self.layout_button)
        for key, label in self._preset_labels.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setToolTip(label)
            action.triggered.connect(lambda _checked=False, preset=key: self.apply_layout_preset(preset))
            self._preset_group.addAction(action)
            self._preset_actions[key] = action
            layout_menu.addAction(action)
            button = QToolButton(toolbar)
            button.setDefaultAction(action)
            button.setAccessibleName(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setIconSize(QSize(40, 28))
            button.setAutoRaise(True)
            button.setStyleSheet(
                "QToolButton { border: 1px solid transparent; border-radius: 5px; padding: 3px; }"
                "QToolButton:hover { background: palette(midlight); border-color: palette(mid); }"
                "QToolButton:checked { background: palette(midlight); border-color: palette(highlight); }"
            )
            toolbar.addWidget(button)

        layout_menu.addSeparator()
        self.main_instrument_menu = layout_menu.addMenu(tr("Main Instrument"))
        self.main_instrument_menu.aboutToShow.connect(self._rebuild_main_instrument_menu)
        self.reapply_layout_action = QAction(tr("Reapply Layout"), self)
        self.reapply_layout_action.triggered.connect(lambda: self.apply_layout_preset(self._layout_preset))
        layout_menu.addAction(self.reapply_layout_action)
        self.undo_layout_action = QAction(tr("Undo Layout"), self)
        self.undo_layout_action.setShortcut("Alt+Backspace")
        self.undo_layout_action.triggered.connect(self.undo_layout)
        layout_menu.addAction(self.undo_layout_action)
        toolbar.addAction(self.undo_layout_action)
        layout_menu.addSeparator()
        default_action = QAction(tr("Default Console"), layout_menu)
        default_action.triggered.connect(self.load_default_console)
        layout_menu.addAction(default_action)
        toolbar.addSeparator()
        self._refresh_layout_controls()
        self._refresh_layout_icons()

        self.stop_all_action = QAction(tr("Stop All"), toolbar)
        self.stop_all_action.setToolTip(tr("Stop all running instruments in the console."))
        self._refresh_stop_all_icon()
        self.stop_all_action.setEnabled(False)
        self.stop_all_action.triggered.connect(self.stop_all_instruments)
        toolbar.addAction(self.stop_all_action)

        self.lock_action = QAction(tr("Lock Layout"), toolbar)
        self.lock_action.setCheckable(True)
        self.lock_action.toggled.connect(self.set_layout_locked)
        toolbar.addAction(self.lock_action)

        self._rebuild_add_menu()

    def _refresh_layout_icons(self) -> None:
        for key, action in self._preset_actions.items():
            action.setIcon(make_layout_icon(key, application_button_text_color()))

    def _refresh_layout_controls(self) -> None:
        enabled = bool(self._docks) and not self._layout_locked
        for key, action in self._preset_actions.items():
            action.setEnabled(enabled)
            action.setChecked(key == self._layout_preset)
        self.reapply_layout_action.setEnabled(enabled)
        self.undo_layout_action.setEnabled(enabled and self._undo_layout is not None)
        self.main_instrument_menu.setEnabled(enabled and self._layout_preset.startswith("main_"))

    def _rebuild_main_instrument_menu(self) -> None:
        self.main_instrument_menu.clear()
        main_index = (
            self._main_module_index if self._main_module_index in self._docks else next(iter(self._docks), None)
        )
        for index, dock in self._docks.items():
            action = self.main_instrument_menu.addAction(dock.windowTitle())
            action.setCheckable(True)
            action.setChecked(index == main_index)
            action.triggered.connect(lambda _checked=False, i=index: self.set_main_instrument(i))

    def set_main_instrument(self, module_index: int) -> None:
        if self._layout_locked or module_index not in self._docks:
            return
        self._remember_layout_for_undo()
        self._main_module_index = module_index
        self.apply_layout_preset(self._layout_preset, remember=False)

    def _refresh_stop_all_icon(self) -> None:
        self.stop_all_action.setIcon(make_header_icon(HeaderIcon.STOP, application_button_text_color()))

    def changeEvent(self, event) -> None:
        """Keep toolbar icons legible after a live light/dark theme switch."""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and hasattr(
            self, "stop_all_action"
        ):
            self._refresh_stop_all_icon()
            self._refresh_layout_icons()

    def _rebuild_add_menu(self) -> None:
        self.add_menu.clear()
        for module_index, module_key in enumerate(self.main_window._module_keys):
            action = QAction(tr(module_key), self.add_menu)
            action.setCheckable(True)
            action.setChecked(module_index in self._docks)
            action.setEnabled(module_index not in self._docks and not self._layout_locked)
            action.triggered.connect(lambda _checked=False, i=module_index: self.add_module(i))
            self.add_menu.addAction(action)

    def load_default_console(self) -> None:
        if self._layout_locked or self._closing:
            return

        default_indices = []
        for module_key in DEFAULT_CONSOLE_MODULES:
            try:
                module_index = self.main_window._module_keys.index(module_key)
            except ValueError:
                logger.warning("Default console module is unavailable: %s", module_key)
                continue
            default_indices.append(module_index)

        # "Default Console" is also the user's explicit recovery action, so it
        # resets the membership instead of merely adding four more instruments.
        for module_index in list(self._docks):
            if module_index not in default_indices:
                self.remove_module(module_index)

        for module_index in default_indices:
            self.add_module(module_index, arrange=False)
        self._docks = {index: self._docks[index] for index in default_indices if index in self._docks}

        self._compact_screen_layout_active = False
        self._pre_compact_screen_dock_state = None
        self._main_module_index = None
        self._undo_layout = None
        self._preset_layout_generation += 1
        generation = self._preset_layout_generation
        QTimer.singleShot(0, lambda: self._arrange_default_console_for_current_screen(generation))

    def _arrange_default_console_for_current_screen(self, generation: int) -> None:
        """Apply the regular preset, then constrain it to the actual screen."""
        if self._closing or generation != self._preset_layout_generation:
            return
        self.apply_layout_preset("grid_2x2", remember=False)
        self._ensure_visible_on_screen()

    def restore_workspace(self) -> bool:
        """Restore the last console layout, falling back to the four-instrument preset."""
        config = self.main_window.config_manager.get_measurement_console_config()
        if config.get("version") != 1:
            self.load_default_console()
            return False

        for module_key in config.get("module_keys", []):
            try:
                module_index = self.main_window._module_keys.index(module_key)
            except ValueError:
                logger.warning("Saved console module is unavailable: %s", module_key)
                continue
            self.add_module(module_index, arrange=False)

        preset = config.get("layout_preset", "grid_2x2")
        self._layout_preset = preset if preset in CONSOLE_LAYOUTS else "grid_2x2"
        main_key = config.get("main_module_key", "")
        self._main_module_index = next(
            (index for index in self._docks if self.main_window._module_keys[index] == main_key), None
        )
        self._refresh_layout_controls()
        compact_keys = set(config.get("compact_module_keys", []))
        for module_index in self._docks:
            wrapper = self.main_window.module_widgets[module_index]
            module_key = self.main_window._module_keys[module_index]
            if wrapper is not None and wrapper.is_compactable:
                wrapper.toggle_compact(module_key in compact_keys)

        geometry_ok = self._restore_blob(config.get("geometry", ""), self.restoreGeometry)
        state_ok = self._restore_blob(
            config.get("dock_state", ""),
            lambda state: self.restoreState(state, 1),
        )
        # Floating instruments deliberately are not part of the streamlined
        # console mode. Normalize older saved layouts that still contain them.
        for dock in self._docks.values():
            if dock.isFloating():
                dock.setFloating(False)

        if self._docks and not state_ok:
            # Apply the recovery preset before restoring the lock flag.  A
            # queued preset would otherwise be rejected when the saved layout
            # itself was locked.
            self.apply_layout_preset(self._layout_preset, remember=False)
        elif self._docks:
            # A dock restored as visible and one restored as hidden are both
            # unchecked while their top-level parent has never been shown.
            # Validate only after Qt has applied child visibility in showEvent.
            self._validate_docks_after_show = True

        self.lock_action.setChecked(bool(config.get("layout_locked", False)))
        return geometry_ok and state_ok

    @staticmethod
    def _restore_blob(encoded: str, restore) -> bool:
        if not encoded:
            return False
        try:
            raw = base64.b64decode(encoded.encode("ascii"), validate=True)
            return bool(restore(QByteArray(raw)))
        except (binascii.Error, ValueError, UnicodeError):
            return False

    def save_workspace(self) -> None:
        compact_keys = []
        for module_index in self._docks:
            wrapper = self.main_window.module_widgets[module_index]
            if wrapper is not None and wrapper.is_compactable and wrapper.content_widget.is_compact_mode():
                compact_keys.append(self.main_window._module_keys[module_index])

        dock_state = bytes(self.saveState(1))
        if self._docks and not all(dock.toggleViewAction().isChecked() for dock in self._docks.values()):
            # Qt clears child visibility while closing a top-level window,
            # before closeEvent is dispatched.  Preserve the most recent state
            # in which every console member was visible instead of serializing
            # that transient shutdown state.
            dock_state = self._last_visible_dock_state or dock_state
        else:
            self._last_visible_dock_state = dock_state

        geometry = bytes(self.saveGeometry())
        if self._docks and not self._has_usable_window_size():
            # On macOS, closing a dock-heavy QMainWindow can briefly collapse
            # its native window to the layout's minimum size before closeEvent
            # runs.  Persist the last stable on-screen geometry instead of that
            # transient shutdown size.
            geometry = self._last_usable_geometry or geometry
        else:
            self._last_usable_geometry = geometry

        config = {
            "version": 1,
            "module_keys": [self.main_window._module_keys[index] for index in self._docks],
            "compact_module_keys": compact_keys,
            "geometry": base64.b64encode(geometry).decode("ascii"),
            "dock_state": base64.b64encode(self._pre_compact_screen_dock_state or dock_state).decode("ascii"),
            "layout_preset": self._layout_preset,
            "main_module_key": (
                self.main_window._module_keys[self._main_module_index] if self._main_module_index in self._docks else ""
            ),
            "layout_locked": self._layout_locked,
        }
        self.main_window.config_manager.set_measurement_console_config(config)

    def _has_usable_window_size(self) -> bool:
        """Return whether the current size is safe to persist for this workspace."""
        if len(self._docks) < 2:
            return self.width() > 0 and self.height() > 0

        screens = QApplication.screens()
        if not screens:
            return self.width() >= self.RECOVERY_MIN_WIDTH and self.height() >= self.RECOVERY_MIN_HEIGHT

        frame = self.frameGeometry()
        matching_screen = next(
            (screen for screen in screens if screen.availableGeometry().intersects(frame)),
            QApplication.primaryScreen() or screens[0],
        )
        available = matching_screen.availableGeometry()
        frame_width = max(0, frame.width() - self.width())
        frame_height = max(0, frame.height() - self.height())
        minimum_width = min(self.RECOVERY_MIN_WIDTH, max(1, available.width() - frame_width))
        minimum_height = min(self.RECOVERY_MIN_HEIGHT, max(1, available.height() - frame_height))
        return self.width() >= minimum_width and self.height() >= minimum_height

    def _schedule_geometry_snapshot(self) -> None:
        """Cache geometry after native move/resize processing has settled."""
        if not self._closing:
            QTimer.singleShot(0, self._cache_usable_geometry)

    def adjustSize(self) -> None:
        """Keep hosted widgets from auto-fitting the whole dock workspace."""
        if self._docks:
            return
        super().adjustSize()

    def _cache_usable_geometry(self) -> None:
        """Remember a stable geometry that cannot collapse the restored console."""
        from PyQt6 import sip

        if sip.isdeleted(self) or self._closing or not self.isVisible():
            return
        if self._has_usable_window_size():
            self._last_usable_geometry = bytes(self.saveGeometry())

    def _ensure_visible_on_screen(self) -> None:
        screens = QApplication.screens()
        if not screens:
            return

        frame = self.frameGeometry()
        matching_screen = next(
            (screen for screen in screens if screen.availableGeometry().intersects(frame)),
            QApplication.primaryScreen() or screens[0],
        )
        available = matching_screen.availableGeometry()
        was_off_screen = not available.intersects(frame)
        was_too_small = len(self._docks) >= 2 and (
            self.width() < self.RECOVERY_MIN_WIDTH or self.height() < self.RECOVERY_MIN_HEIGHT
        )
        frame_width = max(0, frame.width() - self.width())
        frame_height = max(0, frame.height() - self.height())
        max_content_width = max(1, available.width() - frame_width)
        max_content_height = max(1, available.height() - frame_height)
        is_too_large = self.width() > max_content_width or self.height() > max_content_height
        if was_off_screen or was_too_small or is_too_large:
            min_width = min(self.RECOVERY_MIN_WIDTH, max_content_width)
            min_height = min(self.RECOVERY_MIN_HEIGHT, max_content_height)
            target_width = min(max(self.width(), min_width), max_content_width)
            target_height = min(max(self.height(), min_height), max_content_height)
            self.resize(target_width, target_height)
            recovered = self.frameGeometry()
            recovered.moveCenter(available.center())
            self.move(recovered.topLeft())

        self._apply_responsive_layout(available)

        for dock in self._docks.values():
            if dock.isFloating() and not any(
                screen.availableGeometry().intersects(dock.frameGeometry()) for screen in screens
            ):
                dock.setFloating(False)

    def _schedule_geometry_recovery(self) -> None:
        """Run after both Qt and the native window system commit restored geometry."""
        QTimer.singleShot(0, self._ensure_visible_on_screen)

    def _requires_compact_screen_layout(self, available) -> bool:
        """Return whether the available work area cannot safely show a 2 x 2 grid."""
        return available.width() < self.GRID_MIN_WIDTH or available.height() < self.GRID_MIN_HEIGHT

    def _apply_responsive_layout(self, available) -> None:
        """Use one tabbed pane when the current screen is too small for four panes.

        The console deliberately applies this safety layout even when layout lock
        is enabled. Locking prevents user-initiated rearrangement; it must not
        leave a restored instrument beyond the physical screen.
        """
        if not self._docks:
            return

        compact_screen = self._requires_compact_screen_layout(available)
        if compact_screen:
            if self._compact_screen_layout_active:
                return
            self._pre_compact_screen_dock_state = bytes(self.saveState(1))
            self._arrange_preset("tabs")
            self._compact_screen_layout_active = True
            return

        if not self._compact_screen_layout_active:
            return

        state = self._pre_compact_screen_dock_state
        self._compact_screen_layout_active = False
        self._pre_compact_screen_dock_state = None
        self._preset_layout_generation += 1
        if state and self.restoreState(QByteArray(state), 1):
            for dock in self._docks.values():
                dock.show()
            self._schedule_visible_state_snapshot()
        else:
            self._arrange_preset(self._layout_preset)

    def add_module(self, module_index: int, *, arrange: bool = True) -> None:
        if module_index in self._docks:
            self.activate_module(module_index)
            return
        if self._layout_locked:
            return

        wrapper = self.main_window.move_module_to_console(module_index, self)
        if wrapper is None:
            return

        module_key = self.main_window._module_keys[module_index]

        # Compact before inserting into QMainWindow.  Otherwise Qt observes the
        # full instrument's minimum size during the first dock-layout pass and
        # may permanently grow the top-level window before compact mode applies.
        wrapper.set_console_hosted(True)
        if wrapper.is_compactable:
            wrapper.toggle_compact(True)

        existing_docks = list(self._docks.values())
        dock = InstrumentDockWidget(tr(module_key), module_index, module_key, self)
        dock.remove_requested.connect(self.remove_module)
        dock.primary_action_state_changed.connect(self._refresh_stop_all_action)
        dock.dockLocationChanged.connect(lambda _area: self._schedule_visible_state_snapshot())
        dock.topLevelChanged.connect(lambda _floating: self._schedule_visible_state_snapshot())
        dock.visibilityChanged.connect(lambda _visible: self._schedule_visible_state_snapshot())
        dock.set_instrument_widget(wrapper)
        self._docks[module_index] = dock
        self._invalidate_membership_snapshots()
        if arrange and self._compact_screen_layout_active and existing_docks:
            anchor = existing_docks[0]
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
            self.tabifyDockWidget(anchor, dock)
        elif arrange and self._layout_preset != "grid_2x2":
            self._arrange_preset(self._layout_preset)
        elif arrange:
            self._insert_dock_preserving_layout(dock, existing_docks)
        else:
            initial_area = (
                Qt.DockWidgetArea.LeftDockWidgetArea if len(self._docks) % 2 else Qt.DockWidgetArea.RightDockWidgetArea
            )
            self.addDockWidget(initial_area, dock)
        dock.show()
        self._refresh_compact_membership_layout()
        if arrange and len(existing_docks) >= 4:
            # tabifyDockWidget() runs before the dock is shown so Qt never lays
            # it out as a temporary fifth split.  Raise it only after show().
            dock.raise_()

        self._rebuild_add_menu()
        self._refresh_layout_controls()
        self.statusBar().showMessage(tr("{0} instruments in the console.").format(len(self._docks)))
        self._refresh_stop_all_action()

    def stop_all_instruments(self) -> None:
        """Stop every running primary action currently hosted by the console."""
        if self._closing or self._stop_all_active:
            return

        targets = [module_index for module_index, dock in self._docks.items() if dock.primary_action_is_running()]
        if not targets:
            self._refresh_stop_all_action()
            return

        self._stop_all_generation += 1
        generation = self._stop_all_generation
        self._stop_all_queue = targets
        self._stop_all_active = True
        self._stop_all_stopped_count = 0
        self._stop_all_failed_count = 0
        self.stop_all_action.setEnabled(False)
        self._process_next_stop(generation)

    def _process_next_stop(self, generation: int) -> None:
        """Process one stop per event-loop turn to keep the console responsive."""
        if generation != self._stop_all_generation or self._closing:
            return

        while self._stop_all_queue:
            module_index = self._stop_all_queue.pop(0)
            dock = self._docks.get(module_index)
            if dock is None:
                continue

            result = dock.stop_primary_action()
            if result is PrimaryActionStopResult.STOPPED:
                self._stop_all_stopped_count += 1
            elif result in (PrimaryActionStopResult.BLOCKED, PrimaryActionStopResult.FAILED):
                self._stop_all_failed_count += 1

            QTimer.singleShot(0, lambda g=generation: self._process_next_stop(g))
            return

        self._finish_stop_all(generation)

    def _finish_stop_all(self, generation: int) -> None:
        if generation != self._stop_all_generation or self._closing:
            return

        self._stop_all_active = False
        if self._stop_all_failed_count:
            message = tr("Stopped {0} instruments; {1} could not be stopped.").format(
                self._stop_all_stopped_count,
                self._stop_all_failed_count,
            )
        else:
            message = tr("Stopped {0} instruments.").format(self._stop_all_stopped_count)
        self.statusBar().showMessage(message)
        self._refresh_stop_all_action()

    def _refresh_stop_all_action(self) -> None:
        if not hasattr(self, "stop_all_action"):
            return
        has_running_action = any(dock.primary_action_is_running() for dock in self._docks.values())
        self.stop_all_action.setEnabled(has_running_action and not self._stop_all_active and not self._closing)

    def _cancel_stop_all(self) -> None:
        self._stop_all_generation += 1
        self._stop_all_queue.clear()
        self._stop_all_active = False

    def _insert_dock_preserving_layout(
        self,
        dock: InstrumentDockWidget,
        existing_docks: list[InstrumentDockWidget],
    ) -> None:
        """Place one instrument without rebuilding the existing dock tree.

        Reapplying the full 2 x 2 preset made Qt recalculate every splitter from
        the new instrument's size hint.  A wide instrument could consequently
        collapse the other row or column.  Build the first four cells
        incrementally, then add further instruments as tabs from the top-left
        cell onward so the established splitter sizes remain intact.
        """
        if not existing_docks:
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
            return

        if len(existing_docks) == 1:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            return

        if len(existing_docks) < 4:
            anchor = existing_docks[len(existing_docks) - 2]
            area = self.dockWidgetArea(anchor)
            if area is Qt.DockWidgetArea.NoDockWidgetArea:
                area = Qt.DockWidgetArea.LeftDockWidgetArea
            self.addDockWidget(area, dock)
            self.splitDockWidget(anchor, dock, Qt.Orientation.Vertical)
            return

        # Additional instruments share the four established cells in visual
        # row-major order: top-left, top-right, bottom-left, bottom-right.
        anchor = existing_docks[(len(existing_docks) - 4) % 4]
        area = self.dockWidgetArea(anchor)
        if area is Qt.DockWidgetArea.NoDockWidgetArea:
            area = Qt.DockWidgetArea.LeftDockWidgetArea
        self.addDockWidget(area, dock)
        self.tabifyDockWidget(anchor, dock)
        self._schedule_visible_state_snapshot()

    def remove_module(self, module_index: int) -> None:
        if self._layout_locked and not self._closing:
            return
        dock = self._docks.pop(module_index, None)
        if dock is None:
            return

        self._invalidate_membership_snapshots()
        if self._main_module_index == module_index:
            self._main_module_index = None
        wrapper = dock.take_instrument_widget()
        if wrapper is not None:
            wrapper.setParent(None)
        self.removeDockWidget(dock)
        dock._allow_close = True
        dock.deleteLater()

        self.main_window.return_module_from_console(module_index, self)
        self._refresh_compact_membership_layout()
        self._rebuild_add_menu()
        self._refresh_layout_controls()
        if self._docks:
            self.statusBar().showMessage(tr("{0} instruments in the console.").format(len(self._docks)))
        else:
            self.statusBar().showMessage(tr("No instruments in the console."))
        self._refresh_stop_all_action()

    def activate_module(self, module_index: int) -> bool:
        dock = self._docks.get(module_index)
        if dock is None:
            return False
        self.show()
        self.raise_()
        self.activateWindow()
        dock.show()
        dock.raise_()
        if dock.isFloating():
            dock.activateWindow()
        return True

    def _prepare_for_preset(self) -> list[InstrumentDockWidget]:
        self._preset_layout_generation += 1
        docks = list(self._docks.values())
        for dock in docks:
            if dock.isFloating():
                dock.setFloating(False)
            self.removeDockWidget(dock)
        return docks

    def _invalidate_membership_snapshots(self) -> None:
        # Never restore a snapshot containing removed docks or missing new ones.
        self._preset_layout_generation += 1
        self._undo_layout = None
        self._last_visible_dock_state = None
        self._pre_compact_screen_dock_state = None

    def _refresh_compact_membership_layout(self) -> None:
        """Keep the large-screen layout in sync when tabbed membership changes."""
        if not self._compact_screen_layout_active or self._closing or not self._docks:
            return
        # Build and capture synchronously, before Qt paints, then return to tabs.
        # This prevents a stale snapshot from losing added/removed instruments
        # on the next screen change or application launch.
        self._arrange_preset(self._layout_preset)
        self._pre_compact_screen_dock_state = bytes(self.saveState(1))
        self._arrange_preset("tabs")

    def _remember_layout_for_undo(self) -> None:
        self._undo_layout = (
            bytes(self.saveState(1)),
            self._layout_preset,
            self._main_module_index,
            self._pre_compact_screen_dock_state,
        )

    def undo_layout(self) -> None:
        if self._layout_locked or self._undo_layout is None or self._closing:
            return
        state, preset, main_index, compact_state = self._undo_layout
        self._preset_layout_generation += 1
        if self.restoreState(QByteArray(state), 1):
            self._layout_preset = preset
            self._main_module_index = main_index
            self._pre_compact_screen_dock_state = compact_state
            self._compact_screen_layout_active = compact_state is not None
            for dock in self._docks.values():
                dock.show()
            self._schedule_visible_state_snapshot()
        self._undo_layout = None
        self._refresh_layout_controls()

    def apply_layout_preset(self, preset: str, *, remember: bool = True) -> None:
        """Apply a visual preset without changing instruments or measurement state."""
        if self._layout_locked or not self._docks or self._closing or preset not in CONSOLE_LAYOUTS:
            return
        if remember:
            self._remember_layout_for_undo()
        self._layout_preset = preset
        self._compact_screen_layout_active = False
        self._pre_compact_screen_dock_state = None
        self._arrange_preset(preset)
        self._refresh_layout_controls()
        self.statusBar().showMessage(
            tr("Layout: {0} · {1} instruments").format(self._preset_labels[preset], len(self._docks))
        )

    def arrange_side_by_side(self) -> None:
        self.apply_layout_preset("columns")

    def arrange_single_pane(self) -> None:
        self.apply_layout_preset("tabs")

    def arrange_two_by_two(self) -> None:
        self.apply_layout_preset("grid_2x2")

    def _arrange_preset(self, preset: str) -> None:
        """Build each split level before nesting; absent cells consume no space."""
        if self._closing or not self._docks:
            return
        self.setUpdatesEnabled(False)
        try:
            docks = self._prepare_for_preset()
            if preset.startswith("main_") and self._main_module_index in self._docks:
                main_dock = self._docks[self._main_module_index]
                docks.remove(main_dock)
                docks.insert(0, main_dock)
            tree = CONSOLE_LAYOUTS[preset]
            capacity = len(layout_cells(tree))
            resize_groups: list[tuple[list[InstrumentDockWidget], list[int], Qt.Orientation]] = []

            def build(node: int | LayoutSplit, *, root: bool = False) -> None:
                if isinstance(node, int):
                    return
                children = [
                    (child, weight, next(cell for cell in layout_cells(child) if cell < len(docks)))
                    for child, weight in zip(node.children, node.weights, strict=True)
                    if any(cell < len(docks) for cell in layout_cells(child))
                ]
                anchors = [docks[cell] for _, _, cell in children]
                for previous, anchor in zip(anchors, anchors[1:], strict=False):
                    if root and node.orientation == Qt.Orientation.Horizontal and len(anchors) == 2:
                        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, anchor)
                    else:
                        self.splitDockWidget(previous, anchor, node.orientation)
                if len(anchors) > 1:
                    resize_groups.append((anchors, [weight for _, weight, _ in children], node.orientation))
                for child, _, _ in children:
                    build(child)

            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, docks[0])
            build(tree, root=True)
            for index, dock in enumerate(docks[capacity:]):
                anchor = docks[index % capacity]
                self.addDockWidget(self.dockWidgetArea(anchor), dock)
                self.tabifyDockWidget(anchor, dock)
            for dock in docks:
                dock.show()
            for dock in docks[:capacity]:
                dock.raise_()
            generation = self._preset_layout_generation
            self._resize_preset(resize_groups, generation)
            # Qt resolves hosted size hints again after showing the new split tree.
            QTimer.singleShot(0, lambda: self._resize_preset(resize_groups, generation))
            self._schedule_visible_state_snapshot()
        finally:
            self.setUpdatesEnabled(True)

    def _resize_preset(
        self,
        groups: list[tuple[list[InstrumentDockWidget], list[int], Qt.Orientation]],
        generation: int,
    ) -> None:
        from PyQt6 import sip

        if sip.isdeleted(self) or self._closing or generation != self._preset_layout_generation:
            return
        for docks, weights, orientation in groups:
            if any(dock not in self._docks.values() for dock in docks):
                return
            # Use the actual group's span, not the whole window for nested splits.
            span = sum(dock.width() if orientation == Qt.Orientation.Horizontal else dock.height() for dock in docks)
            sizes = [max(1, span * weight // sum(weights)) for weight in weights]
            self.resizeDocks(docks, sizes, orientation)

    def _schedule_visible_state_snapshot(self) -> None:
        from PyQt6 import sip

        if not sip.isdeleted(self) and not self._closing:
            QTimer.singleShot(0, self._cache_visible_dock_state)

    def _cache_visible_dock_state(self) -> None:
        from PyQt6 import sip

        if sip.isdeleted(self) or self._closing or not self._docks:
            return
        if all(dock.toggleViewAction().isChecked() for dock in self._docks.values()):
            self._last_visible_dock_state = bytes(self.saveState(1))

    def _recover_hidden_restored_docks(self) -> None:
        if not self._validate_docks_after_show:
            return
        self._validate_docks_after_show = False
        if all(dock.toggleViewAction().isChecked() for dock in self._docks.values()):
            return

        logger.warning("Saved measurement console hid one or more docks; using safe layout")
        self._arrange_preset(self._layout_preset)

    def set_layout_locked(self, locked: bool) -> None:
        self._layout_locked = bool(locked)
        features = QDockWidget.DockWidgetFeature.NoDockWidgetFeatures if locked else self._UNLOCKED_FEATURES
        for dock in self._docks.values():
            dock.setFeatures(features)
        self.add_button.setEnabled(not locked)
        self.layout_button.setEnabled(not locked)
        self._refresh_layout_controls()
        self._rebuild_add_menu()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._screen_change_connected and self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(self._on_screen_changed)
            self._screen_change_connected = True
        QTimer.singleShot(0, self._recover_hidden_restored_docks)
        # restoreGeometry() may only be committed by the window system during
        # showEvent.  Defer recovery until after that commit so a stale tiny
        # geometry cannot overwrite the corrected size.
        # The first turn applies dock recovery and the native restore; the
        # second turn corrects the final committed top-level geometry.
        QTimer.singleShot(0, self._schedule_geometry_recovery)
        self._schedule_visible_state_snapshot()
        self._schedule_geometry_snapshot()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._schedule_geometry_snapshot()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._schedule_geometry_snapshot()

    def _on_screen_changed(self, _screen) -> None:
        if not self._closing:
            self._schedule_geometry_recovery()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        self._closing = True
        self._cancel_stop_all()
        self.save_workspace()
        for module_index in list(self._docks):
            self.remove_module(module_index)
        event.accept()
        self.closed.emit()
        super().closeEvent(event)

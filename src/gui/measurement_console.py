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
from typing import TYPE_CHECKING

from PyQt6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QMoveEvent, QResizeEvent, QShowEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDockWidget,
    QMainWindow,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStyle,
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

    def _schedule_primary_action_sync(self, *_args) -> None:
        QTimer.singleShot(0, self._sync_primary_action)

    def eventFilter(self, watched, event) -> bool:
        """Keep the title-bar proxy usable when the source action is enabled later."""
        if watched is self._primary_action and event.type() == QEvent.Type.EnabledChange:
            self._schedule_primary_action_sync()
        return super().eventFilter(watched, event)

    def _sync_primary_action(self) -> None:
        if self._primary_action is None or self._primary_button is None:
            return
        running = self._primary_action.isChecked()
        label = self._primary_action.text() or (tr("Stop") if running else tr("Start"))
        icon = QStyle.StandardPixmap.SP_MediaStop if running else QStyle.StandardPixmap.SP_MediaPlay
        self._primary_button.setText(label)
        self._primary_button.setAccessibleName(label)
        self._primary_button.setToolTip(label)
        self._primary_button.setEnabled(self._primary_action.isEnabled())
        self._primary_button.setIcon(self.style().standardIcon(icon))

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
        self.layout_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout_menu = QMenu(self.layout_button)

        side_by_side_action = QAction(tr("Side by Side"), layout_menu)
        side_by_side_action.triggered.connect(self.arrange_side_by_side)
        layout_menu.addAction(side_by_side_action)

        grid_action = QAction(tr("2 x 2 Grid"), layout_menu)
        grid_action.triggered.connect(self.arrange_two_by_two)
        layout_menu.addAction(grid_action)

        default_action = QAction(tr("Default Console"), layout_menu)
        default_action.triggered.connect(self.load_default_console)
        layout_menu.addAction(default_action)

        self.layout_button.setMenu(layout_menu)
        toolbar.addWidget(self.layout_button)

        self.lock_action = QAction(tr("Lock Layout"), toolbar)
        self.lock_action.setCheckable(True)
        self.lock_action.toggled.connect(self.set_layout_locked)
        toolbar.addAction(self.lock_action)

        self._rebuild_add_menu()

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
        if self._layout_locked:
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

        self._compact_screen_layout_active = False
        self._pre_compact_screen_dock_state = None
        QTimer.singleShot(0, self._arrange_default_console_for_current_screen)

    def _arrange_default_console_for_current_screen(self) -> None:
        """Apply the regular preset, then constrain it to the actual screen."""
        self.arrange_two_by_two()
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
            self.arrange_two_by_two()
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
            "dock_state": base64.b64encode(dock_state).decode("ascii"),
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
            self._apply_layout_while_locked(self.arrange_single_pane)
            self._compact_screen_layout_active = True
            return

        if not self._compact_screen_layout_active:
            return

        state = self._pre_compact_screen_dock_state
        self._compact_screen_layout_active = False
        self._pre_compact_screen_dock_state = None
        if state and self.restoreState(QByteArray(state), 1):
            for dock in self._docks.values():
                dock.show()
            self._schedule_visible_state_snapshot()
        else:
            self._apply_layout_while_locked(self.arrange_two_by_two)

    def _apply_layout_while_locked(self, arrange) -> None:
        """Apply a safety preset without changing the user's lock setting."""
        was_locked = self._layout_locked
        self._layout_locked = False
        try:
            arrange()
        finally:
            self._layout_locked = was_locked

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
        dock.dockLocationChanged.connect(lambda _area: self._schedule_visible_state_snapshot())
        dock.topLevelChanged.connect(lambda _floating: self._schedule_visible_state_snapshot())
        dock.visibilityChanged.connect(lambda _visible: self._schedule_visible_state_snapshot())
        dock.set_instrument_widget(wrapper)
        self._docks[module_index] = dock
        if arrange and self._compact_screen_layout_active and existing_docks:
            anchor = existing_docks[0]
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
            self.tabifyDockWidget(anchor, dock)
        elif arrange:
            self._insert_dock_preserving_layout(dock, existing_docks)
        else:
            initial_area = (
                Qt.DockWidgetArea.LeftDockWidgetArea if len(self._docks) % 2 else Qt.DockWidgetArea.RightDockWidgetArea
            )
            self.addDockWidget(initial_area, dock)
        dock.show()
        if arrange and len(existing_docks) >= 4:
            # tabifyDockWidget() runs before the dock is shown so Qt never lays
            # it out as a temporary fifth split.  Raise it only after show().
            dock.raise_()

        self._rebuild_add_menu()
        self.statusBar().showMessage(tr("{0} instruments in the console.").format(len(self._docks)))

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
        dock = self._docks.pop(module_index, None)
        if dock is None:
            return

        wrapper = dock.take_instrument_widget()
        if wrapper is not None:
            wrapper.setParent(None)
        self.removeDockWidget(dock)
        dock._allow_close = True
        dock.deleteLater()

        self.main_window.return_module_from_console(module_index, self)
        self._rebuild_add_menu()
        if self._docks:
            self.statusBar().showMessage(tr("{0} instruments in the console.").format(len(self._docks)))
        else:
            self.statusBar().showMessage(tr("No instruments in the console."))

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
        docks = list(self._docks.values())
        for dock in docks:
            if dock.isFloating():
                dock.setFloating(False)
            self.removeDockWidget(dock)
        return docks

    def arrange_side_by_side(self) -> None:
        """Arrange instruments in two columns, using tabs beyond two instruments.

        A horizontal split per instrument quickly becomes unusable because each
        hosted widget contributes its own minimum width.  Keep only two stable
        comparison panes and distribute further instruments between their tab
        groups instead (four instruments become two tabs on each side).
        """
        if self._layout_locked or not self._docks:
            return
        docks = self._prepare_for_preset()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, docks[0])

        if len(docks) >= 2:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, docks[1])

        column_anchors = docks[:2]
        for index, dock in enumerate(docks[2:]):
            anchor = column_anchors[index % len(column_anchors)]
            area = self.dockWidgetArea(anchor)
            self.addDockWidget(area, dock)
            self.tabifyDockWidget(anchor, dock)

        for dock in docks:
            dock.show()
        for anchor in column_anchors:
            anchor.raise_()
        self._schedule_visible_state_snapshot()

    def arrange_single_pane(self) -> None:
        """Arrange all instruments as tabs in one reachable pane.

        This is the safe fallback for screens smaller than the main window's
        supported 2 x 2 workspace.  Each instrument still has its own scroll
        area, while tabs keep every instrument reachable without shrinking its
        controls below a usable size.
        """
        if self._layout_locked or not self._docks:
            return
        docks = self._prepare_for_preset()
        anchor = docks[0]
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, anchor)
        for dock in docks[1:]:
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
            self.tabifyDockWidget(anchor, dock)

        for dock in docks:
            dock.show()
        anchor.raise_()
        self._schedule_visible_state_snapshot()

    def arrange_two_by_two(self) -> None:
        if self._layout_locked or not self._docks:
            return
        docks = self._prepare_for_preset()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, docks[0])

        if len(docks) >= 2:
            # Use opposing dock areas for the two columns.  With the central
            # workspace collapsed to zero this is more reliable across Qt
            # styles than asking one side area for a horizontal nested split.
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, docks[1])
        if len(docks) >= 3:
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, docks[2])
            self.splitDockWidget(docks[0], docks[2], Qt.Orientation.Vertical)
        if len(docks) >= 4:
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, docks[3])
            self.splitDockWidget(docks[1], docks[3], Qt.Orientation.Vertical)

        # Additional instruments become tabs in the four control-room cells.
        # Stacking more rows makes QMainWindow honor every instrument's minimum
        # height and can grow the console beyond the physical screen.
        for index, dock in enumerate(docks[4:]):
            anchor = docks[index % min(4, len(docks))]
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
            self.tabifyDockWidget(anchor, dock)

        for dock in docks:
            dock.show()
        for dock in docks[:4]:
            dock.raise_()
        self._schedule_visible_state_snapshot()

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
        was_locked = self._layout_locked
        self._layout_locked = False
        try:
            self.arrange_two_by_two()
        finally:
            self._layout_locked = was_locked

    def set_layout_locked(self, locked: bool) -> None:
        self._layout_locked = bool(locked)
        features = QDockWidget.DockWidgetFeature.NoDockWidgetFeatures if locked else self._UNLOCKED_FEATURES
        for dock in self._docks.values():
            dock.setFeatures(features)
        self.add_button.setEnabled(not locked)
        self.layout_button.setEnabled(not locked)
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
        self.save_workspace()
        for module_index in list(self._docks):
            self.remove_module(module_index)
        event.accept()
        self.closed.emit()
        super().closeEvent(event)

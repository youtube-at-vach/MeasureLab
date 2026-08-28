from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from src.gui.module_registry import (
    COMPACT_DEFERRED,
    COMPARISON_DEFERRED,
    NO_INDEPENDENT_DISPLAY,
    SUPPORTED,
    WidgetCapabilities,
)
from src.gui.widgets import detachable_wrapper
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper, HeaderIcon
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


NO_CAPABILITIES = WidgetCapabilities(
    split_window=NO_INDEPENDENT_DISPLAY,
    compact_mode=NO_INDEPENDENT_DISPLAY,
    comparison=NO_INDEPENDENT_DISPLAY,
)


class _TrackingPanel(QWidget):
    def __init__(self, color: Qt.GlobalColor):
        super().__init__()
        self.color = color
        self.grab_calls = 0

    def grab(self) -> QPixmap:
        self.grab_calls += 1
        pixmap = QPixmap(8, 8)
        pixmap.fill(self.color)
        return pixmap


class _SplittableContent(_TrackingPanel, SplittableWidgetInterface):
    def __init__(self):
        super().__init__(Qt.GlobalColor.black)
        self.display_widget = _TrackingPanel(Qt.GlobalColor.green)
        self.control_widget = _TrackingPanel(Qt.GlobalColor.blue)
        self.main_layout = QHBoxLayout(self)
        self.main_layout.addWidget(self.display_widget)
        self.main_layout.addWidget(self.control_widget)

    def get_display_widget(self) -> QWidget:
        return self.display_widget

    def get_control_widget(self) -> QWidget:
        return self.control_widget

    def restore_split_panels(self) -> None:
        self.main_layout.addWidget(self.display_widget)
        self.main_layout.addWidget(self.control_widget)


@pytest.fixture
def split_wrapper(qapp, qtbot):
    content = _SplittableContent()
    capabilities = WidgetCapabilities(
        split_window=SUPPORTED,
        compact_mode=COMPACT_DEFERRED,
        comparison=COMPARISON_DEFERRED,
    )
    wrapper = DetachableWidgetWrapper(content, "Split Actions", capabilities=capabilities)
    qtbot.addWidget(wrapper)
    wrapper.show()
    yield wrapper, content
    if wrapper.is_split:
        wrapper.reattach_all()
    elif wrapper.is_detached:
        wrapper.reattach()
    qapp.processEvents()


def test_screenshot_captures_visible_display_panel_while_split(split_wrapper, tmp_path, qtbot):
    wrapper, content = split_wrapper
    wrapper.config_manager = type(
        "Config",
        (),
        {"get_screenshot_output_dir": lambda self: str(tmp_path)},
    )()
    wrapper.split()
    qtbot.wait(1)

    with patch("src.gui.widgets.detachable_wrapper.QMessageBox.information") as information:
        wrapper.screenshot_btn.click()

    assert content.display_widget.grab_calls == 1
    assert content.control_widget.grab_calls == 0
    assert content.grab_calls == 0
    assert len(list(tmp_path.glob("Split_Actions_*.png"))) == 1
    information.assert_called_once()


def test_split_button_transitions_from_detached_state(split_wrapper, qtbot):
    wrapper, content = split_wrapper
    wrapper.detach()
    qtbot.wait(1)

    assert wrapper.is_detached
    assert wrapper.split_btn is not None
    assert wrapper.split_btn.isEnabled()

    wrapper.split_btn.click()
    qtbot.wait(1)

    assert not wrapper.is_detached
    assert wrapper.is_split
    assert content.display_widget.parent() is wrapper.split_display_window
    assert content.control_widget.parent() is wrapper.split_control_window


def test_detach_request_does_not_corrupt_split_state(split_wrapper, qtbot):
    wrapper, content = split_wrapper
    wrapper.split()
    qtbot.wait(1)
    display_window = wrapper.split_display_window
    control_window = wrapper.split_control_window

    wrapper.detach()

    assert wrapper.is_split
    assert not wrapper.is_detached
    assert wrapper.split_display_window is display_window
    assert wrapper.split_control_window is control_window
    assert content.display_widget.parent() is display_window
    assert content.control_widget.parent() is control_window


def test_activate_external_windows_raises_both_split_windows(qtbot):
    wrapper = DetachableWidgetWrapper(QWidget(), "Split Activation", capabilities=NO_CAPABILITIES)
    qtbot.addWidget(wrapper)
    display_window = MagicMock()
    control_window = MagicMock()
    wrapper.is_split = True
    wrapper.split_display_window = display_window
    wrapper.split_control_window = control_window

    try:
        assert wrapper.activate_external_windows()
        for window in (display_window, control_window):
            window.show.assert_called_once_with()
            window.raise_.assert_called_once_with()
            window.activateWindow.assert_called_once_with()
    finally:
        wrapper.is_split = False
        wrapper.split_display_window = None
        wrapper.split_control_window = None


def test_logs_action_opens_and_activates_shared_viewer(qtbot):
    wrapper = DetachableWidgetWrapper(QWidget(), "Logs Test", capabilities=NO_CAPABILITIES)
    qtbot.addWidget(wrapper)
    viewer = MagicMock()

    with patch("src.gui.widgets.log_viewer.LogViewerWindow.get_instance", return_value=viewer) as get_instance:
        wrapper.logs_action.trigger()

    get_instance.assert_called_once_with()
    viewer.show.assert_called_once_with()
    viewer.raise_.assert_called_once_with()
    viewer.activateWindow.assert_called_once_with()


def test_more_menu_contains_comparison_only_when_supported(qtbot):
    plain_wrapper = DetachableWidgetWrapper(QWidget(), "Plain", capabilities=NO_CAPABILITIES)
    qtbot.addWidget(plain_wrapper)
    assert plain_wrapper.logs_action in plain_wrapper.more_menu.actions()
    assert plain_wrapper.compare_action is None

    comparable_capabilities = WidgetCapabilities(
        split_window=NO_INDEPENDENT_DISPLAY,
        compact_mode=NO_INDEPENDENT_DISPLAY,
        comparison=SUPPORTED,
    )

    from src.gui.widgets.comparable_interface import ComparableWidgetInterface

    class _ComparableContent(QWidget, ComparableWidgetInterface):
        def get_comparable_data(self):
            return []

    comparable_wrapper = DetachableWidgetWrapper(
        _ComparableContent(),
        "Comparable",
        capabilities=comparable_capabilities,
    )
    qtbot.addWidget(comparable_wrapper)

    assert comparable_wrapper.compare_action is not None
    assert comparable_wrapper.compare_action in comparable_wrapper.more_menu.actions()


def test_header_buttons_use_clear_custom_icons_and_accessible_labels(split_wrapper):
    wrapper, _ = split_wrapper

    expected_icons = {
        wrapper.more_btn: ("more", "More"),
        wrapper.screenshot_btn: ("screenshot", "Screenshot"),
        wrapper.split_btn: ("split", "Split Window"),
        wrapper.detach_btn: ("detach", "Detach Window"),
    }

    for button, (icon_name, label) in expected_icons.items():
        assert button is not None
        assert button.property("headerIcon") == icon_name
        assert button.accessibleName() == label
        assert button.toolTip() == label
        assert not button.icon().isNull()
        assert button.iconSize() == QSize(22, 22)
        assert button.size() == QSize(34, 28)


def test_header_icon_rendering_is_reused_for_matching_palette_color():
    detachable_wrapper._cached_header_icon.cache_clear()
    color = QColor("#123456")

    with patch.object(
        detachable_wrapper,
        "_draw_header_icon",
        wraps=detachable_wrapper._draw_header_icon,
    ) as draw_header_icon:
        first = detachable_wrapper.make_header_icon(HeaderIcon.DETACH, color)
        second = detachable_wrapper.make_header_icon(HeaderIcon.DETACH, color)

    assert not first.isNull()
    assert not second.isNull()
    assert draw_header_icon.call_count == 4

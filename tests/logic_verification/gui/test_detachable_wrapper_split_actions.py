from __future__ import annotations

from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from src.gui.module_registry import (
    COMPACT_DEFERRED,
    COMPARISON_DEFERRED,
    SUPPORTED,
    WidgetCapabilities,
)
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.splittable_interface import SplittableWidgetInterface


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

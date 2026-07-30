from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


class SplittableWidgetInterface:
    """
    Interface/Mixin for widgets that support Split Mode (State C).

    A splittable widget can separate its display part and control part
    into two independent windows.
    """

    def __init__(self):
        pass

    def get_display_widget(self) -> "QWidget":
        """
        Returns the display-only sub-widget (e.g. the plot/canvas area).
        This widget will be placed in the display IndependentWindow.
        """
        raise NotImplementedError("Subclasses must implement get_display_widget")

    def get_control_widget(self) -> "QWidget":
        """
        Returns the controls sub-widget (e.g. settings panel).
        This widget will be placed in the control IndependentWindow.
        """
        raise NotImplementedError("Subclasses must implement get_control_widget")

    def restore_split_panels(self) -> None:
        """
        Called by DetachableWidgetWrapper.reattach_all() after both split windows are closed
        and the sub-widgets have been reparented back to this widget.
        Subclasses must re-insert display_widget and control_widget into their layout so
        that the normal (State A) appearance is fully restored.
        """
        raise NotImplementedError("Subclasses must implement restore_split_panels")

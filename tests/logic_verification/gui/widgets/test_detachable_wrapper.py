import pytest
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper

class TestDetachableWidgetWrapper:
    def test_safe_base_filename_normal(self):
        result = DetachableWidgetWrapper._safe_base_filename(None, "MyWidget_2023")
        assert result == "MyWidget_2023"

    def test_safe_base_filename_empty(self):
        result = DetachableWidgetWrapper._safe_base_filename(None, "")
        assert result == "widget"

    def test_safe_base_filename_none(self):
        result = DetachableWidgetWrapper._safe_base_filename(None, None)
        assert result == "widget"

    def test_safe_base_filename_whitespace(self):
        result = DetachableWidgetWrapper._safe_base_filename(None, "   ")
        assert result == "widget"

    def test_safe_base_filename_special_chars(self):
        result = DetachableWidgetWrapper._safe_base_filename(None, "Widget @#$%")
        # Spaces become _, then invalid become _, so it becomes "Widget___" then stripped of "_" -> "Widget"
        assert result == "Widget"

    def test_safe_base_filename_only_invalid(self):
        result = DetachableWidgetWrapper._safe_base_filename(None, "///")
        assert result == "widget"

"""Use the same lazy module registry and factory as MainWindow."""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from src.gui.main_window import _load_module_class
from src.gui.module_registry import MODULE_REGISTRY


def module_keys() -> list[str]:
    return list(MODULE_REGISTRY)


def create_module_widget(key: str, engine) -> tuple[object, QWidget]:
    module = _load_module_class(key)(engine)
    widget = module.get_widget()
    if not isinstance(widget, QWidget):
        raise AssertionError(f"{key}: get_widget() returned {type(widget).__name__}")
    return module, widget

"""Shared geometry for console presets and their miniature previews."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap


@dataclass(frozen=True)
class LayoutSplit:
    orientation: Qt.Orientation
    children: tuple[int | LayoutSplit, ...]
    weights: tuple[int, ...]


H = Qt.Orientation.Horizontal
V = Qt.Orientation.Vertical

CONSOLE_LAYOUTS: dict[str, int | LayoutSplit] = {
    "tabs": 0,
    "columns": LayoutSplit(H, (0, 1), (1, 1)),
    "grid_2x2": LayoutSplit(H, (LayoutSplit(V, (0, 2), (1, 1)), LayoutSplit(V, (1, 3), (1, 1))), (1, 1)),
    "grid_2x3": LayoutSplit(H, (LayoutSplit(V, (0, 2, 4), (1, 1, 1)), LayoutSplit(V, (1, 3, 5), (1, 1, 1))), (1, 1)),
    "grid_3x2": LayoutSplit(
        H,
        (LayoutSplit(V, (0, 3), (1, 1)), LayoutSplit(V, (1, 4), (1, 1)), LayoutSplit(V, (2, 5), (1, 1))),
        (1, 1, 1),
    ),
    "main_right": LayoutSplit(H, (0, LayoutSplit(V, (1, 2, 3), (1, 1, 1))), (2, 1)),
    "main_bottom": LayoutSplit(V, (0, LayoutSplit(H, (1, 2, 3), (1, 1, 1))), (2, 1)),
}


def layout_cells(tree: int | LayoutSplit) -> tuple[int, ...]:
    if isinstance(tree, int):
        return (tree,)
    return tuple(cell for child in tree.children for cell in layout_cells(child))


def make_layout_icon(preset: str, color: QColor) -> QIcon:
    """Draw the same split tree used by the workspace, at high DPI."""
    pixmap = QPixmap(80, 56)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    def draw(tree: int | LayoutSplit, rect: QRectF) -> None:
        if isinstance(tree, int):
            fill = QColor(color)
            fill.setAlpha(95 if tree == 0 and preset.startswith("main_") else 35)
            painter.setPen(color)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 2, 2)
            return
        offset = 0.0
        for child, weight in zip(tree.children, tree.weights, strict=True):
            fraction = weight / sum(tree.weights)
            if tree.orientation == H:
                part = QRectF(rect.x() + rect.width() * offset, rect.y(), rect.width() * fraction, rect.height())
            else:
                part = QRectF(rect.x(), rect.y() + rect.height() * offset, rect.width(), rect.height() * fraction)
            draw(child, part)
            offset += fraction

    draw(CONSOLE_LAYOUTS[preset], QRectF(0, 0, 40, 28))
    painter.end()
    return QIcon(pixmap)

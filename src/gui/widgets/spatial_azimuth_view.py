"""A top view for editing source azimuths; radius never represents distance."""

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPalette, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from src.core.localization import tr


class AzimuthView(QWidget):
    selected = pyqtSignal(int)
    azimuth_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sources: list[tuple[int, float, bool]] = []
        self.selected_id: int | None = None
        self._dragging = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr("Source azimuth map"))
        self.setAccessibleDescription(tr("Drag to change azimuth. Arrow keys adjust the selected source."))
        self.setMinimumSize(240, 240)

    def sizeHint(self):
        return QSize(300, 300)

    def set_sources(self, sources, selected_id):
        self.sources = sources
        self.selected_id = selected_id
        self.update()

    def _geometry(self):
        return QPointF(self.width() / 2, self.height() / 2), min(self.width(), self.height()) / 2 - 46

    def source_point(self, azimuth):
        center, radius = self._geometry()
        angle = math.radians(azimuth)
        # SOFA: +azimuth rotates from front toward the listener's left.
        return center + QPointF(-math.sin(angle) * radius, -math.cos(angle) * radius)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        center, radius = self._geometry()
        text = palette.color(QPalette.ColorRole.Text)
        line = palette.color(QPalette.ColorRole.Mid)
        accent = palette.color(QPalette.ColorRole.Highlight)
        painter.fillRect(self.rect(), palette.brush(QPalette.ColorRole.Base))
        painter.setPen(QPen(line, 1, Qt.PenStyle.DashLine))
        painter.drawEllipse(center, radius, radius)
        painter.drawLine(center + QPointF(-radius, 0), center + QPointF(radius, 0))
        painter.drawLine(center + QPointF(0, -radius), center + QPointF(0, radius))
        painter.setPen(text)
        labels = [
            (QRectF(center.x() - 65, center.y() - radius - 42, 130, 30), tr("Front · 0°")),
            (QRectF(center.x() - 65, center.y() + radius + 14, 130, 30), tr("Rear · 180°")),
            (QRectF(0, center.y() - 42, 86, 28), tr("Left") + " +90°"),
            (QRectF(self.width() - 86, center.y() - 42, 86, 28), tr("Right") + " −90°"),
        ]
        for rect, label in labels:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.setBrush(palette.brush(QPalette.ColorRole.Window))
        painter.setPen(QPen(text, 1.5))
        painter.drawEllipse(center, 16, 20)
        painter.drawPolyline(QPolygonF([center + QPointF(-5, -19), center + QPointF(0, -26), center + QPointF(5, -19)]))
        # Draw the selection last, keeping it reachable when sources overlap.
        for number, azimuth, audible in sorted(self.sources, key=lambda source: source[0] == self.selected_id):
            point = self.source_point(azimuth)
            selected = number == self.selected_id
            painter.setPen(QPen(accent if selected else line, 2 if selected else 1))
            if selected:
                painter.drawLine(center + (point - center) * 0.27, point)
            painter.setBrush(palette.brush(QPalette.ColorRole.Highlight if selected else QPalette.ColorRole.Window))
            painter.drawEllipse(point, 14, 14)
            painter.setPen(palette.color(QPalette.ColorRole.HighlightedText) if selected else text)
            painter.drawText(QRectF(point.x() - 14, point.y() - 14, 28, 28), Qt.AlignmentFlag.AlignCenter, str(number))
            if not audible:
                painter.drawLine(point + QPointF(-10, 10), point + QPointF(10, -10))
        if self.hasFocus():
            painter.setPen(QPen(accent, 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(2, 2, -3, -3))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.sources:
            return
        self.setFocus()
        nearest = min(
            self.sources,
            key=lambda source: (
                (self.source_point(source[1]) - event.position()).manhattanLength(),
                source[0] != self.selected_id,
            ),
        )
        if (self.source_point(nearest[1]) - event.position()).manhattanLength() <= 28:
            self.selected.emit(nearest[0])
        self._dragging = True
        self._move_source(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._move_source(event.position())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _move_source(self, point):
        center, _ = self._geometry()
        delta = point - center
        if self.selected_id is not None and math.hypot(delta.x(), delta.y()) > 20:
            azimuth = round(math.degrees(math.atan2(-delta.x(), -delta.y())))
            self.azimuth_changed.emit(self.selected_id, azimuth)

    def keyPressEvent(self, event):
        source = next((s for s in self.sources if s[0] == self.selected_id), None)
        if source and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home):
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            angle = (
                0 if event.key() == Qt.Key.Key_Home else source[1] + (step if event.key() == Qt.Key.Key_Left else -step)
            )
            self.azimuth_changed.emit(source[0], int((angle + 180) % 360 - 180))
        else:
            super().keyPressEvent(event)

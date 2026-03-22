import logging
import os
import traceback
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QSplashScreen, QWidget


class TopLevelWindowLogger(QObject):
    """Optional startup logger to identify transient top-level windows.

    Enable by setting environment variable MEASURELAB_DEBUG_WINDOWS=1.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self._trace_enabled = os.environ.get("MEASURELAB_DEBUG_WINDOWS_TRACE", "").strip() not in (
            "",
            "0",
            "false",
            "False",
        )
        self._traced_ids = set()

    def _maybe_trace(self, obj: QWidget) -> None:
        if not self._trace_enabled:
            return

        try:
            oid = int(obj.winId()) if obj.winId() else id(obj)
        except (AttributeError, RuntimeError):
            oid = id(obj)

        if oid in self._traced_ids:
            return

        self._traced_ids.add(oid)

        try:
            self.logger.info("[window-trace] begin")
            for line in traceback.format_stack(limit=40):
                self.logger.info(line.rstrip("\n"))
            self.logger.info("[window-trace] end")
        except Exception:
            self.logger.error("Error during window trace", exc_info=True)

    def eventFilter(self, obj, event):
        try:
            if isinstance(obj, QWidget) and obj.isWindow():
                et = event.type()
                if et in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.WindowTitleChange):
                    g = obj.geometry()
                    title = obj.windowTitle()
                    name = obj.__class__.__name__
                    self.logger.info(
                        f"[window] {name} title='{title}' event={int(et)} "
                        f"geom=({g.x()},{g.y()},{g.width()}x{g.height()}) visible={obj.isVisible()}"
                    )

                    # Trace suspicious tiny, untitled top-level windows (often the 'flash').
                    if et == QEvent.Type.Show and not title:
                        if 0 < g.width() <= 650 and 0 < g.height() <= 120:
                            self._maybe_trace(obj)
        except (AttributeError, RuntimeError):
            self.logger.error("Error in event filter", exc_info=True)

        return super().eventFilter(obj, event)


class WrappingSplashScreen(QSplashScreen):
    """
    Custom QSplashScreen that supports text wrapping and padding.
    """

    def __init__(self, pixmap):
        super().__init__(pixmap)
        self._message = ""
        self._alignment = Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter
        self._color = Qt.GlobalColor.black

    def showMessage(
        self,
        message,
        alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        color=Qt.GlobalColor.black,
    ):
        self._message = message
        self._alignment = alignment
        self._color = color
        # Trigger a repaint so paintEvent uses the updated message
        self.repaint()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Draw the original pixmap as background
        painter.drawPixmap(0, 0, self.pixmap())

        painter.setPen(self._color)
        # Add padding around the edges
        margin = 20
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        # Draw text with word wrap
        painter.drawText(rect, self._alignment | Qt.TextFlag.TextWordWrap, self._message)
        painter.end()

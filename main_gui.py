#!/usr/bin/env python3
import os
import signal
import sys

# Suppress benign GNOME portal Settings warnings like:
#   qt.qpa.theme.gnome: dbus reply error: ... org.freedesktop.portal.Settings
# This must be set before importing Qt/PyQt.
_qt_rule = "qt.qpa.theme.gnome=false"
_existing_rules = os.environ.get("QT_LOGGING_RULES")
if not _existing_rules:
    os.environ["QT_LOGGING_RULES"] = _qt_rule

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, QRect
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QApplication, QSplashScreen, QWidget

from src.core.config_manager import ConfigManager
from src.core.localization import get_manager, tr
from src.core.localization import get_manager, tr
from src.core.utils import resource_path
from src.core.fft_manager import fft_manager
from src.gui.main_window import MainWindow


class _TopLevelWindowLogger(QObject):
    """Optional startup logger to identify transient top-level windows.

    Enable by setting environment variable MEASURELAB_DEBUG_WINDOWS=1.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
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
        except Exception:
            oid = id(obj)

        if oid in self._traced_ids:
            return

        self._traced_ids.add(oid)

        try:
            import traceback

            print("[window-trace] begin")
            for line in traceback.format_stack(limit=40):
                print(line.rstrip("\n"))
            print("[window-trace] end")
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            if isinstance(obj, QWidget) and obj.isWindow():
                et = event.type()
                if et in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.WindowTitleChange):
                    g = obj.geometry()
                    title = obj.windowTitle()
                    name = obj.__class__.__name__
                    print(
                        f"[window] {name} title='{title}' event={int(et)} "
                        f"geom=({g.x()},{g.y()},{g.width()}x{g.height()}) visible={obj.isVisible()}"
                    )

                    # Trace suspicious tiny, untitled top-level windows (often the 'flash').
                    if et == QEvent.Type.Show and not title:
                        if 0 < g.width() <= 650 and 0 < g.height() <= 120:
                            self._maybe_trace(obj)
        except Exception:
            pass

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

    def showMessage(self, message, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, color=Qt.GlobalColor.black):
        self._message = message
        self._alignment = alignment
        self._color = color
        # Call super to trigger repaint, but we'll override drawContents
        super().showMessage(message, alignment, color)

    def drawContents(self, painter: QPainter):
        painter.setPen(self._color)
        # Add padding around the edges
        margin = 20
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        # Draw text with word wrap
        painter.drawText(rect, self._alignment | Qt.TextFlag.TextWordWrap, self._message)

def main():
    """GUI Application Entry Point"""
    # Allow Ctrl+C to exit
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Load language early so the splash text matches user settings.
    # Keep this lightweight: just read config + load translations.
    try:
        config_manager = ConfigManager()
        get_manager().load_language(config_manager.get_language())
    except Exception:
        # If config or translations fail, proceed with defaults.
        pass

    app = QApplication(sys.argv)

    # Optional: log transient windows during startup to diagnose flashes.
    if os.environ.get("MEASURELAB_DEBUG_WINDOWS", "").strip() not in ("", "0", "false", "False"):
        app._measurelab_window_logger = _TopLevelWindowLogger(app)  # keep a strong ref
        app.installEventFilter(app._measurelab_window_logger)

    # Startup splash (loading screen): show immediately while MainWindow initializes.
    pixmap = QPixmap(resource_path('src/assets/welcome.png'))
    if pixmap.isNull():
        pixmap = QPixmap(624, 360)
        pixmap.fill(Qt.GlobalColor.black)
    else:
        pixmap = pixmap.scaled(
            624,
            360,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    splash = WrappingSplashScreen(pixmap)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.show()
    # Center on primary screen
    try:
        screen = app.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            splash_rect = splash.frameGeometry()
            splash_rect.moveCenter(geom.center())
            splash.move(splash_rect.topLeft())
    except Exception:
        pass
    splash.showMessage(
        f"{tr('Loading...')}\n{tr('Initializing application...')}",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        Qt.GlobalColor.white,
    )
    app.processEvents()

    # Brand name (do not translate)
    app.setApplicationName("MeasureLab")
    try:
        app.setApplicationDisplayName("MeasureLab")
    except Exception:
        pass

    window = MainWindow()

    # Preload all modules while splash is visible, so module switching feels instant.
    def _update_splash(msg: str):
        # Translate the message here if needed, or pass translated strings
        splash.showMessage(
            f"{tr('Loading...')}\n{msg}",
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            Qt.GlobalColor.white,
        )
        app.processEvents()

    try:
        # 1. Warmup FFT Optimization (Show progress)
        # This will be fast if wisdom exists, or show progress if optimizing
        fft_manager.warmup(callback=_update_splash)

        # 2. Preload Modules
        window.preload_all_modules(progress_callback=_update_splash)
    except Exception as e:
        print(f"Startup error: {e}")
        # If preload fails, still show the window; individual pages may show errors.
        pass

    # Show the main window, then finish the splash on the next event-loop turn.
    # On some Linux WMs, calling finish() immediately can reveal a briefly
    # unpolished (small) initial window before final geometry is applied.
    window.show()
    app.processEvents()
    QTimer.singleShot(0, lambda: splash.finish(window))

    # Self-test mode: exit automatically after 5 seconds to verify startup.
    if "--self-test" in sys.argv:
        print("[Self-Test] Application started successfully. Exiting in 5 seconds...")
        QTimer.singleShot(5000, app.quit)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()

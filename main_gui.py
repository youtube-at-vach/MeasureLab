#!/usr/bin/env python3
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys

from src.core.config_manager import ConfigManager
from src.core.localization import get_manager, tr
from src.core.utils import resource_path
from src.core.fft_manager import fft_manager


def setup_app():
    """Set up the QApplication instance, logging, and environment configuration."""
    # Suppress benign GNOME portal Settings warnings like:
    #   qt.qpa.theme.gnome: dbus reply error: ... org.freedesktop.portal.Settings
    # This must be set before importing Qt/PyQt.
    _qt_rule = "qt.qpa.theme.gnome=false"
    _existing_rules = os.environ.get("QT_LOGGING_RULES")
    if not _existing_rules:
        os.environ["QT_LOGGING_RULES"] = _qt_rule

    # Import PyQt and GUI components only after setting the environment variable
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    # Allow Ctrl+C to exit
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Parse basic arguments for logging before full Qt initialization
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--log-level", default="INFO", help="Set logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    parser.add_argument("--log-file", default=None, help="Path to log file (overrides default)")
    args, _ = parser.parse_known_args()

    numeric_level = getattr(logging, args.log_level.upper(), logging.INFO)

    # Determine log file path
    if os.environ.get("MEASURELAB_TESTING") == "1":
        log_path = os.devnull
    elif args.log_file:
        log_path = args.log_file
    else:
        # Default to User Data Directory
        user_dir = ConfigManager.get_user_data_dir()
        os.makedirs(user_dir, exist_ok=True)
        log_path = os.path.join(user_dir, "measurelab.log")

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (5MB, 2 backups)
    if os.environ.get("MEASURELAB_TESTING") == "1":
        logging.info("MEASURELAB_TESTING=1 detected: Skipping file logging initialization.")
    else:
        try:
            file_handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            logging.error(f"Failed to set up file logging at {log_path}: {e}")

    # Load language early so the splash text matches user settings.
    # Keep this lightweight: just read config + load translations.
    try:
        config_manager = ConfigManager()
        get_manager().load_language(config_manager.get_language())
    except Exception:
        # If config or translations fail, proceed with defaults.
        logging.error("Failed to load configuration or language", exc_info=True)
        pass

    app = QApplication(sys.argv)

    from src.gui.startup import TopLevelWindowLogger
    # Optional: log transient windows during startup to diagnose flashes.
    if os.environ.get("MEASURELAB_DEBUG_WINDOWS", "").strip() not in ("", "0", "false", "False"):
        app._measurelab_window_logger = TopLevelWindowLogger(app)  # keep a strong ref
        app.installEventFilter(app._measurelab_window_logger)

    # Attach the Qt logging handler to the root logger
    try:
        from src.gui.widgets.log_viewer import LogViewerWindow
        LogViewerWindow.attach_to_logger(root_logger)

        # If debug is passed, we might want to ensure the log level matches
        # The QtLogHandler operates at DEBUG and filters based on user selection in the UI.
    except ImportError as e:
        logging.error(f"Could not load GUI LogViewer: {e}")

    # Brand name (do not translate)
    app.setApplicationName("MeasureLab")
    try:
        app.setApplicationDisplayName("MeasureLab")
    except Exception:
        pass

    return app

def main():
    """GUI Application Entry Point"""
    app = setup_app()

    # Import other PyQt components after setup
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QPixmap

    from src.gui.main_window import MainWindow
    from src.gui.startup import WrappingSplashScreen

    # Startup splash (loading screen): show immediately while MainWindow initializes.
    pixmap = QPixmap(resource_path("src/assets/welcome.png"))
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

    enable_experimental = "--experimental" in sys.argv
    window = MainWindow(enable_experimental=enable_experimental)

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
        logging.error(f"Startup error: {e}")
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
        logging.info("[Self-Test] Application started successfully. Exiting in 5 seconds...")
        QTimer.singleShot(5000, app.quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()

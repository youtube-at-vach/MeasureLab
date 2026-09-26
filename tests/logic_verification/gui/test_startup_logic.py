import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from src.gui.startup import WrappingSplashScreen


def test_wrapping_splash_screen_show_message_updates_state_and_repaints(qtbot):
    pixmap = QPixmap(100, 100)
    splash = WrappingSplashScreen(pixmap)
    qtbot.addWidget(splash)

    with patch.object(splash, "repaint") as mock_repaint:
        splash.showMessage("Test message", alignment=Qt.AlignmentFlag.AlignCenter, color=Qt.GlobalColor.red)

        assert splash._message == "Test message"
        assert splash._alignment == Qt.AlignmentFlag.AlignCenter
        assert splash._color == Qt.GlobalColor.red
        mock_repaint.assert_called_once()


def test_setup_app_replays_logs_emitted_before_qapplication():
    root = Path(__file__).resolve().parents[3]
    code = """
import logging
import main_gui
from PyQt6.QtWidgets import QWidget
from src.gui.module_registry import NO_INDEPENDENT_DISPLAY, WidgetCapabilities
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper
from src.gui.widgets.log_viewer import LogViewerWindow, QtLogHandler

class Config:
    def __init__(self):
        logging.warning('early configuration marker')

    def get_language(self):
        return 'en'

main_gui.ConfigManager = Config
app = main_gui.setup_app()
viewer = LogViewerWindow.get_instance()
assert sum('early configuration marker' in message for message, _ in viewer.all_logs) == 1
assert sum(isinstance(handler, QtLogHandler) for handler in logging.getLogger().handlers) == 1
assert app._measurelab_log_handler in logging.getLogger().handlers
wrapper = DetachableWidgetWrapper(
    QWidget(), 'Log test',
    capabilities=WidgetCapabilities(split_window=NO_INDEPENDENT_DISPLAY, compact_mode=NO_INDEPENDENT_DISPLAY),
)
wrapper.show_logs()
assert sum(isinstance(handler, QtLogHandler) for handler in logging.getLogger().handlers) == 1
"""
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", MEASURELAB_TESTING="1")
    result = subprocess.run(  # noqa: S603 - the embedded test program is fixed source
        [sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr

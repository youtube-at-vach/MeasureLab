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

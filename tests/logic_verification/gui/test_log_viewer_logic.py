import logging
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QObject, pyqtSignal

from src.gui.widgets.log_viewer import LogViewerWindow, QtLogHandler


def test_qt_log_handler_emit_none():
    handler = QtLogHandler()
    handler.signals = MagicMock()
    handler.emit(None)
    handler.signals.log_emitted.emit.assert_not_called()


def test_qt_log_handler_emit_success():
    handler = QtLogHandler()
    handler.signals = MagicMock()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    handler.signals.log_emitted.emit.assert_called_once()
    args, _ = handler.signals.log_emitted.emit.call_args
    assert "Test message" in args[0]
    assert args[1] == logging.INFO


def test_qt_log_handler_emit_exception():
    handler = QtLogHandler()
    handler.signals = MagicMock()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    with patch.object(handler, "format", side_effect=Exception("Test Exception")):
        with patch.object(handler, "handleError") as mock_handle_error:
            handler.emit(record)
            mock_handle_error.assert_called_once_with(record)
            handler.signals.log_emitted.emit.assert_not_called()


def test_viewer_created_before_theme_manager_binds_when_shown(qtbot, monkeypatch, qapp):
    class ThemeManager(QObject):
        theme_changed = pyqtSignal(str)

    monkeypatch.delattr(qapp, "theme_manager", raising=False)
    viewer = LogViewerWindow()
    qtbot.addWidget(viewer)
    manager = ThemeManager()
    monkeypatch.setattr(qapp, "theme_manager", manager, raising=False)

    with patch.object(viewer, "_refresh_display") as refresh:
        viewer.show()
        qtbot.wait(0)
        manager.theme_changed.emit("dark")

    assert refresh.call_count >= 2

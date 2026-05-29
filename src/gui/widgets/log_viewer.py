import html
import logging

from PyQt6.QtCore import pyqtSignal, QObject, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QPlainTextEdit,
    QComboBox,
    QApplication,
)

from src.core.localization import tr


class QtLogSignals(QObject):
    log_emitted = pyqtSignal(str, int)  # The message string and the warning level (e.g., logging.WARNING)


class QtLogHandler(logging.Handler):
    """
    Custom logging handler that emits a Qt signal for each log record.
    This allows thread-safe GUI updates from background logging.
    """

    def __init__(self):
        super().__init__()
        self.signals = QtLogSignals()
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record):
        if record is None:
            return

        try:
            msg = self.format(record)
            self.signals.log_emitted.emit(msg, record.levelno)
        except Exception:
            self.handleError(record)


class LogViewerWindow(QDialog):
    """
    A persistent window to display application logs.
    """

    # We keep a strong reference to the singleton instance
    _instance = None

    @classmethod
    def get_instance(cls, parent=None):
        if cls._instance is None:
            cls._instance = cls(parent)
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Error Logs"))
        self.resize(800, 500)

        # Make the dialog modeless, meaning it floats over the application but doesn't block it
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self.current_level = logging.DEBUG
        self.all_logs = []

        self._init_ui()

        # Connect to theme changes to refresh existing logs with new palette colors
        app = QApplication.instance()
        if app and hasattr(app, "theme_manager"):
            app.theme_manager.theme_changed.connect(self._refresh_display)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Header controls
        header_layout = QHBoxLayout()

        self.level_combo = QComboBox()
        self.level_combo.addItem(tr("All Logs (DEBUG)"), logging.DEBUG)
        self.level_combo.addItem(tr("Info"), logging.INFO)
        self.level_combo.addItem(tr("Warnings"), logging.WARNING)
        self.level_combo.addItem(tr("Errors Only"), logging.ERROR)

        # Default to Info for less clutter, but keep all in memory
        self.level_combo.setCurrentIndex(1)
        self.current_level = logging.INFO
        self.level_combo.currentIndexChanged.connect(self._on_level_changed)

        self.clear_btn = QPushButton(tr("Clear Logs"))
        self.clear_btn.clicked.connect(self.clear_logs)

        header_layout.addWidget(self.level_combo)
        header_layout.addStretch()
        header_layout.addWidget(self.clear_btn)

        # Text display
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        # Limit the number of lines to avoid memory/performance issues
        self.text_edit.document().setMaximumBlockCount(1000)

        layout.addLayout(header_layout)
        layout.addWidget(self.text_edit)

        # Bottom buttons
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        self.close_btn = QPushButton(tr("Close"))
        self.close_btn.clicked.connect(self.hide)

        bottom_layout.addWidget(self.close_btn)
        layout.addLayout(bottom_layout)

    def _on_level_changed(self, index):
        self.current_level = self.level_combo.itemData(index)
        self._refresh_display()

    def _refresh_display(self):
        """Redraws the log based on the current filter level"""
        self.text_edit.clear()
        for msg, level in self.all_logs:
            if level >= self.current_level:
                self._append_formatted(msg, level)

    def append_log(self, msg: str, level: int):
        """Append log to memory, and to UI if it meets the filter criteria."""
        # Store in memory (limit to 1000 items here as well)
        self.all_logs.append((msg, level))
        if len(self.all_logs) > 1000:
            self.all_logs.pop(0)

        # If it matches current filter, append to plain text edit
        if level >= self.current_level:
            self._append_formatted(msg, level)

    def _append_formatted(self, msg: str, level: int):
        # Determine color based on log level
        color = None
        if level >= logging.ERROR:
            color = "red"
        elif level >= logging.WARNING:
            color = "#FF8C00"  # DarkOrange: visible on both backgrounds
        elif level <= logging.DEBUG:
            color = "gray"

        # Escape HTML special characters and handle newlines for HTML display
        msg_escaped = html.escape(msg).replace("\n", "<br>")

        if color:
            html_msg = f'<span style="color: {color};">{msg_escaped}</span>'
        else:
            # Use default palette text color for INFO and other standard levels
            html_msg = msg_escaped

        self.text_edit.appendHtml(html_msg)

    def clear_logs(self):
        self.text_edit.clear()
        self.all_logs.clear()

    @classmethod
    def attach_to_logger(cls, root_logger: logging.Logger):
        """Instantiates the QtLogHandler and attaches its signal to the global dialog instance."""
        dialog = cls.get_instance()
        handler = QtLogHandler()
        handler.signals.log_emitted.connect(dialog.append_log)
        root_logger.addHandler(handler)
        # Ensure the handler processes everything
        handler.setLevel(logging.DEBUG)
        return handler

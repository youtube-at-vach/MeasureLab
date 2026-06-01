import os
import re
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.localization import tr
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
from src.core.comparison_manager import ComparisonManager


class IndependentWindow(QMainWindow):
    """
    A separate window to hold the detached widget.
    Emits a signal when closed so the widget can be reclaimed.
    """

    closed = pyqtSignal()
    toggle_compact_requested = pyqtSignal()
    reattach_requested = pyqtSignal()

    def __init__(self, title, widget, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 600)
        self.setCentralWidget(widget)
        self.content_widget = widget

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()

    def keyPressEvent(self, event):
        # 'C' key toggles compact mode
        if event.key() == Qt.Key.Key_C:
            self.toggle_compact_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        # Prevent context menu from blocking plot interactions (e.g., pyqtgraph zoom/pan)
        target_widget = self.childAt(event.pos())
        is_plot = False
        curr = target_widget
        while curr is not None:
            class_name = curr.__class__.__name__
            module_name = curr.__class__.__module__
            if "pyqtgraph" in module_name or "PlotWidget" in class_name or "GraphicsLayoutWidget" in class_name:
                is_plot = True
                break
            curr = curr.parentWidget()

        if is_plot:
            event.ignore()
            return

        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction

        menu = QMenu(self)

        is_compactable = isinstance(self.content_widget, CompactableWidgetInterface) or hasattr(
            self.content_widget, "set_compact_mode"
        )
        if is_compactable:
            is_compact = getattr(self.content_widget, "is_compact_mode", lambda: False)()
            toggle_action = QAction(tr("Toggle Compact Mode"), self)
            toggle_action.setCheckable(True)
            toggle_action.setChecked(is_compact)
            toggle_action.triggered.connect(self.toggle_compact_requested.emit)
            menu.addAction(toggle_action)

        reattach_action = QAction(tr("Reattach"), self)
        reattach_action.triggered.connect(self.reattach_requested.emit)
        menu.addAction(reattach_action)

        menu.exec(event.globalPos())


class DetachableWidgetWrapper(QWidget):
    """
    Wraps a widget to allow it to be detached into a separate window.
    Supports compact mode if the content widget implements CompactableWidgetInterface.
    """

    def __init__(self, widget: QWidget, title: str, config_manager=None):
        super().__init__()
        self.content_widget = widget
        self.title = title
        self.config_manager = config_manager
        self.is_detached = False
        self.independent_window = None

        # Check if the content widget supports compact mode
        self.is_compactable = isinstance(widget, CompactableWidgetInterface) or hasattr(widget, "set_compact_mode")

        # Check if the content widget supports plot comparison
        self.is_comparable = isinstance(widget, ComparableWidgetInterface) or hasattr(widget, "get_comparable_data")

        self.init_ui()

        # Theme handling
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())

    def apply_theme(self, theme_name=None):
        if not theme_name and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_current_theme()

        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        if theme_name == "dark":
            self.title_label.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        else:
            self.title_label.setStyleSheet("color: black; font-weight: bold; font-size: 14px;")

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # --- Header ---
        self.header = QWidget()
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(5, 5, 5, 5)

        self.title_label = QLabel(self.title)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.detach_btn = QPushButton(tr("Detach Window"))
        self.detach_btn.clicked.connect(self.toggle_detach)
        self.detach_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.screenshot_btn = QPushButton(tr("Screenshot"))
        self.screenshot_btn.clicked.connect(self.save_screenshot)
        self.screenshot_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.logs_btn = QPushButton(tr("Logs"))
        self.logs_btn.clicked.connect(self.show_logs)
        self.logs_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.compact_btn = None
        if self.is_compactable:
            self.compact_btn = QPushButton(tr("Compact"))
            self.compact_btn.setCheckable(True)
            self.compact_btn.clicked.connect(self.toggle_compact)
            self.compact_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            self.compact_btn.setEnabled(False)

        self.compare_btn = None
        if self.is_comparable:
            self.compare_btn = QPushButton(tr("Send to Comparer"))
            self.compare_btn.clicked.connect(self.send_to_comparer)
            self.compare_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.logs_btn)
        header_layout.addWidget(self.screenshot_btn)
        if self.compare_btn:
            header_layout.addWidget(self.compare_btn)
        if self.compact_btn:
            header_layout.addWidget(self.compact_btn)
        header_layout.addWidget(self.detach_btn)

        self.layout.addWidget(self.header)

        # --- Content Container ---
        self.content_container = QWidget()
        self.content_container_layout = QVBoxLayout(self.content_container)
        self.content_container_layout.setContentsMargins(0, 0, 0, 0)

        # Perform initial attachment
        self.content_container_layout.addWidget(self.content_widget)
        self.layout.addWidget(self.content_container)

        # --- Placeholder (shown when detached) ---
        self.placeholder_widget = QWidget()
        placeholder_layout = QVBoxLayout(self.placeholder_widget)

        info_label = QLabel(tr("Widget is detached in a separate window."))
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        reattach_btn = QPushButton(tr("Reattach"))
        reattach_btn.clicked.connect(self.reattach)
        reattach_btn.setFixedSize(150, 40)

        placeholder_layout.addStretch()
        placeholder_layout.addWidget(info_label, alignment=Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(reattach_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addStretch()

        self.placeholder_widget.hide()
        self.layout.addWidget(self.placeholder_widget)

    def _get_screenshot_output_dir(self) -> str:
        if self.config_manager is None:
            return "screenshots"
        getter = getattr(self.config_manager, "get_screenshot_output_dir", None)
        if callable(getter):
            try:
                return str(getter())
            except Exception:
                return "screenshots"
        return "screenshots"

    def _safe_base_filename(self, text: str) -> str:
        text = (text or "widget").strip()
        text = re.sub(r"\s+", "_", text)
        text = re.sub(r"[^A-Za-z0-9_\-\.\(\)\[\]]+", "_", text)
        text = text.strip("._ ")
        return text or "widget"

    def _next_available_filepath(self, directory: str, base_name: str, ext: str) -> str:
        base = os.path.join(directory, f"{base_name}.{ext}")
        if not os.path.exists(base):
            return base
        for i in range(1, 1000):
            candidate = os.path.join(directory, f"{base_name}_{i:03d}.{ext}")
            if not os.path.exists(candidate):
                return candidate
        return base

    def save_screenshot(self):
        out_dir = self._get_screenshot_output_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), tr("Failed to create output folder: {0}").format(str(e)))
            return

        try:
            pixmap = self.content_widget.grab()
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), tr("Failed to capture screenshot: {0}").format(str(e)))
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        base_name = self._safe_base_filename(f"{self.title}_{timestamp}")
        path = self._next_available_filepath(out_dir, base_name, "png")

        ok = False
        try:
            ok = bool(pixmap.save(path, "PNG"))
        except Exception:
            ok = False

        if not ok:
            QMessageBox.warning(self, tr("Error"), tr("Failed to save screenshot."))
            return

        QMessageBox.information(self, tr("Success"), tr("Screenshot saved to: {0}").format(path))

    def show_logs(self):
        try:
            from src.gui.widgets.log_viewer import LogViewerWindow

            viewer = LogViewerWindow.get_instance()
            viewer.show()
            viewer.raise_()
            viewer.activateWindow()
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), tr("Failed to open log viewer: {0}").format(str(e)))

    def toggle_compact(self, checked):
        if not self.is_compactable:
            return

        self.content_widget.set_compact_mode(checked)

        if self.compact_btn:
            self.compact_btn.blockSignals(True)
            self.compact_btn.setChecked(checked)
            self.compact_btn.setText(tr("Full Mode") if checked else tr("Compact"))
            self.compact_btn.blockSignals(False)

    def toggle_compact_from_window(self):
        if not self.is_compactable:
            return
        current_state = self.content_widget.is_compact_mode()
        self.toggle_compact(not current_state)

    def toggle_detach(self):
        if self.is_detached:
            self.reattach()
        else:
            self.detach()

    def detach(self):
        if self.is_detached:
            return

        # 1. Remove widget from local layout
        self.content_container_layout.removeWidget(self.content_widget)
        # Ensure it's not hidden (removeWidget sometimes hides it?)
        self.content_widget.setParent(None)
        self.content_widget.show()

        # 2. Create independent window
        self.independent_window = IndependentWindow(self.title, self.content_widget, self)
        self.independent_window.closed.connect(self.reattach)
        self.independent_window.toggle_compact_requested.connect(self.toggle_compact_from_window)
        self.independent_window.reattach_requested.connect(self.reattach)
        self.independent_window.show()

        # 3. Update UI state
        self.content_container.hide()
        self.placeholder_widget.show()
        self.detach_btn.setText(tr("Reattach"))
        self.detach_btn.setEnabled(False)  # Use the big reattach button in placeholder or window close
        if self.compact_btn:
            self.compact_btn.setEnabled(True)
        self.is_detached = True

    def reattach(self):
        if not self.is_detached:
            return

        # 1. Close external window if open
        if self.independent_window:
            # Disconnect signal to avoid recursion if we called close() manually
            try:
                self.independent_window.closed.disconnect(self.reattach)
            except TypeError:
                pass  # Already disconnected

            # If the window is still visible, close it
            if self.independent_window.isVisible():
                self.independent_window.close()

            # Reparent widget back to us
            # Note: IndependentWindow.setCentralWidget gave ownership to the window.
            # When we reparent here, we take it back.
            self.content_widget.setParent(self.content_container)
            self.content_container_layout.addWidget(self.content_widget)

            # Explicitly delete the window to ensure clean C++ destruction in Qt
            self.independent_window.deleteLater()
            self.independent_window = None

        # 2. Update UI state
        self.placeholder_widget.hide()
        self.content_container.show()

        self.detach_btn.setText(tr("Detach Window"))
        self.detach_btn.setEnabled(True)
        if self.compact_btn:
            self.toggle_compact(False)
            self.compact_btn.setEnabled(False)
        self.is_detached = False

    def send_to_comparer(self):
        if not self.is_comparable:
            return
        try:
            traces = self.content_widget.get_comparable_data()
            if not traces:
                QMessageBox.warning(self, tr("Compare"), tr("No data available to compare."))
                return

            manager = ComparisonManager.instance()
            for trace in traces:
                manager.add_trace(trace)

            QMessageBox.information(
                self,
                tr("Compare"),
                tr("Successfully sent {0} traces to Plot Comparer.").format(len(traces)),
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).error("Failed to send data to comparer", exc_info=True)
            QMessageBox.critical(
                self,
                tr("Error"),
                tr("Failed to send data to comparer: {0}").format(str(e)),
            )

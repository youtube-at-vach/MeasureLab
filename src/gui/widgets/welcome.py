import os

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.constants import RELEASE_PAGE_URL_TEMPLATE
from src.core.localization import tr
from src.core.update_checker import UpdateChecker
from src.core.utils import resource_path
from src.core.version import __version__
from src.gui.styles import shell_style


class _PageButton(QPushButton):
    """Let wrapped title/description labels determine the button's geometry."""

    def sizeHint(self):
        return self.layout().totalSizeHint()

    def minimumSizeHint(self):
        return self.layout().totalMinimumSize()


class WelcomeWidget(QWidget):
    page_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setStyleSheet(shell_style(self.palette()))
        self.init_ui()
        # Delay the update check to ensure the UI renders first
        QTimer.singleShot(1000, self.start_update_check)

    def start_update_check(self):
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(self.on_update_available)
        self.update_checker.start()

    def on_update_available(self, new_version):
        self.update_label.setText(tr("⬆︎Update available: {0}").format(new_version))
        self.update_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_label.show()
        self.new_version_url = RELEASE_PAGE_URL_TEMPLATE.format(tag=new_version)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(20)
        layout.addStretch(1)
        header = QHBoxLayout()
        header.setSpacing(24)
        header.addWidget(self._create_image_section())
        introduction = QVBoxLayout()
        introduction.setSpacing(10)
        title = QLabel("MeasureLab")
        font = title.font()
        font.setPointSize(26)
        font.setBold(True)
        title.setFont(font)
        introduction.addWidget(title)
        desc = QLabel(
            tr(
                "A comprehensive set of tools for precision audio analysis and measurement.\nSelect a module from the sidebar to begin."
            )
        )
        desc.setWordWrap(True)
        desc.setProperty("shellSecondary", True)
        introduction.addWidget(desc)
        header.addLayout(introduction, 1)
        layout.addLayout(header)
        layout.addWidget(self._create_text_section())
        recent_heading = QLabel(tr("Recently opened"))
        recent_heading.setProperty("shellSecondary", True)
        layout.addWidget(recent_heading)
        self.recent_container = QWidget()
        self.recent_layout = QGridLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(8)
        self.recent_layout.setColumnStretch(0, 1)
        self.recent_layout.setColumnStretch(1, 1)
        layout.addWidget(self.recent_container)
        self.set_recent_modules([])
        layout.addStretch(2)
        self.update_label = QLabel()
        self.update_label.setTextFormat(Qt.TextFormat.PlainText)
        self.update_label.setStyleSheet("color: palette(link); font-weight: bold;")
        self.update_label.hide()
        self.update_label.mousePressEvent = self.open_release_page
        layout.addWidget(self.update_label)
        version_label = QLabel(tr("Version {0}").format(__version__))
        version_label.setProperty("shellSecondary", True)
        layout.addWidget(version_label)

    def _create_image_section(self) -> QLabel:
        image_label = QLabel()
        assets_path = resource_path("src/assets/welcome.png")

        if not os.path.exists(assets_path):
            assets_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "welcome.png"
            )

        if os.path.exists(assets_path):
            pixmap = QPixmap(assets_path)
            scaled_pixmap = pixmap.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        else:
            image_label.setText(tr("Welcome Image Not Found"))
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        return image_label

    def _page_button(self, key, description=None):
        button = _PageButton()
        button.setProperty("welcomeCard", True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName(tr(key))
        content = QVBoxLayout(button)
        content.setContentsMargins(14, 12, 14, 12)
        content.setSpacing(5)
        title = QLabel(tr(key))
        title.setWordWrap(True)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        content.addWidget(title)
        if description:
            detail = QLabel(description)
            detail.setWordWrap(True)
            detail.setProperty("shellSecondary", True)
            detail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            content.addWidget(detail)
            title.setStyleSheet("font-weight: bold;")
            button.setAccessibleDescription(description)
        button.clicked.connect(lambda checked=False: self.page_requested.emit(key))
        return button

    def _create_text_section(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        setup = QLabel(tr("1. Set up your audio"))
        setup.setStyleSheet("font-weight: bold;")
        grid.addWidget(setup, 0, 0, 1, 2)
        grid.addWidget(self._page_button("Settings", tr("Choose your input and output devices.")), 1, 0)
        grid.addWidget(self._page_button("Remote Audio I/O", tr("Use audio from another MeasureLab computer.")), 1, 1)
        tools = QLabel(tr("2. Choose what to measure"))
        tools.setStyleSheet("font-weight: bold;")
        grid.setRowMinimumHeight(2, 12)
        grid.addWidget(tools, 3, 0, 1, 2)
        pages = [
            ("Signal Generator", tr("Generate a test tone.")),
            ("Spectrum Analyzer", tr("See which frequencies are present.")),
            ("Oscilloscope", tr("Inspect the waveform over time.")),
            ("Distortion Analyzer", tr("Measure harmonic distortion.")),
        ]
        for index, (key, description) in enumerate(pages):
            grid.addWidget(self._page_button(key, description), 4 + index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return container

    def set_recent_modules(self, keys):
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        if not keys:
            empty = QLabel(tr("Modules you open will appear here."))
            empty.setWordWrap(True)
            empty.setProperty("shellSecondary", True)
            self.recent_layout.addWidget(empty, 0, 0, 1, 2)
        for index, key in enumerate(keys[:4]):
            self.recent_layout.addWidget(self._page_button(key), index // 2, index % 2)

    def open_release_page(self, event):
        if hasattr(self, "new_version_url"):
            QDesktopServices.openUrl(QUrl(self.new_version_url))

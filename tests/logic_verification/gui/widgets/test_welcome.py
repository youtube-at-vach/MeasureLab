from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt
from unittest.mock import patch

from src.gui.widgets.welcome import WelcomeWidget
from src.core.version import __version__
from src.core.constants import RELEASE_PAGE_URL_TEMPLATE
from src.core.localization import tr


def test_welcome_widget_instantiation(qtbot):
    """Test that WelcomeWidget can be instantiated correctly."""
    with patch("src.gui.widgets.welcome.QTimer.singleShot") as mock_timer:
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

        # Verify the delayed update check was scheduled
        mock_timer.assert_called_once_with(1000, widget.start_update_check)

        assert widget is not None
        assert isinstance(widget.layout(), QVBoxLayout)


def test_welcome_widget_layout_content(qtbot):
    """Test that the layout contains the expected text elements."""
    with patch("src.gui.widgets.welcome.QTimer.singleShot"):
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

        labels = widget.findChildren(QLabel)
        texts = [label.text() for label in labels]

        # Check for expected texts
        assert "MeasureLab" in texts

        # Verify version label
        version_str = tr("Version {0}").format(__version__)
        assert version_str in texts

        # Shortcuts request navigation; they do not start any instrument.
        buttons = {button.accessibleName(): button for button in widget.findChildren(QPushButton)}
        for key in (
            "Settings",
            "Remote Audio I/O",
            "Signal Generator",
            "Spectrum Analyzer",
            "Oscilloscope",
            "Distortion Analyzer",
        ):
            with qtbot.waitSignal(widget.page_requested) as signal:
                buttons[tr(key)].click()
            assert signal.args == [key]


def test_welcome_widget_on_update_available(qtbot):
    """Test the behavior when an update is available."""
    with patch("src.gui.widgets.welcome.QTimer.singleShot"):
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

        # Initially hidden
        assert widget.update_label.isHidden()

        # Simulate an update being available
        new_version = "v1.2.3"
        widget.on_update_available(new_version)

        # Should be visible now
        assert not widget.update_label.isHidden()
        expected_text = tr("⬆︎Update available: {0}").format(new_version)
        assert widget.update_label.text() == expected_text
        assert widget.update_label.cursor().shape() == Qt.CursorShape.PointingHandCursor
        assert widget.new_version_url == RELEASE_PAGE_URL_TEMPLATE.format(tag=new_version)


def test_welcome_widget_open_release_page(qtbot):
    """Test clicking the update label opens the release page."""
    with patch("src.gui.widgets.welcome.QTimer.singleShot"):
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

        new_version = "v1.2.3"
        widget.on_update_available(new_version)

        with patch("src.gui.widgets.welcome.QDesktopServices.openUrl") as mock_open_url:
            widget.open_release_page(None)

            # Since QUrl equals isn't always trivial in mocks, we can check the URL string
            mock_open_url.assert_called_once()
            url_arg = mock_open_url.call_args[0][0]
            assert url_arg.toString() == RELEASE_PAGE_URL_TEMPLATE.format(tag=new_version)


def test_welcome_widget_start_update_check(qtbot):
    """Test starting the update check."""
    with patch("src.gui.widgets.welcome.QTimer.singleShot"):
        with patch("src.gui.widgets.welcome.UpdateChecker") as MockUpdateChecker:
            widget = WelcomeWidget()
            qtbot.addWidget(widget)

            mock_checker_instance = MockUpdateChecker.return_value

            widget.start_update_check()

            # Check if UpdateChecker was instantiated
            MockUpdateChecker.assert_called_once()

            # Verify the signal was connected (mock check)
            mock_checker_instance.update_available.connect.assert_called_once_with(widget.on_update_available)

            # Verify it was started
            mock_checker_instance.start.assert_called_once()


def test_recent_shortcuts_replaced_and_navigate(qtbot):
    with patch("src.gui.widgets.welcome.QTimer.singleShot"):
        widget = WelcomeWidget()
        qtbot.addWidget(widget)
        widget.set_recent_modules(["Spectrogram", "Signal Generator"])
        widget.resize(780, 660)
        widget.show()
        qtbot.waitUntil(widget.isVisible)
        buttons = widget.recent_container.findChildren(QPushButton)
        for button in widget.findChildren(QPushButton):
            if button.isVisible():
                for label in button.findChildren(QLabel):
                    assert label.height() > 0
                    assert button.rect().contains(label.geometry())
        with qtbot.waitSignal(widget.page_requested) as signal:
            buttons[0].click()
        assert signal.args == ["Spectrogram"]
        widget.set_recent_modules([])
        assert widget.recent_layout.count() == 1

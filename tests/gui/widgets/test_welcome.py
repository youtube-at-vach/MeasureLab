from PyQt6.QtWidgets import QLabel, QVBoxLayout
from PyQt6.QtCore import Qt
from unittest.mock import patch

from src.gui.widgets.welcome import WelcomeWidget
from src.core.version import __version__
from src.core.constants import RELEASE_PAGE_URL_TEMPLATE
from src.core.localization import tr

def test_welcome_widget_instantiation(qtbot):
    """Test that WelcomeWidget can be instantiated correctly."""
    with patch('src.gui.widgets.welcome.QTimer.singleShot') as mock_timer:
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

        # Verify the delayed update check was scheduled
        mock_timer.assert_called_once_with(1000, widget.start_update_check)

        assert widget is not None
        assert isinstance(widget.layout(), QVBoxLayout)
        assert widget.layout().count() == 2 # image section and text section

def test_welcome_widget_layout_content(qtbot):
    """Test that the layout contains the expected text elements."""
    with patch('src.gui.widgets.welcome.QTimer.singleShot'):
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

        labels = widget.findChildren(QLabel)
        texts = [label.text() for label in labels]

        # Check for expected texts
        assert "MeasureLab" in texts

        # Verify version label
        version_str = tr("Version {0}").format(__version__)
        assert version_str in texts

        # Verify features are listed
        features_str = " • ".join([
            tr("Signal Generator"),
            tr("Spectrum Analyzer"),
            tr("Distortion Analyzer"),
            tr("Network Analyzer"),
            tr("Oscilloscope"),
            tr("Lock-in Amplifier"),
            tr("Frequency Counter"),
            tr("Spectrogram"),
        ])
        assert features_str in texts

def test_welcome_widget_on_update_available(qtbot):
    """Test the behavior when an update is available."""
    with patch('src.gui.widgets.welcome.QTimer.singleShot'):
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
    with patch('src.gui.widgets.welcome.QTimer.singleShot'):
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

        new_version = "v1.2.3"
        widget.on_update_available(new_version)

        with patch('src.gui.widgets.welcome.QDesktopServices.openUrl') as mock_open_url:
            widget.open_release_page(None)

            # Since QUrl equals isn't always trivial in mocks, we can check the URL string
            mock_open_url.assert_called_once()
            url_arg = mock_open_url.call_args[0][0]
            assert url_arg.toString() == RELEASE_PAGE_URL_TEMPLATE.format(tag=new_version)

def test_welcome_widget_start_update_check(qtbot):
    """Test starting the update check."""
    with patch('src.gui.widgets.welcome.QTimer.singleShot'):
        with patch('src.gui.widgets.welcome.UpdateChecker') as MockUpdateChecker:
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

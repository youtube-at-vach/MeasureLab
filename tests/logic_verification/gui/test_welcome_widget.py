import sys
import os
from unittest.mock import patch
import pytest
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap

# Ensure src is in path
sys.path.insert(0, os.getcwd())

from src.gui.widgets.welcome import WelcomeWidget


@pytest.fixture
def mock_dependencies():
    with (
        patch("src.gui.widgets.welcome.resource_path") as mock_rp,
        patch("src.gui.widgets.welcome.os.path.exists") as mock_exists,
        patch("src.gui.widgets.welcome.QPixmap") as mock_pixmap,
        patch("src.gui.widgets.welcome.QTimer") as mock_timer,
        patch("src.gui.widgets.welcome.UpdateChecker"),
    ):
        # Setup QPixmap mock to return a REAL QPixmap via side_effect
        # This prevents TypeError in QLabel.setPixmap

        # Keep track of original QPixmap
        OriginalQPixmap = QPixmap

        def create_pixmap(*args, **kwargs):
            # Create a real pixmap so scaledToHeight returns a real pixmap
            # and setPixmap doesn't complain about types.
            p = OriginalQPixmap()
            # We can still mock scaledToHeight if we want to trace it,
            # but it's simpler to just let it be a real empty QPixmap.
            return p

        mock_pixmap.side_effect = create_pixmap

        yield mock_rp, mock_exists, mock_pixmap, mock_timer


def test_welcome_image_primary_path(qtbot, mock_dependencies):
    mock_rp, mock_exists, mock_pixmap, mock_timer = mock_dependencies

    # Setup happy path
    primary_path = "/path/to/assets/welcome.png"
    mock_rp.return_value = primary_path

    # os.path.exists behavior
    def exists_side_effect(path):
        return path == primary_path

    mock_exists.side_effect = exists_side_effect

    widget = WelcomeWidget()
    qtbot.addWidget(widget)

    # Verify QPixmap called with primary path
    mock_pixmap.assert_called_with(primary_path)

    # Verify image label has pixmap set
    labels = widget.findChildren(QLabel)
    found_pixmap = False
    for lbl in labels:
        if lbl.pixmap() is not None:
            found_pixmap = True
            break
    assert found_pixmap


def test_welcome_image_fallback_path(qtbot, mock_dependencies):
    mock_rp, mock_exists, mock_pixmap, mock_timer = mock_dependencies

    primary_path = "/path/to/assets/welcome.png"
    mock_rp.return_value = primary_path

    import src.gui.widgets.welcome

    expected_fallback_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(src.gui.widgets.welcome.__file__))), "assets", "welcome.png"
    )

    # mimic fallback path
    def exists_side_effect(path):
        if path == primary_path:
            return False
        if path == expected_fallback_path:
            return True
        return False

    mock_exists.side_effect = exists_side_effect

    widget = WelcomeWidget()
    qtbot.addWidget(widget)

    # Verify QPixmap called with fallback path
    assert mock_pixmap.call_count == 1
    args, _ = mock_pixmap.call_args
    assert args[0] == expected_fallback_path

    # Verify image label has pixmap set
    labels = widget.findChildren(QLabel)
    found_pixmap = False
    for lbl in labels:
        if lbl.pixmap() is not None:
            found_pixmap = True
            break
    assert found_pixmap


def test_welcome_image_not_found(qtbot, mock_dependencies):
    mock_rp, mock_exists, mock_pixmap, mock_timer = mock_dependencies

    mock_rp.return_value = "/invalid/path"
    mock_exists.return_value = False

    # We need to mock 'tr' specifically for this test to match the original file
    with patch("src.gui.widgets.welcome.tr", return_value="Welcome Image Not Found"):
        widget = WelcomeWidget()
        qtbot.addWidget(widget)

    mock_pixmap.assert_not_called()

    # Verify text "Welcome Image Not Found"
    labels = widget.findChildren(QLabel)
    found = False
    for lbl in labels:
        if "Welcome Image Not Found" in lbl.text():
            found = True
            break
    assert found

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
    with patch('src.gui.widgets.welcome.resource_path') as mock_rp, \
         patch('src.gui.widgets.welcome.os.path.exists') as mock_exists, \
         patch('src.gui.widgets.welcome.QPixmap') as mock_pixmap, \
         patch('src.gui.widgets.welcome.QTimer') as mock_timer, \
         patch('src.gui.widgets.welcome.UpdateChecker'):

        # Setup QPixmap mock to return a REAL QPixmap via side_effect
        # This prevents TypeError in QLabel.setPixmap
        mock_pixmap.side_effect = lambda *args: QPixmap()

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
        # Since we mocked QPixmap, lbl.pixmap() returns the mock if set
        if lbl.pixmap() is not None:
             found_pixmap = True
             break
    assert found_pixmap

def test_welcome_image_fallback_path(qtbot, mock_dependencies):
    mock_rp, mock_exists, mock_pixmap, mock_timer = mock_dependencies

    primary_path = "/path/to/assets/welcome.png"
    mock_rp.return_value = primary_path

    # mimic fallback path
    def exists_side_effect(path):
        if path == primary_path:
            return False
        if "assets" in path and "welcome.png" in path: # Fallback path
            return True
        return False

    mock_exists.side_effect = exists_side_effect

    widget = WelcomeWidget()
    qtbot.addWidget(widget)

    # Verify QPixmap called with fallback path
    # Fallback path is calculated relative to __file__, so it's system dependent
    # But we can verify it's NOT primary path
    assert mock_pixmap.call_count == 1
    args, _ = mock_pixmap.call_args
    assert args[0] != primary_path
    assert "welcome.png" in args[0]

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

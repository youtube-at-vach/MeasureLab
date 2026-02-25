
from PyQt6.QtCore import Qt
from src.gui.widgets.welcome import WelcomeWidget

def test_update_label_prevents_xss(qtbot):
    """
    Verify that the update label is configured to render text as PlainText
    to prevent XSS via malicious version strings (e.g., HTML injection).
    """
    # Instantiate the widget
    widget = WelcomeWidget()
    qtbot.addWidget(widget)

    # Check the text format of the update label.
    # By default, QLabel.textFormat() is Qt.TextFormat.AutoText (0), which is vulnerable to XSS.
    # We require it to be Qt.TextFormat.PlainText (1).
    assert widget.update_label.textFormat() == Qt.TextFormat.PlainText, (
        "update_label must be set to PlainText to prevent XSS."
    )

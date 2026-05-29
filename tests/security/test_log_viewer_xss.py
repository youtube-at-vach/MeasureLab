import logging
from src.gui.widgets.log_viewer import LogViewerWindow


def test_log_viewer_prevents_xss(qtbot):
    widget = LogViewerWindow()
    qtbot.addWidget(widget)

    # Test malicious payload
    payload = "<script>alert('XSS')</script>"
    widget.append_log(payload, logging.INFO)

    # Check the actual plain text vs html
    plain_text = widget.text_edit.toPlainText()

    assert payload in plain_text

"""
Common stylesheet definitions for GUI widgets.
"""
import sys

# Toggle Button Styles (Start/Stop)
STYLE_TOGGLE_BTN_DARK = (
    "QPushButton { background-color: #2e7d32; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px; }"
    "QPushButton:checked { background-color: #c62828; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px; }"
    "QPushButton:hover { background-color: #388e3c; }"
    "QPushButton:checked:hover { background-color: #d32f2f; }"
)

STYLE_TOGGLE_BTN_LIGHT = (
    "QPushButton { background-color: #ccffcc; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; }"
    "QPushButton:checked { background-color: #ffcccc; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; }"
    "QPushButton:hover { background-color: #bbfebb; }"
    "QPushButton:checked:hover { background-color: #ffbbbb; }"
)

# Label Styles (Oscilloscope measurements, etc.)
# Dark Theme
STYLE_LABEL_LEFT_CH_DARK = "font-family: monospace; font-weight: bold; color: #00ff00;"
STYLE_LABEL_RIGHT_CH_DARK = "font-family: monospace; font-weight: bold; color: #ff0000;"
STYLE_LABEL_CURSOR_DARK = "font-family: monospace; font-weight: bold; color: yellow;"

# Light Theme
STYLE_LABEL_LEFT_CH_LIGHT = "font-family: monospace; font-weight: bold; color: #008800;"
STYLE_LABEL_RIGHT_CH_LIGHT = "font-family: monospace; font-weight: bold; color: #cc0000;"
STYLE_LABEL_CURSOR_LIGHT = "font-family: monospace; font-weight: bold; color: #888800;"



# Cross-platform Monospace Font Family
# "Monospace" is not a guaranteed family on macOS/Windows Qt.
# We prefer standard fixed-width fonts suitable for each platform.
if sys.platform == "darwin":
    MONOSPACE_FONT_FAMILY = "Menlo, Monaco, Courier New, monospace"
elif sys.platform == "win32":
    MONOSPACE_FONT_FAMILY = "Consolas, Courier New, monospace"
else:
    # Linux and others
    MONOSPACE_FONT_FAMILY = "Monospace, Courier New, monospace"

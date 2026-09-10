"""
Common stylesheet definitions for GUI widgets.
"""

import sys
from typing import Literal

# Cross-platform Monospace Font Family
# "monospace" (lowercase) is the standard CSS generic family name.
# Qt on some platforms warns if "Monospace" (capital M) is used and not found.
if sys.platform == "darwin":
    MONOSPACE_FONT_FAMILY = "Menlo, Monaco, Courier New"
elif sys.platform == "win32":
    MONOSPACE_FONT_FAMILY = "Consolas, Courier New"
else:
    # Linux and others: Use widely available monospace fonts first to avoid Qt font-alias search warnings.
    # Generic "monospace" is appended at the end as a fallback.
    MONOSPACE_FONT_FAMILY = "DejaVu Sans Mono, Liberation Mono, Courier New, monospace, Courier"


# Solid action fills distinguish measurement controls from neutral buttons.
# White text is readable in both themes; disabled controls use the Qt palette.
START_BACKGROUND = "#286443"
START_HOVER = "#31764f"
START_PRESSED = "#1d4e33"
STOP_BACKGROUND = "#7e343d"
STOP_HOVER = "#94434d"
STOP_PRESSED = "#602832"


def button_style(
    role: Literal["primary", "secondary", "stop", "selected"] = "secondary",
    *,
    toggle: bool = False,
    extra: str = "",
) -> str:
    """Shared action colors and states; extra contains only widget geometry/type.

    Primary actions use a green fill so measurement starts are easy to find.
    Selected options use the selection fill; stop/record actions use a muted red. A start/stop toggle
    changes to the stop role when checked, without changing its dimensions.
    Palette references also work for widgets without a theme-change handler.
    """
    background = "palette(highlight)" if role == "selected" else "palette(button)"
    foreground = "palette(highlighted-text)" if role == "selected" else "palette(button-text)"
    border = "palette(highlight)" if role in {"primary", "selected"} else "palette(mid)"
    hover = "palette(highlight)" if role in {"primary", "selected"} else "palette(midlight)"
    hover_text = "palette(highlighted-text)" if role in {"primary", "selected"} else foreground
    pressed = "palette(base)"
    pressed_text = "palette(text)"
    if role == "primary":
        background, hover, pressed = START_BACKGROUND, START_HOVER, START_PRESSED
        foreground = hover_text = pressed_text = "white"
        border = START_HOVER
    elif role == "stop":
        background, hover, pressed = STOP_BACKGROUND, STOP_HOVER, STOP_PRESSED
        foreground = hover_text = pressed_text = "white"
        border = STOP_HOVER
    # A custom border replaces Qt's native button sizing. Restore a usable
    # hit area for actions, including short translated labels such as "開始".
    geometry = "padding: 4px 12px; min-width: 4em;" if role in {"primary", "stop"} else ""
    style = f"""
        QPushButton {{ background-color: {background}; color: {foreground};
            border: 1px solid {border}; border-radius: 4px; {geometry} {extra} }}
        QPushButton:hover {{ background-color: {hover}; color: {hover_text}; }}
        QPushButton:pressed {{ background-color: {pressed}; color: {pressed_text}; }}
    """
    if toggle:
        style += f"""
            QPushButton:checked {{ background-color: {STOP_BACKGROUND}; color: white; border-color: {STOP_HOVER}; }}
            QPushButton:checked:hover {{ background-color: {STOP_HOVER}; }}
            QPushButton:checked:pressed {{ background-color: {STOP_PRESSED}; }}
        """
    return (
        style
        + """
        QPushButton:focus { border-color: palette(link); }
        QPushButton:disabled, QPushButton:checked:disabled {
            background-color: palette(button); color: palette(placeholder-text); border-color: palette(mid);
        }
    """
    )


# Compatibility names for existing theme handlers; colors resolve via QPalette.
STYLE_TOGGLE_BTN_DARK = button_style("primary", toggle=True, extra="padding: 5px;")
STYLE_TOGGLE_BTN_LIGHT = STYLE_TOGGLE_BTN_DARK

# Label Styles (Oscilloscope measurements, etc.)
# Dark Theme
STYLE_LABEL_LEFT_CH_DARK = f"font-family: {MONOSPACE_FONT_FAMILY}; font-weight: bold; color: #00ff00;"
STYLE_LABEL_RIGHT_CH_DARK = f"font-family: {MONOSPACE_FONT_FAMILY}; font-weight: bold; color: #ff0000;"
STYLE_LABEL_CURSOR_DARK = f"font-family: {MONOSPACE_FONT_FAMILY}; font-weight: bold; color: yellow;"

# Light Theme
STYLE_LABEL_LEFT_CH_LIGHT = f"font-family: {MONOSPACE_FONT_FAMILY}; font-weight: bold; color: #008800;"
STYLE_LABEL_RIGHT_CH_LIGHT = f"font-family: {MONOSPACE_FONT_FAMILY}; font-weight: bold; color: #cc0000;"
STYLE_LABEL_CURSOR_LIGHT = f"font-family: {MONOSPACE_FONT_FAMILY}; font-weight: bold; color: #888800;"

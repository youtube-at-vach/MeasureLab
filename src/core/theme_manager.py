"""
Theme Manager for Qt6 Application

Provides theme detection and switching functionality with support for:
- System theme detection (Qt 6.5+)
- Light/Dark/System theme modes
- Dynamic theme switching with QPalette
"""

import logging
import platform
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory


class ThemeManager(QObject):
    """Manages application theme and color scheme."""

    # Signal emitted when theme changes
    theme_changed = pyqtSignal(str)  # theme_name: 'light', 'dark', 'system'

    def __init__(self, app: QApplication, config_manager=None):
        super().__init__()
        self.app = app
        self.config_manager = config_manager
        self.logger = logging.getLogger(self.__class__.__name__)
        self.current_theme = "system"
        self._original_stylesheet = self.app.styleSheet()

        # Cache original style so we can restore it when leaving dark theme.
        style = self.app.style()
        self._original_style_name = style.objectName() if style is not None else None

        # Cache available styles to avoid repeated queries
        self._available_styles: dict[str, str] = {k.casefold(): k for k in QStyleFactory.keys()}

        # Check if Qt supports colorScheme (Qt 6.5+)
        style_hints = self.app.styleHints()
        self.supports_color_scheme = style_hints is not None and hasattr(style_hints, "colorScheme")

        if self.supports_color_scheme and style_hints is not None:
            # Connect to system theme changes
            try:
                style_hints.colorSchemeChanged.connect(self._on_system_theme_changed)
                self.logger.debug("System theme change detection enabled (Qt 6.5+)")
            except AttributeError:
                self.logger.warning("colorSchemeChanged signal not available")

    def set_theme(self, theme_name: str):
        """
        Set application theme.

        Args:
            theme_name: One of 'system', 'light', 'dark'
        """
        if theme_name not in {"system", "light", "dark"}:
            self.logger.error(f"Invalid theme name: {theme_name}")
            return

        self.current_theme = theme_name
        self.logger.debug(f"Setting theme to: {theme_name}")

        if theme_name == "system":
            self._apply_system_theme()
        elif theme_name == "light":
            self._apply_light_theme()
        elif theme_name == "dark":
            self._apply_dark_theme()

        self.theme_changed.emit(theme_name)

    def get_current_theme(self) -> str:
        """
        Returns the currently active theme ('dark' or 'light').
        If the setting is 'system', it resolves to the actual system theme.
        """
        if self.config_manager is not None:
            theme_setting = self.config_manager.get_theme()
            if theme_setting == "system":
                return self._detect_system_theme()
            return theme_setting

        # Fallback if no config_manager is provided (e.g. legacy/testing)
        return self.current_theme

    def get_effective_theme(self) -> str:
        """
        Returns the effective theme ('light' or 'dark').
        If current_theme is 'system', detects the system theme.
        """
        if self.current_theme == "system":
            return self._detect_system_theme()
        return self.current_theme

    def _on_system_theme_changed(self, scheme):
        """Handle system theme change (Qt 6.5+ only)."""
        if self.current_theme == "system":
            self.logger.debug(f"System theme changed to: {scheme}")
            self._apply_system_theme()
            self.theme_changed.emit("system")

    def dispose(self) -> None:
        """Disconnect from application-owned signals before the manager is discarded."""
        if not self.supports_color_scheme:
            return

        style_hints = self.app.styleHints()
        if style_hints is None:
            return

        try:
            style_hints.colorSchemeChanged.disconnect(self._on_system_theme_changed)
        except (AttributeError, TypeError, RuntimeError):
            # The signal may already be unavailable or disconnected during Qt shutdown.
            pass

    def _detect_system_theme(self) -> str:
        """
        Detect system theme.

        Returns:
            'light' or 'dark'
        """
        style_hints = self.app.styleHints()
        if self.supports_color_scheme and style_hints is not None:
            try:
                from PyQt6.QtCore import Qt

                scheme = style_hints.colorScheme()

                # Qt.ColorScheme.Dark = 2, Qt.ColorScheme.Light = 1
                if hasattr(Qt, "ColorScheme"):
                    if scheme == Qt.ColorScheme.Dark:
                        return "dark"
                    elif scheme == Qt.ColorScheme.Light:
                        return "light"
                else:
                    # Fallback for different Qt 6.5 versions
                    raw_scheme: Any = scheme
                    scheme_val_obj = raw_scheme.value if hasattr(raw_scheme, "value") else raw_scheme
                    scheme_val = scheme_val_obj if isinstance(scheme_val_obj, int) else -1

                    if scheme_val == 2:
                        return "dark"
                    elif scheme_val == 1:
                        return "light"
            except Exception as e:
                self.logger.warning(f"Failed to detect system theme: {e}")

        # Fallback: detect from current palette
        palette = self.app.palette()
        bg_color = palette.color(QPalette.ColorRole.Window)
        # If background is dark (low lightness), assume dark theme
        return "dark" if bg_color.lightness() < 128 else "light"

    def _apply_system_theme(self):
        """Apply system theme."""
        detected = self._detect_system_theme()
        self.logger.debug(f"Applying system theme (detected: {detected})")

        if detected == "dark":
            self._apply_dark_theme()
        else:
            self._apply_light_theme()

    def _apply_light_theme(self):
        """Apply light theme palette."""
        # On macOS, we always use Fusion to ensure consistent styling.
        # On Windows, we restore native style for light theme.
        if platform.system().lower() == "darwin":
            self._ensure_fusion_style()
        else:
            self._restore_native_style_if_needed()

        palette = QPalette()

        # Base colors
        palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(35, 38, 41))
        palette.setColor(QPalette.ColorRole.Base, QColor(252, 252, 252))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(245, 245, 245))
        palette.setColor(QPalette.ColorRole.Text, QColor(35, 38, 41))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(90, 90, 90))
        palette.setColor(QPalette.ColorRole.Button, QColor(235, 235, 235))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(35, 38, 41))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))

        # Highlight colors
        palette.setColor(QPalette.ColorRole.Highlight, QColor(48, 103, 151))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(252, 252, 252))

        # Links
        palette.setColor(QPalette.ColorRole.Link, QColor(48, 103, 151))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(127, 0, 127))

        # Tooltips
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(247, 247, 247))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(35, 38, 41))

        # Disabled colors
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(127, 127, 127))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(127, 127, 127))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))

        self.app.setPalette(palette)
        self.app.setStyleSheet(self._original_stylesheet)
        self.logger.debug("Light theme applied")

    def _apply_dark_theme(self):
        """Apply dark theme palette."""
        self._ensure_fusion_style()
        palette = QPalette()

        # Surface hierarchy: recessed fields, shell, panels, raised controls.
        # Keep the black measurement canvases and their trace colors independent
        # of these chrome colors so data remains the strongest visual layer.
        palette.setColor(QPalette.ColorRole.Window, QColor(22, 24, 27))
        palette.setColor(QPalette.ColorRole.Base, QColor(15, 17, 20))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 33, 37))
        palette.setColor(QPalette.ColorRole.Button, QColor(43, 47, 52))

        # Explicit bevel roles prevent native light-palette edges in dark mode.
        palette.setColor(QPalette.ColorRole.Light, QColor(72, 78, 86))
        palette.setColor(QPalette.ColorRole.Midlight, QColor(57, 63, 70))
        palette.setColor(QPalette.ColorRole.Mid, QColor(48, 53, 59))
        palette.setColor(QPalette.ColorRole.Dark, QColor(100, 109, 120))
        palette.setColor(QPalette.ColorRole.Shadow, QColor(6, 8, 10))

        # Retain readable, softened whites and familiar semantic accents.
        palette.setColor(QPalette.ColorRole.WindowText, QColor(226, 228, 230))
        palette.setColor(QPalette.ColorRole.Text, QColor(226, 228, 230))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(226, 228, 230))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(160, 167, 176))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(65, 112, 153))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(252, 252, 252))
        palette.setColor(QPalette.ColorRole.Link, QColor(126, 183, 230))
        palette.setColor(QPalette.ColorRole.LinkVisited, QColor(200, 100, 200))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(43, 47, 52))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(226, 228, 230))

        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(127, 135, 145))

        self.app.setPalette(palette)
        # Keep native control rendering (including checked/mixed indicators).
        # Empty checkboxes need an explicit edge against the darker surfaces.
        # Tabs use flat panel colors instead of Fusion's bright raised fill;
        # a narrow selection edge keeps navigation distinct from action buttons.
        self.app.setStyleSheet(
            self._original_stylesheet
            + """
            QGroupBox { background-color: palette(alternate-base); }
            QTabWidget::pane { background-color: palette(window); border: 1px solid palette(mid); }
            QTabBar::tab {
                background-color: palette(alternate-base);
                color: palette(placeholder-text);
                border: 1px solid palette(mid);
                border-top: 2px solid transparent;
                padding: 5px 10px;
            }
            QTabBar::tab:selected {
                background-color: palette(window);
                color: palette(window-text);
                border-top-color: palette(highlight);
                border-bottom-color: palette(window);
            }
            QTabBar::tab:!selected:hover:enabled {
                background-color: palette(button);
                color: palette(window-text);
            }
            QTabBar::tab:focus:enabled { border-color: palette(link); }
            QTabBar::tab:disabled { color: palette(button-text); }
            QCheckBox::indicator:unchecked {
                border: 1px solid palette(dark);
                border-radius: 2px;
                background-color: palette(base);
            }
            QCheckBox::indicator:unchecked:disabled { border-color: palette(mid); }
            QCheckBox::indicator:unchecked:hover,
            QCheckBox:focus::indicator:unchecked { border-color: palette(link); }
            """
        )
        self.logger.debug("Dark theme applied")

    def _ensure_fusion_style(self) -> None:
        """Force Fusion style on Windows/macOS so custom palettes render consistently."""
        system = platform.system().lower()
        if not (system.startswith("win") or system == "darwin"):
            return

        try:
            style = self.app.style()
            current = style.objectName() if style is not None else ""
        except Exception:
            current = ""

        # Palette-based dark themes are known to behave inconsistently with native Windows styles.
        # Fusion respects QPalette far more predictably.
        if current.casefold() == "fusion":
            return

        # Use cached style key to avoid expensive QStyleFactory.keys() call
        fusion_key = self._available_styles.get("fusion")
        if not fusion_key:
            self.logger.warning("Fusion style not available; cannot stabilize dark palette on Windows")
            return

        self.logger.debug(f"{system} detected: switching style '{current}' -> '{fusion_key}' for dark theme")
        self.app.setStyle(fusion_key)

    def _restore_native_style_if_needed(self) -> None:
        """Restore the original style (Windows only)."""
        system = platform.system().lower()
        if not system.startswith("win"):
            return
        if not self._original_style_name:
            return

        try:
            style = self.app.style()
            current = style.objectName() if style is not None else ""
        except Exception:
            current = ""

        # Only attempt restore if we're currently on Fusion.
        if current.casefold() != "fusion":
            return

        desired = self._available_styles.get(self._original_style_name.casefold())
        if not desired:
            # If the exact original style isn't available, keep Fusion rather than risking a crash.
            return

        self.logger.debug(f"{system} detected: restoring style '{current}' -> '{desired}'")
        self.app.setStyle(desired)

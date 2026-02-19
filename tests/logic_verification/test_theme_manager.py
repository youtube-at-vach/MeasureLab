
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import importlib

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Mock classes to simulate Qt behavior
class MockQObject:
    """Mock for PyQt6.QtCore.QObject."""
    def __init__(self, *args, **kwargs):
        pass

class MockQColor:
    """Mock for PyQt6.QtGui.QColor."""
    def __init__(self, *args):
        self.r = args[0] if len(args) > 0 else 0
        self.g = args[1] if len(args) > 1 else 0
        self.b = args[2] if len(args) > 2 else 0

    def lightness(self):
        # Simple lightness calculation or just return a value
        # For our tests, we can just return a value if we want, or calculate
        return (self.r + self.g + self.b) // 3

class MockQPalette:
    """Mock for PyQt6.QtGui.QPalette."""
    class ColorRole:
        Window = 0
        WindowText = 1
        Base = 2
        AlternateBase = 3
        Text = 4
        Button = 5
        ButtonText = 6
        BrightText = 7
        Highlight = 8
        HighlightedText = 9
        Link = 10
        LinkVisited = 11
        ToolTipBase = 12
        ToolTipText = 13

    class ColorGroup:
        Disabled = 0

    def __init__(self):
        self.colors = {}

    def setColor(self, *args):
        # args can be (role, color) or (group, role, color)
        if len(args) == 2:
            role, color = args
            self.colors[role] = color
        elif len(args) == 3:
            group, role, color = args
            # We can store with group if needed, but for now just storing by role is enough for basic verification
            self.colors[role] = color

    def color(self, role):
        return self.colors.get(role, MockQColor(255, 255, 255)) # Default to light

class TestThemeManager(unittest.TestCase):
    def setUp(self):
        # prepare sys.modules patcher
        self.modules_patcher = patch.dict(sys.modules, {
            'PyQt6.QtCore': MagicMock(),
            'PyQt6.QtGui': MagicMock(),
            'PyQt6.QtWidgets': MagicMock(),
        })
        self.modules_patcher.start()

        # Configure mocks
        self.mock_qt_core = sys.modules['PyQt6.QtCore']
        self.mock_qt_core.QObject = MockQObject
        # pyqtSignal is called at class definition time. We return a Mock that produces another Mock when instantiated.
        # But actually pyqtSignal() returns a descriptor.
        # However, for simple testing, if pyqtSignal() returns a Mock, then ThemeManager.theme_changed will be that Mock.
        # When accessing it on instance, it returns the same Mock.
        # We need it to have .emit() method.
        self.mock_signal_instance = MagicMock()
        self.mock_qt_core.pyqtSignal = MagicMock(return_value=self.mock_signal_instance)

        self.mock_qt_gui = sys.modules['PyQt6.QtGui']
        self.mock_qt_gui.QColor = MockQColor
        self.mock_qt_gui.QPalette = MockQPalette

        self.mock_qt_widgets = sys.modules['PyQt6.QtWidgets']
        self.mock_qt_widgets.QApplication = MagicMock()
        self.mock_qt_widgets.QStyleFactory = MagicMock()
        # Default styles
        self.mock_qt_widgets.QStyleFactory.keys.return_value = ["Fusion", "Windows", "WindowsVista"]

        # Import/Reload module under test
        if 'src.core.theme_manager' in sys.modules:
            importlib.reload(sys.modules['src.core.theme_manager'])
        else:
            importlib.import_module('src.core.theme_manager')

        self.module_under_test = sys.modules['src.core.theme_manager']
        self.ThemeManager = self.module_under_test.ThemeManager

        # Setup common app mock
        self.mock_app = MagicMock()
        # Setup default style hints
        self.mock_style_hints = MagicMock()
        self.mock_style_hints.colorScheme.return_value = 1 # Light
        # Setup supports_color_scheme check: hasattr(style_hints, "colorScheme") needs to be True
        # Since it's a MagicMock, hasattr usually returns True for any attribute access unless configured otherwise.
        self.mock_app.styleHints.return_value = self.mock_style_hints

        # Setup default palette
        self.mock_app.palette.return_value = MockQPalette()

    def tearDown(self):
        self.modules_patcher.stop()
        if 'src.core.theme_manager' in sys.modules:
            del sys.modules['src.core.theme_manager']

    def test_initialization(self):
        tm = self.ThemeManager(self.mock_app)
        self.assertEqual(tm.current_theme, "system")
        self.assertEqual(tm.app, self.mock_app)

    def test_set_theme_light(self):
        tm = self.ThemeManager(self.mock_app)

        # Capture signal emission
        # Since pyqtSignal returns self.mock_signal_instance, accessing tm.theme_changed should return it.
        # Wait, if pyqtSignal returns a Mock, then it is a class attribute.
        # When accessed on instance, it is still that Mock.
        # So we verify calls on self.mock_signal_instance.

        tm.set_theme("light")

        self.assertEqual(tm.current_theme, "light")
        self.mock_signal_instance.emit.assert_called_with("light")

        # Verify palette was set on app
        self.mock_app.setPalette.assert_called()
        # Verify the palette set has light background (checking one color is enough)
        args = self.mock_app.setPalette.call_args[0]
        palette_set = args[0]
        self.assertIsInstance(palette_set, MockQPalette)
        # Check window color is light (240, 240, 240)
        window_color = palette_set.colors[MockQPalette.ColorRole.Window]
        self.assertEqual(window_color.r, 240)

    def test_set_theme_dark(self):
        tm = self.ThemeManager(self.mock_app)

        tm.set_theme("dark")

        self.assertEqual(tm.current_theme, "dark")
        self.mock_signal_instance.emit.assert_called_with("dark")

        # Verify palette was set on app
        self.mock_app.setPalette.assert_called()
        # Check window color is dark (53, 53, 53)
        args = self.mock_app.setPalette.call_args[0]
        palette_set = args[0]
        window_color = palette_set.colors[MockQPalette.ColorRole.Window]
        self.assertEqual(window_color.r, 53)

    def test_set_theme_system_detect_dark_via_hints(self):
        # Setup Qt 6.5+ hints for Dark
        # Qt.ColorScheme.Dark = 2
        # We need to ensure Qt.ColorScheme exists if code imports it.
        # The code does: from PyQt6.QtCore import Qt
        # So we need to mock Qt.

        mock_qt = MagicMock()
        mock_qt.ColorScheme.Dark = 2
        mock_qt.ColorScheme.Light = 1
        self.mock_qt_core.Qt = mock_qt

        self.mock_style_hints.colorScheme.return_value = 2 # Dark

        tm = self.ThemeManager(self.mock_app)
        tm.set_theme("system")

        self.assertEqual(tm.current_theme, "system")
        self.assertEqual(tm.get_effective_theme(), "dark")

        # Verify dark palette applied
        self.mock_app.setPalette.assert_called()
        args = self.mock_app.setPalette.call_args[0]
        palette_set = args[0]
        window_color = palette_set.colors[MockQPalette.ColorRole.Window]
        self.assertEqual(window_color.r, 53)

    def test_set_theme_system_detect_light_via_hints(self):
        mock_qt = MagicMock()
        mock_qt.ColorScheme.Dark = 2
        mock_qt.ColorScheme.Light = 1
        self.mock_qt_core.Qt = mock_qt

        self.mock_style_hints.colorScheme.return_value = 1 # Light

        tm = self.ThemeManager(self.mock_app)
        tm.set_theme("system")

        self.assertEqual(tm.current_theme, "system")
        self.assertEqual(tm.get_effective_theme(), "light")

        # Verify light palette applied
        self.mock_app.setPalette.assert_called()
        args = self.mock_app.setPalette.call_args[0]
        palette_set = args[0]
        window_color = palette_set.colors[MockQPalette.ColorRole.Window]
        self.assertEqual(window_color.r, 240)

    def test_set_theme_system_fallback_palette_dark(self):
        # Disable colorScheme support
        self.mock_app.styleHints.return_value = None

        # Setup current palette to be dark
        # Window color < 128 lightness
        dark_palette = MockQPalette()
        dark_palette.setColor(MockQPalette.ColorRole.Window, MockQColor(50, 50, 50))
        self.mock_app.palette.return_value = dark_palette

        tm = self.ThemeManager(self.mock_app)
        tm.set_theme("system")

        self.assertEqual(tm.get_effective_theme(), "dark")

    def test_set_theme_system_fallback_palette_light(self):
        # Disable colorScheme support
        self.mock_app.styleHints.return_value = None

        # Setup current palette to be light
        light_palette = MockQPalette()
        light_palette.setColor(MockQPalette.ColorRole.Window, MockQColor(200, 200, 200))
        self.mock_app.palette.return_value = light_palette

        tm = self.ThemeManager(self.mock_app)
        tm.set_theme("system")

        self.assertEqual(tm.get_effective_theme(), "light")

    def test_set_theme_invalid(self):
        tm = self.ThemeManager(self.mock_app)
        tm.set_theme("invalid_theme_name")

        # Should remain at default (system)
        self.assertEqual(tm.current_theme, "system")
        # Should not emit signal
        self.mock_signal_instance.emit.assert_not_called()

    def test_windows_fusion_workaround(self):
        """Test that Fusion style is forced on Windows when switching to dark theme."""
        # Mock platform.system to return 'Windows'
        with patch('platform.system', return_value='Windows'):
            tm = self.ThemeManager(self.mock_app)

            # Setup: Current style is "WindowsVista"
            style_mock = MagicMock()
            style_mock.objectName.return_value = "WindowsVista"
            self.mock_app.style.return_value = style_mock

            # Setup available styles has "Fusion"
            self.mock_qt_widgets.QStyleFactory.keys.return_value = ["Fusion", "WindowsVista"]

            # Re-init to capture available styles
            tm = self.ThemeManager(self.mock_app)

            tm.set_theme("dark")

            # Check that setStyle('Fusion') was called
            # Since _available_styles map keys to original casing, and keys() returned "Fusion"
            # It should call setStyle("Fusion")
            self.mock_app.setStyle.assert_called_with("Fusion")

    def test_windows_restore_style(self):
        """Test that original style is restored on Windows when switching back to light theme."""
        with patch('platform.system', return_value='Windows'):
            # Setup initial style as WindowsVista
            style_mock = MagicMock()
            style_mock.objectName.return_value = "WindowsVista"
            self.mock_app.style.return_value = style_mock

            tm = self.ThemeManager(self.mock_app)

            # Switch to dark (should switch to Fusion)
            tm.set_theme("dark")

            # Now current style is Fusion
            style_mock.objectName.return_value = "Fusion"

            # Switch back to light
            tm.set_theme("light")

            # Should restore WindowsVista
            self.mock_app.setStyle.assert_called_with("WindowsVista")

    def test_on_system_theme_changed(self):
        """Verify handling of system theme change signal."""
        mock_qt = MagicMock()
        mock_qt.ColorScheme.Dark = 2
        mock_qt.ColorScheme.Light = 1
        self.mock_qt_core.Qt = mock_qt

        tm = self.ThemeManager(self.mock_app)

        # Initial: system is light
        self.mock_style_hints.colorScheme.return_value = 1
        tm.set_theme("system")
        self.assertEqual(tm.get_effective_theme(), "light")

        # System changes to dark
        self.mock_style_hints.colorScheme.return_value = 2

        # Simulate signal
        tm._on_system_theme_changed(2)

        # Should now be effectively dark
        self.assertEqual(tm.get_effective_theme(), "dark")

        # Verify palette updated to dark
        args = self.mock_app.setPalette.call_args[0]
        palette_set = args[0]
        window_color = palette_set.colors[MockQPalette.ColorRole.Window]
        self.assertEqual(window_color.r, 53)

    def test_style_factory_keys_cached(self):
        """Test that QStyleFactory.keys() is cached to improve performance."""
        # Reset mock to ensure clean state
        self.mock_qt_widgets.QStyleFactory.keys.reset_mock()

        # Instantiate ThemeManager
        tm = self.ThemeManager(self.mock_app)

        # Should be called once during init to populate cache
        self.mock_qt_widgets.QStyleFactory.keys.assert_called_once()
        self.mock_qt_widgets.QStyleFactory.keys.reset_mock()

        # Trigger method that uses available styles
        with patch('platform.system', return_value='Windows'):
            # Setup style mock
            style_mock = MagicMock()
            style_mock.objectName.return_value = "WindowsVista"
            self.mock_app.style.return_value = style_mock

            # This triggers _ensure_fusion_style_on_windows which checks _available_styles
            tm.set_theme("dark")

        # Should NOT call keys() again
        self.mock_qt_widgets.QStyleFactory.keys.assert_not_called()


    def test_macos_fusion_workaround(self):
        """Test that Fusion style is forced on macOS (Darwin) when switching to dark theme."""
        # Mock platform.system to return 'Darwin'
        with patch('platform.system', return_value='Darwin'):
            # Setup available styles has "Fusion"
            self.mock_qt_widgets.QStyleFactory.keys.return_value = ["Fusion", "Macintosh"]

            tm = self.ThemeManager(self.mock_app)

            # Setup: Current style is "Macintosh"
            style_mock = MagicMock()
            style_mock.objectName.return_value = "Macintosh"
            self.mock_app.style.return_value = style_mock

            # Re-init to capture available styles
            tm = self.ThemeManager(self.mock_app)

            tm.set_theme("dark")

            # Check that setStyle('Fusion') was called
            self.mock_app.setStyle.assert_called_with("Fusion")

    def test_macos_always_fusion_style(self):
        """Test that Fusion style is used on macOS for both light and dark themes."""
        with patch('platform.system', return_value='Darwin'):
            # Setup available styles has "Fusion" and "Macintosh"
            self.mock_qt_widgets.QStyleFactory.keys.return_value = ["Fusion", "Macintosh"]

            # Setup initial style as Macintosh
            style_mock = MagicMock()
            style_mock.objectName.return_value = "Macintosh"
            self.mock_app.style.return_value = style_mock

            tm = self.ThemeManager(self.mock_app)

            # Switch to dark (should switch to Fusion)
            tm.set_theme("dark")

            # Verify Fusion applied
            self.mock_app.setStyle.assert_called_with("Fusion")

            # Reset call count
            self.mock_app.setStyle.reset_mock()

            # Now current style is Fusion
            style_mock.objectName.return_value = "Fusion"

            # Switch back to light (should apply Fusion again or keep it)
            tm.set_theme("light")

            # Verify Fusion applied (or at least native not restored)
            # Since _ensure_fusion_style calls setStyle if current is Fusion it returns early?
            # Wait, _ensure_fusion_style checks: if current.casefold() == "fusion": return
            # So if it's already fusion, setStyle is NOT called.
            self.mock_app.setStyle.assert_not_called()

            # But definitely not "Macintosh"
            try:
                # assert_not_called fails if ANY call was made, which is fine as long as we check args if it WAS called
                # but we expect NO call if it's already Fusion.
                self.mock_app.setStyle.assert_not_called()
            except AssertionError:
                # If it WAS called, check it wasn't Macintosh
                args = self.mock_app.setStyle.call_args
                self.assertNotEqual(args[0][0], "Macintosh")

if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure repo root is in path
sys.path.append(os.getcwd())

class TestDetachableWidgetWrapper(unittest.TestCase):
    def setUp(self):
        # 1. Prepare Mocks
        self.mock_qt = MagicMock()
        self.mock_qt_core = MagicMock()
        self.mock_qt_widgets = MagicMock()

        # Define Mock Classes
        class MockQObject:
            def __init__(self, *args, **kwargs):
                pass
            def setParent(self, parent):
                pass
            def findChild(self, *args):
                return None
            def findChildren(self, *args):
                return []
            def property(self, name):
                return None

        class MockQWidget(MockQObject):
            def __init__(self, *args, **kwargs):
                super().__init__()
                self.layout = None
                self._visible = True
                self._parent = None
            def setLayout(self, layout):
                self.layout = layout
            def layout(self):
                return self.layout
            def show(self):
                self._visible = True
            def hide(self):
                self._visible = False
            def isVisible(self):
                return self._visible
            def setParent(self, parent):
                self._parent = parent
            def parent(self):
                return self._parent
            def grab(self):
                return MagicMock() # Return mock pixmap
            def close(self):
                self.closeEvent(MagicMock())
            def closeEvent(self, event):
                pass
            def setSizePolicy(self, *args):
                pass
            def setFixedSize(self, *args):
                pass
            def setStyleSheet(self, *args):
                pass
            def window(self):
                p = self.parent()
                while p and p.parent():
                    p = p.parent()
                return p

        class MockQMainWindow(MockQWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.central_widget = None
            def setCentralWidget(self, widget):
                self.central_widget = widget
                if widget:
                    widget.setParent(self)
            def setWindowTitle(self, title):
                pass
            def resize(self, w, h):
                pass

        class MockLayout(MockQObject):
             def __init__(self, parent=None):
                 super().__init__()
                 self.widgets = []
                 if parent:
                     parent.setLayout(self)
             def addWidget(self, widget, *args, **kwargs):
                 self.widgets.append(widget)
             def removeWidget(self, widget):
                 if widget in self.widgets:
                     self.widgets.remove(widget)
             def setContentsMargins(self, *args):
                 pass
             def addStretch(self):
                 pass

        class MockQVBoxLayout(MockLayout):
            pass

        class MockQHBoxLayout(MockLayout):
            pass

        class MockQLabel(MockQWidget):
            def __init__(self, text="", parent=None):
                super().__init__(parent)
                self._text = text
            def setText(self, text):
                self._text = text
            def text(self):
                return self._text
            def setAlignment(self, align):
                pass

        class MockQPushButton(MockQWidget):
            def __init__(self, text="", parent=None):
                super().__init__(parent)
                self._text = text
                self.clicked = MagicMock()
                self._enabled = True
            def setText(self, text):
                self._text = text
            def text(self):
                return self._text
            def setEnabled(self, enabled):
                self._enabled = enabled
            def isEnabled(self):
                return self._enabled

        class MockQMessageBox(MockQWidget):
            warning = MagicMock()
            information = MagicMock()

        # Assign mocks
        self.mock_qt.QtCore.QObject = MockQObject
        self.mock_qt.QtCore.Qt.AlignmentFlag = MagicMock()
        self.mock_qt.QtCore.pyqtSignal = lambda *args: MagicMock()

        self.mock_qt.QtWidgets.QWidget = MockQWidget
        self.mock_qt.QtWidgets.QMainWindow = MockQMainWindow
        self.mock_qt.QtWidgets.QVBoxLayout = MockQVBoxLayout
        self.mock_qt.QtWidgets.QHBoxLayout = MockQHBoxLayout
        self.mock_qt.QtWidgets.QLabel = MockQLabel
        self.mock_qt.QtWidgets.QPushButton = MockQPushButton
        self.mock_qt.QtWidgets.QMessageBox = MockQMessageBox
        self.mock_qt.QtWidgets.QSizePolicy = MagicMock()

        # Patch sys.modules
        self.modules_patcher = patch.dict(sys.modules, {
            'PyQt6': self.mock_qt,
            'PyQt6.QtCore': self.mock_qt.QtCore,
            'PyQt6.QtWidgets': self.mock_qt.QtWidgets,
        })
        self.modules_patcher.start()

        # Mock localization
        self.mock_localization = MagicMock()
        self.mock_localization.tr = lambda x: x
        sys.modules['src.core.localization'] = self.mock_localization

        # Force re-import
        if 'src.gui.widgets.detachable_wrapper' in sys.modules:
            del sys.modules['src.gui.widgets.detachable_wrapper']

        import src.gui.widgets.detachable_wrapper
        self.module = src.gui.widgets.detachable_wrapper
        self.DetachableWidgetWrapper = self.module.DetachableWidgetWrapper
        self.IndependentWindow = self.module.IndependentWindow

    def tearDown(self):
        self.modules_patcher.stop()
        if 'src.gui.widgets.detachable_wrapper' in sys.modules:
            del sys.modules['src.gui.widgets.detachable_wrapper']
        if 'src.core.localization' in sys.modules:
             del sys.modules['src.core.localization']

    def test_initialization(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        self.assertEqual(wrapper.title, "Test Title")
        self.assertEqual(wrapper.content_widget, mock_widget)
        self.assertFalse(wrapper.is_detached)
        self.assertIsNone(wrapper.independent_window)

        # Check layout
        self.assertIn(mock_widget, wrapper.content_container_layout.widgets)
        self.assertTrue(wrapper.content_container.isVisible())
        self.assertFalse(wrapper.placeholder_widget.isVisible())
        self.assertEqual(wrapper.detach_btn.text(), "Detach Window")

    def test_detach(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        wrapper.detach()

        self.assertTrue(wrapper.is_detached)
        self.assertIsNotNone(wrapper.independent_window)
        self.assertTrue(wrapper.independent_window.isVisible())

        # Check that widget was removed from wrapper layout
        self.assertNotIn(mock_widget, wrapper.content_container_layout.widgets)

        # Check that widget is now in independent window
        self.assertEqual(wrapper.independent_window.central_widget, mock_widget)

        self.assertFalse(wrapper.content_container.isVisible())
        self.assertTrue(wrapper.placeholder_widget.isVisible())
        self.assertEqual(wrapper.detach_btn.text(), "Reattach")
        self.assertFalse(wrapper.detach_btn.isEnabled())

    def test_reattach(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")
        wrapper.detach()

        # Simulate reattach
        wrapper.reattach()

        self.assertFalse(wrapper.is_detached)
        self.assertIsNone(wrapper.independent_window)

        self.assertIn(mock_widget, wrapper.content_container_layout.widgets)
        self.assertTrue(wrapper.content_container.isVisible())
        self.assertFalse(wrapper.placeholder_widget.isVisible())
        self.assertEqual(wrapper.detach_btn.text(), "Detach Window")

    def test_toggle_detach(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        wrapper.detach = MagicMock(wraps=wrapper.detach)
        wrapper.reattach = MagicMock(wraps=wrapper.reattach)

        # Toggle to detach
        wrapper.toggle_detach()
        wrapper.detach.assert_called_once()
        self.assertTrue(wrapper.is_detached)

        # Toggle to reattach
        wrapper.toggle_detach()
        wrapper.reattach.assert_called_once()
        self.assertFalse(wrapper.is_detached)

    def test_independent_window_signal_connection(self):
        """Test that the independent window closed signal is connected to reattach."""
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        wrapper.detach()
        independent_window = wrapper.independent_window

        # Verify the signal connection
        # Since closed is a MagicMock (from mocked pyqtSignal), connect is a mock method
        independent_window.closed.connect.assert_called_with(wrapper.reattach)

    def test_screenshot_success(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        with patch('src.gui.widgets.detachable_wrapper.os.makedirs') as mock_makedirs, \
             patch('src.gui.widgets.detachable_wrapper.os.path.exists', return_value=False), \
             patch('src.gui.widgets.detachable_wrapper.datetime') as mock_datetime:

            mock_now = MagicMock()
            mock_now.strftime.return_value = "20230101"
            mock_datetime.now.return_value = mock_now

            mock_pixmap = MagicMock()
            mock_pixmap.save.return_value = True
            mock_widget.grab = MagicMock(return_value=mock_pixmap)

            wrapper.save_screenshot()

            mock_makedirs.assert_called()
            mock_widget.grab.assert_called()
            mock_pixmap.save.assert_called()
            self.mock_qt.QtWidgets.QMessageBox.information.assert_called()

    def test_screenshot_fail_makedirs(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        with patch('src.gui.widgets.detachable_wrapper.os.makedirs', side_effect=OSError("Fail")):
            wrapper.save_screenshot()
            self.mock_qt.QtWidgets.QMessageBox.warning.assert_called()
            args = self.mock_qt.QtWidgets.QMessageBox.warning.call_args[0]
            self.assertIn("Failed to create output folder", args[2])

    def test_config_manager(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        mock_config = MagicMock()
        mock_config.get_screenshot_output_dir.return_value = "custom/dir"

        wrapper = self.DetachableWidgetWrapper(mock_widget, "Title", config_manager=mock_config)
        self.assertEqual(wrapper._get_screenshot_output_dir(), "custom/dir")

    def test_screenshot_fail_grab(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        # Mock os.makedirs to succeed
        with patch('src.gui.widgets.detachable_wrapper.os.makedirs'), \
             patch('src.gui.widgets.detachable_wrapper.QMessageBox') as mock_msg:

            mock_widget.grab = MagicMock(side_effect=Exception("Grab error"))

            wrapper.save_screenshot()

            mock_msg.warning.assert_called()
            args = mock_msg.warning.call_args[0]
            self.assertIn("Failed to capture screenshot", args[2])

    def test_screenshot_fail_save(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Test Title")

        with patch('src.gui.widgets.detachable_wrapper.os.makedirs'), \
             patch('src.gui.widgets.detachable_wrapper.os.path.exists', return_value=False), \
             patch('src.gui.widgets.detachable_wrapper.QMessageBox') as mock_msg:

            mock_pixmap = MagicMock()
            mock_pixmap.save.return_value = False # Simulate save failure
            mock_widget.grab = MagicMock(return_value=mock_pixmap)

            wrapper.save_screenshot()

            mock_msg.warning.assert_called()
            args = mock_msg.warning.call_args[0]
            self.assertIn("Failed to save screenshot", args[2])

    def test_safe_base_filename(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Title")

        self.assertEqual(wrapper._safe_base_filename("Valid Name"), "Valid_Name")
        self.assertEqual(wrapper._safe_base_filename("Invalid/Name*"), "Invalid_Name")
        self.assertEqual(wrapper._safe_base_filename("  Trim Me  "), "Trim_Me")
        self.assertEqual(wrapper._safe_base_filename(""), "widget")
        self.assertEqual(wrapper._safe_base_filename(None), "widget")

    def test_next_available_filepath(self):
        mock_widget = self.mock_qt.QtWidgets.QWidget()
        wrapper = self.DetachableWidgetWrapper(mock_widget, "Title")

        with patch('src.gui.widgets.detachable_wrapper.os.path.exists') as mock_exists:
            # Case 1: Base file doesn't exist
            mock_exists.return_value = False
            path = wrapper._next_available_filepath("dir", "base", "png")
            self.assertEqual(path, os.path.join("dir", "base.png"))

            # Case 2: Base file exists, _001 doesn't
            mock_exists.side_effect = [True, False]
            path = wrapper._next_available_filepath("dir", "base", "png")
            self.assertEqual(path, os.path.join("dir", "base_001.png"))

            # Case 3: Base and _001 exist, _002 doesn't
            mock_exists.side_effect = [True, True, False]
            path = wrapper._next_available_filepath("dir", "base", "png")
            self.assertEqual(path, os.path.join("dir", "base_002.png"))

if __name__ == '__main__':
    unittest.main()

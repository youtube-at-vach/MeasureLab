import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import importlib

class TestWelcomeWidgetLogic(unittest.TestCase):
    def setUp(self):
        # Mocks for PyQt6
        self.mock_qt_core = MagicMock()
        self.mock_qt_widgets = MagicMock()
        self.mock_qt_gui = MagicMock()

        # We need a proper mock class for QWidget and QLabel so super().__init__() works
        class MockQWidget:
            def __init__(self, *args, **kwargs):
                pass
            def setLayout(self, layout):
                pass
            def setStyleSheet(self, style):
                pass
            def findChildren(self, type):
                return []

        class MockQLabel(MockQWidget):
            def __init__(self, *args, **kwargs):
                super().__init__()
            def setPixmap(self, pixmap):
                pass
            def setText(self, text):
                pass
            def setAlignment(self, alignment):
                pass
            def setStyleSheet(self, style):
                pass
            def setFont(self, font):
                pass
            def setTextFormat(self, fmt):
                pass
            def setCursor(self, cursor):
                pass
            def show(self):
                pass
            def hide(self):
                pass

        class MockQPixmap:
            def __init__(self, *args, **kwargs):
                pass
            def scaledToHeight(self, *args, **kwargs):
                return self

        self.mock_qt_widgets.QWidget = MockQWidget

        # Keep references to the specific created labels to verify assertions
        self.created_labels = []
        def create_label(*args, **kwargs):
            lbl = MagicMock(spec=MockQLabel)
            self.created_labels.append(lbl)
            return lbl

        self.mock_qt_widgets.QLabel = create_label
        self.mock_qt_widgets.QVBoxLayout = MagicMock()
        self.mock_qt_widgets.QHBoxLayout = MagicMock()

        self.mock_pixmap_instance = MagicMock()
        self.mock_qt_gui.QPixmap = MagicMock(return_value=self.mock_pixmap_instance)
        self.mock_qt_gui.QDesktopServices = MagicMock()

        self.modules_patcher = patch.dict(sys.modules, {
            "PyQt6": MagicMock(),
            "PyQt6.QtCore": self.mock_qt_core,
            "PyQt6.QtWidgets": self.mock_qt_widgets,
            "PyQt6.QtGui": self.mock_qt_gui,
            "certifi": MagicMock(),
        })
        self.modules_patcher.start()

    def tearDown(self):
        self.modules_patcher.stop()
        if "src.gui.widgets.welcome" in sys.modules:
            del sys.modules["src.gui.widgets.welcome"]

    def test_init_ui_primary_path_exists(self):
        # Import inside the test to ensure the mocks are in place
        import src.gui.widgets.welcome
        importlib.reload(src.gui.widgets.welcome)

        with patch.object(src.gui.widgets.welcome, 'UpdateChecker', MagicMock()), \
             patch.object(src.gui.widgets.welcome, 'resource_path') as mock_resource_path, \
             patch('os.path.exists') as mock_exists:

            from src.gui.widgets.welcome import WelcomeWidget

            primary_path = "/mock/primary/path/assets/welcome.png"
            mock_resource_path.return_value = primary_path

            def mock_exists_side_effect(path):
                return path == primary_path
            mock_exists.side_effect = mock_exists_side_effect

            # Reset created labels list
            self.created_labels.clear()
            self.mock_qt_gui.QPixmap.reset_mock()

            _ = WelcomeWidget()

            # Verify resource_path was called
            mock_resource_path.assert_called_with("src/assets/welcome.png")

            # Verify QPixmap was instantiated with primary_path
            self.mock_qt_gui.QPixmap.assert_called_with(primary_path)

            # Verify scaledToHeight was called on the pixmap
            self.mock_pixmap_instance.scaledToHeight.assert_called_with(
                400, self.mock_qt_core.Qt.TransformationMode.SmoothTransformation
            )

            # Verify image label received the scaled pixmap
            # The first label created is the image label
            image_label = self.created_labels[0]
            image_label.setPixmap.assert_called_with(self.mock_pixmap_instance.scaledToHeight.return_value)
            image_label.setAlignment.assert_called_with(self.mock_qt_core.Qt.AlignmentFlag.AlignCenter)
            image_label.setStyleSheet.assert_called_with("background-color: #1e1e1e;")

    def test_init_ui_fallback_path_exists(self):
        import src.gui.widgets.welcome
        importlib.reload(src.gui.widgets.welcome)

        with patch.object(src.gui.widgets.welcome, 'UpdateChecker', MagicMock()), \
             patch.object(src.gui.widgets.welcome, 'resource_path') as mock_resource_path, \
             patch('os.path.exists') as mock_exists:

            from src.gui.widgets.welcome import WelcomeWidget

            primary_path = "/mock/primary/path/assets/welcome.png"
            mock_resource_path.return_value = primary_path

            # Since WelcomeWidget file is src/gui/widgets/welcome.py,
            # os.path.dirname(os.path.dirname(os.path.dirname(__file__))) should be src/
            expected_fallback_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(src.gui.widgets.welcome.__file__))),
                "assets",
                "welcome.png"
            )

            def mock_exists_side_effect(path):
                if path == primary_path:
                    return False
                if path == expected_fallback_path:
                    return True
                return False
            mock_exists.side_effect = mock_exists_side_effect

            # Reset created labels list
            self.created_labels.clear()
            self.mock_qt_gui.QPixmap.reset_mock()

            _ = WelcomeWidget()

            # Verify QPixmap was instantiated with fallback_path
            self.mock_qt_gui.QPixmap.assert_called_with(expected_fallback_path)

    def test_init_ui_not_found(self):
        import src.gui.widgets.welcome
        importlib.reload(src.gui.widgets.welcome)

        with patch.object(src.gui.widgets.welcome, 'UpdateChecker', MagicMock()), \
             patch.object(src.gui.widgets.welcome, 'resource_path') as mock_resource_path, \
             patch('os.path.exists') as mock_exists, \
             patch.object(src.gui.widgets.welcome, 'tr', side_effect=lambda x: f"TR_{x}"):

            from src.gui.widgets.welcome import WelcomeWidget

            mock_resource_path.return_value = "/mock/invalid/path/welcome.png"
            mock_exists.return_value = False

            # Reset created labels list
            self.created_labels.clear()
            self.mock_qt_gui.QPixmap.reset_mock()

            _ = WelcomeWidget()

            # Verify QPixmap was not called
            self.mock_qt_gui.QPixmap.assert_not_called()

            # Verify fallback text was set on the label
            image_label = self.created_labels[0]
            image_label.setText.assert_called_with("TR_Welcome Image Not Found")
            image_label.setAlignment.assert_called_with(self.mock_qt_core.Qt.AlignmentFlag.AlignCenter)

if __name__ == '__main__':
    unittest.main()

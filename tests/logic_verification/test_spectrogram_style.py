import sys
from unittest.mock import MagicMock, patch

# Helper to create mock QWidget-like class
class MockQWidget(MagicMock):
    def _get_child_mock(self, **kw):
        return MagicMock(**kw)

def test_spectrogram_style():
    # Import actual styles for verification
    try:
        from src.gui.styles import STYLE_TOGGLE_BTN_DARK, STYLE_TOGGLE_BTN_LIGHT
    except ImportError:
        # If running from a place where src is not in path (though python -m pytest adds it)
        sys.path.append(".")
        from src.gui.styles import STYLE_TOGGLE_BTN_DARK, STYLE_TOGGLE_BTN_LIGHT

    # Define mocks
    mock_np = MagicMock()
    mock_pg = MagicMock()

    # Configure Qt
    mock_qt_core = MagicMock()
    mock_qt_core.QTimer = MagicMock()

    mock_qt_widgets = MagicMock()
    mock_qt_widgets.QWidget = MockQWidget
    mock_qt_widgets.QPushButton = MagicMock()
    mock_qt_widgets.QApplication = MagicMock()
    mock_qt_widgets.QComboBox = MagicMock()
    mock_qt_widgets.QGroupBox = MagicMock()
    mock_qt_widgets.QHBoxLayout = MagicMock()
    mock_qt_widgets.QVBoxLayout = MagicMock()
    mock_qt_widgets.QLabel = MagicMock()
    mock_qt_widgets.QSpinBox = MagicMock()

    # Mock dependencies
    mock_modules = {
        "numpy": mock_np,
        "pyqtgraph": mock_pg,
        "PyQt6": MagicMock(),
        "PyQt6.QtCore": mock_qt_core,
        "PyQt6.QtGui": MagicMock(),
        "PyQt6.QtWidgets": mock_qt_widgets,
        "src.core.audio_engine": MagicMock(),
        "src.core.analysis": MagicMock(),
        "src.core.localization": MagicMock(),
        "src.core.fft_manager": MagicMock(),
    }

    # Patch modules
    with patch.dict(sys.modules, mock_modules):
        # Clean import
        if "src.gui.widgets.spectrogram" in sys.modules:
            del sys.modules["src.gui.widgets.spectrogram"]

        from src.gui.widgets.spectrogram import SpectrogramWidget, Spectrogram # noqa: E402

        # Setup
        mock_audio_engine = MagicMock()
        spectrogram = Spectrogram(mock_audio_engine)

        # Mock QApplication instance to have theme_manager
        mock_app = MagicMock()
        mock_theme_manager = MagicMock()
        mock_app.theme_manager = mock_theme_manager
        mock_qt_widgets.QApplication.instance.return_value = mock_app

        # Instantiate Widget
        # init_ui calls apply_theme, which will use the mock_theme_manager
        mock_theme_manager.get_current_theme.return_value = "light"

        widget = SpectrogramWidget(spectrogram)

        # Test Dark Theme
        widget.apply_theme("dark")
        widget.toggle_btn.setStyleSheet.assert_called_with(STYLE_TOGGLE_BTN_DARK)

        # Test Light Theme
        widget.apply_theme("light")
        widget.toggle_btn.setStyleSheet.assert_called_with(STYLE_TOGGLE_BTN_LIGHT)

        print("Spectrogram style verification passed.")

if __name__ == "__main__":
    test_spectrogram_style()

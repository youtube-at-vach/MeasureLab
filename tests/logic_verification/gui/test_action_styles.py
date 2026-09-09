from unittest.mock import MagicMock

import pytest
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QPushButton

from src.core.theme_manager import ThemeManager
from src.gui.styles import button_style
from src.gui.widgets.impedance_analyzer import ImpedanceAnalyzer, ImpedanceAnalyzerWidget
from src.gui.widgets.spectrum_analyzer import SpectrumAnalyzer, SpectrumAnalyzerWidget


@pytest.fixture
def theme_manager(qapp, monkeypatch):
    palette, stylesheet = qapp.palette(), qapp.styleSheet()
    manager = ThemeManager(qapp)
    monkeypatch.setattr(qapp, "theme_manager", manager, raising=False)
    yield manager
    qapp.setPalette(palette)
    qapp.setStyleSheet(stylesheet)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_toggle_disabled_is_muted_without_resizing(qapp, qtbot, theme_manager, theme):
    theme_manager.set_theme(theme)
    button = QPushButton("Start / Stop")
    button.setCheckable(True)
    button.setStyleSheet(button_style("primary", toggle=True, extra="padding: 5px;"))
    qtbot.addWidget(button)
    button.show()
    qapp.processEvents()
    normal_size = button.sizeHint()
    normal_text = button.palette().color(QPalette.ColorRole.ButtonText)
    button.setChecked(True)
    button.setEnabled(False)
    qapp.processEvents()
    assert button.sizeHint() == normal_size
    disabled_text = button.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    assert disabled_text != normal_text


@pytest.mark.parametrize(
    "module_type,widget_type",
    [
        (SpectrumAnalyzer, SpectrumAnalyzerWidget),
        (ImpedanceAnalyzer, ImpedanceAnalyzerWidget),
    ],
)
def test_widget_theme_subscription_is_not_recursive(qtbot, theme_manager, module_type, widget_type):
    engine = MagicMock()
    engine.sample_rate = 48000
    engine.calibration.input_sensitivity = 1.0
    engine.calibration.get_input_offset_db.return_value = 0.0
    theme_manager.set_theme("dark")
    widget = widget_type(module_type(engine))
    qtbot.addWidget(widget)
    subscribers = theme_manager.receivers(theme_manager.theme_changed)
    assert subscribers >= 1
    for theme in ("light", "dark", "light"):
        theme_manager.set_theme(theme)
        assert theme_manager.receivers(theme_manager.theme_changed) == subscribers

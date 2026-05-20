from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QListWidget

from src.gui.main_window import MainWindow


class _DummyModule:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _DummyWrapper:
    def __init__(self, is_detached=False):
        self.is_detached = is_detached


def _build_window_stub(qtbot):
    window = MainWindow()
    window._module_keys = ["Signal Generator", "Recorder / Player"]
    window.modules = [None, None]
    window.module_widgets = [None, None]
    window.sidebar = QListWidget()
    window.sidebar.addItem("Welcome")
    window.sidebar.addItem("Settings")
    window.sidebar.addItem("Signal Generator")
    window.sidebar.addItem("Recorder / Player")
    qtbot.addWidget(window.sidebar)
    return window


def test_module_is_active_supports_nonstandard_flags(qtbot):
    window = _build_window_stub(qtbot)

    assert window._module_is_active(_DummyModule(is_playing=True))
    assert window._module_is_active(_DummyModule(is_recording=True))
    assert window._module_is_active(_DummyModule(rotation_active=True))
    assert not window._module_is_active(_DummyModule())


def test_refresh_sidebar_activity_indicators_updates_visuals_and_tooltips(qtbot):
    window = _build_window_stub(qtbot)
    window.modules[0] = _DummyModule(is_playing=True)
    window.modules[1] = _DummyModule(is_recording=True)
    window.module_widgets[1] = _DummyWrapper(is_detached=True)

    window._refresh_sidebar_activity_indicators()

    active_item = window.sidebar.item(2)
    detached_item = window.sidebar.item(3)
    default_brush = window.sidebar.palette().brush(QPalette.ColorRole.Text)
    active_brush = window.sidebar.palette().brush(QPalette.ColorRole.Highlight)

    assert active_item.font().bold()
    assert active_item.foreground().color() == active_brush.color()
    assert "ACTIVE" in active_item.toolTip()

    assert detached_item.font().bold()
    assert detached_item.foreground().color() == active_brush.color()
    assert "ACTIVE" in detached_item.toolTip()
    assert "detached" in detached_item.toolTip().lower()

    window.modules[0] = _DummyModule()
    window.modules[1] = _DummyModule()
    window.module_widgets[1] = _DummyWrapper(is_detached=False)

    window._refresh_sidebar_activity_indicators()

    inactive_item = window.sidebar.item(2)
    assert not inactive_item.font().bold()
    assert inactive_item.foreground().color() == default_brush.color()

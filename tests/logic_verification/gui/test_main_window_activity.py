from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QListWidget

from src.core.localization import tr
from src.gui.main_window import MainWindow


class _DummyModule:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _DummyWrapper:
    def __init__(self, is_detached=False):
        self.is_detached = is_detached


def _build_window_stub(qtbot):
    window = MainWindow.__new__(MainWindow)
    window.__init__()
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
    assert tr("ACTIVE") in active_item.toolTip()

    assert detached_item.font().bold()
    assert detached_item.foreground().color() == active_brush.color()
    assert tr("ACTIVE") in detached_item.toolTip()
    assert tr("Widget is detached in a separate window.") in detached_item.toolTip()

    window.modules[0] = _DummyModule()
    window.modules[1] = _DummyModule()
    window.module_widgets[1] = _DummyWrapper(is_detached=False)

    window._refresh_sidebar_activity_indicators()

    inactive_item = window.sidebar.item(2)
    assert not inactive_item.font().bold()
    assert inactive_item.foreground().color() == default_brush.color()


def test_build_module_activity_tooltip(qtbot):
    window = _build_window_stub(qtbot)

    # Test case 1: Active module
    window.modules[0] = _DummyModule(is_playing=True)
    window.module_widgets[0] = _DummyWrapper(is_detached=False)
    tooltip1 = window._build_module_activity_tooltip(0)
    assert tr("Signal Generator") in tooltip1
    assert tr("ACTIVE") in tooltip1
    assert tr("Widget is detached in a separate window.") not in tooltip1

    # Test case 2: Inactive and detached module
    window.modules[1] = _DummyModule()
    window.module_widgets[1] = _DummyWrapper(is_detached=True)
    tooltip2 = window._build_module_activity_tooltip(1)
    assert tr("Recorder / Player") in tooltip2
    assert tr("ACTIVE") not in tooltip2
    assert tr("Widget is detached in a separate window.") in tooltip2

    # Test case 3: Active and detached module
    window.modules[1] = _DummyModule(is_recording=True)
    tooltip3 = window._build_module_activity_tooltip(1)
    assert tr("Recorder / Player") in tooltip3
    assert tr("ACTIVE") in tooltip3
    assert tr("Widget is detached in a separate window.") in tooltip3

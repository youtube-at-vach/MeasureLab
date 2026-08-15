from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QListWidget, QWidget
from unittest.mock import MagicMock

from src.core.localization import tr
from src.gui.main_window import MainWindow
from src.gui.module_registry import NO_INDEPENDENT_DISPLAY, WidgetCapabilities
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper


NO_CAPABILITIES = WidgetCapabilities(
    split_window=NO_INDEPENDENT_DISPLAY,
    compact_mode=NO_INDEPENDENT_DISPLAY,
    comparison=NO_INDEPENDENT_DISPLAY,
)


class _DummyModule:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _DummyWrapper:
    def __init__(self, is_detached=False, is_split=False):
        self.is_detached = is_detached
        self.is_split = is_split


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

    # Test case 4: Split state takes precedence over detached wording
    window.module_widgets[1] = _DummyWrapper(is_split=True)
    tooltip4 = window._build_module_activity_tooltip(1)
    assert tr("Widget is split into display and control windows.") in tooltip4
    assert tr("Widget is detached in a separate window.") not in tooltip4


def test_menu_only_double_click_raises_both_split_windows(qtbot):
    window = _build_window_stub(qtbot)
    wrapper = DetachableWidgetWrapper(QWidget(), "Split Module", capabilities=NO_CAPABILITIES)
    qtbot.addWidget(wrapper)
    display_window = MagicMock()
    control_window = MagicMock()
    wrapper.is_split = True
    wrapper.split_display_window = display_window
    wrapper.split_control_window = control_window
    window._menu_only_mode = True
    window.modules[0] = _DummyModule()
    window.module_widgets[0] = wrapper

    try:
        window.on_sidebar_item_double_clicked(window.sidebar.item(2))
        for external_window in (display_window, control_window):
            external_window.show.assert_called_once_with()
            external_window.raise_.assert_called_once_with()
            external_window.activateWindow.assert_called_once_with()
    finally:
        wrapper.is_split = False
        wrapper.split_display_window = None
        wrapper.split_control_window = None


def _audio_status(*, latched=None, count=0, active=True, error_count=0, last_error=None):
    return {
        "active": active,
        "offline_mode": False,
        "input_channels": "stereo",
        "output_channels": "stereo",
        "sample_rate": 48000,
        "cpu_load": 0.125,
        "active_clients": 1,
        "input_device": None,
        "output_device": None,
        "status_flags": 0,
        "latched_xrun_status": latched or {},
        "latched_xrun_count": count,
        "error_count": error_count,
        "last_error": last_error,
    }


def test_audio_io_error_is_latched_in_full_and_menu_only_status(qtbot):
    window = _build_window_stub(qtbot)
    window.audio_engine.get_status = MagicMock(
        return_value=_audio_status(
            latched={"input_overflow": True, "output_underflow": True},
            count=3,
            active=False,
        )
    )

    window.update_status()

    assert not window.io_error_button.isHidden()
    assert "color: red" in window.io_error_button.styleSheet()
    assert tr("Input overflow") in window.io_error_button.toolTip()
    assert tr("Output underflow") in window.io_error_button.toolTip()
    assert tr("Occurrences: {0}").format(3) in window.io_error_button.toolTip()
    assert window.cpu_label.text() == tr("CPU: {0:.1f}%").format(12.5)

    window.set_menu_only_mode(True)

    assert window.sidebar_footer_layout.indexOf(window.io_error_button) >= 0
    assert not window.io_error_button.isHidden()


def test_audio_io_error_requires_explicit_acknowledgement(qtbot):
    window = _build_window_stub(qtbot)
    window.audio_engine.clear_latched_audio_status = MagicMock()
    window._update_audio_io_error_indicator(_audio_status(latched={"input_underflow": True}, count=1))

    window.io_error_button.click()

    window.audio_engine.clear_latched_audio_status.assert_called_once_with()
    assert window.io_error_button.isHidden()
    assert not window._io_error_latched


def test_audio_io_error_indicator_stays_hidden_without_xrun(qtbot):
    window = _build_window_stub(qtbot)

    window._update_audio_io_error_indicator(_audio_status())

    assert window.io_error_button.isHidden()
    assert not window._io_error_latched


def test_audio_callback_error_is_latched_until_acknowledged(qtbot):
    window = _build_window_stub(qtbot)
    window.audio_engine.get_status = MagicMock(
        side_effect=[
            _audio_status(error_count=2, last_error="processing failed"),
            _audio_status(),
        ]
    )

    window.update_status()

    assert not window.io_error_button.isHidden()
    assert "processing failed" in window.io_error_button.toolTip()
    assert tr("Error Count") in window.io_error_button.toolTip()

    window.update_status()
    assert not window.io_error_button.isHidden()

    window.io_error_button.click()
    assert window.io_error_button.isHidden()
    assert not window._callback_error_latched


def test_init_audio_uses_portaudio_defaults_without_saved_devices():
    window = MagicMock()
    window.config_manager.get_audio_config.return_value = {}

    MainWindow._init_audio(window)

    window.audio_engine.set_devices.assert_called_once_with(None, None)

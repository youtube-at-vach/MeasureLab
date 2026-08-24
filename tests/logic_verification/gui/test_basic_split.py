import sys
import os
import pytest
from unittest.mock import MagicMock

pytest.importorskip("PyQt6")

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = MagicMock()

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication, QWidget
from src.gui.module_registry import MODULE_REGISTRY
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper

from src.core.module_constants import (
    MODULE_BNIM_METER,
    MODULE_GONIOMETER,
    MODULE_LUFS_METER,
    MODULE_NOISE_PROFILER,
    MODULE_RAW_TIME_SERIES,
)
from src.gui.widgets.bnim_meter import BNIMMeter, BNIMMeterWidget
from src.gui.widgets.goniometer import Goniometer, GoniometerWidget
from src.gui.widgets.lufs_meter import LufsMeter, LufsMeterWidget
from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseProfilerWidget
from src.gui.widgets.raw_time_series import RawTimeSeries, RawTimeSeriesWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture(
    params=[
        (BNIMMeter, BNIMMeterWidget, MODULE_BNIM_METER, "BNIM Meter"),
        (Goniometer, GoniometerWidget, MODULE_GONIOMETER, "Goniometer"),
        (LufsMeter, LufsMeterWidget, MODULE_LUFS_METER, "LUFS Meter"),
        (NoiseProfiler, NoiseProfilerWidget, MODULE_NOISE_PROFILER, "Noise Profiler"),
        (RawTimeSeries, RawTimeSeriesWidget, MODULE_RAW_TIME_SERIES, "Raw Time Series"),
    ]
)
def module_setup(request, qapp):
    ModuleClass, WidgetClass, module_constant, title = request.param

    mock_engine = MagicMock()
    mock_engine.sample_rate = 48000
    mock_engine.calibration = MagicMock()
    mock_engine.calibration.input_sensitivity = 1.0
    mock_engine.calibration.get_input_offset_db.return_value = 0.0

    module = ModuleClass(mock_engine)
    widget = WidgetClass(module)

    return widget, module_constant, title


def test_splittable_interface_implementation(module_setup):
    widget, _, _ = module_setup
    assert isinstance(widget, SplittableWidgetInterface)

    display_widget = widget.get_display_widget()
    control_widget = widget.get_control_widget()

    assert isinstance(display_widget, QWidget)
    assert isinstance(control_widget, QWidget)
    assert display_widget is widget.display_widget

    # Some widgets use 'sidebar', some use 'controls_group'
    actual_control = (
        getattr(widget, "sidebar", None)
        or getattr(widget, "controls_group", None)
        or getattr(widget, "right_widget", None)
    )
    assert control_widget is actual_control


def test_detachable_wrapper_split_flow(module_setup):
    widget, module_constant, title = module_setup

    wrapper = DetachableWidgetWrapper(
        widget,
        title,
        capabilities=MODULE_REGISTRY[module_constant].capabilities,
    )
    assert wrapper.is_splittable
    assert wrapper.split_btn is not None
    assert wrapper.split_btn.isEnabled()

    # Transition to State C (Split)
    wrapper.split()
    assert wrapper.is_split
    assert wrapper.split_display_window is not None
    assert wrapper.split_control_window is not None

    # Ensure compact mode check handles split state safely
    widget.set_compact_mode(True)
    if module_constant == MODULE_NOISE_PROFILER:
        assert not widget.sidebar.isHidden()
    assert widget.is_compact_mode()

    # Reattach all back to State A
    wrapper.reattach_all()
    assert not wrapper.is_split
    assert widget.display_widget.parent() is widget
    actual_control = (
        getattr(widget, "sidebar", None)
        or getattr(widget, "controls_group", None)
        or getattr(widget, "right_widget", None)
    )
    assert actual_control.parent() is widget

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.widgets.loopback_finder import LoopbackFinder, LoopbackFinderWidget  # noqa: E402


def _widget(qtbot):
    engine = MagicMock()
    engine.input_device = 0
    engine.output_device = 1
    engine.sample_rate = 48_000
    engine.offline_mode = False
    engine.is_active.return_value = False
    engine._get_cached_audio_info.return_value = (
        [
            {"name": "Input", "max_input_channels": 2, "max_output_channels": 0},
            {"name": "Output", "max_input_channels": 0, "max_output_channels": 2},
        ],
        (),
    )
    module = LoopbackFinder(engine)
    widget = LoopbackFinderWidget(module)
    qtbot.addWidget(widget)
    return module, widget


def test_stop_scan_requests_non_blocking_cancellation(qtbot):
    module, widget = _widget(qtbot)
    worker = MagicMock()
    worker.isRunning.return_value = True
    module.worker = worker

    widget.stop_scan()

    worker.stop.assert_called_once()
    worker.wait.assert_not_called()
    assert not widget.stop_btn.isEnabled()
    module.worker = None


def test_stop_scan_without_worker_is_a_noop(qtbot):
    module, widget = _widget(qtbot)
    module.worker = None

    widget.stop_scan()

    assert module.worker is None

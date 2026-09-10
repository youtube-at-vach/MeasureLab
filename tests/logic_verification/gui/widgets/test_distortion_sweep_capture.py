from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.gui.widgets.distortion_analyzer import DistortionAnalyzer, SweepWorker


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
@pytest.mark.parametrize("completed_captures", [0, 1, 2, 4])
def test_sweep_does_not_publish_incomplete_averages(qtbot, failure, completed_captures, caplog):
    engine = MagicMock()
    engine.sample_rate = 48000
    module = DistortionAnalyzer(engine)
    module.average_count = 2
    worker = SweepWorker(module, "frequency", 100, 200, 2, duration_ms=300)
    results = []
    progress = []
    finished = []
    worker.result_ready.connect(results.append)
    worker.progress.connect(lambda step, total: progress.append((step, total)))
    worker.finished.connect(lambda: finished.append(True))
    captures = 0

    def capture():
        nonlocal captures
        module.capture_requested = True
        module.capture_ready = captures < completed_captures
        if module.capture_ready:
            module.captured_buffer = np.ones(32)
            module.capture_requested = False
        elif failure == "cancel":
            worker.stop()
        captures += 1

    module.request_capture = capture
    with (
        patch("src.gui.widgets.distortion_analyzer.AudioCalc.analyze_harmonics") as analyze,
        patch.object(module, "_apply_result_averaging", side_effect=lambda result: result),
    ):
        analyze.side_effect = lambda *args, **kwargs: {"basic_wave": {}, "thdn_percent": 0.1}
        # Run synchronously with real Qt timers and no hardware callback.
        worker.run()

    assert analyze.call_count == completed_captures
    assert len(results) == completed_captures // module.average_count
    assert progress == [(step, 2) for step in range(1, len(results) + 1)]
    assert finished == [True]
    assert not module.capture_requested
    if completed_captures < 4:
        assert not worker.is_running
    if failure == "timeout" and completed_captures < 4:
        assert "audio capture timed out" in caplog.text

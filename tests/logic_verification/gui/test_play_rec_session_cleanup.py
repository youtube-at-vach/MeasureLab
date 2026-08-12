from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from src.gui.widgets.network_analyzer import NetworkAnalyzer
from src.gui.widgets.nonlinear_response_analyzer import NonlinearResponseAnalyzer


class _FailingSession:
    instances = []

    def __init__(self, *args, **kwargs):
        self.stopped = False
        self.input_data = None
        self.__class__.instances.append(self)

    def start(self):
        return None

    def wait(self, timeout=None):
        raise RuntimeError("simulated device timeout")

    def stop(self):
        self.stopped = True


@pytest.mark.parametrize(
    ("session_path", "run_play_rec"),
    [
        ("src.gui.widgets.network_analyzer.PlayRecSession", NetworkAnalyzer.run_play_rec),
        (
            "src.gui.widgets.nonlinear_response_analyzer.PlayRecSession",
            NonlinearResponseAnalyzer.run_play_rec,
        ),
    ],
)
def test_play_rec_session_stops_after_wait_error(session_path, run_play_rec):
    _FailingSession.instances.clear()
    analyzer = SimpleNamespace(audio_engine=SimpleNamespace(sample_rate=48000))
    output_data = np.zeros((1, 2), dtype=np.float32)

    with patch(session_path, _FailingSession), pytest.raises(RuntimeError, match="simulated device timeout"):
        run_play_rec(analyzer, output_data)

    assert _FailingSession.instances[0].stopped

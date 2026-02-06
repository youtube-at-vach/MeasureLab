import sys
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QThreadPool

# Mock sounddevice
sys.modules["sounddevice"] = MagicMock()

# App imports must be after the mock
from src.gui.widgets.noise_profiler import NoiseAnalysisWorker, NoiseProfiler, NoiseProfilerWidget  # noqa: E402


def test_noise_profiler_offloading(qtbot):
    # Mock AudioEngine
    audio_engine = MagicMock()
    audio_engine.sample_rate = 48000
    audio_engine.calibration = MagicMock()
    audio_engine.calibration.get_input_offset_db.return_value = 0.0

    # Create Module
    module = NoiseProfiler(audio_engine)
    module.process_data = MagicMock(return_value=None)

    # Create Widget
    # widget needs to be created on main thread (qtbot does this implicitly)
    widget = NoiseProfilerWidget(module)
    qtbot.addWidget(widget)

    # Mock ThreadPool
    widget.thread_pool = MagicMock(spec=QThreadPool)

    # Simulate Running State
    module.is_running = True

    # Trigger Update
    widget.update_analysis()

    # Assertions
    # 1. process_data should NOT be called synchronously
    module.process_data.assert_not_called()

    # 2. ThreadPool.start should be called with a Worker
    widget.thread_pool.start.assert_called_once()
    worker_arg = widget.thread_pool.start.call_args[0][0]
    assert isinstance(worker_arg, NoiseAnalysisWorker)


def test_worker_error_signal(qtbot):
    # Mock AudioEngine
    audio_engine = MagicMock()
    module = NoiseProfiler(audio_engine)

    # Mock process_data to raise exception
    module.process_data = MagicMock(side_effect=ValueError("Test Error"))

    worker = NoiseAnalysisWorker(module, 0, "dBV", False)

    # Check if 'error' signal exists
    if not hasattr(worker.signals, "error"):
        pytest.fail("NoiseAnalysisSignals has no 'error' signal")

    # Mock signal slots
    mock_error = MagicMock()
    worker.signals.error.connect(mock_error)

    mock_finished = MagicMock()
    worker.signals.finished.connect(mock_finished)

    # Run worker synchronously
    worker.run()

    # Assertions
    mock_finished.assert_called_once()
    mock_error.assert_called_with("Test Error")

from unittest.mock import MagicMock, patch

# Ensure sounddevice is mocked (handled by conftest.py if running via pytest, but double check)
# We rely on pytest's conftest.py

from src.gui.widgets.noise_profiler import NoiseProfiler, NoiseAnalysisWorker

def test_worker_exception_logging():
    """
    Verify that exceptions in NoiseAnalysisWorker.run are logged using logger.error with exc_info=True,
    and that the error signal is emitted.
    """
    # Mock AudioEngine
    mock_engine = MagicMock()

    # Initialize Module
    module = NoiseProfiler(mock_engine)

    # Mock process_data to raise an exception
    test_exception = ValueError("Simulated Crash")
    module.process_data = MagicMock(side_effect=test_exception)

    # Create Worker
    # We don't need real channel_idx etc for this test as process_data is mocked
    worker = NoiseAnalysisWorker(module, channel_idx=0, unit_mode="dBV", apply_gain=False)

    # Connect signals
    error_slot = MagicMock()
    worker.signals.error.connect(error_slot)

    # Mock the logger in the module
    # We use 'create=True' so that if the logger doesn't exist yet (before implementation), we don't crash immediately,
    # though the code under test won't call it if it's not implemented.
    with patch('src.gui.widgets.noise_profiler.logger', create=True) as mock_logger:
        # Run worker directly
        worker.run()

        # Check if error signal was emitted
        error_slot.assert_called_once_with("Simulated Crash")

        # Check if logger.error was called
        # This assertion will fail if the code uses print() instead of logger
        assert mock_logger.error.called, "logger.error should be called"

        # Verify arguments
        args, kwargs = mock_logger.error.call_args
        # The message should contain the exception string
        assert "Error in NoiseAnalysisWorker" in args[0]
        assert "Simulated Crash" in args[0]
        # exc_info should be True to log traceback
        assert kwargs.get('exc_info') is True, "exc_info=True is required for full traceback"


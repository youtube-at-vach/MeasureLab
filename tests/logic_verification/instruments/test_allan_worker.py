import sys
from unittest.mock import MagicMock, patch
import pytest
import numpy as np

# Prepare mocks
mock_qt_core = MagicMock()


class MockQRunnable:
    def __init__(self):
        pass


class MockQObject:
    def __init__(self):
        pass


mock_qt_core.QRunnable = MockQRunnable
mock_qt_core.QObject = MockQObject
mock_qt_core.pyqtSignal = MagicMock(side_effect=lambda *args: MagicMock())

mock_modules = {
    "PyQt6": MagicMock(),
    "PyQt6.QtCore": mock_qt_core,
    "PyQt6.QtGui": MagicMock(),
    "PyQt6.QtWidgets": MagicMock(),
    "pyqtgraph": MagicMock(),
}


@pytest.fixture(autouse=True)
def mock_gui_deps():
    with patch.dict(sys.modules, mock_modules):
        # We must remove the module under test from sys.modules to force reload with mocks
        if "src.gui.widgets.frequency_counter" in sys.modules:
            del sys.modules["src.gui.widgets.frequency_counter"]
        yield


def test_worker_logic_basic():
    # Import inside the test/fixture context
    from src.gui.widgets.frequency_counter import AllanWorker

    np.random.seed(42)
    noise = np.random.normal(1000, 1.0, 1000)
    history = list(noise)

    worker = AllanWorker(history, update_interval_ms=100, display_mode="frequency")

    # Check signals
    # Since we reload module, AllanWorkerSignals class is recreated.
    # pyqtSignal (mock) is called.

    # We need to access the signal on the instance.
    # self.signals.result is the mock returned by pyqtSignal

    worker.run()

    worker.signals.result.emit.assert_called_once()
    args = worker.signals.result.emit.call_args[0]
    taus, devs = args

    assert len(taus) > 5
    assert len(devs) > 5


def test_worker_empty_history():
    from src.gui.widgets.frequency_counter import AllanWorker

    worker = AllanWorker([], 100, "frequency")

    worker.run()

    worker.signals.result.emit.assert_called_once_with([], [])


def test_worker_period_mode():
    from src.gui.widgets.frequency_counter import AllanWorker

    freqs = [100.0] * 100
    worker = AllanWorker(freqs, 100, "period")

    worker.run()

    worker.signals.result.emit.assert_called_once()
    args = worker.signals.result.emit.call_args[0]
    taus, devs = args

    assert len(taus) > 0
    assert devs[0] == 0.0

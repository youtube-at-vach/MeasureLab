import pytest
from src.core.session_manager import SessionManager


@pytest.fixture
def session_manager():
    """Fixture to provide a clean SessionManager instance."""
    return SessionManager()


def test_initial_state(session_manager):
    """Verify that a new SessionManager is initialized correctly."""
    assert session_manager.current_module is None
    assert session_manager.is_running is False
    assert session_manager.results == []


def test_set_module(session_manager):
    """Verify that set_module correctly updates the current_module."""
    dummy_module = "dummy_module"
    session_manager.set_module(dummy_module)
    assert session_manager.current_module == dummy_module


def test_set_module_none(session_manager):
    """Verify that set_module(None) clears the current_module."""
    session_manager.set_module("temp_module")
    session_manager.set_module(None)
    assert session_manager.current_module is None


def test_start_measurement_success(session_manager):
    """Verify that start_measurement sets is_running to True when a module is set."""
    session_manager.set_module("valid_module")
    session_manager.start_measurement()
    assert session_manager.is_running is True


def test_start_measurement_no_module(session_manager):
    """Verify that start_measurement does NOT set is_running to True if no module is set."""
    # current_module is None by default
    session_manager.start_measurement()
    assert session_manager.is_running is False


def test_stop_measurement(session_manager):
    """Verify that stop_measurement sets is_running to False."""
    session_manager.set_module("valid_module")
    session_manager.start_measurement()
    assert session_manager.is_running is True

    session_manager.stop_measurement()
    assert session_manager.is_running is False


def test_stop_measurement_idempotent(session_manager):
    """Verify that calling stop_measurement multiple times is safe."""
    session_manager.set_module("valid_module")
    session_manager.start_measurement()
    session_manager.stop_measurement()
    assert session_manager.is_running is False

    # Call again
    session_manager.stop_measurement()
    assert session_manager.is_running is False


def test_start_measurement_idempotent(session_manager):
    """Verify that calling start_measurement multiple times keeps is_running True."""
    session_manager.set_module("valid_module")
    session_manager.start_measurement()
    assert session_manager.is_running is True

    # Call again
    session_manager.start_measurement()
    assert session_manager.is_running is True


def test_change_module_while_running(session_manager):
    """Verify behavior when changing module while running."""
    session_manager.set_module("module_a")
    session_manager.start_measurement()
    assert session_manager.is_running is True

    session_manager.set_module("module_b")
    assert session_manager.current_module == "module_b"
    # Assuming implementation allows changing module while running without stopping
    assert session_manager.is_running is True

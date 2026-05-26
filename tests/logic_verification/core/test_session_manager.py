import pytest
from src.core.session_manager import SessionManager


@pytest.fixture
def session_manager():
    """Fixture to provide a clean SessionManager instance."""
    return SessionManager()


def test_start_measurement_success(session_manager):
    """Verify that start_measurement sets is_running to True when a module is set."""
    session_manager.current_module = "valid_module"
    session_manager.start_measurement()
    assert session_manager.is_running is True


def test_start_measurement_no_module(session_manager):
    """Verify that start_measurement does NOT set is_running to True if no module is set."""
    # current_module is None by default
    session_manager.start_measurement()
    assert session_manager.is_running is False


def test_stop_measurement(session_manager):
    """Verify that stop_measurement sets is_running to False."""
    session_manager.current_module = "valid_module"
    session_manager.start_measurement()
    assert session_manager.is_running is True

    session_manager.stop_measurement()
    assert session_manager.is_running is False


def test_stop_measurement_idempotent(session_manager):
    """Verify that calling stop_measurement multiple times is safe."""
    session_manager.current_module = "valid_module"
    session_manager.start_measurement()
    session_manager.stop_measurement()
    assert session_manager.is_running is False

    # Call again
    session_manager.stop_measurement()
    assert session_manager.is_running is False


def test_start_measurement_idempotent(session_manager):
    """Verify that calling start_measurement multiple times keeps is_running True."""
    session_manager.current_module = "valid_module"
    session_manager.start_measurement()
    assert session_manager.is_running is True

    # Call again
    session_manager.start_measurement()
    assert session_manager.is_running is True


def test_change_module_while_running(session_manager):
    """Verify behavior when changing module while running."""
    session_manager.current_module = "module_a"
    session_manager.start_measurement()
    assert session_manager.is_running is True

    session_manager.current_module = "module_b"
    assert session_manager.current_module == "module_b"
    # Assuming implementation allows changing module while running without stopping
    assert session_manager.is_running is True

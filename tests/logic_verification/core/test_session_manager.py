import pytest
from src.core.session_manager import SessionManager


@pytest.fixture
def session_manager():
    return SessionManager()


def test_session_manager_lifecycle(session_manager):
    # Default state
    assert session_manager.is_running is False

    # Starting without module does not run
    session_manager.start_measurement()
    assert session_manager.is_running is False

    # Starting with module runs
    session_manager.current_module = "valid_module"
    session_manager.start_measurement()
    assert session_manager.is_running is True

    # Changing module while running is allowed and keeps it running
    session_manager.current_module = "module_b"
    assert session_manager.is_running is True

    # Stopping
    session_manager.stop_measurement()
    assert session_manager.is_running is False

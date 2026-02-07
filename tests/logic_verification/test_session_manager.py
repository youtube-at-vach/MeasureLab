from src.core.session_manager import SessionManager

def test_initialization():
    """Verify that a new SessionManager is initialized correctly."""
    manager = SessionManager()
    assert manager.current_module is None
    assert manager.is_running is False
    assert manager.results == []

def test_set_module():
    """Verify that set_module correctly updates the current_module."""
    manager = SessionManager()
    dummy_module = "dummy_module"
    manager.set_module(dummy_module)
    assert manager.current_module == dummy_module

def test_start_measurement_with_module():
    """Verify that start_measurement sets is_running to True when a module is set."""
    manager = SessionManager()
    manager.set_module("some_module")
    manager.start_measurement()
    assert manager.is_running is True

def test_start_measurement_without_module():
    """Verify that start_measurement does NOT set is_running to True if no module is set."""
    manager = SessionManager()
    # current_module is None by default
    manager.start_measurement()
    assert manager.is_running is False

def test_stop_measurement():
    """Verify that stop_measurement sets is_running to False."""
    manager = SessionManager()
    manager.set_module("some_module")
    manager.start_measurement()
    assert manager.is_running is True

    manager.stop_measurement()
    assert manager.is_running is False

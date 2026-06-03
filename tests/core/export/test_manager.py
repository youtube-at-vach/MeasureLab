from src.core.export.manager import ExportManager
from src.core.export.json_exporter import JsonTraceExporter
from src.core.export.csv_exporter import CsvTraceExporter
from src.core.export.base import BaseTraceExporter


def test_export_manager_instance_is_singleton():
    """Test that multiple calls to ExportManager.instance() return the same object."""
    # Force reset to ensure clean state
    ExportManager._instance = None

    instance1 = ExportManager.instance()
    instance2 = ExportManager.instance()

    assert instance1 is instance2


def test_export_manager_initializes_with_default_exporters():
    """Test that the instance initializes with JSON and CSV exporters."""
    ExportManager._instance = None
    manager = ExportManager.instance()

    formats = manager.get_supported_formats()
    assert "json" in formats
    assert "csv" in formats

    assert isinstance(manager.get_exporter("json"), JsonTraceExporter)
    assert isinstance(manager.get_exporter("csv"), CsvTraceExporter)


def test_export_manager_register_and_get_exporter():
    """Test registering a new exporter and retrieving it."""
    manager = ExportManager()

    class DummyExporter(BaseTraceExporter):
        @property
        def format_id(self) -> str:
            return "dummy"

        @property
        def name(self) -> str:
            return "Dummy Format"

        @property
        def file_filter(self) -> str:
            return "Dummy Files (*.dummy)"

        @property
        def default_extension(self) -> str:
            return ".dummy"

        def export_traces(self, filepath, traces, options) -> bool:
            return True

    dummy = DummyExporter()
    manager.register_exporter(dummy)

    assert "dummy" in manager.get_supported_formats()
    assert manager.get_exporter("dummy") is dummy

    all_exporters = manager.get_all_exporters()
    assert "dummy" in all_exporters
    assert all_exporters["dummy"] is dummy


def test_export_manager_get_nonexistent_exporter():
    """Test getting an exporter that hasn't been registered."""
    manager = ExportManager()
    assert manager.get_exporter("nonexistent") is None


def test_export_manager_init_idempotent():
    """Test that calling __init__ multiple times does not re-initialize the exporters."""
    manager = ExportManager()

    # Store the original exporters dict
    original_exporters = manager._exporters

    # Call __init__ again, which should return early due to _initialized flag
    manager.__init__()

    # The exporters dict should be the exact same object, not a new one
    assert manager._exporters is original_exporters


def test_export_manager_get_all_exporters():
    """Test get_all_exporters returns a copy of the exporters dictionary."""
    ExportManager._instance = None
    manager = ExportManager.instance()

    exporters = manager.get_all_exporters()
    assert "json" in exporters
    assert "csv" in exporters

    # Verify it returns a copy, modifying it doesn't affect internal state
    exporters["dummy"] = "fake_exporter"
    assert "dummy" not in manager._exporters

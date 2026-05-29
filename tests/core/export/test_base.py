import pytest
from typing import List, Dict, Any
from src.core.export.base import BaseTraceExporter


def test_base_trace_exporter_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseTraceExporter()


def test_incomplete_subclass_cannot_be_instantiated():
    class IncompleteExporter(BaseTraceExporter):
        @property
        def format_id(self) -> str:
            return "test"

    with pytest.raises(TypeError):
        IncompleteExporter()


def test_complete_subclass_can_be_instantiated():
    class CompleteExporter(BaseTraceExporter):
        @property
        def format_id(self) -> str:
            _ = super().format_id
            return "test"

        @property
        def name(self) -> str:
            _ = super().name
            return "Test Format"

        @property
        def file_filter(self) -> str:
            _ = super().file_filter
            return "Test Files (*.test)"

        @property
        def default_extension(self) -> str:
            _ = super().default_extension
            return ".test"

        def export_traces(self, filepath: str, traces: List[Any], options: Dict[str, Any]) -> bool:
            super().export_traces(filepath, traces, options)
            return True

    exporter = CompleteExporter()
    assert exporter.format_id == "test"
    assert exporter.name == "Test Format"
    assert exporter.file_filter == "Test Files (*.test)"
    assert exporter.default_extension == ".test"
    assert exporter.export_traces("path", [], {}) is True

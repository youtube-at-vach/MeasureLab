import logging
from unittest.mock import patch

from src.core.export.csv_exporter import CsvTraceExporter


def test_export_traces_error_path(caplog):
    exporter = CsvTraceExporter()
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        with caplog.at_level(logging.ERROR):
            result = exporter.export_traces("fake_path.csv", [], {})

    assert result is False
    assert "Failed to export traces to CSV" in caplog.text


def test_export_traces_success():
    exporter = CsvTraceExporter()
    with patch("builtins.open"):
        result = exporter.export_traces("fake_path.csv", [], {})

    assert result is True

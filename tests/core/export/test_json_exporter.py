import json
import logging
from unittest.mock import patch, mock_open

from src.core.export.json_exporter import JsonTraceExporter
from src.core.comparison_manager import ComparisonTrace, AxisMetadata


def test_export_traces_error_path(caplog):
    exporter = JsonTraceExporter()
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        with caplog.at_level(logging.ERROR):
            result = exporter.export_traces("fake_path.json", [], {})

    assert result is False
    assert "Failed to export traces to JSON" in caplog.text


def test_export_traces_success():
    exporter = JsonTraceExporter()
    trace = ComparisonTrace(
        id="test_1",
        name="Test Trace",
        source_module="test",
        timestamp="2023-10-01",
        plot_type="time_series",
        x_axis=AxisMetadata("time", "s", "ms"),
        y_axis=AxisMetadata("voltage", "V", "V"),
        x_data=[0.0, 1.0, 2.0],
        y_data=[1.0, 2.0, 3.0],
    )

    mock_file = mock_open()
    with patch("builtins.open", mock_file):
        result = exporter.export_traces("fake_path.json", [trace], {})

    assert result is True

    # Verify file was written
    mock_file.assert_called_once_with("fake_path.json", "w", encoding="utf-8")

    # We can join all write calls to check the JSON structure
    handle = mock_file()
    written_data = "".join(call.args[0] for call in handle.write.call_args_list)
    parsed_json = json.loads(written_data)

    assert parsed_json["version"] == "1.0"
    assert len(parsed_json["traces"]) == 1
    assert parsed_json["traces"][0]["id"] == "test_1"
    assert parsed_json["traces"][0]["x_data"] == [0.0, 1.0, 2.0]
    assert parsed_json["traces"][0]["y_data"] == [1.0, 2.0, 3.0]

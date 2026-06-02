import csv
import logging
import pytest
from unittest.mock import patch
from src.core.comparison_manager import ComparisonTrace, AxisMetadata
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


@pytest.fixture
def sample_traces():
    t1 = ComparisonTrace(
        id="trace_1",
        name="Trace 1",
        source_module="module_a",
        timestamp="2023-01-01T10:00:00",
        plot_type="frequency_response",
        x_axis=AxisMetadata("frequency", "Hz", "Hz", False),
        y_axis=AxisMetadata("voltage", "V", "dBV", False),
        x_data=[10.0, 20.0, 30.0],
        y_data=[-10.0, -20.0, -30.0],
    )

    t2 = ComparisonTrace(
        id="trace_2",
        name="Trace 2",
        source_module="module_b",
        timestamp="2023-01-01T10:05:00",
        plot_type="frequency_response",
        x_axis=AxisMetadata("frequency", "Hz", "kHz", False),
        y_axis=AxisMetadata("ratio", "linear", "%", False),
        y2_axis=AxisMetadata("phase", "deg", "deg", False),
        x_data=[15.0, 25.0],
        y_data=[1.0, 2.0],
        y2_data=[45.0, 90.0],
    )

    t_empty = ComparisonTrace(
        id="trace_empty",
        name="Trace Empty",
        source_module="module_c",
        timestamp="2023-01-01T10:10:00",
        plot_type="frequency_response",
        x_axis=AxisMetadata("time", "s", "ms", False),
        y_axis=AxisMetadata("voltage", "V", "V", False),
        x_data=[],
        y_data=[],
    )

    t_empty_y2 = ComparisonTrace(
        id="trace_empty_y2",
        name="Trace Empty Y2",
        source_module="module_d",
        timestamp="2023-01-01T10:15:00",
        plot_type="frequency_response",
        x_axis=AxisMetadata("time", "s", "ms", False),
        y_axis=AxisMetadata("voltage", "V", "V", False),
        y2_axis=AxisMetadata("phase", "deg", "deg", False),
        x_data=[],
        y_data=[],
        y2_data=[],
    )

    return [t1, t2, t_empty, t_empty_y2]


def test_exporter_properties():
    exporter = CsvTraceExporter()
    assert exporter.format_id == "csv"
    assert "CSV" in exporter.name
    assert "csv" in exporter.file_filter.lower()
    assert exporter.default_extension == ".csv"


def test_export_merged_union(tmp_path, sample_traces):
    exporter = CsvTraceExporter()
    filepath = str(tmp_path / "merged_union.csv")

    options = {
        "layout": "merged",
        "reference_trace_id": "union",
        "include_headers": True,
        "include_metadata": True,
    }

    assert exporter.export_traces(filepath, sample_traces, options) is True

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        lines = list(reader)

    assert lines[0][0] == "# MeasureLab Exported Traces"

    header_idx = 0
    for i, line in enumerate(lines):
        if line and line[0] == "Frequency (Hz)":
            header_idx = i
            break

    header = lines[header_idx]
    assert "Frequency (Hz)" in header[0]
    assert "Trace 1 - Voltage (dBV)" in header[1]
    assert "Trace 2 - Ratio (%)" in header[2]
    assert "Trace 2 - Phase (deg)" in header[3]
    assert "Trace Empty - Voltage (V)" in header[4]

    x_vals = [float(row[0]) for row in lines[header_idx + 1 :] if row and row[0].replace(".", "", 1).isdigit()]
    assert x_vals == [10.0, 15.0, 20.0, 25.0, 30.0]

    row_15 = [row for row in lines[header_idx + 1 :] if float(row[0]) == 15.0][0]
    assert float(row_15[1]) == -15.0
    assert row_15[4] == ""
    assert row_15[5] == ""


def test_export_merged_specific_ref(tmp_path, sample_traces):
    exporter = CsvTraceExporter()
    filepath = str(tmp_path / "merged_ref.csv")

    options = {
        "layout": "merged",
        "reference_trace_id": "trace_2",
        "include_headers": False,
        "include_metadata": False,
    }

    assert exporter.export_traces(filepath, sample_traces, options) is True

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        lines = list(reader)

    x_vals = [float(row[0]) for row in lines if row]
    assert x_vals == [15.0, 25.0]


def test_export_merged_empty_traces(tmp_path):
    exporter = CsvTraceExporter()
    filepath = str(tmp_path / "empty.csv")

    options = {"layout": "merged"}
    assert exporter.export_traces(filepath, [], options) is True

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2


def test_export_merged_all_empty_x(tmp_path, sample_traces):
    exporter = CsvTraceExporter()
    filepath = str(tmp_path / "empty_x.csv")

    options = {"layout": "merged"}
    assert exporter.export_traces(filepath, [sample_traces[2]], options) is True

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Trace Empty" in content


def test_export_independent(tmp_path, sample_traces):
    exporter = CsvTraceExporter()
    filepath = str(tmp_path / "independent.csv")

    options = {
        "layout": "independent",
        "delimiter": "tab",
        "include_headers": True,
        "include_metadata": False,
    }

    assert exporter.export_traces(filepath, sample_traces, options) is True

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="	")
        lines = list(reader)

    header = lines[0]
    assert header[0] == "Trace 1_Frequency (Hz)"
    assert header[1] == "Trace 1_Voltage (dBV)"
    assert header[2] == "Trace 2_Frequency (kHz)"
    assert header[3] == "Trace 2_Ratio (%)"
    assert header[4] == "Trace 2_Phase (deg)"
    assert header[5] == "Trace Empty_Time (ms)"
    assert header[6] == "Trace Empty_Voltage (V)"

    assert len(lines[1:]) == 3

    row1 = lines[1]
    assert float(row1[0]) == 10.0
    assert float(row1[1]) == -10.0
    assert float(row1[2]) == 15.0
    assert float(row1[3]) == 1.0
    assert float(row1[4]) == 45.0
    assert row1[5] == ""
    assert row1[6] == ""

    row3 = lines[3]
    assert float(row3[0]) == 30.0
    assert float(row3[1]) == -30.0
    assert row3[2] == ""
    assert row3[3] == ""
    assert row3[4] == ""


def test_export_csv_injection_prevention(tmp_path, sample_traces):
    # Modify trace name to simulate CSV injection
    sample_traces[0].name = "=cmd|' /C calc'!A0"

    exporter = CsvTraceExporter()
    filepath = str(tmp_path / "injection.csv")

    options = {
        "layout": "merged",
        "include_headers": True,
        "include_metadata": False,
    }

    assert exporter.export_traces(filepath, sample_traces, options) is True

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        lines = list(reader)

    header = lines[0]
    # Check that the malicious trace name was sanitized by prepending an apostrophe
    assert header[1].startswith("'=")
    assert header[1] == "'=cmd|' /C calc'!A0 - Voltage (dBV)"

"""The trace export dialog writes CSV and JSON files from supplied data."""

import csv
import json
from unittest.mock import patch

import pytest

from src.core.export.trace import AxisMetadata, ExportTrace
from src.gui.widgets.export_dialog import ExportSettingsDialog


@pytest.mark.parametrize("format_id", ["csv", "json"])
def test_export_dialog_writes_selected_trace(qtbot, tmp_path, format_id):
    trace = ExportTrace(
        id="trace-1",
        name="Measurement",
        source_module="Example",
        timestamp="2026-09-25T00:00:00",
        plot_type="time_series",
        x_axis=AxisMetadata("time", "s", "s"),
        y_axis=AxisMetadata("voltage", "V", "V"),
        x_data=[0.0, 1.0],
        y_data=[1.0, 2.0],
    )
    dialog = ExportSettingsDialog([trace])
    qtbot.addWidget(dialog)
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(format_id))
    path = tmp_path / f"measurement.{format_id}"
    dialog.path_edit.setText(str(path))

    with patch("src.gui.widgets.export_dialog.QMessageBox.information"):
        dialog.do_export()

    assert path.exists()
    if format_id == "csv":
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.reader(stream))
        assert ["0.0", "1.0"] in rows
        assert ["1.0", "2.0"] in rows
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["traces"][0]["y_data"] == [1.0, 2.0]

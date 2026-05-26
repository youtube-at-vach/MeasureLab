import csv
import logging
import numpy as np
from typing import List, Dict, Any
from src.core.comparison_manager import ComparisonTrace
from src.core.localization import tr
from .base import BaseTraceExporter

logger = logging.getLogger(__name__)


class CsvTraceExporter(BaseTraceExporter):
    @property
    def format_id(self) -> str:
        return "csv"

    @property
    def name(self) -> str:
        return tr("CSV (Comma Separated Values)")

    @property
    def file_filter(self) -> str:
        return tr("CSV Files (*.csv);;Text Files (*.txt)")

    @property
    def default_extension(self) -> str:
        return ".csv"

    def export_traces(self, filepath: str, traces: List[ComparisonTrace], options: Dict[str, Any]) -> bool:
        delimiter = "," if options.get("delimiter", "comma") == "comma" else "\t"
        layout = options.get("layout", "merged")  # "independent" or "merged"
        include_headers = options.get("include_headers", True)
        include_metadata = options.get("include_metadata", True)

        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f, delimiter=delimiter)

                # Write metadata header if requested
                if include_metadata:
                    writer.writerow(["# MeasureLab Exported Traces"])
                    for t in traces:
                        writer.writerow([f"# Trace: {t.name} (Source: {t.source_module}, Timestamp: {t.timestamp})"])
                    writer.writerow([])  # empty line separator

                if layout == "merged":
                    self._export_merged(writer, traces, include_headers, options)
                else:
                    self._export_independent(writer, traces, include_headers)
            return True
        except Exception as e:
            logger.error(f"Failed to export traces to CSV: {e}", exc_info=True)
            return False

    def _export_merged(self, writer, traces: List[ComparisonTrace], include_headers: bool, options: Dict[str, Any]):
        ref_id = options.get("reference_trace_id", "union")

        # 1. Determine common X grid
        x_grid = None
        if ref_id != "union":
            # Use specific trace's X grid
            for t in traces:
                if t.id == ref_id:
                    x_grid = np.array(t.x_data, dtype=float)
                    break

        if x_grid is None:
            # Union of all X axes
            all_x = []
            for t in traces:
                all_x.extend(t.x_data)
            if not all_x:
                return
            x_grid = np.unique(all_x)
            x_grid.sort()

        # 2. Write Headers
        if include_headers:
            # Find the first trace with dimension information for X Axis unit
            x_dim_str = tr("X_Axis")
            if traces:
                first_t = traces[0]
                dim_cap = tr(first_t.x_axis.dimension).capitalize()
                unit = first_t.x_axis.display_unit
                x_dim_str = f"{dim_cap} ({unit})" if unit else dim_cap

            headers = [x_dim_str]
            for t in traces:
                dim_cap = tr(t.y_axis.dimension).capitalize()
                unit = t.y_axis.display_unit
                headers.append(f"{t.name} - {dim_cap} ({unit})" if unit else f"{t.name} - {dim_cap}")

                if t.y2_data is not None and t.y2_axis:
                    dim_cap2 = tr(t.y2_axis.dimension).capitalize()
                    unit2 = t.y2_axis.display_unit
                    headers.append(f"{t.name} - {dim_cap2} ({unit2})" if unit2 else f"{t.name} - {dim_cap2}")
            writer.writerow(headers)

        # 3. Interpolate and Write Data
        for x_val in x_grid:
            row = [x_val]
            for t in traces:
                orig_x = np.array(t.x_data, dtype=float)
                orig_y = np.array(t.y_data, dtype=float)

                # Check for empty data safely
                if len(orig_x) == 0:
                    row.append("")
                    if t.y2_data is not None:
                        row.append("")
                    continue

                y_val = np.interp(x_val, orig_x, orig_y)
                row.append(y_val)

                if t.y2_data is not None:
                    orig_y2 = np.array(t.y2_data, dtype=float)
                    y2_val = np.interp(x_val, orig_x, orig_y2)
                    row.append(y2_val)
            writer.writerow(row)

    def _export_independent(self, writer, traces: List[ComparisonTrace], include_headers: bool):
        # 1. Write Headers
        if include_headers:
            headers = []
            for t in traces:
                x_dim = tr(t.x_axis.dimension).capitalize()
                x_unit = t.x_axis.display_unit
                x_lbl = f"{t.name}_{x_dim} ({x_unit})" if x_unit else f"{t.name}_{x_dim}"

                y_dim = tr(t.y_axis.dimension).capitalize()
                y_unit = t.y_axis.display_unit
                y_lbl = f"{t.name}_{y_dim} ({y_unit})" if y_unit else f"{t.name}_{y_dim}"

                headers.extend([x_lbl, y_lbl])

                if t.y2_data is not None and t.y2_axis:
                    y2_dim = tr(t.y2_axis.dimension).capitalize()
                    y2_unit = t.y2_axis.display_unit
                    y2_lbl = f"{t.name}_{y2_dim} ({y2_unit})" if y2_unit else f"{t.name}_{y2_dim}"
                    headers.append(y2_lbl)
            writer.writerow(headers)

        # 2. Find maximum row length
        max_len = max([len(t.x_data) for t in traces]) if traces else 0

        # 3. Write Data Row by Row
        for i in range(max_len):
            row: List[Any] = []
            for t in traces:
                if i < len(t.x_data):
                    row.extend([t.x_data[i], t.y_data[i]])
                    if t.y2_data is not None:
                        row.append(t.y2_data[i])
                else:
                    row.extend(["", ""])
                    if t.y2_data is not None:
                        row.append("")
            writer.writerow(row)

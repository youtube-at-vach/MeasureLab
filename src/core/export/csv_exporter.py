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

    def _sanitize_csv_field(self, field: str) -> str:
        """Sanitizes a string to prevent CSV injection (Formula Injection)."""
        field_str = str(field)
        field_str = field_str.replace("\n", " ").replace("\r", " ")
        if field_str.startswith(("=", "+", "-", "@", "\t")):
            return f"'{field_str}"
        return field_str

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
                        safe_name = self._sanitize_csv_field(t.name)
                        safe_source = self._sanitize_csv_field(t.source_module)
                        writer.writerow([f"# Trace: {safe_name} (Source: {safe_source}, Timestamp: {t.timestamp})"])
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
            ref_trace = next((t for t in traces if t.id == ref_id), None)
            if ref_trace is not None:
                x_grid = np.array(ref_trace.x_data, dtype=float)

        if x_grid is None:
            # Union of all X axes
            x_arrays = [t.x_data for t in traces if len(t.x_data) > 0]
            if not x_arrays:
                return
            x_grid = np.unique(np.concatenate(x_arrays))

        # 2. Write Headers
        if include_headers:
            # Find the first trace with dimension information for X Axis unit
            x_dim_str = tr("X_Axis")
            if traces:
                first_t = traces[0]
                dim_cap = tr(first_t.x_axis.dimension).capitalize()
                unit = first_t.x_axis.display_unit
                x_dim_str = f"{dim_cap} ({unit})" if unit else dim_cap

            headers = [self._sanitize_csv_field(x_dim_str)]
            # Cache formatted axis strings
            axis_cache = {}
            for t in traces:
                y_dim_key = (t.y_axis.dimension, t.y_axis.display_unit)
                if y_dim_key not in axis_cache:
                    dim_cap = tr(t.y_axis.dimension).capitalize()
                    unit = t.y_axis.display_unit
                    axis_cache[y_dim_key] = f" - {dim_cap} ({unit})" if unit else f" - {dim_cap}"

                y_lbl = f"{t.name}{axis_cache[y_dim_key]}"
                headers.append(self._sanitize_csv_field(y_lbl))

                if t.y2_data is not None and t.y2_axis:
                    y2_dim_key = (t.y2_axis.dimension, t.y2_axis.display_unit)
                    if y2_dim_key not in axis_cache:
                        dim_cap2 = tr(t.y2_axis.dimension).capitalize()
                        unit2 = t.y2_axis.display_unit
                        axis_cache[y2_dim_key] = f" - {dim_cap2} ({unit2})" if unit2 else f" - {dim_cap2}"

                    y2_lbl = f"{t.name}{axis_cache[y2_dim_key]}"
                    headers.append(self._sanitize_csv_field(y2_lbl))
            writer.writerow(headers)

        # 3. Interpolate and prepare columns directly
        cols = [x_grid]

        cached_x_id = None
        cached_orig_x = None
        is_same_as_grid = False

        for t in traces:
            if len(t.x_data) == 0:
                empty_col = [""] * len(x_grid)
                cols.append(empty_col)
                if t.y2_data is not None:
                    cols.append(empty_col)
                continue

            x_id = id(t.x_data)
            if x_id != cached_x_id:
                orig_x = np.array(t.x_data, dtype=float)
                cached_x_id = x_id
                cached_orig_x = orig_x
                is_same_as_grid = len(orig_x) == len(x_grid) and np.array_equal(orig_x, x_grid)
            else:
                assert cached_orig_x is not None
                orig_x = cached_orig_x

            if is_same_as_grid:
                cols.append(t.y_data)
                if t.y2_data is not None:
                    cols.append(t.y2_data)
            else:
                orig_y = np.array(t.y_data, dtype=float)
                cols.append(np.interp(x_grid, orig_x, orig_y))

                if t.y2_data is not None:
                    orig_y2 = np.array(t.y2_data, dtype=float)
                    cols.append(np.interp(x_grid, orig_x, orig_y2))

        writer.writerows(zip(*cols, strict=False))

    def _export_independent(self, writer, traces: List[ComparisonTrace], include_headers: bool):
        # 1. Write Headers
        if include_headers:
            headers = []
            axis_cache = {}
            for t in traces:
                x_dim_key = (t.x_axis.dimension, t.x_axis.display_unit)
                if x_dim_key not in axis_cache:
                    x_dim = tr(t.x_axis.dimension).capitalize()
                    x_unit = t.x_axis.display_unit
                    axis_cache[x_dim_key] = f"_{x_dim} ({x_unit})" if x_unit else f"_{x_dim}"
                x_lbl = f"{t.name}{axis_cache[x_dim_key]}"

                y_dim_key = (t.y_axis.dimension, t.y_axis.display_unit)
                if y_dim_key not in axis_cache:
                    y_dim = tr(t.y_axis.dimension).capitalize()
                    y_unit = t.y_axis.display_unit
                    axis_cache[y_dim_key] = f"_{y_dim} ({y_unit})" if y_unit else f"_{y_dim}"
                y_lbl = f"{t.name}{axis_cache[y_dim_key]}"

                headers.extend([self._sanitize_csv_field(x_lbl), self._sanitize_csv_field(y_lbl)])

                if t.y2_data is not None and t.y2_axis:
                    y2_dim_key = (t.y2_axis.dimension, t.y2_axis.display_unit)
                    if y2_dim_key not in axis_cache:
                        y2_dim = tr(t.y2_axis.dimension).capitalize()
                        y2_unit = t.y2_axis.display_unit
                        axis_cache[y2_dim_key] = f"_{y2_dim} ({y2_unit})" if y2_unit else f"_{y2_dim}"
                    y2_lbl = f"{t.name}{axis_cache[y2_dim_key]}"
                    headers.append(self._sanitize_csv_field(y2_lbl))
            writer.writerow(headers)

        # 2. Write Data Row by Row
        import itertools

        columns = []
        for t in traces:
            columns.append(t.x_data)
            columns.append(t.y_data)
            if t.y2_data is not None:
                columns.append(t.y2_data)

        writer.writerows(itertools.zip_longest(*columns, fillvalue=""))

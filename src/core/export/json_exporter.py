import json
import logging
from typing import List, Dict, Any
from src.core.comparison_manager import ComparisonTrace
from src.core.localization import tr
from .base import BaseTraceExporter

logger = logging.getLogger(__name__)


class JsonTraceExporter(BaseTraceExporter):
    @property
    def format_id(self) -> str:
        return "json"

    @property
    def name(self) -> str:
        return tr("MeasureLab Comparison Files (*.mlcomp)")

    @property
    def file_filter(self) -> str:
        return tr("MeasureLab Comparison Files (*.mlcomp *.json)")

    @property
    def default_extension(self) -> str:
        return ".mlcomp"

    def export_traces(self, filepath: str, traces: List[ComparisonTrace], options: Dict[str, Any]) -> bool:
        try:
            export_data = [trace.to_dict() for trace in traces]

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0", "traces": export_data}, f, indent=4)
            logger.info(f"Exported {len(export_data)} traces to {filepath} using JsonTraceExporter")
            return True
        except Exception as e:
            logger.error(f"Failed to export traces to JSON: {e}", exc_info=True)
            return False

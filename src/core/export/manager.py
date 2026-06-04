import logging
from typing import Dict, Optional
from .base import BaseTraceExporter
from .json_exporter import JsonTraceExporter
from .csv_exporter import CsvTraceExporter

logger = logging.getLogger(__name__)


class ExportManager:
    _instance: Optional["ExportManager"] = None

    @classmethod
    def instance(cls) -> "ExportManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._exporters: Dict[str, BaseTraceExporter] = {}
        self._initialized = True

        # Register default exporters
        self.register_exporter(JsonTraceExporter())
        self.register_exporter(CsvTraceExporter())
        logger.info("ExportManager initialized with default exporters.")

    def register_exporter(self, exporter: BaseTraceExporter):
        self._exporters[exporter.format_id] = exporter
        logger.info(f"Registered exporter for format: '{exporter.format_id}'")

    def get_exporter(self, format_id: str) -> Optional[BaseTraceExporter]:
        return self._exporters.get(format_id)

    def get_all_exporters(self) -> Dict[str, BaseTraceExporter]:
        return self._exporters.copy()

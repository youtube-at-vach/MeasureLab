from abc import ABC, abstractmethod
from typing import List, Dict, Any
from src.core.comparison_manager import ComparisonTrace

class BaseTraceExporter(ABC):
    @property
    @abstractmethod
    def format_id(self) -> str:
        """Unique ID for the format (e.g. 'csv', 'json')"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name for UI (e.g. 'CSV (Comma Separated)')"""
        pass

    @property
    @abstractmethod
    def file_filter(self) -> str:
        """File filter for QFileDialog (e.g. 'CSV Files (*.csv)')"""
        pass

    @property
    @abstractmethod
    def default_extension(self) -> str:
        """Default file extension (e.g. '.csv')"""
        pass

    @abstractmethod
    def export_traces(self, filepath: str, traces: List[ComparisonTrace], options: Dict[str, Any]) -> bool:
        """Execute the export logic."""
        pass

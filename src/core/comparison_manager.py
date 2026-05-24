import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)


@dataclass
class CalibrationInfo:
    is_calibrated: bool = False
    input_sensitivity: float = 1.0
    applied_offset_db: float = 0.0
    reference_level: str = "relative"  # "relative" (FS/dBFS) or "absolute" (V/dBV/dBu)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationInfo":
        if not data:
            return cls()
        return cls(
            is_calibrated=bool(data.get("is_calibrated", False)),
            input_sensitivity=float(data.get("input_sensitivity", 1.0)),
            applied_offset_db=float(data.get("applied_offset_db", 0.0)),
            reference_level=str(data.get("reference_level", "relative")),
        )


@dataclass
class AxisMetadata:
    dimension: str  # "voltage", "frequency", "time", "impedance", "ratio", "sound_level", etc.
    base_unit: str  # "V", "Hz", "s", "ohm", "linear", etc.
    display_unit: str  # "dBV", "kHz", "ms", "ohm", "%", etc.
    is_log: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AxisMetadata":
        return cls(
            dimension=str(data.get("dimension", "")),
            base_unit=str(data.get("base_unit", "")),
            display_unit=str(data.get("display_unit", "")),
            is_log=bool(data.get("is_log", False)),
        )


@dataclass
class ComparisonTrace:
    id: str  # Unique trace ID
    name: str  # Display name
    source_module: str  # Generating module name
    timestamp: str  # Measurement timestamp (ISO format)
    plot_type: str  # "frequency_response", "time_series", "spectrum", "time_history", "xy_plot"

    # Axis definitions
    x_axis: AxisMetadata
    y_axis: AxisMetadata
    y2_axis: Optional[AxisMetadata] = None

    # Data arrays (Always stored as float list in base_unit)
    x_data: List[float] = field(default_factory=list)
    y_data: List[float] = field(default_factory=list)
    y2_data: Optional[List[float]] = None

    # Calibration info
    calibration: CalibrationInfo = field(default_factory=CalibrationInfo)

    # Extra parameters/settings
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_module": self.source_module,
            "timestamp": self.timestamp,
            "plot_type": self.plot_type,
            "x_axis": self.x_axis.to_dict(),
            "y_axis": self.y_axis.to_dict(),
            "y2_axis": self.y2_axis.to_dict() if self.y2_axis else None,
            "x_data": self.x_data,
            "y_data": self.y_data,
            "y2_data": self.y2_data,
            "calibration": self.calibration.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ComparisonTrace":
        # Convert list of floats (handling potential NumPy conversions upstream if necessary)
        def _clean_float_list(lst: Optional[List[Any]]) -> Optional[List[float]]:
            if lst is None:
                return None
            return [float(x) for x in lst]

        x_axis_data = data.get("x_axis")
        y_axis_data = data.get("y_axis")
        y2_axis_data = data.get("y2_axis")

        return cls(
            id=str(data.get("id", str(uuid.uuid4()))),
            name=str(data.get("name", "Trace")),
            source_module=str(data.get("source_module", "Unknown")),
            timestamp=str(data.get("timestamp", "")),
            plot_type=str(data.get("plot_type", "frequency_response")),
            x_axis=AxisMetadata.from_dict(x_axis_data) if x_axis_data else AxisMetadata("unknown", "", ""),
            y_axis=AxisMetadata.from_dict(y_axis_data) if y_axis_data else AxisMetadata("unknown", "", ""),
            y2_axis=AxisMetadata.from_dict(y2_axis_data) if y2_axis_data else None,
            x_data=_clean_float_list(data.get("x_data")) or [],
            y_data=_clean_float_list(data.get("y_data")) or [],
            y2_data=_clean_float_list(data.get("y2_data")),
            calibration=CalibrationInfo.from_dict(data.get("calibration", {})),
            metadata=dict(data.get("metadata", {})),
        )


class ComparisonManager(QObject):
    """
    Singleton class to manage the list of traces shared across all modules
    for comparative plotting.
    """

    trace_added = pyqtSignal(str)  # Emits trace_id
    trace_removed = pyqtSignal(str)  # Emits trace_id
    cleared = pyqtSignal()

    _instance: Optional["ComparisonManager"] = None

    @classmethod
    def instance(cls) -> "ComparisonManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        # Prevent double initialization if subclassed or called multiple times
        if hasattr(self, "_initialized"):
            return
        self._traces: Dict[str, ComparisonTrace] = {}
        self._initialized = True
        logger.info("ComparisonManager initialized.")

    def add_trace(self, trace: ComparisonTrace):
        """Add or update a comparison trace."""
        self._traces[trace.id] = trace
        logger.info(f"Trace added: '{trace.name}' (ID: {trace.id}, Source: {trace.source_module})")
        self.trace_added.emit(trace.id)

    def remove_trace(self, trace_id: str):
        """Remove a trace by its ID."""
        if trace_id in self._traces:
            name = self._traces[trace_id].name
            del self._traces[trace_id]
            logger.info(f"Trace removed: '{name}' (ID: {trace_id})")
            self.trace_removed.emit(trace_id)

    def get_trace(self, trace_id: str) -> Optional[ComparisonTrace]:
        """Retrieve a specific trace."""
        return self._traces.get(trace_id)

    def get_all_traces(self) -> Dict[str, ComparisonTrace]:
        """Get all currently loaded traces."""
        return self._traces.copy()

    def clear_all_traces(self):
        """Remove all loaded traces."""
        self._traces.clear()
        logger.info("All comparison traces cleared.")
        self.cleared.emit()

    def export_to_file(self, filepath: str, trace_ids: List[str]) -> bool:
        """
        Export selected traces to a JSON file.
        """
        try:
            export_data = []
            for tid in trace_ids:
                trace = self.get_trace(tid)
                if trace:
                    export_data.append(trace.to_dict())

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0", "traces": export_data}, f, indent=4)
            logger.info(f"Exported {len(export_data)} traces to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to export traces: {e}", exc_info=True)
            return False

    def import_from_file(self, filepath: str) -> List[str]:
        """
        Import traces from a JSON file and add them to the manager.
        Returns a list of newly imported trace IDs.
        """
        imported_ids = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = json.load(f)

            traces_data = content.get("traces", [])
            for tdata in traces_data:
                trace = ComparisonTrace.from_dict(tdata)
                # Ensure trace ID is unique if we're importing it again
                # but usually we want to preserve it unless it collides.
                # If ID exists, we can generate a new one or overwrite. Let's overwrite.
                self.add_trace(trace)
                imported_ids.append(trace.id)

            logger.info(f"Imported {len(imported_ids)} traces from {filepath}")
            return imported_ids
        except Exception as e:
            logger.error(f"Failed to import traces: {e}", exc_info=True)
            return []

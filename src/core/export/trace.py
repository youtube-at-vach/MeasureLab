"""Trace data shared by CSV/JSON exporters and their callers."""

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


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
class ExportTrace:
    id: str  # Unique trace ID
    name: str  # Display name
    source_module: str  # Generating module name
    timestamp: str  # Measurement timestamp (ISO format)
    plot_type: str  # "frequency_response", "time_series", "spectrum", "time_history", "xy_plot"

    # Axis definitions
    x_axis: AxisMetadata
    y_axis: AxisMetadata
    y2_axis: Optional[AxisMetadata] = None

    # Data arrays (Can be list or numpy array)
    x_data: Any = field(default_factory=list)
    y_data: Any = field(default_factory=list)
    y2_data: Optional[Any] = None

    # Calibration info
    calibration: CalibrationInfo = field(default_factory=CalibrationInfo)

    # Extra parameters/settings
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        import numpy as np

        # Convert data to numpy arrays of float to avoid repetitive conversions in drawing loop
        if not isinstance(self.x_data, np.ndarray):
            self.x_data = np.array(self.x_data, dtype=float) if self.x_data is not None else np.array([], dtype=float)
        elif self.x_data.dtype != float:
            self.x_data = self.x_data.astype(float)

        if not isinstance(self.y_data, np.ndarray):
            self.y_data = np.array(self.y_data, dtype=float) if self.y_data is not None else np.array([], dtype=float)
        elif self.y_data.dtype != float:
            self.y_data = self.y_data.astype(float)

        if self.y2_data is not None:
            if not isinstance(self.y2_data, np.ndarray):
                self.y2_data = np.array(self.y2_data, dtype=float)
            elif self.y2_data.dtype != float:
                self.y2_data = self.y2_data.astype(float)

    def to_dict(self) -> Dict[str, Any]:
        import numpy as np

        x_val = self.x_data.tolist() if isinstance(self.x_data, np.ndarray) else self.x_data
        y_val = self.y_data.tolist() if isinstance(self.y_data, np.ndarray) else self.y_data
        y2_val = self.y2_data.tolist() if isinstance(self.y2_data, np.ndarray) else self.y2_data

        return {
            "id": self.id,
            "name": self.name,
            "source_module": self.source_module,
            "timestamp": self.timestamp,
            "plot_type": self.plot_type,
            "x_axis": self.x_axis.to_dict(),
            "y_axis": self.y_axis.to_dict(),
            "y2_axis": self.y2_axis.to_dict() if self.y2_axis else None,
            "x_data": x_val,
            "y_data": y_val,
            "y2_data": y2_val,
            "calibration": self.calibration.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExportTrace":
        import numpy as np

        # Convert list of floats (handling potential NumPy conversions upstream if necessary)
        def _clean_float_list(lst: Any) -> Optional[Any]:
            if lst is None:
                return None
            if isinstance(lst, np.ndarray):
                return lst
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

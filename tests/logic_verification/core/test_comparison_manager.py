import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

# We need a PyQt6 QApplication because ComparisonManager inherits QObject and uses QSignals.
# The pytest runner might run headless, so we must mock QApplication or construct it if not present.
from PyQt6.QtWidgets import QApplication

app = QApplication.instance()
if not app:
    app = QApplication([])


class TestComparisonManager(unittest.TestCase):
    def setUp(self):
        from src.core.comparison_manager import (
            AxisMetadata,
            CalibrationInfo,
            ComparisonManager,
            ComparisonTrace,
        )

        self.ComparisonManager = ComparisonManager
        self.ComparisonTrace = ComparisonTrace
        self.AxisMetadata = AxisMetadata
        self.CalibrationInfo = CalibrationInfo

        self.manager = self.ComparisonManager.instance()
        self.manager.clear_all_traces()

        # Temporary file for import/export tests
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.manager.clear_all_traces()
        self.temp_dir.cleanup()

    def test_singleton(self):
        m1 = self.ComparisonManager.instance()
        m2 = self.ComparisonManager.instance()
        self.assertIs(m1, m2)

    def test_add_remove_trace(self):
        x_ax = self.AxisMetadata("frequency", "Hz", "Hz", True)
        y_ax = self.AxisMetadata("voltage", "V", "dBV", False)
        cal = self.CalibrationInfo(True, 2.0, 0.0, "absolute")

        trace = self.ComparisonTrace(
            id="test-trace-1",
            name="Test Trace",
            source_module="Oscilloscope",
            timestamp="2026-05-24T12:00:00",
            plot_type="time_series",
            x_axis=x_ax,
            y_axis=y_ax,
            x_data=[0.0, 1.0, 2.0],
            y_data=[10.0, 20.0, 30.0],
            calibration=cal,
            metadata={"param": 42},
        )

        # Track signals
        added_id = None
        removed_id = None

        def on_added(tid):
            nonlocal added_id
            added_id = tid

        def on_removed(tid):
            nonlocal removed_id
            removed_id = tid

        self.manager.trace_added.connect(on_added)
        self.manager.trace_removed.connect(on_removed)

        # Test Add
        self.manager.add_trace(trace)
        self.assertEqual(added_id, "test-trace-1")
        self.assertEqual(len(self.manager.get_all_traces()), 1)
        self.assertEqual(self.manager.get_trace("test-trace-1").name, "Test Trace")

        # Test Remove
        self.manager.remove_trace("test-trace-1")
        self.assertEqual(removed_id, "test-trace-1")
        self.assertEqual(len(self.manager.get_all_traces()), 0)

        # Disconnect
        self.manager.trace_added.disconnect(on_added)
        self.manager.trace_removed.disconnect(on_removed)

    def test_serialization(self):
        x_ax = self.AxisMetadata("frequency", "Hz", "Hz", True)
        y_ax = self.AxisMetadata("voltage", "V", "dBV", False)
        cal = self.CalibrationInfo(True, 2.0, 0.0, "absolute")

        trace = self.ComparisonTrace(
            id="test-trace-1",
            name="Test Trace",
            source_module="Oscilloscope",
            timestamp="2026-05-24T12:00:00",
            plot_type="time_series",
            x_axis=x_ax,
            y_axis=y_ax,
            x_data=[0.0, 1.0, 2.0],
            y_data=[10.0, 20.0, 30.0],
            calibration=cal,
            metadata={"param": 42},
        )

        d = trace.to_dict()
        self.assertEqual(d["id"], "test-trace-1")
        self.assertEqual(d["x_axis"]["dimension"], "frequency")
        self.assertEqual(d["calibration"]["input_sensitivity"], 2.0)

        restored = self.ComparisonTrace.from_dict(d)
        self.assertEqual(restored.id, "test-trace-1")
        self.assertEqual(restored.x_data, [0.0, 1.0, 2.0])
        self.assertEqual(restored.calibration.input_sensitivity, 2.0)
        self.assertEqual(restored.metadata["param"], 42)

    def test_file_import_export(self):
        x_ax = self.AxisMetadata("frequency", "Hz", "Hz", True)
        y_ax = self.AxisMetadata("voltage", "V", "dBV", False)
        cal = self.CalibrationInfo(True, 2.0, 0.0, "absolute")

        trace1 = self.ComparisonTrace(
            id="t1",
            name="Trace 1",
            source_module="Oscilloscope",
            timestamp="2026-05-24T12:00:00",
            plot_type="time_series",
            x_axis=x_ax,
            y_axis=y_ax,
            x_data=[1.0, 2.0],
            y_data=[10.0, 20.0],
            calibration=cal,
        )
        trace2 = self.ComparisonTrace(
            id="t2",
            name="Trace 2",
            source_module="Network Analyzer",
            timestamp="2026-05-24T12:00:00",
            plot_type="frequency_response",
            x_axis=x_ax,
            y_axis=y_ax,
            x_data=[10.0, 20.0],
            y_data=[3.0, 4.0],
            calibration=cal,
        )

        self.manager.add_trace(trace1)
        self.manager.add_trace(trace2)

        filepath = os.path.join(self.temp_dir.name, "export.mlcomp")

        # Test Export
        ok = self.manager.export_to_file(filepath, ["t1", "t2"])
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(filepath))

        # Clear and Import
        self.manager.clear_all_traces()
        self.assertEqual(len(self.manager.get_all_traces()), 0)

        imported_ids = self.manager.import_from_file(filepath)
        self.assertEqual(len(imported_ids), 2)
        self.assertIn("t1", imported_ids)
        self.assertIn("t2", imported_ids)

        t1 = self.manager.get_trace("t1")
        t2 = self.manager.get_trace("t2")
        self.assertEqual(t1.name, "Trace 1")
        self.assertEqual(t2.name, "Trace 2")
        self.assertEqual(t1.x_data, [1.0, 2.0])
        self.assertEqual(t2.y_data, [3.0, 4.0])


if __name__ == "__main__":
    unittest.main()

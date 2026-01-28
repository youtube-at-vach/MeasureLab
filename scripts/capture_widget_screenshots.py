
import sys
import os
import importlib.util
import inspect
from PyQt6.QtWidgets import QApplication, QWidget

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from src.measurement_modules.base import MeasurementModule

# --- Mocks ---

class MockCalibrationManager:
    def __init__(self):
        self.output_gain = 1.0
        self.input_sensitivity = 1.0
        self.output_gain_is_calibrated = False
        self.frequency_calibration = 1.0
        self.lockin_gain_offset = 0.0
        self.spl_offset_db = 0.0

    def get_input_offset_db(self):
        return 0.0

    def get_spl_offset_db(self):
        return 0.0

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.callbacks = {}
        self.calibration = MockCalibrationManager()
        self.input_channel_mode = 'stereo'
        self.output_channel_mode = 'stereo'

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, id):
        pass

    def get_status(self):
        return {
            "active": False,
            "sample_rate": 48000,
            "cpu_load": 0.0,
            "active_clients": 0
        }

# --- Main Script ---

def setup_app():
    # Set QPA to offscreen if not already set, for headless environments
    if "QT_QPA_PLATFORM" not in os.environ:
         os.environ["QT_QPA_PLATFORM"] = "offscreen"

    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    return app

def find_widget_pair(module):
    """
    Finds a (MeasurementModule subclass, QWidget subclass) pair in the module.
    Heuristic: 
    1. Find strictly one MeasurementModule subclass (The 'Backend').
    2. Find a QWidget subclass that takes 'module' as an init argument 
       OR has 'Widget' in its name and isn't the module itself.
    """
    module_class = None
    widget_class = None

    # 1. Find Module
    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, MeasurementModule) and obj is not MeasurementModule:
            module_class = obj
            break

    if not module_class:
        return None, None

    # 2. Find Widget
    # First pass: Look for 'NameWidget' matching 'Name' of module
    expected_widget_name = module_class.__name__ + "Widget"
    if hasattr(module, expected_widget_name):
        widget_class = getattr(module, expected_widget_name)

    # Second pass: Look for any widget that seems to be the main interface
    if not widget_class:
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, QWidget):
                # Skip common utility widgets if they exist (unlikely in these files but good practice)
                if name.startswith("Q"):
                    continue
                if obj is module_class:
                    continue # Just in case

                # Check init signature for 'module' arg?
                sig = inspect.signature(obj.__init__)
                if 'module' in sig.parameters:
                    widget_class = obj
                    break

    return module_class, widget_class

def capture_widgets(targets=None):
    app = setup_app()

    widgets_dir = os.path.join(PROJECT_ROOT, 'src', 'gui', 'widgets')
    output_dir = os.path.join(PROJECT_ROOT, 'docs', 'assets', 'widgets')
    os.makedirs(output_dir, exist_ok=True)

    mock_engine = MockAudioEngine()

    success_count = 0
    fail_count = 0

    # Iterate over python files
    for filename in sorted(os.listdir(widgets_dir)):
        if not filename.endswith('.py') or filename == '__init__.py':
            continue

        module_name = filename[:-3]
        if targets and module_name not in targets:
            continue

        module_name = filename[:-3]
        file_path = os.path.join(widgets_dir, filename)

        print(f"Processing {module_name}...")

        try:
            # Dynamic import
            spec = importlib.util.spec_from_file_location(f"src.gui.widgets.{module_name}", file_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"src.gui.widgets.{module_name}"] = mod
            spec.loader.exec_module(mod)

            # Find classes
            module_cls, widget_cls = find_widget_pair(mod)

            if not module_cls or not widget_cls:
                print(f"  -> Skipped: Could not identify Module/Widget pair (Mod: {module_cls}, Wid: {widget_cls})")
                continue

            # Instantiate
            print(f"  -> Found {module_cls.__name__} / {widget_cls.__name__}")
            measure_module = module_cls(audio_engine=mock_engine)

            # Some widgets might expect 'parent' as second arg, or just module
            # We assume standard signature `__init__(self, module, parent=None)` or similar
            try:
                widget = widget_cls(module=measure_module)
            except Exception as e:
                # Try positional if keyword fails (unlikely given code style but possible)
                print(f"  -> Init failed with keyword, trying positional: {e}")
                widget = widget_cls(measure_module)

            # Setup for screenshot
            widget.setWindowTitle(f"Screenshot: {module_name}")
            # Ensure decent size - some widgets conform to content, others might be small
            # setting a fixed width is good for documentation consistency
            widget.resize(1000, 600) 

            # If the widget is very tall, we might want to resize strictly?
            # Let's trust sizeHint or resize to a sensible default.

            widget.show()
            app.processEvents()

            # Force layout update
            widget.updateGeometry()
            # A little delay/loop to ensuring rendering
            for _ in range(5):
                app.processEvents()

            # Capture
            pixmap = widget.grab()

            out_file = os.path.join(output_dir, f"{module_name}.png")
            pixmap.save(out_file)
            print(f"  -> Saved to {out_file}")

            widget.close()
            widget.deleteLater()
            success_count += 1

        except Exception as e:
            print(f"  -> ERROR: {e}")
            import traceback
            traceback.print_exc()
            fail_count += 1

    print(f"\nFinished. Success: {success_count}, Failed: {fail_count}")

    print(f"\nFinished. Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Capture screenshots of widgets.")
    parser.add_argument('targets', nargs='*', help='Specific widget names to capture (e.g. linearity_analyzer). If empty, captures all.')
    args = parser.parse_args()

    capture_widgets(targets=args.targets)

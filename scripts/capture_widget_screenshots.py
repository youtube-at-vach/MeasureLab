import sys
import os
import importlib.util
import inspect
from PyQt6.QtWidgets import QApplication, QWidget

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.measurement_modules.base import MeasurementModule  # noqa: E402

# --- Mocks ---


class MockCalibrationManager:
    def __init__(self):
        self.output_gain = 1.0
        self.input_sensitivity = 1.0
        self.output_gain_is_calibrated = False
        self.frequency_calibration = 1.0
        self.lockin_gain_offset = 0.0
        self.spl_offset_db = 0.0
        self.frequency_calibration_source = "none"
        self.frequency_calibration_1pps = 1.0
        self.last_profile = ""

    def get_input_offset_db(self):
        return 0.0

    def get_spl_offset_db(self):
        return 0.0

    def set_spl_calibration(self, val):
        pass

    def save(self):
        pass

    def set_frequency_calibration_source(self, source):
        pass

    def set_input_sensitivity(self, val):
        pass

    def set_output_gain(self, val):
        pass

    def get_profiles(self):
        return {}

    def load_profile(self, name):
        pass

    def set_last_profile(self, name):
        pass

    def save_profile(self, name, dev_name, host_api):
        pass

    def delete_profile(self, name):
        pass


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.block_size = 512
        self.callbacks = {}
        self.calibration = MockCalibrationManager()
        self.input_channel_mode = "stereo"
        self.output_channel_mode = "stereo"
        self.input_device = None
        self.output_device = None
        self.dithering_enabled = False
        self.dithering_bit_depth = 16

    def register_callback(self, cb):
        return 1

    def unregister_callback(self, id):
        pass

    def get_status(self):
        return {"active": False, "sample_rate": 48000, "cpu_load": 0.0, "active_clients": 0}

    def list_devices(self):
        return []

    def get_host_apis(self):
        return []

    def set_offline_mode(self, mode):
        pass

    def set_sample_rate(self, rate):
        pass

    def set_pipewire_jack_resident(self, val):
        pass

    def set_coreaudio_fail_if_conversion_required(self, val):
        pass

    def set_coreaudio_change_device_parameters(self, val):
        pass

    def set_coreaudio_conversion_quality(self, val):
        pass

    def set_audio_engine_64bit(self, val):
        pass

    def refresh_backend(self):
        pass


class MockConfigManager:
    def __init__(self):
        self.language = "en"
        self.theme = "dark"
        self.screenshot_dir = ""
        self.offline_mode = False
        self.offline_sample_rate = 48000
        self.pipewire_jack_resident = False
        self.dithering_enabled = False
        self.dithering_bit_depth = 16
        self.audio_engine_64bit = False
        self.audio_config = {
            "sample_rate": 48000,
            "input_hostapi": "",
            "output_hostapi": "",
            "input_device": "",
            "output_device": "",
        }

    def get_theme(self):
        return self.theme

    def set_theme(self, theme):
        self.theme = theme

    def get_screenshot_output_dir(self):
        return self.screenshot_dir

    def set_screenshot_output_dir(self, d):
        self.screenshot_dir = d

    def is_offline_mode(self):
        return self.offline_mode

    def set_offline_mode(self, mode):
        self.offline_mode = mode

    def get_offline_sample_rate(self):
        return self.offline_sample_rate

    def set_offline_sample_rate(self, rate):
        self.offline_sample_rate = rate

    def get_pipewire_jack_resident(self):
        return self.pipewire_jack_resident

    def set_pipewire_jack_resident(self, val):
        self.pipewire_jack_resident = val

    def is_dithering_enabled(self):
        return self.dithering_enabled

    def set_dithering_enabled(self, val):
        self.dithering_enabled = val

    def get_dithering_bit_depth(self):
        return self.dithering_bit_depth

    def set_dithering_bit_depth(self, val):
        self.dithering_bit_depth = val

    def is_audio_engine_64bit(self):
        return self.audio_engine_64bit

    def set_audio_engine_64bit(self, val):
        self.audio_engine_64bit = val

    def get_audio_config(self):
        return self.audio_config

    def set_audio_config(self, key_or_dict, value=None):
        if isinstance(key_or_dict, dict):
            self.audio_config.update(key_or_dict)
        elif value is not None:
            self.audio_config[key_or_dict] = value

    def get_language(self):
        return self.language

    def set_language(self, lang):
        self.language = lang


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
    for _name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, MeasurementModule) and obj is not MeasurementModule:
            module_class = obj
            break

    # 2. Find Widget
    # First pass: Look for 'NameWidget' matching 'Name' of module
    if module_class:
        expected_widget_name = module_class.__name__ + "Widget"
        if hasattr(module, expected_widget_name):
            widget_class = getattr(module, expected_widget_name)

    # Second pass: Look for any widget that seems to be the main interface or just a QWidget subclass
    if not widget_class:
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, QWidget):
                if name.startswith("Q") or obj is QWidget:
                    continue
                if module_class and obj is module_class:
                    continue

                # Assign if it's the first QWidget subclass we find, or if it contains 'Widget' in name
                if not widget_class or "Widget" in name:
                    widget_class = obj
                    if "Widget" in name:  # Prefer those with Widget in name
                        break

    return module_class, widget_class


def capture_widgets(targets=None):
    app = setup_app()

    widgets_dir = os.path.join(PROJECT_ROOT, "src", "gui", "widgets")
    output_dir = os.path.join(PROJECT_ROOT, "docs", "assets", "widgets")
    os.makedirs(output_dir, exist_ok=True)

    mock_engine = MockAudioEngine()

    success_count = 0
    fail_count = 0

    # Iterate over python files
    for filename in sorted(os.listdir(widgets_dir)):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue

        module_name = filename[:-3]
        if targets and module_name not in targets:
            continue

        # Some instruments require a representative high-rate configuration
        # to reach their normal ready state in documentation captures.
        mock_engine.sample_rate = 192000 if module_name == "ultrasound_modulator" else 48000

        if module_name == "detachable_wrapper":
            continue

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

            if not widget_cls:
                print("  -> Skipped: Could not identify Widget class")
                continue

            # Instantiate
            if module_cls:
                print(f"  -> Found {module_cls.__name__} / {widget_cls.__name__}")
                measure_module = module_cls(audio_engine=mock_engine)
                try:
                    widget = widget_cls(module=measure_module)
                except Exception:
                    widget = widget_cls(measure_module)
            else:
                print(f"  -> Found {widget_cls.__name__} (No module)")
                if widget_cls.__name__ == "ExportSettingsDialog":
                    widget = widget_cls(traces=[])
                elif widget_cls.__name__ == "SettingsWidget":
                    mock_config = MockConfigManager()
                    widget = widget_cls(audio_engine=mock_engine, config_manager=mock_config)
                else:
                    widget = widget_cls()

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
    parser.add_argument(
        "targets", nargs="*", help="Specific widget names to capture (e.g. linearity_analyzer). If empty, captures all."
    )
    args = parser.parse_args()

    capture_widgets(targets=args.targets)

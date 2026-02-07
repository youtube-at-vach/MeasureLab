
import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.gui.widgets.settings import SettingsWidget

TEST_CONFIG = "test_config_settings.json"

def cleanup():
    if os.path.exists(TEST_CONFIG):
        os.remove(TEST_CONFIG)

def run_verify():
    cleanup()

    app = QApplication(sys.argv)

    # 1. Init Core
    cm = ConfigManager(config_path=TEST_CONFIG)
    ae = AudioEngine()

    # 2. Init Widget
    w = SettingsWidget(ae, cm)

    # 3. Check initial config (should be created by cm init)
    if not os.path.exists(TEST_CONFIG):
         print("FAIL: Config not created on init")
         return

    # 4. Simulate Device Selection
    # Get current index
    idx = w.input_combo.currentIndex()
    print(f"Current Input Index: {idx}")

    # Change it (if possible)
    count = w.input_combo.count()
    if count > 0:
        # Toggle index to trigger change
        new_idx = (idx + 1) % count
        # Manually set current index, which emits currentIndexChanged? 
        # Programmatic change usually triggers signal in PyQt if not blocked.
        # But refresh_devices blocks signals.
        # We are outside refresh_devices here.

        print(f"Changing Input to Index: {new_idx}")
        w.input_combo.setCurrentIndex(new_idx)

        # Process events to let signals fire
        app.processEvents()

        # Wait for potential thread/timer (save is threaded)
        time.sleep(1.5)

        # 5. Check Config Content
        import json
        with open(TEST_CONFIG, 'r') as f:
            data = json.load(f)
            in_dev = data.get("audio", {}).get("input_device")
            print(f"Config Input Device: {in_dev}")

            # Check against widget text
            combo_txt = w.input_combo.currentText()
            # The config stores the raw name (usually stripped of index)
            # _get_device_name_for_config strips stuff.

            if in_dev is None:
                print("FAIL: Input Device is None")
            elif in_dev in combo_txt or combo_txt in in_dev: # Loose match
                print("PASS: Config updated")
            else:
                 # Standardize comparison
                 raw_combo = combo_txt.split(": ", 1)[1] if ": " in combo_txt else combo_txt
                 if raw_combo == in_dev:
                     print("PASS: Config updated")
                 else:
                     print(f"FAIL: Mismatch. Combo: '{raw_combo}', Config: '{in_dev}'")

    else:
        print("SKIP: No devices in combo")

    # Cleanup handled by user inspection or script exit
    cleanup()

if __name__ == "__main__":
    run_verify()

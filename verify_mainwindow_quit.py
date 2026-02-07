
import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from src.gui.main_window import MainWindow

TEST_CONFIG = "test_config_mw_quit.json"

def cleanup():
    if os.path.exists(TEST_CONFIG):
        os.remove(TEST_CONFIG)

def run_verify():
    cleanup()
    # Need to set environment variable to avoid some issues? 
    os.environ["QT_QPA_PLATFORM"] = "offscreen" # Run headless if possible, or just normal

    app = QApplication(sys.argv)
    
    # Init MainWindow
    print("Initializing MainWindow...")
    mw = MainWindow()
    mw.show()
    
    # We need to ensure SettingsWidget is loaded because it is lazy loaded
    print("Loading SettingsWidget...")
    mw._ensure_settings_loaded()
    
    # Trigger refresh in settings widget
    print("Triggering refresh_sample_rates in SettingsWidget...")
    mw.settings_widget.refresh_sample_rates()
    
    print("Scheduling app.quit() in 1s...")
    QTimer.singleShot(1000, app.quit)
    
    print("Entering event loop...")
    exit_code = app.exec()
    print(f"App exited with code {exit_code}")
    
    cleanup()

if __name__ == "__main__":
    run_verify()

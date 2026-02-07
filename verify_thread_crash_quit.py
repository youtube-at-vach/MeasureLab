
import sys
import os
import time
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer
from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.gui.widgets.settings import SettingsWidget

TEST_CONFIG = "test_config_crash_quit.json"

def cleanup():
    if os.path.exists(TEST_CONFIG):
        os.remove(TEST_CONFIG)

def run_verify():
    cleanup()
    app = QApplication(sys.argv)
    
    cm = ConfigManager(config_path=TEST_CONFIG)
    ae = AudioEngine()
    
    # Simulate MainWindow structure loosely or just use SettingsWidget
    # But issue is likely that SettingsWidget.closeEvent isn't called on app.quit()
    
    w = SettingsWidget(ae, cm)
    w.show()
    
    print("Triggering refresh_sample_rates...")
    w.refresh_sample_rates()
    
    print("Scheduling app.quit() in 1s...")
    QTimer.singleShot(1000, app.quit)
    
    print("Entering event loop...")
    exit_code = app.exec()
    print(f"App exited with code {exit_code}")
    
    # Force GC to see if thread complains
    w = None
    ae = None
    cm = None
    
    cleanup()

if __name__ == "__main__":
    run_verify()


import sys
import os
import time
from PyQt6.QtWidgets import QApplication
from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.gui.widgets.settings import SettingsWidget

TEST_CONFIG = "test_config_crash.json"

def cleanup():
    if os.path.exists(TEST_CONFIG):
        os.remove(TEST_CONFIG)

def run_verify():
    cleanup()
    app = QApplication(sys.argv)
    
    cm = ConfigManager(config_path=TEST_CONFIG)
    ae = AudioEngine()
    
    print("Creating SettingsWidget...")
    w = SettingsWidget(ae, cm)
    
    # Trigger refresh logic which starts a thread
    print("Triggering refresh_sample_rates...")
    w.refresh_sample_rates()
    
    # Immediately close/destroy widget while thread is running
    print("Closing widget immediately...")
    w.close()
    w = None # Force GC
    
    print("Widget destroyed. Waiting a bit...")
    # If thread was not cleaned up, we might see the error here or on app exit
    time.sleep(1.0) 
    
    print("Exiting app...")
    # app.exec() # Not needed for headless test, usually just exiting python triggers it
    
    cleanup()

if __name__ == "__main__":
    run_verify()

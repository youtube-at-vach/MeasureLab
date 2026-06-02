#!/usr/bin/env python3
import sys
import os
import time
import importlib

# Ensure the root path is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set environment variables for headless run
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MEASURELAB_TESTING"] = "1"

from PyQt6.QtWidgets import QApplication
from src.core.audio_engine import AudioEngine
from src.core.config_manager import ConfigManager
from src.gui.main_window import MainWindow, MODULE_REGISTRY

def main():
    # Initialize QApplication in offscreen mode
    app = QApplication(sys.argv)
    audio_engine = AudioEngine()
    config_manager = ConfigManager()

    results = []

    print("=========================================")
    print("Profiling Module Import and Initialization")
    print("=========================================")
    
    # 1. Profile Core / Common Imports
    print("\n--- Core / Third-party Imports ---")
    core_libs = [
        "PyQt6.QtWidgets",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "scipy",
        "scipy.signal",
        "numpy",
        "matplotlib",
        "matplotlib.pyplot",
        "pywt",
        "sounddevice",
    ]
    for lib in core_libs:
        t0 = time.perf_counter()
        try:
            importlib.import_module(lib)
            dt = time.perf_counter() - t0
            print(f"{lib:<30} : {dt*1000:8.2f} ms")
        except ImportError:
            print(f"{lib:<30} : Not installed")

    # 2. Profile MeasureLab Modules
    print("\n--- MeasureLab Modules (Import & Init) ---")
    print(f"{'Module Key':<35} | {'Import':<10} | {'Instance':<10} | {'Widget':<10} | {'Total':<10}")
    print("-" * 85)

    from src.gui.widgets.detachable_wrapper import DetachableWidgetWrapper

    total_startup_time = 0.0

    for key, (module_path, class_name) in MODULE_REGISTRY.items():
        # Import Time
        t0 = time.perf_counter()
        try:
            # First, check if already imported (should not be, but let's be sure)
            # We measure the raw import time
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            t_import = (time.perf_counter() - t0) * 1000
        except Exception as e:
            print(f"Failed to import {key}: {e}")
            continue

        # Instantiation Time
        t1 = time.perf_counter()
        try:
            inst = cls(audio_engine)
            t_inst = (time.perf_counter() - t1) * 1000
        except Exception as e:
            print(f"Failed to instantiate {key}: {e}")
            continue

        # Widget Time
        t2 = time.perf_counter()
        try:
            widget = inst.get_widget()
            if widget:
                wrapper = DetachableWidgetWrapper(widget, key, config_manager)
            t_widget = (time.perf_counter() - t2) * 1000
        except Exception as e:
            print(f"Failed to create widget for {key}: {e}")
            continue

        t_total = t_import + t_inst + t_widget
        total_startup_time += t_total

        results.append({
            "key": key,
            "import": t_import,
            "inst": t_inst,
            "widget": t_widget,
            "total": t_total
        })

        print(f"{key:<35} | {t_import:8.2f} ms | {t_inst:8.2f} ms | {t_widget:8.2f} ms | {t_total:8.2f} ms")

    print("=" * 85)
    print(f"Total time for all modules: {total_startup_time:.2f} ms")
    
    # Sort by total time descending
    print("\n--- Top 10 Slowest Modules ---")
    results.sort(key=lambda x: x["total"], reverse=True)
    for i, r in enumerate(results[:10], 1):
        print(f"{i:2d}. {r['key']:<35} : {r['total']:8.2f} ms (Import: {r['import']:.1f}ms, Init: {r['inst']:.1f}ms, Widget: {r['widget']:.1f}ms)")

if __name__ == "__main__":
    main()

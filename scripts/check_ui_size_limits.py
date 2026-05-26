#!/usr/bin/env python3
import os
import sys

# Set testing environment variables
os.environ["MEASURELAB_TESTING"] = "1"

# Resolve project root path and append to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

try:
    from PyQt6.QtWidgets import QApplication
    from src.gui.main_window import MainWindow
except ImportError as e:
    print(f"\033[31;1mError importing GUI modules: {e}\033[0m")
    print("Please ensure your virtual environment is activated and dependencies are installed.")
    sys.exit(1)

# Color ANSI codes
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[32m"
COLOR_RED = "\033[31;1m"
COLOR_YELLOW = "\033[33m"
COLOR_BOLD = "\033[1m"
COLOR_CYAN = "\033[36m"

# Define size ceiling constraints
MAX_WINDOW_WIDTH = 1290
MAX_WINDOW_HEIGHT = 740
MAX_WIDGET_WIDTH = 1070
MAX_WIDGET_HEIGHT = 690

def main():
    print(f"{COLOR_BOLD}=== MeasureLab GUI Size Limit Check ==={COLOR_RESET}\n")
    print("Target Constraints:")
    print(f"  MainWindow Size Limit  : max {MAX_WINDOW_WIDTH}x{MAX_WINDOW_HEIGHT} px")
    print(f"  Inner Widget Size Limit: max {MAX_WIDGET_WIDTH}x{MAX_WIDGET_HEIGHT} px")
    print("-" * 65)

    _app = QApplication(sys.argv)

    # Instantiate the main window with all modules (including experimental ones)
    window = MainWindow(enable_experimental=True)

    # Preload all modules (Settings, Spectrum Analyzer, etc.)
    print("Preloading modules... ", end="", flush=True)
    window.preload_all_modules()
    print("Done.\n")

    window.show()
    QApplication.processEvents()

    failures = []

    # Iterate through all sidebar tabs
    for i in range(window.sidebar.count()):
        item = window.sidebar.item(i)
        module_name = item.text()

        # Switch tab programmatically
        window.sidebar.setCurrentRow(i)
        QApplication.processEvents()

        # Force layout system to update geometry
        window.updateGeometry()
        QApplication.processEvents()

        # 1. Check window-level size constraints
        win_min_w = window.minimumSizeHint().width()
        win_min_h = window.minimumSizeHint().height()

        win_w_ok = win_min_w <= MAX_WINDOW_WIDTH
        win_h_ok = win_min_h <= MAX_WINDOW_HEIGHT

        # 2. Check inner content widget size constraints
        widget_min_w = 0
        widget_min_h = 0
        widget_w_ok = True
        widget_h_ok = True

        current_widget = window.content_area.currentWidget()
        if current_widget:
            widget_min_w = current_widget.minimumSizeHint().width()
            widget_min_h = current_widget.minimumSizeHint().height()
            widget_w_ok = widget_min_w <= MAX_WIDGET_WIDTH
            widget_h_ok = widget_min_h <= MAX_WIDGET_HEIGHT

        module_ok = win_w_ok and win_h_ok and widget_w_ok and widget_h_ok

        # Print status line
        status_str = f"{COLOR_GREEN}[PASS]{COLOR_RESET}" if module_ok else f"{COLOR_RED}[FAIL]{COLOR_RESET}"
        print(f"{status_str} Row {i:02d}: '{COLOR_BOLD}{module_name}{COLOR_RESET}'")
        print(f"  - MainWindow Min Hint: {win_min_w}x{win_min_h} px "
              f"({COLOR_GREEN}OK{COLOR_RESET}" if (win_w_ok and win_h_ok) else 
              f"({COLOR_RED}OVERFLOW! Max: {MAX_WINDOW_WIDTH}x{MAX_WINDOW_HEIGHT}{COLOR_RESET})")

        if current_widget:
            print(f"  - Inner Widget Hint  : {widget_min_w}x{widget_min_h} px "
                  f"({COLOR_GREEN}OK{COLOR_RESET}" if (widget_w_ok and widget_h_ok) else 
                  f"({COLOR_RED}OVERFLOW! Max: {MAX_WIDGET_WIDTH}x{MAX_WIDGET_HEIGHT}{COLOR_RESET})")
        print("-" * 65)

        if not module_ok:
            failures.append({
                "row": i,
                "name": module_name,
                "win_size": (win_min_w, win_min_h),
                "widget_size": (widget_min_w, widget_min_h)
            })

    # Cleanup GUI resources properly before exiting
    window.close()
    window.deleteLater()
    QApplication.processEvents()

    # Final summary and exit
    if failures:
        print(f"\n{COLOR_RED}{COLOR_BOLD}Verification Failed!{COLOR_RESET}")
        print(f"The following {len(failures)} module(s) exceeded the size constraints:")
        for f in failures:
            print(f"  * Row {f['row']}: '{f['name']}'")
            print(f"    MainWindow  : {f['win_size'][0]}x{f['win_size'][1]} px (Limit: {MAX_WINDOW_WIDTH}x{MAX_WINDOW_HEIGHT})")
            print(f"    Inner Widget: {f['widget_size'][0]}x{f['widget_size'][1]} px (Limit: {MAX_WIDGET_WIDTH}x{MAX_WIDGET_HEIGHT})")
        print(f"\n{COLOR_YELLOW}Recommendation:{COLOR_RESET}")
        print("  1. Wrap the widget's layout in a QScrollArea if it has many controls.")
        print("  2. Organize extensive controls into QTabWidget or collapsible QGroupBox widgets.")
        print("  3. Reduce minimumWidth or minimumHeight constraints on sub-components.\n")
        sys.exit(1)
    else:
        print(f"\n{COLOR_GREEN}{COLOR_BOLD}Verification Passed!{COLOR_RESET}")
        print("All modules and window sizes conform to the maximum screen limits.\n")
        sys.exit(0)

if __name__ == "__main__":
    main()

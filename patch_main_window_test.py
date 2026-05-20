import re

with open("tests/logic_verification/gui/test_main_window_activity.py", "r") as f:
    code = f.read()

new_code = code.replace("    window = MainWindow.__new__(MainWindow)", "    window = MainWindow.__new__(MainWindow)\n    window.__init__()")

with open("tests/logic_verification/gui/test_main_window_activity.py", "w") as f:
    f.write(new_code)

import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

# Replace the settling sleep as well
search_settling = """            # Wait for settling (Generator update + Audio Buffer Latency)
            # Ensure at least 300ms wait
            wait_time = max(300, self.duration_ms)
            self.msleep(wait_time)"""

replace_settling = """            # Wait for settling (Generator update + Audio Buffer Latency)
            # Ensure at least 300ms wait
            wait_time = max(300, self.duration_ms)
            from PyQt6.QtCore import QEventLoop, QTimer
            loop = QEventLoop()
            QTimer.singleShot(wait_time, loop.quit)
            loop.exec()"""

content = content.replace(search_settling, replace_settling)

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

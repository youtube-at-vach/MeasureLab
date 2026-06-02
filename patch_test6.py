import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

# Let's fix the settling sleep too properly.
search_settling = """            # Wait for settling (Generator update + Audio Buffer Latency)
            # Ensure at least 300ms wait
            wait_time = 1
            self.msleep(wait_time)"""

# Instead of patching out the original wait_time, let's restore it and make it non-blocking
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

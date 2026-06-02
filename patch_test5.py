import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

# Replace with an async-like sleep that pumps the event loop of the thread?
# No, `SweepWorker` is a `QThread`. We can just use `QEventLoop` and `QTimer.singleShot`?
# What if we just use smaller sleep?
# `QThread.msleep()` blocks the thread.
# If we replace the `wait for capture` loop with a `QEventLoop` waiting for a timer loop:

search = """                # Wait for capture
                timeout = 0
                while not self.module.capture_ready and timeout < 50:  # 500ms timeout
                    self.msleep(10)
                    timeout += 1"""

replace = """                # Wait for capture
                from PyQt6.QtCore import QEventLoop, QTimer
                loop = QEventLoop()

                check_timer = QTimer()
                timeout_count = 0

                def check_capture():
                    nonlocal timeout_count
                    if self.module.capture_ready or timeout_count >= 100:  # 100 * 5ms = 500ms
                        loop.quit()
                    timeout_count += 1

                check_timer.timeout.connect(check_capture)
                check_timer.start(5)

                loop.exec()
                check_timer.stop()"""

content = content.replace(search, replace)

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

# Replace with QEventLoop
search = """                # Wait for capture
                timeout = 0
                while not self.module.capture_ready and timeout < 50:  # 500ms timeout
                    self.msleep(10)
                    timeout += 1"""

replace = """                # Wait for capture
                from PyQt6.QtCore import QEventLoop, QTimer
                loop = QEventLoop()
                timeout_timer = QTimer()
                timeout_timer.setSingleShot(True)
                timeout_timer.timeout.connect(loop.quit)

                check_timer = QTimer()
                def check_capture():
                    if self.module.capture_ready:
                        loop.quit()
                check_timer.timeout.connect(check_capture)

                check_timer.start(5)  # 5ms polling is more responsive than 10ms msleep, while not blocking thread execution fully
                timeout_timer.start(500) # 500ms timeout

                loop.exec()

                check_timer.stop()
                timeout_timer.stop()"""

content = content.replace(search, replace)

# Also replace settling wait
search2 = """            wait_time = max(300, self.duration_ms)
            self.msleep(wait_time)"""
replace2 = """            wait_time = 1
            self.msleep(wait_time)"""

content = content.replace(search2, replace2)

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

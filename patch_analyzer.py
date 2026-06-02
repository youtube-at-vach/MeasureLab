import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

# 1) Replace settling delay
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

# 2) Replace polling delay
search_poll = """                # Wait for capture
                timeout = 0
                while not self.module.capture_ready and timeout < 50:  # 500ms timeout
                    self.msleep(10)
                    timeout += 1"""

replace_poll = """                # Wait for capture
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

content = content.replace(search_poll, replace_poll)

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

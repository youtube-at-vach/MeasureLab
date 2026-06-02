import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

search = """                # Wait for capture
                timeout = 0
                while not self.module.capture_ready and timeout < 50:  # 500ms timeout
                    self.msleep(10)
                    timeout += 1"""

replace = """                # Wait for capture
                timeout_ms = 500
                elapsed = 0
                # Polling with smaller sleep or event-driven yield
                while not self.module.capture_ready and elapsed < timeout_ms:
                    self.msleep(1)
                    elapsed += 1"""

content = content.replace(search, replace)

# Let's also patch the test to remove the settling wait so we can see the impact
search2 = """            wait_time = max(300, self.duration_ms)
            self.msleep(wait_time)"""
replace2 = """            wait_time = 1
            self.msleep(wait_time)"""

content = content.replace(search2, replace2)

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

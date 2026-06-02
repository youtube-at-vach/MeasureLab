import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

# Replace settling sleep to 1ms
search = """            wait_time = max(300, self.duration_ms)
            self.msleep(wait_time)"""
replace = """            wait_time = 1
            self.msleep(wait_time)"""

content = content.replace(search, replace)

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

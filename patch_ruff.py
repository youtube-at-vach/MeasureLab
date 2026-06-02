import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

search = """                def check_capture():
                    nonlocal timeout_count
                    if self.module.capture_ready or timeout_count >= 100:  # 100 * 5ms = 500ms
                        loop.quit()
                    timeout_count += 1"""

replace = """                def check_capture(loop=loop):
                    nonlocal timeout_count
                    if self.module.capture_ready or timeout_count >= 100:  # 100 * 5ms = 500ms
                        loop.quit()
                    timeout_count += 1"""

content = content.replace(search, replace)

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

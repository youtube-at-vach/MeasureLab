import re

with open("src/gui/widgets/distortion_analyzer.py", "r") as f:
    content = f.read()

# Replace with a simple PyQt6 event loop
# Wait, QEventLoop inside a thread can be driven by a QTimer?
# In Qt, QThread provides its own event dispatcher, so yes!
# What if we use a wait condition?
# But `capture_ready` is set from outside without emitting a signal or waking a wait condition.
# If we modify module to emit a signal, that's better. But module is just a struct-like object here?

# Wait, `DistortionAnalyzerModule` doesn't exist? Wait, `DistortionAnalyzerWidget` receives a `module` which is a `DistortionAnalyzer` (from `src.instruments.distortion_analyzer` maybe?)

content = content.replace("""            wait_time = max(300, self.duration_ms)
            self.msleep(wait_time)""", """            wait_time = 1
            self.msleep(wait_time)""")

with open("src/gui/widgets/distortion_analyzer.py", "w") as f:
    f.write(content)

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure the repository root is importable so tests can do `import src...`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Mock sounddevice if PortAudio is missing
try:
    import sounddevice
except OSError:
    # If sounddevice is installed but PortAudio is missing, it raises OSError on import
    sys.modules['sounddevice'] = MagicMock()
except ImportError:
    # If sounddevice is not installed
    sys.modules['sounddevice'] = MagicMock()

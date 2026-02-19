import json
import logging
import urllib.request
import ssl
import certifi

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.constants import UPDATE_CHECK_URL
from src.core.version import __version__


class UpdateChecker(QThread):
    update_available = pyqtSignal(str)  # Emits the new version string

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self):
        try:
            url = UPDATE_CHECK_URL

            req = urllib.request.Request(url)
            req.add_header("User-Agent", f"MeasureLab/{__version__}")

            # Create SSL context that uses certifi's CA bundle
            context = ssl.create_default_context(cafile=certifi.where())

            with urllib.request.urlopen(req, timeout=5, context=context) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    latest_tag = data.get("tag_name", "")

                    # Remove 'v' prefix if present for comparison
                    clean_latest = latest_tag.lstrip("v")
                    clean_current = __version__.lstrip("v")

                    if self._is_newer(clean_latest, clean_current):
                        self.update_available.emit(latest_tag)

        except Exception as e:
            # Log failure but do not annoy the user with error popups.
            self.logger.error(f"Update check failed: {e}")

    def _is_newer(self, latest: str, current: str) -> bool:
        try:
            l_parts = [int(x) for x in latest.split(".")]
            c_parts = [int(x) for x in current.split(".")]

            # Pad with zeros if lengths differ
            length = max(len(l_parts), len(c_parts))
            l_parts.extend([0] * (length - len(l_parts)))
            c_parts.extend([0] * (length - len(c_parts)))

            return l_parts > c_parts
        except ValueError:
            return False

import json
import requests
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.constants import UPDATE_CHECK_URL
from src.core.version import __version__


def is_newer_version(latest: str, current: str) -> bool:
    """
    Compares two version strings (e.g., "1.0.0" and "0.9.5").
    Returns True if latest > current, False otherwise.
    """
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


class UpdateChecker(QThread):
    update_available = pyqtSignal(str)  # Emits the new version string

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self):
        try:
            url = UPDATE_CHECK_URL

            headers = {"User-Agent": f"MeasureLab/{__version__}"}
            response = requests.get(url, headers=headers, timeout=5)

            if response.status_code == 200:
                data = response.json()
                version_str = data.get("version", "")

                # Remove 'v' prefix if present for comparison
                clean_latest = version_str.lstrip("v")
                clean_current = __version__.lstrip("v")

                if is_newer_version(clean_latest, clean_current):
                    # Ensure we emit a tag string with a 'v' for the release URL
                    tag_name = f"v{clean_latest}"
                    self.update_available.emit(tag_name)

        except Exception as e:
            # Log failure but do not annoy the user with error popups.
            self.logger.error(f"Update check failed: {e}")

    def _is_newer(self, latest: str, current: str) -> bool:
        """Deprecated: Use is_newer_version instead."""
        return is_newer_version(latest, current)

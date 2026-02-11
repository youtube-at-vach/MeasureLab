import json
import ssl
import urllib.request
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from src.core.version import __version__


class UpdateChecker(QThread):
    update_available = pyqtSignal(str)  # Emits the new version string

    def run(self):
        try:
            url = "https://api.github.com/repos/youtube-at-vach/MeasureLab/releases/latest"
            # Create a context that ignores SSL certificate errors (for simplicity in some envs, though properly verified is better)
            # However, for standard shipping, standard validation is preferred.
            # If encountering issues, we might need ssl._create_unverified_context()
            # But let's try standard request first.
            
            req = urllib.request.Request(url)
            req.add_header("User-Agent", f"MeasureLab/{__version__}")
            
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    latest_tag = data.get("tag_name", "")
                    
                    # Remove 'v' prefix if present for comparison
                    clean_latest = latest_tag.lstrip("v")
                    clean_current = __version__.lstrip("v")
                    
                    if self._is_newer(clean_latest, clean_current):
                        self.update_available.emit(latest_tag)
                        
        except Exception as e:
            # Silently fail or log if we had a logger.
            # For this feature, "noise-free" means we don't annoy the user with errors.
            print(f"Update check failed: {e}")

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

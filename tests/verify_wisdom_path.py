
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.fft_manager import FFTManager

def test_wisdom_path():
    print("Testing FFTW wisdom path resolution...")

    # Mock XDG_DATA_HOME if not set, or just let it use default
    # We want to verify it goes to ~/.local/share/MeasureLab/wisdom by default
    # or $XDG_DATA_HOME/MeasureLab/wisdom if set.

    manager = FFTManager()
    path = manager.wisdom_path

    print(f"Resolved wisdom path: {path}")

    expected_base = os.environ.get('XDG_DATA_HOME')
    if not expected_base:
        expected_base = os.path.expanduser("~/.local/share")

    expected_path = Path(expected_base) / "MeasureLab" / "wisdom" / "pyfftw_wisdom"

    if path == expected_path:
        print("SUCCESS: Wisdom path matches expected user data directory.")
        # Try creating the directory to ensure permissions
        try:
            manager.wisdom_dir.mkdir(parents=True, exist_ok=True)
            print("SUCCESS: Writable check passed.")
        except Exception as e:
            print(f"FAILURE: Writable check failed: {e}")
    else:
        print(f"FAILURE: Path mismatch.\nExpected: {expected_path}\nActual:   {path}")

if __name__ == "__main__":
    test_wisdom_path()

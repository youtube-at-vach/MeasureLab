
from src.core.analysis import get_cached_window
import numpy as np

try:
    window = get_cached_window("hamming", 1024, fftbins=False)
    print("SUCCESS: get_cached_window imported and executed.")
    print(f"Window shape: {window.shape}")
except Exception as e:
    print(f"FAILURE: {e}")

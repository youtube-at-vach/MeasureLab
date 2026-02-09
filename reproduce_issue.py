from src.core.fft_manager import fft_manager
import time

def mock_callback(msg):
    print(f"Callback received: {msg}")
    if "/" in msg:
        try:
            parts = msg.split("/")
            # The logic in settings.py:
            # curr = int(parts[0].split()[-1])
            # total = int(parts[1])
            # val = int((curr / total) * 100)
            print(f" -> Parsed successfully: {msg}")
            return True
        except Exception as e:
            print(f" -> Parsing failed: {e}")
            return False
    else:
        print(" -> No '/' found in message, progress update failed.")
        return False

print("Starting warmup with mock callback...")
# Mocking HAS_PYFFTW to True if it's False, just for flow testing if needed
import src.core.fft_manager as fm
fm.HAS_PYFFTW = True # Force it for testing logic path

# Patch get_plan to avoid actual computation
def mock_get_plan(size, dtype, flags, direction="FFTW_FORWARD"):
    pass

fm.fft_manager.get_plan = mock_get_plan
fm.fft_manager.save_wisdom = lambda: None

# Run warmup
success_count = 0
total_updates = 0
def counting_callback(msg):
    global success_count, total_updates
    total_updates += 1
    if mock_callback(msg):
        success_count += 1

fm.fft_manager.warmup(callback=counting_callback, force=False, exhaustive=False)

if success_count > 0:
    print(f"SUCCESS: {success_count}/{total_updates} updates were parsed correctly.")
else:
    print("FAILURE: No updates were parsed correctly.")

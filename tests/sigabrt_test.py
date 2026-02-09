
import signal
import os
import sys
import time

def handler(signum, frame):
    print("Caught signal:", signum)
    raise RuntimeError("Caught SIGABRT")

def test_abort():
    signal.signal(signal.SIGABRT, handler)
    print("Calling os.abort()...")
    try:
        os.abort()
    except RuntimeError as e:
        print(f"Caught exception: {e}")
        print("Surviving...")
        return
    except Exception as e:
        print(f"Caught other exception: {e}")
        
    print("This line should not be reached if abort kills process.")

if __name__ == "__main__":
    test_abort()
    print("Finished.")


import sounddevice as sd
import subprocess
import time
import os

def check_jack_client():
    print("Initializing sounddevice...")
    try:
        sd._initialize()
        print("sounddevice initialized.")
    except Exception as e:
        print(f"Failed to initialize sounddevice: {e}")
        return

    print("Checking jack_lsp...")
    try:
        output = subprocess.check_output(["jack_lsp"]).decode('utf-8')
        print("--- jack_lsp output ---")
        print(output)
        print("-----------------------")
        
        if "PortAudio" in output or "MeasureLab" in output:
             print("Found PortAudio/MeasureLab client in jack_lsp.")
        else:
             print("Did NOT find PortAudio/MeasureLab client in jack_lsp.")
             
    except Exception as e:
        print(f"jack_lsp failed: {e}")

    # Keep alive briefly just in case
    time.sleep(1)
    
    print("Terminating sounddevice...")
    sd._terminate()

if __name__ == "__main__":
    check_jack_client()

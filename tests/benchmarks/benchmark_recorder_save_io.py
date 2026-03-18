import time
import tracemalloc
import numpy as np
import os
import sys
import tempfile
import soundfile as sf
from unittest.mock import MagicMock, patch

def benchmark_save(duration_sec=120, sr=48000, channels=2):
    print(f"Benchmarking saving with {duration_sec}s of audio...")

    mocks = {
        'sounddevice': MagicMock(),
        'PyQt6.QtCore': MagicMock(),
        'PyQt6.QtWidgets': MagicMock()
    }

    with patch.dict(sys.modules, mocks):
        from src.gui.widgets.recorder_player import RecorderPlayer
        from src.core.audio_engine import AudioEngine

        # Setup audio engine and player
        audio_engine = MagicMock(spec=AudioEngine)
        audio_engine.sample_rate = sr
        player = RecorderPlayer(audio_engine)

        # Generate large dummy temp file manually
        # This simulates what _file_writer does
        fd, temp_file = tempfile.mkstemp(suffix=".wav")
        player._temp_record_file = temp_file

        # generate 120 seconds of random float data
        frames = duration_sec * sr
        data = np.random.rand(frames, channels).astype(np.float32)

        with sf.SoundFile(temp_file, mode="w", samplerate=sr, channels=channels, subtype="FLOAT", format="WAV") as f:
            f.write(data)

        print(f"Created temp file: {temp_file} ({os.path.getsize(temp_file)/1024/1024:.2f} MB)")

        filepath = "benchmark_output.wav"
        if os.path.exists(filepath):
            os.remove(filepath)

        # Measure memory and time
        tracemalloc.start()
        start_time = time.time()

        try:
            success, msg = player.save_recording(filepath)
            print(f"Result: {success}, {msg}")
        except Exception as e:
            print(f"Error saving: {e}")
        finally:
            current, peak = tracemalloc.get_traced_memory()
            end_time = time.time()
            tracemalloc.stop()

        print(f"Time taken: {end_time - start_time:.4f} seconds")
        print(f"Peak memory usage: {peak / 1024 / 1024:.2f} MB")

        # Cleanup
        if os.path.exists(filepath):
            os.remove(filepath)
        if os.path.exists(temp_file):
            os.remove(temp_file)

if __name__ == "__main__":
    benchmark_save(duration_sec=300)

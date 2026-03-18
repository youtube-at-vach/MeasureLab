import time
import tracemalloc
import numpy as np
import os
import tempfile
import soundfile as sf
import shutil
from unittest.mock import MagicMock

def benchmark_save_worker(duration_sec=600, sr=48000, channels=2):
    print(f"Benchmarking FileSaveWorker with {duration_sec}s of audio...")

    class MockFileSaveWorker_Block:
        def __init__(self, source_path, target_path, format=None, subtype=None):
            self.source_path = source_path
            self.target_path = target_path
            self.format = format
            self.subtype = subtype
            self.finished = MagicMock()

        def run(self):
            try:
                WRITE_BLOCK_SIZE = 65536
                info = sf.info(self.source_path)
                samplerate = info.samplerate
                channels = info.channels

                with sf.SoundFile(self.source_path, "r") as f_in:
                    with sf.SoundFile(
                        self.target_path,
                        "w",
                        samplerate=samplerate,
                        channels=channels,
                        format=self.format,
                        subtype=self.subtype,
                    ) as f_out:
                        while f_in.tell() < f_in.frames:
                            data = f_in.read(WRITE_BLOCK_SIZE)
                            f_out.write(data)
                self.finished.emit(True, f"Saved: {self.target_path}")
            except Exception as e:
                self.finished.emit(False, str(e))

    class MockFileSaveWorker_Shutil:
        def __init__(self, source_path, target_path, format=None, subtype=None):
            self.source_path = source_path
            self.target_path = target_path
            self.format = format
            self.subtype = subtype
            self.finished = MagicMock()

        def run(self):
            try:
                if self.format is None and self.subtype is None:
                    # If format/subtype are unspecified or unchanged, we might just be able to copy the file?
                    # But actually we might want to convert. If we have to convert we must use sf.
                    # Wait, the prompt says "Utilizing shutil.copyfileobj or larger chunks is often preferred."
                    pass
            except Exception:
                pass

    class MockFileSaveWorker_Block_Large:
        def __init__(self, source_path, target_path, format=None, subtype=None):
            self.source_path = source_path
            self.target_path = target_path
            self.format = format
            self.subtype = subtype
            self.finished = MagicMock()

        def run(self):
            try:
                WRITE_BLOCK_SIZE = 1048576 # 1M frames
                info = sf.info(self.source_path)
                samplerate = info.samplerate
                channels = info.channels

                with sf.SoundFile(self.source_path, "r") as f_in:
                    with sf.SoundFile(
                        self.target_path,
                        "w",
                        samplerate=samplerate,
                        channels=channels,
                        format=self.format,
                        subtype=self.subtype,
                    ) as f_out:
                        while f_in.tell() < f_in.frames:
                            data = f_in.read(WRITE_BLOCK_SIZE)
                            f_out.write(data)
                self.finished.emit(True, f"Saved: {self.target_path}")
            except Exception as e:
                self.finished.emit(False, str(e))

    class MockFileSaveWorker_Block_ReadBlocks:
        def __init__(self, source_path, target_path, format=None, subtype=None):
            self.source_path = source_path
            self.target_path = target_path
            self.format = format
            self.subtype = subtype
            self.finished = MagicMock()

        def run(self):
            try:
                info = sf.info(self.source_path)
                samplerate = info.samplerate
                channels = info.channels

                with sf.SoundFile(self.source_path, "r") as f_in:
                    with sf.SoundFile(
                        self.target_path,
                        "w",
                        samplerate=samplerate,
                        channels=channels,
                        format=self.format,
                        subtype=self.subtype,
                    ) as f_out:
                        for block in f_in.blocks(blocksize=1048576):
                            f_out.write(block)
                self.finished.emit(True, f"Saved: {self.target_path}")
            except Exception as e:
                self.finished.emit(False, str(e))

    class MockFileSaveWorker_Shutil_CopyFileObj:
        def __init__(self, source_path, target_path, format=None, subtype=None):
            self.source_path = source_path
            self.target_path = target_path
            self.format = format
            self.subtype = subtype
            self.finished = MagicMock()

        def run(self):
            try:
                # If format and subtype aren't changing, or we just want to save the WAV we can use shutil
                # The issue is we might need to convert based on format
                info = sf.info(self.source_path)
                target_format = self.format if self.format else info.format
                target_subtype = self.subtype if self.subtype else info.subtype

                if target_format == info.format and target_subtype == info.subtype:
                    # Direct binary copy!
                    with open(self.source_path, 'rb') as f_in:
                        with open(self.target_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out, length=1024*1024)
                else:
                    # Fallback to soundfile copy
                    with sf.SoundFile(self.source_path, "r") as f_in:
                        with sf.SoundFile(
                            self.target_path,
                            "w",
                            samplerate=info.samplerate,
                            channels=info.channels,
                            format=self.format,
                            subtype=self.subtype,
                        ) as f_out:
                            for block in f_in.blocks(blocksize=1048576):
                                f_out.write(block)

                self.finished.emit(True, f"Saved: {self.target_path}")
            except Exception as e:
                self.finished.emit(False, str(e))


    # Generate large dummy temp file manually
    fd, temp_file = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    duration_sec * sr
    with sf.SoundFile(temp_file, mode="w", samplerate=sr, channels=channels, subtype="FLOAT", format="WAV") as f:
        chunk_size = sr * 10
        for _ in range(duration_sec // 10):
            data = np.random.rand(chunk_size, channels).astype(np.float32)
            f.write(data)

    print(f"Created temp file: {temp_file} ({os.path.getsize(temp_file)/1024/1024:.2f} MB)")

    filepath = "benchmark_output.wav"

    def run_bench(worker_cls, name):
        if os.path.exists(filepath):
            os.remove(filepath)

        worker = worker_cls(temp_file, filepath)

        tracemalloc.start()
        start_time = time.time()

        worker.run()

        current, peak = tracemalloc.get_traced_memory()
        end_time = time.time()
        tracemalloc.stop()

        print(f"[{name}] Time taken: {end_time - start_time:.4f} seconds, Peak memory: {peak / 1024 / 1024:.2f} MB")

    run_bench(MockFileSaveWorker_Block, "Original Block Size (64k)")
    run_bench(MockFileSaveWorker_Block_Large, "Large Block Size (1M)")
    run_bench(MockFileSaveWorker_Block_ReadBlocks, "SoundFile blocks(1M)")
    run_bench(MockFileSaveWorker_Shutil_CopyFileObj, "Shutil.copyfileobj / Fallback")

    if os.path.exists(filepath):
        os.remove(filepath)
    if os.path.exists(temp_file):
        os.remove(temp_file)

if __name__ == "__main__":
    benchmark_save_worker(duration_sec=600)

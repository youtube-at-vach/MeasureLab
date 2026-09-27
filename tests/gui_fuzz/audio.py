"""Feed real AudioEngine client callbacks without opening PortAudio."""

from __future__ import annotations

import numpy as np

from src.core.audio_engine import AudioEngine


class _NoDeviceStream:
    active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.active = False


class FuzzAudioEngine(AudioEngine):
    def _start_master_stream(self) -> None:
        self._update_channel_modes()
        self.stream = _NoDeviceStream()
        self.active_dtype = self._get_dtype()

    def list_devices(self):
        return []

    def list_host_apis(self):
        return []

    def get_host_apis(self):
        return []

    def feed(self, kind: str, frames: int = 1024) -> np.ndarray:
        """Execute production mixing, acquisition and callback paths synchronously."""
        rate = float(self.sample_rate)
        t = np.arange(frames, dtype=np.float32) / rate
        rng = np.random.default_rng(1367 + frames)
        mono = {
            "silence": lambda: np.zeros(frames, dtype=np.float32),
            "sine": lambda: (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32),
            "noise": lambda: rng.uniform(-0.3, 0.3, frames).astype(np.float32),
            "tiny": lambda: (1e-9 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32),
            "full": lambda: (0.99 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32),
            "clipping": lambda: np.full(frames, 1.2, dtype=np.float32),
            "dc": lambda: np.full(frames, 0.2, dtype=np.float32),
        }[kind if kind not in {"left", "right", "different"} else "sine"]()
        right = np.zeros_like(mono) if kind == "left" else (-0.5 * mono if kind == "different" else mono)
        if kind == "right":
            mono, right = np.zeros_like(mono), mono
        data = np.column_stack((mono, right))
        output = np.zeros_like(data)
        self._master_callback(data, output, frames, None, 0)
        if self.last_callback_error is not None:
            raise AssertionError(f"Audio callback failed: {self.last_callback_error!r}") from self.last_callback_error
        if not np.isfinite(output).all():
            raise AssertionError("Audio output contains NaN/Inf")
        return output

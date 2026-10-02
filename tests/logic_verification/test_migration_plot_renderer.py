"""The spike verifier must reject incorrect pixels, source lookup and transport."""

import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import migration_plot_renderer as spike


def metadata(points, frame, low=0.0, high=1.0):
    data = spike.values(points, frame)
    index = spike.expected_cursor(points, low, high)
    return {
        "input_sha256": spike.digest(data.tobytes()),
        "cursor_bin": index,
        "cursor_hz": index * 24000 / (points - 1),
        "cursor_value": float(data[index]),
    }


def test_deterministic_f32_source_and_cursor_endpoints():
    data = spike.values(100_000, 0)
    assert data.dtype == np.dtype("float32")
    assert data[0] == np.float32(0.001)
    assert data[100_000 // 3] == np.float32(0.8)
    assert spike.expected_cursor(100_001, 0.375, 0.875) == 62_500
    assert spike.expected_cursor(100_001, 0.375, 0.875, 1) == 87_500
    assert spike.expected_cursor(100_001, 0, 1, 1) == 100_000


def test_peak_loss_and_wrong_cursor_cannot_pass():
    pixels = np.zeros((spike.HEIGHT, spike.WIDTH, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    good = metadata(100_000, 0)
    with pytest.raises(RuntimeError, match="lost the narrow peak"):
        spike.check_gpu(good, pixels.tobytes(), 100_000, 0, 0, 1, "spectrum")
    with pytest.raises(RuntimeError, match="original data"):
        spike.check_gpu({**good, "cursor_value": 0.0}, pixels.tobytes(), 100_000, 0, 0, 1, "spectrum")
    with pytest.raises(RuntimeError, match="input bytes differ"):
        spike.check_gpu({**good, "input_sha256": "wrong"}, pixels.tobytes(), 100_000, 0, 0, 1, "spectrum")


def test_rolling_history_corruption_cannot_pass():
    pixels = np.zeros((spike.HEIGHT, spike.WIDTH, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    with pytest.raises(RuntimeError, match="rolling image row"):
        spike.check_gpu(metadata(1024, 35), pixels.tobytes(), 1024, 35, 0, 1, "spectrogram")


@pytest.mark.parametrize("size", [1, spike.WIDTH * spike.HEIGHT * 4])
def test_wrong_size_or_truncated_transport_cannot_pass(size):
    worker = object.__new__(spike.Worker)
    worker.process = SimpleNamespace(stdout=io.BytesIO(json.dumps({"rgba_bytes": size}).encode() + b"\nshort"))
    with pytest.raises(RuntimeError, match="unexpected GPU image size|truncated GPU image"):
        worker.receive()

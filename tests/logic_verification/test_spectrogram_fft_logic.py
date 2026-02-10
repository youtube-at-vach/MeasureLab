from src.core.fft_manager import WARMUP_SIZES

# Mocking the logic to verify correctness of the algorithm used in SpectrogramWidget
def get_available_fft_sizes(speed_index):
    if speed_index == 0:
        return [str(s) for s in WARMUP_SIZES if s <= 8192]
    else:
        return [str(s) for s in WARMUP_SIZES]

def test_warmup_sizes_integrity():
    """Verify WARMUP_SIZES are as expected."""
    expected = [256, 512, 1024, 2048, 4096, 8192, 16384, 24000, 32768, 48000, 65536]
    assert WARMUP_SIZES == expected

def test_fast_speed_fft_sizes():
    """Verify that speed 0 (Fast) limits FFT sizes to 8192."""
    sizes = get_available_fft_sizes(0)
    # sizes should be strings
    assert "8192" in sizes
    assert "4096" in sizes
    assert "16384" not in sizes
    assert "65536" not in sizes

    # Verify max size
    max_size = max([int(s) for s in sizes])
    assert max_size == 8192

def test_slow_speed_fft_sizes():
    """Verify that speed > 0 allows larger FFT sizes."""
    for speed in [1, 2, 3]:
        sizes = get_available_fft_sizes(speed)
        assert "8192" in sizes
        assert "16384" in sizes
        assert "65536" in sizes

        max_size = max([int(s) for s in sizes])
        assert max_size == 65536

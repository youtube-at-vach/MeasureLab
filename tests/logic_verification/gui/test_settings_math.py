from src.gui.widgets.settings import next_power_of_two


def test_next_power_of_two_positive_integers():
    """Test standard power of two calculation for positive integers."""
    assert next_power_of_two(1) == 1
    assert next_power_of_two(2) == 2
    assert next_power_of_two(3) == 4
    assert next_power_of_two(4) == 4
    assert next_power_of_two(5) == 8
    assert next_power_of_two(15) == 16
    assert next_power_of_two(16) == 16
    assert next_power_of_two(255) == 256
    assert next_power_of_two(256) == 256
    assert next_power_of_two(257) == 512
    assert next_power_of_two(1000) == 1024
    assert next_power_of_two(1024) == 1024
    assert next_power_of_two(1025) == 2048


def test_next_power_of_two_non_positive():
    """Test edge cases for zero and negative numbers which fallback to 256."""
    assert next_power_of_two(0) == 256
    assert next_power_of_two(-1) == 256
    assert next_power_of_two(-100) == 256
    assert next_power_of_two(0.0) == 256
    assert next_power_of_two(-5.5) == 256


def test_next_power_of_two_floats():
    """
    Test behavior with floating point numbers.
    The function truncates with int(n), so 2.9 becomes 2 (power of 2 is 2),
    while 3.0 becomes 3 (power of 2 is 4).
    """
    assert next_power_of_two(2.0) == 2
    assert next_power_of_two(2.1) == 2
    assert next_power_of_two(2.9) == 2
    assert next_power_of_two(3.0) == 4
    assert next_power_of_two(3.1) == 4
    assert next_power_of_two(3.9) == 4
    assert next_power_of_two(4.0) == 4


def test_next_power_of_two_large_numbers():
    """Test with larger buffer sizes used in audio processing."""
    assert next_power_of_two(32768) == 32768
    assert next_power_of_two(65536) == 65536
    assert next_power_of_two(65537) == 131072

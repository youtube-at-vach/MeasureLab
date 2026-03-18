from src.core.generators import PinkNoise


def test_pink_noise_initialization():
    generator = PinkNoise()
    assert generator.b0 == 0.0
    assert generator.b1 == 0.0
    assert generator.b2 == 0.0
    assert generator.b3 == 0.0
    assert generator.b4 == 0.0
    assert generator.b5 == 0.0
    assert generator.b6 == 0.0

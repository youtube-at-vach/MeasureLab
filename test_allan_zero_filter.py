
import numpy as np

def test_zero_filtering():
    taus = np.array([0.1, 0.2, 0.4, 0.8, 1.6])
    devs = np.array([1e-5, 0.0, 1e-6, 0.0, 1e-7])

    print(f"Original Devs: {devs}")

    mask = (devs > 1e-20)

    filtered_taus = taus[mask]
    filtered_devs = devs[mask]

    print(f"Filtered Devs: {filtered_devs}")

    assert len(filtered_devs) == 3
    assert np.all(filtered_devs > 0)
    assert 0.2 not in filtered_taus
    assert 0.8 not in filtered_taus
    print("Zero filtering test passed!")

if __name__ == "__main__":
    test_zero_filtering()

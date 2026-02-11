
import numpy as np

def check_copyto_truncation():
    floats = np.array([1.1, 1.9, -1.1, -1.9, 0.5, -0.5, 2**60 + 0.5], dtype=np.float64)
    expected = floats.astype(np.int64)

    ints = np.zeros_like(floats, dtype=np.int64)
    np.copyto(ints, floats, casting='unsafe')

    print("Floats:   ", floats)
    print("Expected: ", expected)
    print("Copyto:   ", ints)

    if np.array_equal(expected, ints):
        print("MATCH")
    else:
        print("MISMATCH")

if __name__ == "__main__":
    check_copyto_truncation()

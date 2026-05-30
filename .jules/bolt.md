## 2026-05-26 - Optimized Sine Fitting Frequency Search with Euler's Formula

**Learning:** In tight NumPy calculation loops like `_perform_coarse_search`, `np.exp(1j * phase)` is slow due to memory allocation and complex exponential math. The codebase's memory advises replacing `np.exp(1j * phase)` with Euler's formula (`np.cos(phase) + 1j * np.sin(phase)`), using `out=` buffers to prevent reallocation. Applying this with large complex signal arrays (using `np.empty` to preallocate and `np.cos(phase, out=buffer.real)` and `np.sin(phase, out=buffer.imag)`) reduced the search time from ~3.6s to ~2.8s in tight benchmark loops, cutting `optimize_frequency` time by ~20%.

**Action:** Whenever using `np.exp(1j * phase)` heavily inside a signal processing loop over arrays, preallocate a complex NumPy array and populate it directly with `np.cos(..., out=buffer.real)` and `np.sin(..., out=buffer.imag)` to save significant memory reallocation overhead and complex math time.

## 2024-05-19 - Inverse Filter JSON Array Validation Optimization

**Learning:** When validating very large 2D arrays loaded from JSON, using exhaustive list comprehensions and `all()` with `isinstance` on every single element is extremely slow. Instead, performing a quick sanity check on the container and the first element, and letting subsequent vectorized operations (like numpy conversion or sorting) implicitly validate or fail, drastically improves performance.
**Action:** Replace exhaustive nested element-by-element type validation with shallow checks plus `try...except` handling when parsing large datasets into structured data like numpy arrays or Pandas DataFrames.

## 2025-02-23 - Vectorize Arbitrary Harmonic Generator

**Learning:** Calculating signals in a tight loop inside a Python thread adds latency. Vectorizing over the time array using matrix multiplication and angle addition eliminates Python loop overhead.
**Action:** Replace sequential element-wise numpy array additions and multiple trigonometric functions with matrix products using the angle addition formula.

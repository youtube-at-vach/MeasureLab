## 2024-05-28 - Optimize Arbitrary Harmonic Generator math with matrix multiplication

**Learning:** When calculating many harmonic sine waves with arbitrary amplitudes and phases, broadcasting a full (harmonics, frames) array and computing `np.sin()` on it is slow and memory intensive. The fastest way is to mathematically decompose the amplitude and phase into real and imaginary coefficients using the sine addition formula, and then compute the final signal in one go using matrix multiplication (`@`) against a pre-computed array of pure harmonic sine/cosine basis vectors.

**Action:** Whenever using `np.exp(1j * phase)` heavily inside a signal processing loop over arrays, preallocate a complex NumPy array and populate it directly with `np.cos(..., out=buffer.real)` and `np.sin(..., out=buffer.imag)` to save significant memory reallocation overhead and complex math time.

## 2024-05-19 - Inverse Filter JSON Array Validation Optimization

**Learning:** When validating very large 2D arrays loaded from JSON, using exhaustive list comprehensions and `all()` with `isinstance` on every single element is extremely slow. Instead, performing a quick sanity check on the container and the first element, and letting subsequent vectorized operations (like numpy conversion or sorting) implicitly validate or fail, drastically improves performance.
**Action:** Replace exhaustive nested element-by-element type validation with shallow checks plus `try...except` handling when parsing large datasets into structured data like numpy arrays or Pandas DataFrames.
**Action:** When vectorizing audio harmonic generation, use dot products (`@`) instead of looping over harmonics or broadcasting large arrays inside `np.sin()`.
## 2026-05-28 - Optimized PyQt QTableWidget Updates By Reusing Items

**Learning:** When updating data in QTableWidget (e.g., high-frequency realtime results or benchmark tables), unconditionally instantiating new `QTableWidgetItem` objects and calling `setItem` is extremely slow and triggers high garbage collection and layout overhead. Instead, using the walrus operator (`:=`) to assign and reuse an existing item reference (`if item := self.table.item(row, col): item.setText(val) else: ...`) minimizes PyQt C++ crossings and object creations. Furthermore, surrounding large table updates with `self.table.setUpdatesEnabled(False)` and a `try/finally` block drastically reduces redraw overhead.

**Action:** Whenever a PyQt table is populated continuously or has dynamic row counts, use `setUpdatesEnabled(False)`, and always lookup existing table items with `item()` before instantiating new `QTableWidgetItem` objects.

## 2026-05-26 - Optimized Sine Fitting Frequency Search with Euler's Formula

**Learning:** In tight NumPy calculation loops like `_perform_coarse_search`, `np.exp(1j * phase)` is slow due to memory allocation and complex exponential math. The codebase's memory advises replacing `np.exp(1j * phase)` with Euler's formula (`np.cos(phase) + 1j * np.sin(phase)`), using `out=` buffers to prevent reallocation. Applying this with large complex signal arrays (using `np.empty` to preallocate and `np.cos(phase, out=buffer.real)` and `np.sin(phase, out=buffer.imag)`) reduced the search time from ~3.6s to ~2.8s in tight benchmark loops, cutting `optimize_frequency` time by ~20%.

**Action:** Whenever using `np.exp(1j * phase)` heavily inside a signal processing loop over arrays, preallocate a complex NumPy array and populate it directly with `np.cos(..., out=buffer.real)` and `np.sin(..., out=buffer.imag)` to save significant memory reallocation overhead and complex math time.

## 2026-05-28 - Optimized PyQt QTableWidget Updates By Reusing Items

**Learning:** When updating data in QTableWidget (e.g., high-frequency realtime results or benchmark tables), unconditionally instantiating new `QTableWidgetItem` objects and calling `setItem` is extremely slow and triggers high garbage collection and layout overhead. Instead, using the walrus operator (`:=`) to assign and reuse an existing item reference (`if item := self.table.item(row, col): item.setText(val) else: ...`) minimizes PyQt C++ crossings and object creations. Furthermore, surrounding large table updates with `self.table.setUpdatesEnabled(False)` and a `try/finally` block drastically reduces redraw overhead.

**Action:** Whenever a PyQt table is populated continuously or has dynamic row counts, use `setUpdatesEnabled(False)`, and always lookup existing table items with `item()` before instantiating new `QTableWidgetItem` objects.

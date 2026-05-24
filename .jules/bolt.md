## 2026-05-21 - [Vectorize mathematical search and optimize membership testing]

**Learning:** In NumPy, `np.outer(A, B)` has significant overhead due to internal flattening and function calls. Direct array broadcasting `(A[:, None] * B[None, :])` is functionally equivalent for 1D arrays and measurably faster in high-frequency numerical loops. Additionally, while set membership testing (`in {...}`) provides O(1) lookups, indiscriminately converting `for` loops to iterate over sets scrambles iteration order, which can cause UI components or business logic to execute randomly.
**Action:** When replacing `np.outer` with broadcasting, verify input array shapes. When optimizing lists to sets for `in` operator lookups, ensure they are strictly membership checks (`if x in {...}`) and not iterations. For `for` loops, convert lists to tuples (`for x in (...)`) to preserve deterministic execution order while still gaining a minor speedup over lists.

## 2024-05-22 - PyQtGraph fast plot clearing

**Learning:** In pyqtgraph, calling `.clear()` on `PlotDataItem` instances (e.g., plot curves) is significantly faster than using `.setData([], [])` to empty the data. It bypasses the overhead of parsing empty lists and instantiating empty NumPy arrays within the data-updating pipeline.
**Action:** Always use `.clear()` to reset or clear pyqtgraph curve data instead of passing empty lists to `setData`.

## 2024-05-23 - LockInHarmonicAnalyzer QTableWidget performance improvement

**Learning:** Instantiating new `QTableWidgetItem` on every update loop severely impacts performance due to unnecessary memory allocations and garbage collection overhead.
**Action:** Always prefer `.item(row, col)` with the walrus operator to fetch existing table items and `.setText()` to update them, avoiding the creation of new `QTableWidgetItem` whenever possible. Also, disable UI updates using `setUpdatesEnabled(False)` when iterating rows to further reduce UI stuttering.

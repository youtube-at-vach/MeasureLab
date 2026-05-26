## 2024-05-25 - Replace setData([], []) with clear() in pyqtgraph

**Learning:** pyqtgraph's setData([], []) introduces unnecessary overhead by creating empty NumPy arrays and parsing empty lists. While using .clear() avoids this overhead, it should be noted that in infrequent UI event handlers, this is a micro-optimization with minimal measurable overall impact, but it remains a cleaner and more idiomatic practice.
**Action:** Always prefer .clear() for emptying plot data in pyqtgraph instead of setting empty lists, both for readability and to bypass the internal list-parsing pipeline, even if the absolute performance gain is small in non-frequent loops.

## $(date +%Y-%m-%d) - Optimize CSV Exporter Unique Filtering
**Learning:** Using Python loops with `list.extend()` to aggregate data before calling `np.unique()` adds significant overhead due to list reallocation and list-to-array conversion.
**Action:** Replace `list.extend()` + `np.unique()` with list comprehensions that collect numpy arrays directly, and use `np.unique(np.concatenate(arrays))` to leverage C-level execution for array concatenation. Additionally, recognize that `np.unique` returns a sorted array by default, making subsequent `.sort()` calls redundant.

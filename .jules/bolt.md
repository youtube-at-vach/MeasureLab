## 2024-05-25 - Replace setData([], []) with clear() in pyqtgraph

**Learning:** pyqtgraph's setData([], []) introduces unnecessary overhead by creating empty NumPy arrays and parsing empty lists. While using .clear() avoids this overhead, it should be noted that in infrequent UI event handlers, this is a micro-optimization with minimal measurable overall impact, but it remains a cleaner and more idiomatic practice.
**Action:** Always prefer .clear() for emptying plot data in pyqtgraph instead of setting empty lists, both for readability and to bypass the internal list-parsing pipeline, even if the absolute performance gain is small in non-frequent loops.


import timeit
import numpy as np

class MockModule:
    def __init__(self):
        self.heatmap_size = (600, 400)
        self.heatmap_l = np.random.rand(600, 400) * 300.0
        self.heatmap_r = np.random.rand(600, 400) * 300.0

def original_implementation(module):
    w, h = module.heatmap_size
    rgba = np.zeros((w, h, 4), dtype=np.ubyte)

    # Green (Left)
    l_val = np.clip(module.heatmap_l, 0, 255).astype(np.ubyte)
    # Red (Right)
    r_val = np.clip(module.heatmap_r, 0, 255).astype(np.ubyte)

    rgba[..., 0] = r_val  # R
    rgba[..., 1] = l_val  # G
    # B is 0
    alpha = np.maximum(l_val, r_val)
    rgba[..., 3] = alpha
    return rgba

class OptimizedWidget:
    def __init__(self, module):
        self.module = module
        self._rgba_buffer = None
        self._clip_buffer = None

    def update(self):
        w, h = self.module.heatmap_size

        # Check if buffer needs (re)allocation
        if (self._rgba_buffer is None or
            self._rgba_buffer.shape[:2] != (w, h)):
            self._rgba_buffer = np.zeros((w, h, 4), dtype=np.ubyte)
            # Create float buffer for clipping
            self._clip_buffer = np.empty((w, h), dtype=self.module.heatmap_l.dtype)

        # 1. Clip Left (Green)
        # Reuse _clip_buffer for intermediate float result
        np.clip(self.module.heatmap_l, 0, 255, out=self._clip_buffer)

        # Write to G channel.
        # Note: astype(np.ubyte) creates a temporary array.
        # We can't avoid this easily without Cython, but we saved the float alloc.
        self._rgba_buffer[..., 1] = self._clip_buffer.astype(np.ubyte)

        # 2. Clip Right (Red)
        np.clip(self.module.heatmap_r, 0, 255, out=self._clip_buffer)
        self._rgba_buffer[..., 0] = self._clip_buffer.astype(np.ubyte)

        # 3. Alpha (Max of R, G)
        # Use in-place maximum calculation on ubyte buffers
        np.maximum(self._rgba_buffer[..., 1], self._rgba_buffer[..., 0], out=self._rgba_buffer[..., 3])

        # B is untouched (0) because we initialized with zeros and only overwrite R, G, A.
        # If heatmap size changes, we re-allocate with zeros.

        return self._rgba_buffer

def run_benchmark():
    module = MockModule()

    # Warmup and Verify Correctness
    orig_res = original_implementation(module)
    widget = OptimizedWidget(module)
    opt_res = widget.update()

    if not np.array_equal(orig_res, opt_res):
        print("Mismatch in results!")
        if orig_res.shape != opt_res.shape:
             print(f"Shape mismatch: {orig_res.shape} vs {opt_res.shape}")
        else:
             diff = orig_res != opt_res
             print(f"Indices differing: {np.where(diff)}")
             idx = np.where(diff)
             if len(idx[0]) > 0:
                 print(f"Orig: {orig_res[idx][0]}")
                 print(f"Opt: {opt_res[idx][0]}")
        return False

    iters = 2000

    start = timeit.default_timer()
    for _ in range(iters):
        original_implementation(module)
    t_orig = timeit.default_timer() - start

    start = timeit.default_timer()
    for _ in range(iters):
        widget.update()
    t_opt = timeit.default_timer() - start

    print(f"Original: {t_orig*1000/iters:.4f} ms/iter")
    print(f"Optimized: {t_opt*1000/iters:.4f} ms/iter")
    print(f"Speedup: {t_orig/t_opt:.2f}x")
    return True

if __name__ == "__main__":
    if not run_benchmark():
        exit(1)

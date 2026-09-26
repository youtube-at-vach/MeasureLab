import functools
import numpy as np
import multiprocessing
import threading
import logging
import os
import json
import base64
import hashlib
from pathlib import Path
from src.core.localization import tr

logger = logging.getLogger(__name__)

try:
    import pyfftw

    HAS_PYFFTW = True
except ImportError:
    HAS_PYFFTW = False
    logger.warning("pyfftw not found. Falling back to numpy.fft")

# Common FFT sizes offered by the real-time instruments.
WARMUP_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384, 24000, 32768, 48000, 65536]
# Medium sizes for standard exhaustive optimization (on-demand)
MEDIUM_SIZES = [131072, 262144, 524288]
# Huge sizes that take very long to optimize (optional)
HUGE_SIZES = [1048576, 2097152, 4194304]


class FFTManager:
    """
    Manages FFTW plans to optimize FFT performance.
    """

    def __init__(self):
        self._plans = {}
        self._lock = threading.Lock()
        self._measured_plans = set()
        self._optimization_status_known = True

        # Limit the maximum number of threads to 8. Small 1D transforms use one
        # thread in _create_plan to avoid FFTW's synchronization overhead.
        self.threads = min(8, multiprocessing.cpu_count())

        if HAS_PYFFTW:
            pyfftw.config.NUM_THREADS = self.threads

        # Store wisdom in XDG compliant user data directory
        # This fixes the issue where wisdom cannot be saved in read-only AppImage environments
        # We also use JSON with Base64 encoding instead of pickle for security (prevents arbitrary code execution)
        if os.environ.get("MEASURELAB_TESTING") == "1":
            import tempfile

            self.wisdom_dir = Path(tempfile.gettempdir()) / "MeasureLab_test" / "wisdom"
        else:
            xdg_data_home = os.environ.get("XDG_DATA_HOME")
            if not xdg_data_home:
                xdg_data_home = os.path.join(os.path.expanduser("~"), ".local", "share")
            self.wisdom_dir = Path(xdg_data_home) / "MeasureLab" / "wisdom"

        self.wisdom_path = self.wisdom_dir / "pyfftw_wisdom"

        # Create directory if it doesn't exist
        try:
            self.wisdom_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Failed to create wisdom directory: {e}")

        self._in_warmup = False
        self.load_wisdom()

    def load_wisdom(self):
        if not HAS_PYFFTW:
            return

        if self.wisdom_path.exists():
            self._optimization_status_known = False
            try:
                # Use JSON + Base64 to safely load wisdom (avoids pickle deserialization vulnerabilities)
                with open(self.wisdom_path, "r") as f:
                    data = json.load(f)
                    if not isinstance(data, list):
                        raise ValueError(f"Invalid wisdom format in {self.wisdom_path}")

                # Decode base64 strings back to bytes
                wisdom = tuple(base64.b64decode(item) for item in data)
                imported = pyfftw.import_wisdom(wisdom)
                if all(imported[:2]):
                    self._load_optimization_status()
                else:
                    self._optimization_status_known = False
                logger.debug(f"Loaded pyfftw wisdom from {self.wisdom_path}")
            except Exception as e:
                logger.warning(f"Failed to load wisdom: {e}")

    def _load_optimization_status(self):
        """Load verified plan details; legacy wisdom has no inspectable size list."""
        self._optimization_status_known = False
        status_path = self.wisdom_path.with_name(self.wisdom_path.name + "_status.json")
        try:
            with open(status_path, encoding="utf-8") as f:
                status = json.load(f)
            digest = hashlib.sha256(self.wisdom_path.read_bytes()).hexdigest()
            if status["version"] != 1 or status["wisdom_sha256"] != digest:
                return
            plans = status["measured_plans"]
            if not isinstance(plans, list):
                return
            measured = set()
            for plan in plans:
                if (
                    not isinstance(plan, list)
                    or len(plan) != 3
                    or not isinstance(plan[0], int)
                    or plan[0] <= 0
                    or plan[1] not in ("float32", "float64")
                    or plan[2] not in ("FFTW_FORWARD", "FFTW_BACKWARD")
                ):
                    return
                measured.add(tuple(plan))
            self._measured_plans = measured
            self._optimization_status_known = True
        except (OSError, ValueError, TypeError, KeyError) as e:
            logger.debug(f"Could not read FFT optimization status: {e}")

    def get_measured_plan_sizes(self):
        """Return measured forward FFT sizes by precision, or None for legacy wisdom."""
        coverage = self.get_forward_plan_coverage()
        if coverage is None:
            return None
        return {
            dtype: {size for size, plan_dtype in coverage["measured"] if plan_dtype == dtype}
            for dtype in ("float32", "float64")
        }

    def get_forward_plan_coverage(self):
        """Return measured and estimated real FFT plans, or None for legacy wisdom."""
        if not HAS_PYFFTW or not self._optimization_status_known:
            return None
        with self._lock:
            measured = {(size, dtype) for size, dtype, direction in self._measured_plans if direction == "FFTW_FORWARD"}
            estimated = {
                (size, dtype)
                for (size, dtype, direction), plan in self._plans.items()
                if direction == "FFTW_FORWARD" and "FFTW_MEASURE" not in plan["flags"]
            }
        return {"measured": measured, "estimated": estimated - measured}

    def save_wisdom(self):
        if not HAS_PYFFTW:
            return

        try:
            self.wisdom_path.parent.mkdir(parents=True, exist_ok=True)
            wisdom = pyfftw.export_wisdom()

            # Convert tuple of bytes to list of base64 strings
            data = [base64.b64encode(item).decode("ascii") for item in wisdom]

            with open(self.wisdom_path, "w") as f:
                json.dump(data, f)
            digest = hashlib.sha256(self.wisdom_path.read_bytes()).hexdigest()
            status_path = self.wisdom_path.with_name(self.wisdom_path.name + "_status.json")
            with open(status_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "version": 1,
                        "wisdom_sha256": digest,
                        "measured_plans": [list(plan) for plan in sorted(self._measured_plans)],
                    },
                    f,
                )
            logger.debug(f"Saved pyfftw wisdom to {self.wisdom_path}")
        except Exception as e:
            logger.error(f"Failed to save wisdom: {e}")

    def _get_dtype_str(self, dtype):
        """
        Returns "float32" if dtype is single precision (float32 or complex64),
        otherwise returns "float64".
        """
        if dtype == np.float32 or dtype == np.complex64:
            return "float32"
        return "float64"

    def get_plan(self, size, dtype="float64", flags=("FFTW_ESTIMATE",), direction="FFTW_FORWARD"):
        """
        Get or create an FFT plan for the given size.
        flags: tuple of strategies, e.g. ('FFTW_ESTIMATE',) or ('FFTW_MEASURE',)
        direction: 'FFTW_FORWARD' (rfft) or 'FFTW_BACKWARD' (irfft)
        """
        key = (size, dtype, direction)

        # Fast path: Check if plan exists without acquiring lock
        # This is safe because:
        # 1. Dictionary get is atomic in CPython
        # 2. Plan entries are only mutated during creation (under lock)
        # 3. If we get a stale entry (extremely unlikely), the lock below handles it
        existing_plan = self._plans.get(key)
        if existing_plan:
            existing_flags = existing_plan.get("flags", ("FFTW_MEASURE",))
            # If we have what we need, return immediately
            # If requested flags require upgrade (e.g. MEASURE requested but only ESTIMATE exists), fall through to lock
            if not ("FFTW_MEASURE" in flags and "FFTW_MEASURE" not in existing_flags):
                return existing_plan

        with self._lock:
            # Check if plan exists
            if key in self._plans:
                existing_plan = self._plans[key]
                existing_flags = existing_plan.get("flags", ("FFTW_MEASURE",))  # Default to measure if unknown (legacy)

                # If we requested MEASURE but have ESTIMATE, we should upgrade (re-create)
                if "FFTW_MEASURE" in flags and "FFTW_MEASURE" not in existing_flags:
                    logger.debug(f"Upgrading plan for size {size} from ESTIMATE to MEASURE")
                    self._create_plan(size, dtype, flags, direction)
                # Otherwise, use existing (ESTIMATE is fine if we requested MEASURE or ESTIMATE and have MEASURE,
                # and MEASURE is fine if we requested ESTIMATE and have MEASURE)
            else:
                self._create_plan(size, dtype, flags, direction)

            return self._plans.get(key)

    def _create_plan(self, size, dtype_str, flags, direction):
        if not HAS_PYFFTW:
            return

        try:
            # Determine dtypes based on precision
            if dtype_str == "float32":
                real_dtype = "float32"
                complex_dtype = "complex64"
            else:
                real_dtype = "float64"
                complex_dtype = "complex128"

            # Determine input/output shapes and dtypes based on direction
            # rfft: Real input -> Complex output (FFTW_FORWARD)
            # irfft: Complex input -> Real output (FFTW_BACKWARD)
            if direction == "FFTW_FORWARD":
                input_shape = size
                input_dtype = real_dtype
                output_shape = size // 2 + 1
                output_dtype = complex_dtype
            else:
                input_shape = size // 2 + 1
                input_dtype = complex_dtype
                output_shape = size
                output_dtype = real_dtype

            input_array = pyfftw.empty_aligned(input_shape, dtype=input_dtype)
            output_array = pyfftw.empty_aligned(output_shape, dtype=output_dtype)

            # Use provided flags (ESTIMATE vs MEASURE)
            plan_threads = 1 if size <= 8192 else self.threads
            fft_object = pyfftw.FFTW(input_array, output_array, direction=direction, flags=flags, threads=plan_threads)

            # Save wisdom only if we did a measurement (MEASURE or PATIENT etc),
            # though ESTIMATE doesn't generate wisdom worth saving usually, saving doesn't hurt.
            # But typically we only care about saving after costly optimizations.
            self._plans[(size, dtype_str, direction)] = {
                "object": fft_object,
                "input": input_array,
                "output": output_array,
                "flags": flags,
                "lock": threading.Lock(),
            }
            if "FFTW_MEASURE" in flags:
                self._measured_plans.add((size, dtype_str, direction))
                if not self._in_warmup:
                    self.save_wisdom()
            logger.debug(f"Created pyfftw plan for size {size} ({dtype_str}, {direction}) with flags {flags}")

        except Exception as e:
            logger.error(f"Failed to create pyfftw plan for size {size}: {e}")

    def rfft(self, data, out=None, copy=True):
        """
        Perform Real FFT.
        """
        size = len(data)
        # Determine dtype
        dtype_str = self._get_dtype_str(data.dtype)

        if HAS_PYFFTW:
            # fast default: ESTIMATE
            plan_entry = self.get_plan(size, dtype_str, flags=("FFTW_ESTIMATE",), direction="FFTW_FORWARD")
            if plan_entry:
                with plan_entry["lock"]:
                    fft_obj = plan_entry["object"]
                    input_arr = plan_entry["input"]

                    # Copy data
                    input_arr[:] = data

                    # Execute
                    fft_obj()

                    # Return copy of result (to avoid buffer reuse issues by caller)
                    if out is not None:
                        out[:] = plan_entry["output"]
                        return out
                    elif not copy:
                        return plan_entry["output"]
                    else:
                        return plan_entry["output"].copy()

        # Fallback
        result = np.fft.rfft(data)
        if out is not None:
            out[:] = result
            return out
        return result

    def irfft(self, data, n=None, out=None, copy=True):
        """
        Perform Inverse Real FFT.
        """
        if n is None:
            n = 2 * (len(data) - 1)

        # Check dtype compatibility
        dtype_str = self._get_dtype_str(data.dtype)

        if HAS_PYFFTW:
            plan_entry = self.get_plan(n, dtype_str, flags=("FFTW_ESTIMATE",), direction="FFTW_BACKWARD")
            if plan_entry:
                with plan_entry["lock"]:
                    fft_obj = plan_entry["object"]
                    input_arr = plan_entry["input"]

                    # Safety check for input length
                    # PyFFTW input buffer expects n//2 + 1 complex numbers
                    expected_len = len(input_arr)
                    if len(data) != expected_len:
                        result = np.fft.irfft(data, n=n)
                        if out is not None:
                            out[:] = result
                            return out
                        return result

                    input_arr[:] = data
                    fft_obj()

                    # FFTW behavior note: Standard FFTW inverse transforms are unnormalized (scaled by N).
                    # However, pyfftw in this environment appears to produce normalized output (matching numpy.fft.irfft).
                    # Explicit 1/N scaling caused double-normalization in tests, so it is omitted here.

                    if out is not None:
                        out[:] = plan_entry["output"]
                        return out
                    elif not copy:
                        return plan_entry["output"]
                    else:
                        return plan_entry["output"].copy()

        result = np.fft.irfft(data, n=n)
        if out is not None:
            out[:] = result
            return out
        return result

    def rfftfreq(self, n, d=1.0):
        """
        Wrapper for numpy.fft.rfftfreq.
        """
        return np.fft.rfftfreq(n, d)

    def prepare_startup_plans(self):
        """Build the common real-time plans without measuring every FFT size.

        FFTW_ESTIMATE uses imported wisdom when available. On a fresh install it
        builds plans in milliseconds, so instruments are ready before the main
        window opens without making the user wait for a full FFTW measurement.
        Explicit optimization in Settings still uses warmup() and FFTW_MEASURE.
        """
        if not HAS_PYFFTW:
            return

        for size in WARMUP_SIZES:
            for dtype in ("float64", "float32"):
                self.get_plan(size, dtype, flags=("FFTW_ESTIMATE",))

    def warmup(self, callback=None, force=False, exhaustive=False, include_huge=False):
        """
        Pre-calculate plans for common sizes.
        callback: function(str) -> None, used to report progress.
        force: bool, if True, clears cached wisdom/plans and re-measures.
        exhaustive: bool, if True, optimizes WARMUP + MEDIUM sizes.
        include_huge: bool, if True, also optimizes HUGE sizes (requires exhaustive=True).
        """
        if not HAS_PYFFTW:
            return

        if force:
            pyfftw.forget_wisdom()
            with self._lock:
                self._plans.clear()
                self._measured_plans.clear()
                self._optimization_status_known = True
            if self.wisdom_path.exists():
                try:
                    self.wisdom_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete wisdom file: {e}")
            status_path = self.wisdom_path.with_name(self.wisdom_path.name + "_status.json")
            try:
                status_path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"Failed to delete FFT optimization status: {e}")

        sizes_to_optimize = WARMUP_SIZES
        if exhaustive:
            sizes_to_optimize = WARMUP_SIZES + MEDIUM_SIZES
            if include_huge:
                sizes_to_optimize += HUGE_SIZES

        self._in_warmup = True
        try:
            total = len(sizes_to_optimize)
            for _i, size in enumerate(sizes_to_optimize):
                if callback:
                    # Progress ranges from 0 to total-1 during optimization
                    callback(tr("Optimizing FFT... (Size {0}) {1}/{2}").format(size, _i + 1, total))

                # Use MEASURE for warmup to ensure peak performance
                for dtype in ("float64", "float32"):
                    plan = self.get_plan(size, dtype, flags=("FFTW_MEASURE",))
                    if plan is None or "FFTW_MEASURE" not in plan["flags"]:
                        raise RuntimeError(f"Failed to create FFT plan for size {size} ({dtype})")
        finally:
            self._in_warmup = False

        # Save wisdom at the end of warmup to capture any new measurements
        if callback:
            callback(tr("Saving optimization results... {0}/{1}").format(total, total + 1))
        self.save_wisdom()

        if callback:
            callback(tr("Done {0}/{1}").format(total + 1, total + 1))

    def get_available_windows(self):
        """
        Returns a list of supported window functions from scipy.signal.
        Strings are compatible with scipy.signal.get_window().
        """
        return [
            "boxcar",
            "triang",
            "blackman",
            "hamming",
            "hann",
            "bartlett",
            "flattop",
            "parzen",
            "bohman",
            "blackmanharris",
            "nuttall",
            "barthann",
            "cosine",
            "exponential",
            "tukey",
            "taylor",
        ]


@functools.lru_cache(maxsize=16)
def get_dpss_windows(N, NW=3, Kmax=None):
    """
    Get DPSS windows, caching them for performance.
    """
    # Lazy import to avoid hard dependency at module level
    from scipy.signal.windows import dpss

    if Kmax is None:
        Kmax = int(2 * NW - 1)

    return dpss(N, NW, int(Kmax))


# Global instance for easy access
fft_manager = FFTManager()

import numpy as np
import multiprocessing
import logging
import os
import pickle
from pathlib import Path
from src.core.localization import tr

logger = logging.getLogger(__name__)

try:
    import pyfftw

    HAS_PYFFTW = True
except ImportError:
    HAS_PYFFTW = False
    logger.warning("pyfftw not found. Falling back to numpy.fft")

# Common FFT sizes to optimize during startup
# Common FFT sizes to optimize during startup
WARMUP_SIZES = [256, 512, 1024, 2048, 4096, 8192, 16384, 24000, 32768, 48000, 65536]
# Medium sizes for standard exhaustive optimization (on-demand)
MEDIUM_SIZES = [131072, 262144]
# Huge sizes that take very long to optimize (optional)
HUGE_SIZES = [1048576, 2097152, 4194304]
# Backwards compatibility or default full set if needed, but logic currently uses WARMUP + MEDIUM
EXTENDED_SIZES = MEDIUM_SIZES + HUGE_SIZES


class FFTManager:
    """
    Manages FFTW plans to optimize FFT performance.
    """

    def __init__(self):
        self._plans = {}
        self.threads = multiprocessing.cpu_count()
        if HAS_PYFFTW:
            pyfftw.config.NUM_THREADS = self.threads

        # Store wisdom in XDG compliant user data directory
        # This fixes the issue where wisdom cannot be saved in read-only AppImage environments
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

        self.load_wisdom()

    def load_wisdom(self):
        if not HAS_PYFFTW:
            return

        if self.wisdom_path.exists():
            try:
                with open(self.wisdom_path, "rb") as f:
                    wisdom = pickle.load(f)
                    pyfftw.import_wisdom(wisdom)
                logger.info(f"Loaded pyfftw wisdom from {self.wisdom_path}")
            except Exception as e:
                logger.warning(f"Failed to load wisdom: {e}")

    def save_wisdom(self):
        if not HAS_PYFFTW:
            return

        try:
            self.wisdom_path.parent.mkdir(parents=True, exist_ok=True)
            wisdom = pyfftw.export_wisdom()
            with open(self.wisdom_path, "wb") as f:
                pickle.dump(wisdom, f)
            logger.info(f"Saved pyfftw wisdom to {self.wisdom_path}")
        except Exception as e:
            logger.error(f"Failed to save wisdom: {e}")

    def get_plan(self, size, dtype="float64", flags=("FFTW_ESTIMATE",), direction="FFTW_FORWARD"):
        """
        Get or create an FFT plan for the given size.
        flags: tuple of strategies, e.g. ('FFTW_ESTIMATE',) or ('FFTW_MEASURE',)
        direction: 'FFTW_FORWARD' (rfft) or 'FFTW_BACKWARD' (irfft)
        """
        key = (size, dtype, direction)

        # Check if plan exists
        if key in self._plans:
            existing_plan = self._plans[key]
            existing_flags = existing_plan.get("flags", ("FFTW_MEASURE",))  # Default to measure if unknown (legacy)

            # If we requested MEASURE but have ESTIMATE, we should upgrade (re-create)
            if "FFTW_MEASURE" in flags and "FFTW_MEASURE" not in existing_flags:
                logger.info(f"Upgrading plan for size {size} from ESTIMATE to MEASURE")
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
            # We focus on rfft (Real input -> Complex output) and irfft (Complex input -> Real output)
            if direction == "FFTW_FORWARD":
                if dtype_str == "float32":
                    input_array = pyfftw.empty_aligned(size, dtype="float32")
                    output_array = pyfftw.empty_aligned(size // 2 + 1, dtype="complex64")
                else:
                    input_array = pyfftw.empty_aligned(size, dtype="float64")
                    output_array = pyfftw.empty_aligned(size // 2 + 1, dtype="complex128")
            else:  # FFTW_BACKWARD (irfft)
                if dtype_str == "float32":
                    input_array = pyfftw.empty_aligned(size // 2 + 1, dtype="complex64")
                    output_array = pyfftw.empty_aligned(size, dtype="float32")
                else:
                    input_array = pyfftw.empty_aligned(size // 2 + 1, dtype="complex128")
                    output_array = pyfftw.empty_aligned(size, dtype="float64")

            # Use provided flags (ESTIMATE vs MEASURE)
            fft_object = pyfftw.FFTW(input_array, output_array, direction=direction, flags=flags, threads=self.threads)

            # Save wisdom only if we did a measurement (MEASURE or PATIENT etc),
            # though ESTIMATE doesn't generate wisdom worth saving usually, saving doesn't hurt.
            # But typically we only care about saving after costly optimizations.
            if "FFTW_MEASURE" in flags:
                self.save_wisdom()

            self._plans[(size, dtype_str, direction)] = {
                "object": fft_object,
                "input": input_array,
                "output": output_array,
                "flags": flags,
            }
            logger.info(f"Created pyfftw plan for size {size} ({dtype_str}, {direction}) with flags {flags}")

        except Exception as e:
            logger.error(f"Failed to create pyfftw plan for size {size}: {e}")

    def rfft(self, data, out=None):
        """
        Perform Real FFT.
        """
        size = len(data)
        # Determine dtype
        if data.dtype == np.float32:
            dtype_str = "float32"
        else:
            dtype_str = "float64"  # Default for generic types

        if HAS_PYFFTW:
            # fast default: ESTIMATE
            plan_entry = self.get_plan(size, dtype_str, flags=("FFTW_ESTIMATE",), direction="FFTW_FORWARD")
            if plan_entry:
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
                else:
                    return plan_entry["output"].copy()

        # Fallback
        result = np.fft.rfft(data)
        if out is not None:
            out[:] = result
            return out
        return result

    def irfft(self, data, n=None, out=None):
        """
        Perform Inverse Real FFT.
        """
        if n is None:
            n = 2 * (len(data) - 1)

        # Check dtype compatibility
        if data.dtype == np.complex64:
            dtype_str = "float32"
        else:
            dtype_str = "float64"

        if HAS_PYFFTW:
            plan_entry = self.get_plan(n, dtype_str, flags=("FFTW_ESTIMATE",), direction="FFTW_BACKWARD")
            if plan_entry:
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

                # FFTW is unnormalized, numpy.fft.irfft includes 1/n scaling
                if out is not None:
                    np.divide(plan_entry["output"], n, out=out)
                    return out
                else:
                    result = plan_entry["output"].copy()
                    result /= n
                    return result

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
            self._plans.clear()
            if self.wisdom_path.exists():
                try:
                    self.wisdom_path.unlink()
                except Exception:
                    pass

        sizes_to_optimize = WARMUP_SIZES
        if exhaustive:
            sizes_to_optimize = WARMUP_SIZES + MEDIUM_SIZES
            if include_huge:
                sizes_to_optimize += HUGE_SIZES

        total = len(sizes_to_optimize)
        for _i, size in enumerate(sizes_to_optimize):
            if callback:
                # Progress ranges from 0 to total-1 during optimization
                callback(tr("Optimizing FFT... (Size {0})").format(size))

            # Use MEASURE for warmup to ensure peak performance
            self.get_plan(size, "float64", flags=("FFTW_MEASURE",))

        # Save wisdom at the end of warmup to capture any new measurements
        if callback:
            callback(tr("Saving optimization results... {0}/{1}").format(total, total + 1))
        self.save_wisdom()

        if callback:
            callback(tr("Done {0}/{1}").format(total + 1, total + 1))


# Global instance for easy access
fft_manager = FFTManager()


import numpy as np
import multiprocessing
import logging
import os
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pyfftw
    HAS_PYFFTW = True
except ImportError:
    HAS_PYFFTW = False
    logger.warning("pyfftw not found. Falling back to numpy.fft")

# Common FFT sizes to optimize during startup
WARMUP_SIZES = [1024, 2048, 4096, 8192, 16384, 32768, 65536]
# Extended sizes for exhaustive optimization (on-demand)
EXTENDED_SIZES = [131072, 262144, 1048576, 2097152, 4194304]



class FFTManager:
    """
    Manages FFTW plans to optimize FFT performance.
    """
    def __init__(self):
        self._plans = {}
        self.threads = multiprocessing.cpu_count()
        if HAS_PYFFTW:
             pyfftw.config.NUM_THREADS = self.threads
        
        # Store wisdom in project root for portability
        root_dir = Path(__file__).resolve().parent.parent.parent
        self.wisdom_dir = root_dir / 'wisdom'
        self.wisdom_path = self.wisdom_dir / 'pyfftw_wisdom'
        # Create directory if it doesn't exist (done in save, but good to ensure for load check logic if we expanded it)
        try:
            self.wisdom_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        
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

    def get_plan(self, size, dtype='float64'):
        """
        Get or create an FFT plan for the given size.
        """
        key = (size, dtype)
        if key not in self._plans:
            self._create_plan(size, dtype)
        
        return self._plans.get(key)

    def _create_plan(self, size, dtype_str):
        if not HAS_PYFFTW:
            return

        try:
            # We focus on rfft (Real input -> Complex output)
            if dtype_str == 'float32':
                input_array = pyfftw.empty_aligned(size, dtype='float32')
                output_array = pyfftw.empty_aligned(size // 2 + 1, dtype='complex64')
            else:
                input_array = pyfftw.empty_aligned(size, dtype='float64')
                output_array = pyfftw.empty_aligned(size // 2 + 1, dtype='complex128')

            # Use ESTIMATE for faster creation. MEASURE can be very slow for large sizes.
            fft_object = pyfftw.FFTW(
                input_array, 
                output_array, 
                direction='FFTW_FORWARD', 
                flags=('FFTW_MEASURE',), 
                threads=self.threads
            )
            
            # Save wisdom after creating new plan
            self.save_wisdom()
            
            self._plans[(size, dtype_str)] = {
                'object': fft_object,
                'input': input_array,
                'output': output_array
            }
            logger.info(f"Created pyfftw plan for size {size} ({dtype_str})")

        except Exception as e:
            logger.error(f"Failed to create pyfftw plan for size {size}: {e}")

    def rfft(self, data):
        """
        Perform Real FFT.
        """
        size = len(data)
        # Determine dtype
        if data.dtype == np.float32:
            dtype_str = 'float32'
        else:
            dtype_str = 'float64' # Default for generic types
            
        if HAS_PYFFTW:
            plan_entry = self.get_plan(size, dtype_str)
            if plan_entry:
                fft_obj = plan_entry['object']
                input_arr = plan_entry['input']
                
                # Copy data 
                input_arr[:] = data
                
                # Execute
                fft_obj()
                
                # Return copy of result (to avoid buffer reuse issues by caller)
                return plan_entry['output'].copy()
        
        # Fallback
        return np.fft.rfft(data)

    def warmup(self, callback=None, force=False, exhaustive=False):
        """
        Pre-calculate plans for common sizes.
        callback: function(str) -> None, used to report progress.
        force: bool, if True, clears cached wisdom/plans and re-measures.
        exhaustive: bool, if True, optimizes ALL supported sizes including very large ones.
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
            sizes_to_optimize = WARMUP_SIZES + EXTENDED_SIZES

        total = len(sizes_to_optimize)
        for i, size in enumerate(sizes_to_optimize):
            if callback:
                callback(f"Optimizing FFT (Size {size})... {i+1}/{total}")
            
            # Check if plan exists in memory first (fastest)
            # If not, create it. _create_plan will use wisdom if available (fast),
            # or MEASURE if not (slow).
            self.get_plan(size, 'float64')

        # Save wisdom at the end of warmup to capture any new measurements
        self.save_wisdom()



# Global instance for easy access
fft_manager = FFTManager()

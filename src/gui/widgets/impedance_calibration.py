import bisect
import json
import logging

logger = logging.getLogger(__name__)


class ImpedanceCalibrator:
    def __init__(self):
        self.cal_open = {}
        self.cal_short = {}
        self.cal_load = {}
        self.load_standard_real = 100.0  # Ohm
        self.use_calibration = False
        self.use_cal_interpolation = True

        # Calibration Cache (to avoid sorting keys every time)
        # We store (ref, length, sorted_keys) for each known dictionary attribute.
        # This is strictly local to this instance and avoids global cache memory leaks.
        # Map: 'open'/'short'/'load' -> (cal_dict_obj, cal_dict_len, sorted_keys_list)
        self._cal_cache_state = {}

    def apply_calibration(self, z_meas, freq):
        """
        Apply Open/Short/Load (OSL) calibration.
        Formula:
        Z_dut = Z_std * ((Z_open - Z_load) * (Z_meas - Z_short)) / ((Z_open - Z_meas) * (Z_load - Z_short))
        Fallback to Open/Short (OS) if Load not available:
        Z_dut = (Z_meas - Z_short) / (1 - (Z_meas - Z_short) * Y_open)
        """
        if not self.cal_short or not self.cal_open:
            return z_meas

        # Get Calibration Data (Always Interpolate)
        # Pass cache keys to enable safe caching of sorted keys.
        z_short = self._get_interpolated_cal_value(self.cal_short, freq, cache_key="short")
        z_open = self._get_interpolated_cal_value(self.cal_open, freq, cache_key="open")
        if self.cal_load:
            z_load = self._get_interpolated_cal_value(self.cal_load, freq, cache_key="load")
        else:
            z_load = None

        # OSL Calibration
        if z_load is not None:
            z_std = self.load_standard_real

            # Denominator check
            term1 = z_open - z_meas
            term2 = z_load - z_short
            if abs(term1) < 1e-12 or abs(term2) < 1e-12:
                return z_meas

            numerator = z_std * (z_open - z_load) * (z_meas - z_short)
            denominator = term1 * term2

            return numerator / denominator

        # OS Calibration (Fallback)
        if z_open == 0:
            return z_meas
        y_open = 1.0 / z_open

        numerator = z_meas - z_short
        denominator = 1.0 - (numerator * y_open)

        if abs(denominator) < 1e-12:
            return z_meas

        return numerator / denominator

    def _get_interpolated_cal_value(self, cal_dict, freq, cache_key=None):
        """
        Get interpolated calibration value for a specific frequency.
        Uses linear interpolation on complex real/imag parts.
        If freq is outside range, uses nearest neighbor.
        """
        # --- Caching sorted keys ---
        # Sorting is expensive (O(N log N)), so we cache the sorted keys.
        # Safe caching requires validation of identity and content change.
        # We rely on 'cache_key' (e.g., 'open') to scope the cache to a specific attribute.

        sorted_freqs = None

        if cache_key is not None:
            # Check if we have a valid cache entry
            if cache_key in self._cal_cache_state:
                cached_ref, cached_len, cached_keys = self._cal_cache_state[cache_key]
                # Validate: Object Identity AND Length (detects in-place additions)
                if (cal_dict is cached_ref) and (len(cal_dict) == cached_len):
                    sorted_freqs = cached_keys

        if sorted_freqs is None:
            # Cache miss or invalid -> Re-sort
            sorted_freqs = sorted(cal_dict.keys())
            if cache_key is not None:
                self._cal_cache_state[cache_key] = (cal_dict, len(cal_dict), sorted_freqs)

        if not sorted_freqs:
            return 0j

        if freq <= sorted_freqs[0]:
            return cal_dict[sorted_freqs[0]]
        if freq >= sorted_freqs[-1]:
            return cal_dict[sorted_freqs[-1]]

        # --- Binary Search Interval ---
        # Find index i such that sorted_freqs[i] <= freq <= sorted_freqs[i+1]

        idx = bisect.bisect_right(sorted_freqs, freq)
        # bisect_right returns insertion point after freq.
        # Since we checked freq > sorted_freqs[0] and freq < sorted_freqs[-1],
        # idx will be in range [1, len-1].

        i = idx - 1
        # Now sorted_freqs[i] <= freq < sorted_freqs[i+1]

        f_low = sorted_freqs[i]
        f_high = sorted_freqs[i + 1]

        t = (freq - f_low) / (f_high - f_low)
        z_low = cal_dict[f_low]
        z_high = cal_dict[f_high]

        # Interpolate Real and Imag separately
        r = z_low.real + t * (z_high.real - z_low.real)
        im = z_low.imag + t * (z_high.imag - z_low.imag)
        return complex(r, im)

    def save_calibration(self, filename):
        data = {
            "cal_open": self._serialize_cal(self.cal_open),
            "cal_short": self._serialize_cal(self.cal_short),
            "cal_load": self._serialize_cal(self.cal_load),
            "load_std_real": self.load_standard_real,
        }
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)

    def load_calibration(self, filename):
        try:
            with open(filename, "r") as f:
                data = json.load(f)

            self.cal_open = self._deserialize_cal(data.get("cal_open", {}))
            self.cal_short = self._deserialize_cal(data.get("cal_short", {}))
            self.cal_load = self._deserialize_cal(data.get("cal_load", {}))
            self.load_standard_real = data.get("load_std_real", 100.0)
            return True, ""
        except Exception as e:
            return False, str(e)

    def _serialize_cal(self, cal_dict):
        # Dict[float, complex] -> Dict[str, [real, imag]]
        return {str(f): [z.real, z.imag] for f, z in cal_dict.items()}

    def _deserialize_cal(self, data_dict):
        # Dict[str, [real, imag]] -> Dict[float, complex]
        new_cal = {}
        for f_str, z_list in data_dict.items():
            try:
                f = float(f_str)
                z = complex(z_list[0], z_list[1])
                new_cal[f] = z
            except Exception:
                pass
        return new_cal

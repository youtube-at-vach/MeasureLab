import json
import os
import logging

import numpy as np


class CalibrationManager:
    """
    Manages audio calibration data (sensitivity, gain) and conversions.
    Stores data in a JSON file.
    """

    def __init__(self, config_path="calibration.json"):
        self.config_path = config_path
        self.logger = logging.getLogger(self.__class__.__name__)
        self.input_sensitivity = 1.0  # Volts per Full Scale (V/FS) (Peak)
        self.output_gain = 1.0  # Volts per Full Scale (V/FS) (Peak)
        # Whether the output gain was explicitly calibrated by the user.
        # Used to decide when to offer voltage-based UI controls.
        self.output_gain_is_calibrated = False
        self.frequency_calibration = 1.0  # Multiplier for frequency correction
        self.frequency_calibration_1pps = 1.0  # Independent 1PPS-derived calibration
        self.lockin_gain_offset = 0.0  # dB offset for Lock-in Amplifier
        # SPL calibration: maps measured (C-weighted) dBFS to SPL.
        # Stored as an offset: SPL[dB] = dBFS_C + spl_offset_db.
        self.spl_offset_db = None
        self.profiles = {}
        self.last_profile = None
        self.frequency_map = []
        # Caches for vectorized interpolation
        self._map_freqs = np.array([])
        self._map_mags = np.array([])
        self._map_phases = np.array([])
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                    self.input_sensitivity = data.get("input_sensitivity", 1.0)
                    self.output_gain = data.get("output_gain", 1.0)
                    # New flag (backward compatible)
                    if "output_gain_is_calibrated" in data:
                        self.output_gain_is_calibrated = bool(data.get("output_gain_is_calibrated"))
                    else:
                        # Heuristic for older files: treat non-default values as calibrated.
                        try:
                            self.output_gain_is_calibrated = abs(float(self.output_gain) - 1.0) > 1e-12
                        except Exception:
                            self.output_gain_is_calibrated = False
                    self.frequency_calibration = data.get("frequency_calibration", 1.0)
                    self.frequency_calibration_1pps = data.get("frequency_calibration_1pps", 1.0)
                    self.lockin_gain_offset = data.get("lockin_gain_offset", 0.0)

                    # New format
                    if "spl_offset_db" in data:
                        try:
                            self.spl_offset_db = float(data.get("spl_offset_db"))
                        except Exception:
                            self.spl_offset_db = None

                    # Backward compatibility (older dict-based format)
                    if self.spl_offset_db is None:
                        legacy = data.get("spl_calibration", None)
                        if isinstance(legacy, dict) and legacy:
                            entry = legacy.get("speaker") or legacy.get("subwoofer")
                            if entry is None:
                                try:
                                    entry = next(iter(legacy.values()))
                                except Exception:
                                    entry = None
                            if isinstance(entry, dict) and "offset_db" in entry:
                                try:
                                    self.spl_offset_db = float(entry.get("offset_db"))
                                except Exception:
                                    self.spl_offset_db = None

                    self.profiles = data.get("profiles", {})
                    self.last_profile = data.get("last_profile")
            except Exception as e:
                self.logger.error("Failed to load calibration: %s", e)

    def save(self):
        # Synchronize current settings to the active profile if one is selected
        if self.last_profile and self.last_profile in self.profiles:
            p = self.profiles[self.last_profile]
            p["input_sensitivity"] = self.input_sensitivity
            p["output_gain"] = self.output_gain
            p["output_gain_is_calibrated"] = bool(self.output_gain_is_calibrated)
            p["frequency_calibration"] = self.frequency_calibration
            p["frequency_calibration_1pps"] = self.frequency_calibration_1pps
            p["lockin_gain_offset"] = self.lockin_gain_offset
            p["spl_offset_db"] = self.spl_offset_db

        data = {
            "input_sensitivity": self.input_sensitivity,
            "output_gain": self.output_gain,
            "output_gain_is_calibrated": bool(self.output_gain_is_calibrated),
            "frequency_calibration": self.frequency_calibration,
            "frequency_calibration_1pps": self.frequency_calibration_1pps,
            "lockin_gain_offset": self.lockin_gain_offset,
            # Keep a single SPL calibration value.
            "spl_offset_db": self.spl_offset_db,
            "profiles": getattr(self, "profiles", {}),
            "last_profile": self.last_profile,
        }
        try:
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            self.logger.error("Failed to save calibration: %s", e)

    # --- SPL Calibration ---

    def set_spl_calibration(self, measured_dbfs_c, measured_spl_db):
        """Stores SPL calibration as an offset (SPL = dBFS_C + spl_offset_db)."""
        try:
            measured_dbfs_c = float(measured_dbfs_c)
            measured_spl_db = float(measured_spl_db)
        except Exception:
            raise ValueError("Invalid SPL calibration values") from None

        offset_db = measured_spl_db - measured_dbfs_c
        self.spl_offset_db = float(offset_db)
        self.save()

    def get_spl_offset_db(self):
        try:
            return None if self.spl_offset_db is None else float(self.spl_offset_db)
        except Exception:
            return None

    def dbfs_to_spl(self, dbfs_c, profile=None):
        """Converts (C-weighted) dBFS to SPL using the stored offset."""
        off = self.get_spl_offset_db()
        if off is None:
            return None
        return float(dbfs_c) + off

    def set_input_sensitivity(self, v_per_fs):
        """Sets input sensitivity in Volts (Peak) corresponding to 1.0 FS."""
        self.input_sensitivity = v_per_fs
        self.save()

    def set_output_gain(self, v_per_fs):
        """Sets output gain in Volts (Peak) corresponding to 1.0 FS."""
        try:
            v_per_fs = float(v_per_fs)
        except Exception:
            raise ValueError("Invalid output gain") from None
        if not np.isfinite(v_per_fs) or v_per_fs <= 0:
            raise ValueError("Invalid output gain")

        self.output_gain = v_per_fs
        self.output_gain_is_calibrated = True
        self.save()

    def set_frequency_calibration(self, factor):
        """Sets the frequency calibration factor (multiplier)."""
        self.frequency_calibration = factor
        self.save()

    def set_frequency_calibration_1pps(self, factor):
        """Sets the 1PPS-derived frequency calibration factor (multiplier)."""
        self.frequency_calibration_1pps = factor
        self.save()

    def set_last_profile(self, name):
        """Sets the last selected profile name."""
        self.last_profile = name
        self.save()

    # --- Profile Management ---

    def save_profile(self, name, device_name, host_api=None):
        """Saves current settings as a named profile."""
        if not hasattr(self, "profiles"):
            self.profiles = {}

        self.profiles[name] = {
            "device_name": device_name,
            "host_api": host_api,
            "input_sensitivity": self.input_sensitivity,
            "output_gain": self.output_gain,
            "output_gain_is_calibrated": self.output_gain_is_calibrated,
            "frequency_calibration": self.frequency_calibration,
            "frequency_calibration_1pps": self.frequency_calibration_1pps,
            "lockin_gain_offset": self.lockin_gain_offset,
            "spl_offset_db": self.spl_offset_db,
        }
        self.save()

    def load_profile(self, name):
        """Loads settings from a named profile."""
        if not hasattr(self, "profiles") or name not in self.profiles:
            raise ValueError(f"Profile '{name}' not found")

        p = self.profiles[name]
        self.input_sensitivity = p.get("input_sensitivity", self.input_sensitivity)
        self.output_gain = p.get("output_gain", self.output_gain)
        self.output_gain_is_calibrated = p.get("output_gain_is_calibrated", self.output_gain_is_calibrated)
        self.frequency_calibration = p.get("frequency_calibration", self.frequency_calibration)
        self.frequency_calibration_1pps = p.get("frequency_calibration_1pps", self.frequency_calibration_1pps)
        self.lockin_gain_offset = p.get("lockin_gain_offset", self.lockin_gain_offset)

        # spl_offset_db can be None, handled explicitly
        if "spl_offset_db" in p:
            self.spl_offset_db = p["spl_offset_db"]

        self.save()  # Persist as current

    def delete_profile(self, name):
        """Deletes a named profile."""
        if name in self.profiles:
            del self.profiles[name]
            self.save()

    def get_profiles(self):
        """Returns the dictionary of profiles."""
        if not hasattr(self, "profiles"):
            self.profiles = {}
        return self.profiles

    def dbfs_to_dbv(self, dbfs):
        """Converts dBFS to dBV."""
        # 0 dBFS = 20 * log10(1.0)
        # Voltage at 0 dBFS = input_sensitivity
        # dBV = 20 * log10(Voltage)
        # Voltage = 10^(dBFS/20) * input_sensitivity
        # dBV = 20 * log10(10^(dBFS/20) * input_sensitivity)
        #     = dBFS + 20 * log10(input_sensitivity)
        return dbfs + self.get_input_offset_db()

    def dbfs_to_volts(self, dbfs):
        """Converts dBFS to Volts (Peak)."""
        return (10 ** (dbfs / 20)) * self.input_sensitivity

    def get_input_offset_db(self):
        """Returns the dB offset to add to dBFS to get dBV."""
        return 20 * np.log10(self.input_sensitivity)

    # --- Frequency Correction Map ---

    def load_frequency_map(self, path):
        """
        Loads a frequency correction map from a JSON file.
        Format: [[freq, mag_db, phase_deg], ...]
        """
        if not os.path.exists(path):
            self.logger.warning("Calibration map not found: %s", path)
            return False

        try:
            with open(path, "r") as f:
                data = json.load(f)
                # Sort by frequency just in case
                self.frequency_map = sorted(data, key=lambda x: x[0])
                self._update_map_cache()
                self.logger.info("Loaded calibration map with %d points.", len(self.frequency_map))
                return True
        except Exception as e:
            self.logger.error("Failed to load calibration map: %s", e)
            return False

    def save_frequency_map(self, path, data):
        """
        Saves the frequency correction map to a JSON file.
        data: list of [freq, mag_db, phase_deg]
        """
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            self.frequency_map = sorted(data, key=lambda x: x[0])
            self._update_map_cache()
            self.logger.info("Saved calibration map to %s", path)
            return True
        except Exception as e:
            self.logger.error("Failed to save calibration map: %s", e)
            return False

    def get_frequency_correction(self, freq):
        """
        Returns (mag_correction_db, phase_correction_deg) for the given frequency.
        Uses linear interpolation.
        Returns (0.0, 0.0) if no map is loaded.
        """
        if not self.frequency_map:
            return 0.0, 0.0

        # If out of range, clamp to nearest
        if freq <= self.frequency_map[0][0]:
            return self.frequency_map[0][1], self.frequency_map[0][2]
        if freq >= self.frequency_map[-1][0]:
            return self.frequency_map[-1][1], self.frequency_map[-1][2]

        # Use cached numpy arrays for interpolation
        mag_corr = np.interp(freq, self._map_freqs, self._map_mags)
        phase_corr = np.interp(freq, self._map_freqs, self._map_phases)

        return mag_corr, phase_corr

    def _update_map_cache(self):
        if not self.frequency_map:
            self._map_freqs = np.array([])
            self._map_mags = np.array([])
            self._map_phases = np.array([])
            return

        data = np.array(self.frequency_map)
        self._map_freqs = data[:, 0]
        self._map_mags = data[:, 1]
        self._map_phases = data[:, 2]

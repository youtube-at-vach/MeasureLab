import json
import os
import logging
from copy import deepcopy

import numpy as np

from src.core.config_manager import ConfigManager


class CalibrationManager:
    """
    Manages audio calibration data (sensitivity, gain) and conversions.
    Stores data in a JSON file.
    """

    def __init__(self, config_filename="calibration.json"):
        # Resolve config path using ConfigManager's logic (User Data Directory)
        # This ensures consistent storage across platforms (e.g. macOS App Support)
        if os.path.dirname(config_filename):
            # If absolute or relative with dir, use as is
            self.config_path = config_filename
        else:
            # If just a filename, put in user data dir
            user_dir = ConfigManager.get_user_data_dir()
            try:
                os.makedirs(user_dir, mode=0o700, exist_ok=True)
                self.config_path = os.path.join(user_dir, config_filename)
            except Exception:
                # Fallback to current working directory
                self.config_path = os.path.abspath(config_filename)

        self.logger = logging.getLogger(self.__class__.__name__)
        self.input_sensitivity = 1.0  # Volts per Full Scale (V/FS) (Peak)
        # Whether the input sensitivity was explicitly calibrated by the user.
        # Physical voltage units must not be exposed while this is false.
        self.input_sensitivity_is_calibrated = False
        self.output_gain = 1.0  # Volts per Full Scale (V/FS) (Peak)
        # Whether the output gain was explicitly calibrated by the user.
        # Used to decide when to offer voltage-based UI controls.
        self.output_gain_is_calibrated = False
        self.frequency_calibration = 1.0  # Multiplier for frequency correction
        self.frequency_calibration_1pps = 1.0  # Independent 1PPS-derived calibration
        self.frequency_calibration_source = "basic"  # "basic" or "1pps"
        self.lockin_gain_offset = 0.0  # dB offset for Lock-in Amplifier
        # SPL calibration: maps measured (C-weighted) dBFS to SPL.
        # Stored as an offset: SPL[dB] = dBFS_C + spl_offset_db.
        self.spl_offset_db = None
        self.profiles = {}
        self.last_profile = None
        self.frequency_map = []
        # Caches for vectorized interpolation
        self._freq_cache = np.array([])
        self._mag_cache = np.array([])
        self._phase_cache = np.array([])
        self._map_cache = (np.array([]), np.array([]), np.array([]))
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                    self.input_sensitivity = data.get("input_sensitivity", 1.0)
                    if "input_sensitivity_is_calibrated" in data:
                        self.input_sensitivity_is_calibrated = bool(
                            data.get("input_sensitivity_is_calibrated")
                        )
                    else:
                        # Legacy files did not record this state. A non-default
                        # sensitivity could only be entered through calibration
                        # settings, so preserve it as calibrated. The ambiguous
                        # 1.0 V/FS case intentionally fails closed.
                        try:
                            self.input_sensitivity_is_calibrated = (
                                abs(float(self.input_sensitivity) - 1.0) > 1e-12
                            )
                        except Exception:
                            self.input_sensitivity_is_calibrated = False
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
                    self.frequency_calibration_source = data.get("frequency_calibration_source", "basic")
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

                    stored_profiles = data.get("profiles", {})
                    self.profiles = stored_profiles if isinstance(stored_profiles, dict) else {}
                    stored_last_profile = data.get("last_profile")
                    self.last_profile = (
                        stored_last_profile
                        if isinstance(stored_last_profile, str)
                        and stored_last_profile in self.profiles
                        else None
                    )
            except Exception as e:
                self.logger.error("Failed to load calibration: %s", e)

    def save(self):
        # Synchronize current settings to the active profile if one is selected
        if self.last_profile and self.last_profile in self.profiles:
            p = self.profiles[self.last_profile]
            p["input_sensitivity"] = self.input_sensitivity
            p["input_sensitivity_is_calibrated"] = bool(
                self.input_sensitivity_is_calibrated
            )
            p["output_gain"] = self.output_gain
            p["output_gain_is_calibrated"] = bool(self.output_gain_is_calibrated)
            p["frequency_calibration"] = self.frequency_calibration
            p["frequency_calibration_1pps"] = self.frequency_calibration_1pps
            p["frequency_calibration_source"] = self.frequency_calibration_source
            p["lockin_gain_offset"] = self.lockin_gain_offset
            p["spl_offset_db"] = self.spl_offset_db

        data = {
            "input_sensitivity": self.input_sensitivity,
            "input_sensitivity_is_calibrated": bool(
                self.input_sensitivity_is_calibrated
            ),
            "output_gain": self.output_gain,
            "output_gain_is_calibrated": bool(self.output_gain_is_calibrated),
            "frequency_calibration": self.frequency_calibration,
            "frequency_calibration_1pps": self.frequency_calibration_1pps,
            "frequency_calibration_source": self.frequency_calibration_source,
            "lockin_gain_offset": self.lockin_gain_offset,
            # Keep a single SPL calibration value.
            "spl_offset_db": self.spl_offset_db,
            "profiles": getattr(self, "profiles", {}),
            "last_profile": self.last_profile,
        }
        try:
            # Use os.open to ensure secure permissions (600) on creation
            fd = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

            # Ensure permissions on existing files (best effort)
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, 0o600)
                else:
                    os.chmod(self.config_path, 0o600)
            except Exception as e:
                self.logger.warning("Failed to set secure permissions for calibration file: %s", e)

            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=4)
            return True
        except Exception as e:
            self.logger.error("Failed to save calibration: %s", e)
            return False

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
        try:
            v_per_fs = float(v_per_fs)
        except Exception:
            raise ValueError("Invalid input sensitivity") from None
        if not np.isfinite(v_per_fs) or v_per_fs <= 0:
            raise ValueError("Invalid input sensitivity")

        self.input_sensitivity = v_per_fs
        self.input_sensitivity_is_calibrated = True
        self.save()

    @property
    def is_calibrated(self):
        """Backward-compatible alias for input sensitivity calibration state."""
        return bool(self.input_sensitivity_is_calibrated)

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

    def set_frequency_calibration_source(self, source):
        """Sets the active frequency calibration source ('basic' or '1pps')."""
        if source in ("basic", "1pps"):
            self.frequency_calibration_source = source
            self.save()

    def get_active_frequency_calibration(self):
        """Returns the calibration factor for the currently active source."""
        if self.frequency_calibration_source == "1pps":
            return self.frequency_calibration_1pps
        return self.frequency_calibration

    def set_lockin_gain_offset(self, offset):
        """Sets the gain offset for the lock-in amplifier in dB."""
        try:
            self.lockin_gain_offset = float(offset)
            self.save()
        except (ValueError, TypeError) as e:
            self.logger.warning("Invalid lock-in gain offset provided: %s", e)

    def set_last_profile(self, name):
        """Sets the last selected profile name without changing calibration values."""
        if name is not None and name not in self.profiles:
            raise ValueError(f"Profile '{name}' not found")
        self.last_profile = name
        self.save()

    # --- Profile Management ---

    @staticmethod
    def _normalize_profile_name(name):
        """Return a storage-safe profile name or raise a user-correctable error."""
        name = str(name).strip()
        if not name:
            raise ValueError("Profile name cannot be empty")
        if any(ord(char) < 32 for char in name):
            raise ValueError("Profile name contains invalid characters")
        return name

    @staticmethod
    def _default_calibration_snapshot():
        """Return the safe, explicitly uncalibrated state for a new profile."""
        return {
            "input_sensitivity": 1.0,
            "input_sensitivity_is_calibrated": False,
            "output_gain": 1.0,
            "output_gain_is_calibrated": False,
            "frequency_calibration": 1.0,
            "frequency_calibration_1pps": 1.0,
            "frequency_calibration_source": "basic",
            "lockin_gain_offset": 0.0,
            "spl_offset_db": None,
        }

    def _snapshot_current_calibration(self):
        """Capture all values owned by a calibration profile."""
        return {
            "input_sensitivity": self.input_sensitivity,
            "input_sensitivity_is_calibrated": bool(
                self.input_sensitivity_is_calibrated
            ),
            "output_gain": self.output_gain,
            "output_gain_is_calibrated": bool(self.output_gain_is_calibrated),
            "frequency_calibration": self.frequency_calibration,
            "frequency_calibration_1pps": self.frequency_calibration_1pps,
            "frequency_calibration_source": self.frequency_calibration_source,
            "lockin_gain_offset": self.lockin_gain_offset,
            "spl_offset_db": self.spl_offset_db,
        }

    def _apply_calibration_snapshot(self, snapshot):
        """Apply a complete profile snapshot while preserving legacy defaults."""
        self.input_sensitivity = snapshot.get("input_sensitivity", 1.0)
        if "input_sensitivity_is_calibrated" in snapshot:
            self.input_sensitivity_is_calibrated = bool(
                snapshot.get("input_sensitivity_is_calibrated")
            )
        else:
            try:
                self.input_sensitivity_is_calibrated = (
                    abs(float(self.input_sensitivity) - 1.0) > 1e-12
                )
            except Exception:
                self.input_sensitivity_is_calibrated = False

        self.output_gain = snapshot.get("output_gain", 1.0)
        self.output_gain_is_calibrated = bool(
            snapshot.get("output_gain_is_calibrated", False)
        )
        self.frequency_calibration = snapshot.get("frequency_calibration", 1.0)
        self.frequency_calibration_1pps = snapshot.get(
            "frequency_calibration_1pps", 1.0
        )
        self.frequency_calibration_source = snapshot.get(
            "frequency_calibration_source", "basic"
        )
        self.lockin_gain_offset = snapshot.get("lockin_gain_offset", 0.0)
        self.spl_offset_db = snapshot.get("spl_offset_db", None)

    @staticmethod
    def _profile_device_metadata(
        device_name,
        host_api=None,
        output_device_name="",
        output_host_api=None,
    ):
        """Build device metadata while retaining the legacy input-device keys."""
        input_name = str(device_name or "")
        input_api = str(host_api or "")
        return {
            "device_name": input_name,
            "host_api": input_api,
            "input_device_name": input_name,
            "input_host_api": input_api,
            "output_device_name": str(output_device_name or ""),
            "output_host_api": str(output_host_api or ""),
        }

    def _restore_profile_mutation(self, profiles, last_profile, snapshot):
        self.profiles = profiles
        self.last_profile = last_profile
        self._apply_calibration_snapshot(snapshot)

    def _save_profile_mutation_or_raise(self, profiles, last_profile, snapshot):
        if self.save():
            return
        self._restore_profile_mutation(profiles, last_profile, snapshot)
        raise OSError("Failed to save calibration profiles")

    def create_profile(
        self,
        name,
        device_name="",
        host_api=None,
        output_device_name="",
        output_host_api=None,
    ):
        """Create and activate an explicitly uncalibrated profile."""
        name = self._normalize_profile_name(name)
        if name in self.profiles:
            raise ValueError(f"Profile '{name}' already exists")

        old_profiles = deepcopy(self.profiles)
        old_last_profile = self.last_profile
        old_snapshot = self._snapshot_current_calibration()
        if not self.save():
            raise OSError("Failed to save the active calibration profile")

        snapshot = self._default_calibration_snapshot()
        profile = self._profile_device_metadata(
            device_name,
            host_api,
            output_device_name,
            output_host_api,
        )
        profile.update(snapshot)
        self.profiles[name] = profile
        self._apply_calibration_snapshot(snapshot)
        self.last_profile = name
        self._save_profile_mutation_or_raise(
            old_profiles, old_last_profile, old_snapshot
        )

    def duplicate_profile(
        self,
        name,
        device_name="",
        host_api=None,
        output_device_name="",
        output_host_api=None,
    ):
        """Save the current calibration state under a new name and activate it."""
        name = self._normalize_profile_name(name)
        if name in self.profiles:
            raise ValueError(f"Profile '{name}' already exists")

        old_profiles = deepcopy(self.profiles)
        old_last_profile = self.last_profile
        snapshot = self._snapshot_current_calibration()
        if not self.save():
            raise OSError("Failed to save the active calibration profile")

        profile = self._profile_device_metadata(
            device_name,
            host_api,
            output_device_name,
            output_host_api,
        )
        profile.update(snapshot)
        self.profiles[name] = profile
        self.last_profile = name
        self._save_profile_mutation_or_raise(
            old_profiles, old_last_profile, snapshot
        )

    def rename_profile(self, old_name, new_name):
        """Rename a profile without changing its calibration or device metadata."""
        old_name = self._normalize_profile_name(old_name)
        new_name = self._normalize_profile_name(new_name)
        if old_name not in self.profiles:
            raise ValueError(f"Profile '{old_name}' not found")
        if old_name == new_name:
            return
        if new_name in self.profiles:
            raise ValueError(f"Profile '{new_name}' already exists")

        old_profiles = deepcopy(self.profiles)
        old_last_profile = self.last_profile
        snapshot = self._snapshot_current_calibration()
        if not self.save():
            raise OSError("Failed to save the active calibration profile")

        self.profiles[new_name] = self.profiles.pop(old_name)
        if self.last_profile == old_name:
            self.last_profile = new_name
        self._save_profile_mutation_or_raise(
            old_profiles, old_last_profile, snapshot
        )

    def save_profile(
        self,
        name,
        device_name,
        host_api=None,
        output_device_name="",
        output_host_api=None,
    ):
        """Saves current settings as a named profile."""
        if not hasattr(self, "profiles"):
            self.profiles = {}

        name = self._normalize_profile_name(name)
        profile = self._profile_device_metadata(
            device_name,
            host_api,
            output_device_name,
            output_host_api,
        )
        profile.update(self._snapshot_current_calibration())
        self.profiles[name] = profile
        self.save()

    def load_profile(self, name):
        """Loads settings from a named profile."""
        name = self._normalize_profile_name(name)
        if not hasattr(self, "profiles") or name not in self.profiles:
            raise ValueError(f"Profile '{name}' not found")

        old_snapshot = self._snapshot_current_calibration()
        old_last_profile = self.last_profile
        if not self.save():
            raise OSError("Failed to save the active calibration profile")

        p = self.profiles[name]
        self._apply_calibration_snapshot(p)
        self.last_profile = name  # Update current profile name before saving
        if not self.save():
            self.last_profile = old_last_profile
            self._apply_calibration_snapshot(old_snapshot)
            raise OSError("Failed to activate calibration profile")

    def activate_profile(self, name):
        """Activate a named profile, or detach while preserving current values."""
        if name is None:
            old_last_profile = self.last_profile
            if old_last_profile is None:
                return
            if not self.save():
                raise OSError("Failed to save the active calibration profile")
            self.last_profile = None
            if not self.save():
                self.last_profile = old_last_profile
                raise OSError("Failed to clear the active calibration profile")
            return
        self.load_profile(name)

    def delete_profile(self, name):
        """Deletes a named profile."""
        name = self._normalize_profile_name(name)
        if name not in self.profiles:
            return

        old_profiles = deepcopy(self.profiles)
        old_last_profile = self.last_profile
        snapshot = self._snapshot_current_calibration()
        if not self.save():
            raise OSError("Failed to save the active calibration profile")

        del self.profiles[name]
        if self.last_profile == name:
            self.last_profile = None
        self._save_profile_mutation_or_raise(
            old_profiles, old_last_profile, snapshot
        )

    def get_profiles(self):
        """Returns the dictionary of profiles."""
        if not hasattr(self, "profiles"):
            self.profiles = {}
        return self.profiles

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
                self.logger.debug("Loaded calibration map with %d points.", len(self.frequency_map))
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
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

            # Ensure permissions on existing files (best effort)
            try:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, 0o600)
                else:
                    os.chmod(path, 0o600)
            except Exception as e:
                self.logger.warning("Failed to set secure permissions for calibration map: %s", e)

            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=4)
            self.frequency_map = sorted(data, key=lambda x: x[0])
            self._update_map_cache()
            self.logger.debug("Saved calibration map to %s", path)
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

        # Retrieve the cached tuple atomically
        cache = getattr(self, "_map_cache", None)
        if cache is None or len(cache[0]) == 0:
            return 0.0, 0.0

        freq_cache, mag_cache, phase_unwrapped = cache

        # If out of range, clamp to nearest
        is_scalar = np.isscalar(freq)
        freq_arr = np.atleast_1d(freq)

        # Use cached numpy arrays for interpolation
        mag_corr = np.interp(freq_arr, freq_cache, mag_cache)
        phase_corr = np.interp(freq_arr, freq_cache, phase_unwrapped)
        phase_corr = (phase_corr + 180) % 360 - 180

        if is_scalar:
            return float(mag_corr[0]), float(phase_corr[0])
        return mag_corr, phase_corr

    def _update_map_cache(self):
        if not self.frequency_map:
            self._freq_cache = None
            self._mag_cache = None
            self._phase_cache = None
            self._map_cache = (np.array([]), np.array([]), np.array([]))
            return

        try:
            data = np.array(self.frequency_map)
            freq_tmp = data[:, 0]
            mag_tmp = data[:, 1]
            phase_tmp = data[:, 2]

            # Unwrap phase before caching to avoid repeating this operation on every interpolation call
            phase_unwrapped_tmp = np.degrees(np.unwrap(np.radians(phase_tmp)))

            # Update legacy attributes (backward compatible, but may be accessed asynchronously)
            self._freq_cache = freq_tmp
            self._mag_cache = mag_tmp
            self._phase_cache = phase_tmp

            # Atomic update for thread-safe access (store the unwrapped phase in cache for speed)
            self._map_cache = (freq_tmp, mag_tmp, phase_unwrapped_tmp)
        except Exception as e:
            self.logger.error("Failed to update map cache: %s", e)
            self._freq_cache = None
            self._mag_cache = None
            self._phase_cache = None
            self._map_cache = (np.array([]), np.array([]), np.array([]))

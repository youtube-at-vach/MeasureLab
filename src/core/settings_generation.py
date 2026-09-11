"""Change epochs for acquisition snapshots (no polling or audio scans)."""


class SettingsGeneration:
    _measurement_fields: frozenset[str] = frozenset()
    settings_generation = 0

    def __setattr__(self, name, value):
        if name in self._measurement_fields and name in self.__dict__ and self.__dict__[name] != value:
            object.__setattr__(self, "settings_generation", self.settings_generation + 1)
        object.__setattr__(self, name, value)

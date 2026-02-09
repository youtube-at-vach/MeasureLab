import argparse
from abc import ABC, abstractmethod


class MeasurementModule(ABC):
    """
    Base class for all measurement modules.

    Provides interfaces for GUI (get_widget).
    Note: CLI functionality has been removed.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Module name used for identification."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief description of the module's purpose."""
        pass

    def get_widget(self):
        """
        Returns a QWidget instance for the GUI.
        Override this method to provide a custom GUI for the module.
        """
        return None

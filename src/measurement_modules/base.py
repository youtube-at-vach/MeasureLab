import argparse
from abc import ABC, abstractmethod


class MeasurementModule(ABC):
    """
    Base class for all measurement modules.

    Provides interfaces for both GUI (get_widget) and CLI (run).
    Note: CLI functionality (run method) is currently suspended/frozen.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Module name used for identification and CLI command."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief description of the module's purpose."""
        pass

    def run(self, args: argparse.Namespace):
        """
        Execute the measurement from CLI.
        Currently frozen/not implemented for most modules.
        """
        pass

    def get_widget(self):
        """
        Returns a QWidget instance for the GUI.
        Override this method to provide a custom GUI for the module.
        """
        return None

from typing import List
from src.core.comparison_manager import ComparisonTrace


class ComparableWidgetInterface:
    """
    Interface/Mixin for widgets that can export their plot data for comparison.
    """

    def get_comparable_data(self) -> List[ComparisonTrace]:
        """
        Returns a list of ComparisonTrace objects representing the current plot data.
        Subclasses must implement this.
        """
        raise NotImplementedError("Subclasses must implement get_comparable_data")

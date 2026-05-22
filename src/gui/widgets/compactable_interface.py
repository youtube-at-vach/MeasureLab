class CompactableWidgetInterface:
    """
    Interface/Mixin for widgets supporting a Compact Mode (display-only/plot-only).
    """
    def __init__(self):
        self._is_compact = False

    def set_compact_mode(self, enabled: bool):
        """Sets the compact mode and updates the layout."""
        self._is_compact = enabled
        self.update_compact_layout()

    def is_compact_mode(self) -> bool:
        """Returns True if currently in compact mode."""
        return self._is_compact

    def update_compact_layout(self):
        """
        Subclasses must implement this to hide/show control panels and other non-essential widgets.
        """
        raise NotImplementedError("Subclasses must implement update_compact_layout")

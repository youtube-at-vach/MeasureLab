import math

import pyqtgraph as pg


def logarithmic_ticks_125(minimum: float, maximum: float, suffix: str = "") -> list[tuple[float, str]]:
    """Return labelled log-domain tick positions for a positive linear range."""
    lower, upper = sorted((float(minimum), float(maximum)))
    if not math.isfinite(lower) or not math.isfinite(upper) or lower <= 0:
        return []

    return [
        (math.log10(value), f"{value:g}{suffix}")
        for decade in range(math.floor(math.log10(lower)), math.ceil(math.log10(upper)) + 1)
        for mantissa in InstrumentAxisItem._MAJOR_MANTISSAS
        if lower <= (value := mantissa * 10.0**decade) <= upper
    ]


class InstrumentAxisItem(pg.AxisItem):
    """Axis whose logarithmic major ticks follow the instrument 1-2-5 series."""

    _MAJOR_MANTISSAS = (1.0, 2.0, 5.0)
    _MINOR_MANTISSAS = (3.0, 4.0, 6.0, 7.0, 8.0, 9.0)

    def logTickValues(self, minVal, maxVal, size, stdTicks):
        del size, stdTicks
        lower, upper = sorted((float(minVal), float(maxVal)))
        if not math.isfinite(lower) or not math.isfinite(upper):
            return []

        first_decade = math.floor(lower)
        last_decade = math.ceil(upper)
        major = self._log_ticks(lower, upper, first_decade, last_decade, self._MAJOR_MANTISSAS)
        minor = self._log_ticks(lower, upper, first_decade, last_decade, self._MINOR_MANTISSAS)
        return [(None, major), (None, minor)]

    @staticmethod
    def _log_ticks(lower, upper, first_decade, last_decade, mantissas):
        return [
            position
            for decade in range(first_decade, last_decade + 1)
            for mantissa in mantissas
            if lower <= (position := decade + math.log10(mantissa)) <= upper
        ]


class InstrumentPlotWidget(pg.PlotWidget):
    """Plot widget with guideline-compliant linear and logarithmic axes."""

    def __init__(self, parent=None, background="default", plotItem=None, **kwargs):
        plot_item = plotItem
        if plot_item is None:
            plot_item = pg.PlotItem(
                axisItems={
                    orientation: InstrumentAxisItem(orientation) for orientation in ("left", "bottom", "right", "top")
                },
                **kwargs,
            )
            plot_item.hideAxis("right")
            plot_item.hideAxis("top")
        super().__init__(parent=parent, background=background, plotItem=plot_item)

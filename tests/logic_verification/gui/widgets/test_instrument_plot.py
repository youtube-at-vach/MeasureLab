import math

from src.gui.widgets.instrument_plot import InstrumentAxisItem, InstrumentPlotWidget, logarithmic_ticks_125


def test_log_axis_major_ticks_follow_125_series(qtbot):
    del qtbot
    axis = InstrumentAxisItem("bottom")

    levels = axis.logTickValues(math.log10(20), math.log10(20_000), 600, [])

    major_values = [round(10**position) for position in levels[0][1]]
    assert major_values == [20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000]


def test_instrument_plot_installs_preferred_axes(qtbot):
    plot = InstrumentPlotWidget()
    qtbot.addWidget(plot)

    for orientation in ("left", "bottom", "right", "top"):
        assert isinstance(plot.getPlotItem().getAxis(orientation), InstrumentAxisItem)


def test_labelled_log_ticks_follow_125_series():
    ticks = logarithmic_ticks_125(0.01, 10, suffix="%")

    assert [label for _, label in ticks] == ["0.01%", "0.02%", "0.05%", "0.1%", "0.2%", "0.5%", "1%", "2%", "5%", "10%"]

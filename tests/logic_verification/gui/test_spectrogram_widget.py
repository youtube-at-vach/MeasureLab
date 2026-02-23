from pyqtgraph.graphicsItems.GradientEditorItem import Gradients

def test_spectrogram_colormaps_exist():
    """
    Verify that all colormaps used in the Spectrogram widget exist in pyqtgraph.
    This ensures that future updates to pyqtgraph do not break the widget if presets are removed or renamed.
    """
    # List of colormaps used in SpectrogramWidget.init_ui
    # Note: 'greyscale' was removed in a previous step, so we don't test for it unless it's added back.
    # Current list in code: ["viridis", "plasma", "inferno", "magma", "turbo", "thermal", "flame", "yellowy", "bipolar", "spectrum", "cyclic"]
    used_colormaps = [
        "viridis", "plasma", "inferno", "magma", "turbo",
        "thermal", "flame", "yellowy", "bipolar", "spectrum", "cyclic"
    ]

    missing_colormaps = []
    for cmap in used_colormaps:
        if cmap not in Gradients:
            missing_colormaps.append(cmap)

    assert not missing_colormaps, f"The following colormaps are missing in pyqtgraph: {missing_colormaps}"

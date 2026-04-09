import pytest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor

from src.core.audio_engine import AudioEngine
from src.gui.widgets.spatial_binaural_mixer import SpatialBinauralMixer, SpatialBinauralMixerWidget

def test_spatial_binaural_mixer_instantiation(qtbot):
    """Smoke test to ensure the widget can be instantiated without crashing."""
    module = SpatialBinauralMixer(None)
    
    widget = module.get_widget()
    qtbot.addWidget(widget)
    
    assert widget is not None
    assert widget.layout() is not None

def test_add_remove_track(qtbot):
    module = SpatialBinauralMixer(None)
    
    widget = module.get_widget()
    qtbot.addWidget(widget)

    # Initially 0 tracks
    assert widget.tracks_inner_layout.count() == 0
    
    # Add track
    widget.add_track()
    # Now there should be one track UI + stretch
    assert len(widget.tracks) == 1
    
    # Remove track
    track_ui = widget.tracks[0]
    track_ui.remove_btn.click() # Simulate remove click
    
    assert len(widget.tracks) == 0

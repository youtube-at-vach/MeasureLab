"""Regressions found by the first GUI smoke run."""

from __future__ import annotations

import numpy as np

from tests.gui_fuzz.discovery import create_module_widget
from tests.gui_fuzz.invariants import check_closed


def test_signal_generator_close_stops_active_output_and_pollers(qapp, fuzz_engine):
    module, widget = create_module_widget("Signal Generator", fuzz_engine)
    widget.show()
    qapp.processEvents()
    widget.toggle_btn.click()
    qapp.processEvents()
    assert module.callback_id in fuzz_engine.callbacks
    widget.close()
    qapp.processEvents()
    check_closed(widget, module, fuzz_engine)


def test_hrtf_close_releases_registered_callback(qapp, fuzz_engine):
    module, widget = create_module_widget("HRTF Player", fuzz_engine)
    widget.show()
    qapp.processEvents()
    module.callback_id = fuzz_engine.register_callback(module._callback)
    widget.close()
    qapp.processEvents()
    check_closed(widget, module, fuzz_engine)


def test_hrtf_stop_rotation_releases_idle_callback(qapp, fuzz_engine):
    module, widget = create_module_widget("HRTF Player", fuzz_engine)
    widget.show()
    module.music_buffer = np.zeros((64, 2), dtype=np.float32)
    assert module.start_rotation("Horizontal", 10)
    assert module.callback_id in fuzz_engine.callbacks
    module.stop_rotation()
    assert module.callback_id is None
    assert not fuzz_engine.callbacks
    widget.close()

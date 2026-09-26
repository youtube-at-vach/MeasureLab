"""Regression for zero-energy side/mid channels found by GUI exploration."""

from __future__ import annotations

import math
import warnings

from tests.gui_fuzz.discovery import create_module_widget


def test_pure_mid_and_single_channel_keep_alignment_metrics_finite(qapp, fuzz_engine):
    module, widget = create_module_widget("Stereo Alignment Monitor", fuzz_engine)
    widget.show()
    widget.btn_toggle.click()
    assert module.is_running

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        for kind in ("sine", "left", "right", "different"):
            for _ in range(4):
                fuzz_engine.feed(kind, 1024)
            qapp.processEvents()
            assert math.isfinite(module.ms_ratio_db)
            assert math.isfinite(module.balance_db)
            assert math.isfinite(module.center_focus)

    widget.btn_toggle.click()
    widget.close()

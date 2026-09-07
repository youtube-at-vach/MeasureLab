"""Capture Routing review fixtures without opening audio devices or loading a VST.

Run with --output-dir to choose where the five PNG review images are written.
These fixtures demonstrate UI states; they are not live plugin/audio tests.
"""

import argparse
from dataclasses import replace
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["MEASURELAB_TESTING"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.core.audio_engine import AudioEngine  # noqa: E402
from src.core.localization import get_manager  # noqa: E402
from src.core.theme_manager import ThemeManager  # noqa: E402
from src.gui.widgets.routing import RoutingWidget  # noqa: E402


def capture(output_dir: Path):
    app = QApplication.instance() or QApplication([])
    theme = ThemeManager(app)
    output_dir.mkdir(parents=True, exist_ok=True)
    profiles = (
        ("en", "virtual", False, "light"),
        ("ja", "virtual", True, "light"),
        ("en", "local", False, "light"),
        ("ja", "virtual", False, "dark"),
        ("en", "dry", False, "light"),
    )
    for language, mode, expanded, appearance in profiles:
        get_manager().load_language(language)
        theme.set_theme(appearance)
        engine = AudioEngine()
        engine.offline_mode = mode != "local"
        engine.list_devices = lambda: [{"name": "USB Audio Interface", "hostapi": 0, "max_output_channels": 2}]
        engine.input_device = engine.output_device = 0
        if mode != "local":
            engine.vst_dut.path = "Example.vst3"
            engine.vst_dut.name = "Example EQ"
            engine.vst_dut.return_routes = ("wet1", "dry1") if mode == "dry" else ("wet1", "wet2")
            engine.monitor.route = replace(engine.monitor.route, device=0, device_name="USB Audio Interface")
        widget = RoutingWidget(engine)
        widget.timer.stop()
        widget.details_toggle.setChecked(expanded)
        widget.resize(1080, 690)
        widget.show()
        app.processEvents()
        app.processEvents()
        filename = f"{language}-{mode}-{'expanded' if expanded else 'flow'}-{appearance}.png"
        target = output_dir / filename
        if not widget.grab().save(str(target)):
            raise RuntimeError(f"Could not save {target}")
        print(target)
        widget.close()
        engine.vst_dut.close()
        widget.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    capture(parser.parse_args().output_dir)

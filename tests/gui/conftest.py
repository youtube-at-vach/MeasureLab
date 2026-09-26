from __future__ import annotations

import pytest

from tests.gui_fuzz.audio import FuzzAudioEngine
from tests.gui_fuzz.diagnostics import RUN_TOTALS


@pytest.fixture
def fuzz_engine(monkeypatch):
    """Block device, network and process entry points for this test layer."""
    import sounddevice as sd
    import subprocess

    def blocked(*args, **kwargs):
        raise AssertionError("External I/O is forbidden in GUI fuzz tests")

    for name in ("Stream", "InputStream", "OutputStream", "play", "rec", "query_devices", "query_hostapis"):
        monkeypatch.setattr(sd, name, blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    # System CPU discovery in this page launches sysctl/lscpu on some hosts.
    monkeypatch.setattr("src.gui.widgets.processor_benchmark.get_cpu_name", lambda: "Test CPU")
    engine = FuzzAudioEngine()
    yield engine
    engine.stop_stream(force=True)


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(
        f"GUI fuzz: {RUN_TOTALS['scenarios']} scenarios, {RUN_TOTALS['operations']} operations "
        f"({RUN_TOTALS['audio_blocks']} audio blocks)"
    )

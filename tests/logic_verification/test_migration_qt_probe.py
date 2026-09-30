"""The native smoke runner must not accept clean exits without lifecycle evidence."""

import os
from pathlib import Path
import sys

import pytest

from scripts.migration_qt_probe import run_probe

PASS = "PROBE_READY\nPROBE_PASS cancel failure stop model slow_gui stale recreate subscriptions window_recreate shutdown\nPROBE_TEARDOWN workers=0 models=0"


def executable(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "probe"
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(0o700)
    return path


@pytest.mark.parametrize(
    ("output", "code", "expected"),
    [
        (PASS, 0, True),
        (PASS, 1, False),
        ("PROBE_READY", 0, False),
        (PASS + "\nPROBE_FAIL broken", 0, False),
        (PASS + "\nTypeError: stale view", 0, False),
        ("", 0, False),
    ],
)
def test_requires_exit_and_lifecycle_markers(tmp_path, output, code, expected):
    binary = executable(tmp_path, f"print({output!r})\nraise SystemExit({code})")
    result = run_probe(binary, dict(os.environ), 2)
    assert result["passed"] is expected
    assert result["exit_code"] == code
    assert len(result["binary_sha256"]) == 64


def test_timeout_preserves_partial_output_and_fails(tmp_path):
    binary = executable(tmp_path, "import time\nprint('PROBE_READY', flush=True)\ntime.sleep(10)")
    result = run_probe(binary, dict(os.environ), 0.2)
    assert not result["passed"]
    assert result["reason"] == "timeout"
    assert result["exit_code"] is None
    assert "PROBE_READY" in result["output"]

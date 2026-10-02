"""Verify the reference launcher cannot pick up the checkout's portable settings."""

import json
import os
from pathlib import Path
import subprocess
import sys


def test_reference_storage_is_isolated(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    portable_config = checkout / "config.json"
    portable_config.write_text('{"language": "de", "audio": {"offline_mode": false}}')
    original_portable_config = portable_config.read_bytes()
    state_dir = tmp_path / "reference"
    # Exercise repeated startup with non-default settings that must survive.
    state_dir.mkdir()
    config_path = state_dir / "config.json"
    config_path.write_text(json.dumps({"language": "ja", "audio": {"offline_mode": False}}))
    calibration_path = state_dir / "calibration.json"
    calibration_path.write_text('{"input_sensitivity": 2.5}')
    original_calibration = calibration_path.read_bytes()

    result = subprocess.run(  # noqa: S603 - current interpreter, fixed code, and pytest-owned paths
        [
            sys.executable,
            "-c",
            "import os, sys; from pathlib import Path; "
            "sys.path.insert(0, str(Path.cwd())); "
            "from scripts import migration_reference; "
            "migration_reference.REPO_ROOT = Path(sys.argv.pop(1)); "
            "os.chdir(migration_reference.REPO_ROOT); migration_reference.main()",
            str(checkout),
            "--state-dir",
            str(state_dir),
            "--check",
        ],
        cwd=repo_root,
        env={**os.environ, "MEASURELAB_TESTING": "1", "XDG_DATA_HOME": str(tmp_path / "stable-data")},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    report = json.loads(result.stdout)
    assert report["source_root"] == str(checkout)
    for key in ("config", "calibration", "fft_wisdom", "log", "screenshots"):
        assert Path(report[key]).is_relative_to(state_dir), report
    assert report["offline_mode"] is True
    saved = json.loads(config_path.read_text())
    assert saved["audio"]["offline_mode"] is True
    assert saved["audio"]["pipewire_jack_resident"] is False
    assert saved["language"] == "ja"
    assert calibration_path.read_bytes() == original_calibration
    assert portable_config.read_bytes() == original_portable_config
    assert not (tmp_path / "stable-data").exists()

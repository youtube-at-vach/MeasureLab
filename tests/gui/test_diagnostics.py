"""Regression tests for GUI fuzz failure artifacts."""

from __future__ import annotations

import json

import pytest

from tests.gui_fuzz import diagnostics


def test_scenario_replay_replaces_stale_failure_artifacts(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "ARTIFACT_ROOT", tmp_path)
    directory = tmp_path / "Example_Widget_17"
    directory.mkdir()
    (directory / "failure.json").write_text("old failure", encoding="utf-8")
    (directory / "last.png").write_bytes(b"old screenshot")

    with diagnostics.Scenario("Example Widget", 17):
        assert not (directory / "failure.json").exists()
        assert not (directory / "last.png").exists()

    assert (directory / "trace.json").exists()
    assert not (directory / "failure.json").exists()

    with pytest.raises(ValueError, match="new failure"):
        with diagnostics.Scenario("Example Widget", 17):
            raise ValueError("new failure")

    report = json.loads((directory / "failure.json").read_text(encoding="utf-8"))
    assert "ValueError: new failure" in report["error"]

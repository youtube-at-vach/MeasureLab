"""Reject stale or incomplete Generator restart acceptance evidence."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from qa_gui_redesign import cases, generator_replay_selection, main


class GeneratorReplayAcceptance(unittest.TestCase):
    def run_pair(self, *, save_fails=False, replay_marker=True, rewrite_checkpoint=False):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            root = output / "repo"
            (root / "i18n").mkdir(parents=True)
            (root / "i18n/source-hashes.json").write_text("{}", encoding="utf-8")
            directory = output / "generator-internal"
            directory.mkdir()
            # Old successful-looking files must not rescue a failed producer.
            for name in ("settings.json", "results.json"):
                (directory / name).write_text("stale checkpoint", encoding="utf-8")
            calls = []

            def git_output(command, **kwargs):
                return b"" if command[1:] == ["diff", "--binary"] else "fixture\n"

            def run(command, **kwargs):
                env = kwargs["env"]
                replay = "MEASURELAB_UI_SMOKE_GENERATOR_REPLAY" in env
                calls.append(replay)
                self.assertEqual(env["MEASURELAB_UI_SMOKE_GENERATOR_ARTIFACTS"], str(directory))
                if not replay or rewrite_checkpoint:
                    for name in ("settings.json", "results.json"):
                        (directory / name).write_text("replayed" if replay else "fresh checkpoint", encoding="utf-8")
                log = "UI assertions only OK:\nGUI navigation OK:\nGenerator UI OK:\nComparison independent input oracle OK:\n"
                if replay and replay_marker:
                    log += "Generator replay OFF OK:\nGenerator replay UI OK:\n"
                return SimpleNamespace(stdout=log, stderr="", returncode=int(save_fails and not replay))

            argv = [
                "qa_gui_redesign.py",
                "--case",
                "generator-internal-replay",
                "--assertions-only",
                "--binary",
                __file__,
                "--output",
                temporary,
            ]
            with (
                patch("sys.argv", argv),
                patch("qa_gui_redesign.ROOT", root),
                patch("qa_gui_redesign.subprocess.check_output", side_effect=git_output),
                patch("qa_gui_redesign.subprocess.run", side_effect=run),
                patch("qa_gui_redesign.platform.platform", return_value="test-platform"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                try:
                    main()
                    failed = False
                except SystemExit:
                    failed = True
            return failed, calls, json.loads((output / "manifest.json").read_text(encoding="utf-8"))

    def test_replay_selection_includes_its_route_specific_producer(self):
        available = list(cases(("BlackHole 2ch", "BlackHole 16ch", "ZOOM UAC-232")))
        selected = generator_replay_selection({"generator-blackhole-16ch-replay"}, available)
        self.assertEqual(selected, {"generator-blackhole-16ch", "generator-blackhole-16ch-replay"})
        selected = generator_replay_selection({"generator-replay"}, available)
        self.assertEqual(len(selected), 8)

    def test_fresh_save_and_replay_use_the_same_unchanged_checkpoint(self):
        failed, calls, manifest = self.run_pair()
        self.assertFalse(failed)
        self.assertEqual(calls, [False, True])
        first, second = manifest["cases"]
        self.assertTrue(first["passed"] and second["passed"])
        self.assertEqual(first["checkpoint_sha256"], second["checkpoint_sha256"])

    def test_failed_save_never_launches_replay_even_with_old_files(self):
        failed, calls, manifest = self.run_pair(save_fails=True)
        self.assertTrue(failed)
        self.assertEqual(calls, [False])
        self.assertTrue(all(not case["passed"] for case in manifest["cases"]))

    def test_generic_generator_success_does_not_accept_replay(self):
        failed, _, manifest = self.run_pair(replay_marker=False)
        self.assertTrue(failed)
        self.assertFalse(manifest["cases"][-1]["passed"])

    def test_replay_cannot_overwrite_the_saved_reference(self):
        failed, _, manifest = self.run_pair(rewrite_checkpoint=True)
        self.assertTrue(failed)
        self.assertFalse(manifest["cases"][-1]["passed"])


if __name__ == "__main__":
    unittest.main()

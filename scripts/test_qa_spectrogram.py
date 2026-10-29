"""Regression gates for GUI suspension hidden by an otherwise good p95."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from qa_spectrogram import STFT_SIZES, assess, audit_manifest, comparisons, peak_rss, profile_cases, routes

LOG = """UI profile: 6000 frames over 122.0 s, frame interval p95 27.0 ms, max 1020.0 ms, input dropped 0
Spectrogram stress QA OK: 1200 display steps
Spectrogram numerical QA OK: 48000 Hz, CH 1, N 8192, hop 2048,
UI stall OK:
Spectrogram response: 1300 applied, request-to-UI p95 70.0 ms, max 130.0 ms
Spectrogram GPU payload: 200 bytes current / 300 bytes resize peak, 900 uploaded bytes
STFT profile: 48000 Hz, 2 ch, CH 1, 8192-point F64, rows 1000, input dropped 0, result dropped 0, worker CPU 200.0 ms total
Cepstrum extra log/inverse CPU: 0.0 ms total
Spectrogram preparation: 1300 rasters, worker 300.0 ms total / 0.231 ms mean / 1.0 ms max
STFT history profile: 88.0 MiB retained / 90.0 MiB peak frames, 0 retired, 0 storage dropped, collector CPU 10.0 ms total
UI QA profile complete: finite result audited and input stopped
QA skipped surface acquisitions after warm-up: 0
"""


class ProfileAcceptance(unittest.TestCase):
    def accepted(self, log):
        return assess(log, "stress", 120, 0, {"ui_p95_ms": 27.0})[0]

    def test_cepstrogram_requires_its_own_numerical_oracle(self):
        cepstral = LOG.replace("Spectrogram numerical QA OK:", "Cepstrogram numerical QA OK:")
        args = ("stress", 120, 0, {"ui_p95_ms": 27.0})
        self.assertFalse(assess(LOG, *args, analysis="cepstrogram")[0])
        self.assertTrue(assess(cepstral, *args, analysis="cepstrogram")[0])
        self.assertFalse(assess(cepstral, *args)[0])
        with self.assertRaises(ValueError):
            assess(LOG, *args, analysis="unknown")

    def test_intentional_one_second_stall_is_allowed(self):
        self.assertTrue(self.accepted(LOG))

    def test_long_gui_suspension_fails_even_with_good_p95(self):
        self.assertFalse(self.accepted(LOG.replace("max 1020.0", "max 180000.0")))

    def test_incomplete_display_and_operation_coverage_fails(self):
        self.assertFalse(self.accepted(LOG.replace("6000 frames", "38 frames")))
        self.assertFalse(self.accepted(LOG.replace("1200 display steps", "34 display steps")))

    def test_late_finite_stop_is_not_a_120_second_interactive_run(self):
        self.assertFalse(self.accepted(LOG.replace("over 122.0", "over 192.0")))

    def test_failed_baseline_cannot_accept_the_stress_comparison(self):
        self.assertFalse(assess(LOG, "stress", 120, 0, None)[0])

    def test_loss_counters_and_inactive_inverse_are_checked_even_with_success_markers(self):
        for old, new in (
            ("input dropped 0", "input dropped 1"),
            ("result dropped 0", "result dropped 1"),
            ("0 storage dropped", "1 storage dropped"),
            ("inverse CPU: 0.0", "inverse CPU: 0.1"),
            ("rows 1000", "rows 0"),
        ):
            with self.subTest(counter=old):
                self.assertFalse(self.accepted(LOG.replace(old, new)))

    def test_applied_conditions_must_match_the_requested_matrix_cell(self):
        args = (LOG, "stress", 120, 0, {"ui_p95_ms": 27})
        self.assertTrue(assess(*args, environment={})[0])
        for key, value in (("SAMPLE_RATE", "192000"), ("STFT_SIZE", "1024"), ("CHANNEL", "16"), ("STFT_OVERLAP", "50")):
            with self.subTest(key=key):
                self.assertFalse(assess(*args, environment={key: value})[0])

    def test_repeated_capture_requires_completed_writes_and_still_rejects_gui_stalls(self):
        captures = LOG + "UI screenshot: dist/ui-smoke.png (worker 80.0 ms)\n" * 100
        args = ("stress", 120, 0, {"ui_p95_ms": 27.0}, True)
        self.assertFalse(assess(LOG, *args)[0])
        self.assertTrue(assess(captures, *args)[0])
        self.assertFalse(assess(captures.replace("max 1020.0", "max 5000.0"), *args)[0])
        self.assertFalse(assess(captures + "UI screenshot failed: disk unavailable\n", *args)[0])


class ComparisonMatrix(unittest.TestCase):
    def test_all_sizes_overlaps_and_modes_have_isolated_live_baselines(self):
        selected = [route for route in routes(()) if route[0].startswith("demo-")]
        cases = list(profile_cases(selected, "both", STFT_SIZES, 48000))
        self.assertEqual(len(cases), 72)
        self.assertEqual(len({case["name"] for case in cases}), 72)
        for live, stress in zip(cases[::2], cases[1::2], strict=True):
            self.assertEqual((live["mode"], stress["mode"]), ("live", "stress"))
            self.assertEqual(live["baseline_key"], stress["baseline_key"])
            self.assertEqual(live["analysis"], stress["analysis"])
            self.assertEqual(live["environment"] | {"SPECTROGRAM": "stress"}, stress["environment"])
            self.assertEqual(live["environment"]["SAMPLE_RATE"], "48000")
            self.assertEqual("CEPSTROGRAM" in live["environment"], live["analysis"] == "cepstrogram")
        self.assertEqual(len({case["baseline_key"] for case in cases}), 36)
        self.assertEqual(len({case["comparison_key"] for case in cases}), 36)

    def test_default_routes_keep_their_previous_rate_size_and_case_names(self):
        cases = list(profile_cases(routes(()), "spectrogram"))
        self.assertEqual(cases[0]["name"], "demo-50-live")
        self.assertNotIn("STFT_SIZE", cases[0]["environment"])
        software = next(case for case in cases if case["name"] == "software-live")
        self.assertEqual(software["environment"]["SAMPLE_RATE"], "192000")
        self.assertEqual(software["environment"]["FFT_SIZE"], "32768")
        override = list(profile_cases([("software", software["environment"], [])], "both", [1024], 48000))
        self.assertEqual(override[0]["environment"]["FFT_SIZE"], "8192")
        self.assertEqual(override[0]["environment"]["STFT_SIZE"], "1024")

    def test_comparison_uses_per_row_cost_and_never_hides_a_failure(self):
        cases = []
        for kind, count, total in (("spectrogram", 1000, 200), ("cepstrogram", 500, 150)):
            values = assess(LOG, "stress", 120, 0, {"ui_p95_ms": 27})[1]
            values |= {"stft_rows": count, "stft_cpu_ms": total}
            cases.append(
                {
                    "name": kind,
                    "analysis": kind,
                    "comparison_key": "same-condition",
                    "metrics": values,
                    "passed": kind == "spectrogram",
                }
            )
        report = comparisons(cases)[0]
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["cepstrogram_minus_spectrogram"]["stft_cpu_ms_per_row"], 0.1)
        cases[1]["metrics"]["stft_rows"] = 0
        self.assertEqual(comparisons(cases)[0]["cepstrogram_minus_spectrogram"], {})
        cases[1]["metrics"] = {}
        self.assertFalse(comparisons(cases)[0]["passed"])
        self.assertEqual(comparisons(cases[:1]), [])

    def test_rss_missing_empty_malformed_and_nonfinite_samples_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rss.csv"
            with self.assertRaises(ValueError):
                peak_rss(path)
            for contents in (
                "elapsed,rss\n",
                "elapsed,rss\n0\n",
                "elapsed,rss\n0,nan\n",
                "elapsed,rss\n0,-1\n",
                "elapsed,rss\n0,0\n",
            ):
                path.write_text(contents)
                with self.subTest(contents=contents), self.assertRaises(ValueError):
                    peak_rss(path)
            path.write_text("elapsed,rss\n0,1024\n1,2048\n2,0\n")
            self.assertEqual(peak_rss(path), 2)

    def test_audit_respects_per_case_analysis_and_rejects_an_incomplete_matrix(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            cases = list(profile_cases([("demo-75", {}, [])], "both"))
            for case in cases:
                case["passed"], case["returncode"], case["log"] = True, 0, case["name"] + ".log"
                log = LOG.replace("Spectrogram stress QA OK:", f"Spectrogram {case['mode']} QA OK:")
                if case["analysis"] == "cepstrogram":
                    log = log.replace("Spectrogram numerical QA OK:", "Cepstrogram numerical QA OK:")
                (root / case["log"]).write_text(log)
                (root / f"{case['name']}-rss.csv").write_text("elapsed,rss\n0,1024\n")
            manifest = {
                "analysis": "both",
                "duration_seconds": 120,
                "acceptance_duration": True,
                "planned_cases": 4,
                "cases": cases,
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            self.assertTrue(audit_manifest(path))
            audited = json.loads(path.with_stem("manifest-audited").read_text())
            self.assertTrue(all(pair["passed"] for pair in audited["comparisons"]))
            self.assertEqual(len(audited["comparisons"]), 2)
            manifest["cases"] = cases[:2]
            path.write_text(json.dumps(manifest))
            self.assertFalse(audit_manifest(path))
            manifest["cases"] = []
            path.write_text(json.dumps(manifest))
            self.assertFalse(audit_manifest(path))


if __name__ == "__main__":
    unittest.main()

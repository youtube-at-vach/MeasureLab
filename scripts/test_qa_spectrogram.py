"""Regression gates for GUI suspension hidden by an otherwise good p95."""

import unittest

from qa_spectrogram import assess

LOG = """UI profile: 6000 frames over 122.0 s, frame interval p95 27.0 ms, max 1020.0 ms, input dropped 0
Spectrogram stress QA OK: 1200 display steps
Spectrogram numerical QA OK:
UI stall OK:
Spectrogram response: 1300 applied, request-to-UI p95 70.0 ms
Spectrogram GPU payload: 200 bytes current / 300 bytes resize peak, 900 uploaded bytes
STFT history profile: 88.0 MiB retained / 90.0 MiB peak frames
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

    def test_repeated_capture_requires_completed_writes_and_still_rejects_gui_stalls(self):
        captures = LOG + "UI screenshot: dist/ui-smoke.png (worker 80.0 ms)\n" * 100
        args = ("stress", 120, 0, {"ui_p95_ms": 27.0}, True)
        self.assertFalse(assess(LOG, *args)[0])
        self.assertTrue(assess(captures, *args)[0])
        self.assertFalse(assess(captures.replace("max 1020.0", "max 5000.0"), *args)[0])
        self.assertFalse(assess(captures + "UI screenshot failed: disk unavailable\n", *args)[0])


if __name__ == "__main__":
    unittest.main()

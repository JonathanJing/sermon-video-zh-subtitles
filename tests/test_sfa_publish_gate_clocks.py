"""The publish gate's content-clock rule.

`durationSeconds` is the source-video clock; `audioDurationSeconds` is the dub track. Synchronized
pages keep them within a second of each other, while the natural-rate podcast dubs used since
2026-11-01 deliberately carry an independent dub clock (the iOS reader's "Independent clocks").
The rule accepts the second case only inside a plausible band for one episode, so a mixed-up or
truncated audio file still fails the gate.
"""

from tests import experiment_modules

import unittest

gate = experiment_modules.load("tools/ops/sfa_publish_gate.py")

ZH_DURATION, ZH_AUDIO = 3476.16, 3469.72   # 2026-11-01 podcast, natural rate
ES_AUDIO = 3564.58
SYNC_DURATION, SYNC_AUDIO = 2019.370667, 2019.40  # week-8 sermon, synchronized


class SynchronizedClockTest(unittest.TestCase):
    def test_equal_clocks_pass(self):
        kind, ok, detail = gate.content_clock_verdict(SYNC_DURATION, SYNC_DURATION)
        self.assertEqual(kind, "synchronized")
        self.assertTrue(ok)
        self.assertIn("synchronized", detail)

    def test_audio_slightly_longer_passes(self):
        kind, ok, _ = gate.content_clock_verdict(SYNC_DURATION, SYNC_DURATION + 0.8)
        self.assertEqual(kind, "synchronized")
        self.assertTrue(ok)

    def test_audio_slightly_shorter_passes(self):
        kind, ok, _ = gate.content_clock_verdict(SYNC_DURATION, SYNC_DURATION - 0.05)
        self.assertEqual(kind, "synchronized")
        self.assertTrue(ok)

    def test_upper_edge_moves_to_independent_clock(self):
        kind, ok, _ = gate.content_clock_verdict(1000.0, 1001.1)
        self.assertEqual(kind, "independent")
        self.assertTrue(ok)


class IndependentClockTest(unittest.TestCase):
    def test_natural_rate_short_dub_passes(self):
        kind, ok, detail = gate.content_clock_verdict(ZH_DURATION, ZH_AUDIO)
        self.assertEqual(kind, "independent")
        self.assertTrue(ok)
        self.assertIn("independent clocks", detail)

    def test_natural_rate_long_dub_passes(self):
        kind, ok, _ = gate.content_clock_verdict(ZH_DURATION, ES_AUDIO)
        self.assertEqual(kind, "independent")
        self.assertTrue(ok)

    def test_lower_band_edge_passes(self):
        kind, ok, _ = gate.content_clock_verdict(1000.0, 750.0)
        self.assertEqual(kind, "independent")
        self.assertTrue(ok)

    def test_upper_band_edge_passes(self):
        kind, ok, _ = gate.content_clock_verdict(1000.0, 1350.0)
        self.assertEqual(kind, "independent")
        self.assertTrue(ok)

    def test_truncated_audio_fails(self):
        kind, ok, _ = gate.content_clock_verdict(1000.0, 749.9)
        self.assertEqual(kind, "independent")
        self.assertFalse(ok)

    def test_audio_of_another_episode_fails(self):
        kind, ok, _ = gate.content_clock_verdict(1000.0, 2400.0)
        self.assertEqual(kind, "independent")
        self.assertFalse(ok)

    def test_far_too_short_audio_fails(self):
        kind, ok, _ = gate.content_clock_verdict(3476.16, 1800.0)
        self.assertFalse(ok)


class InvalidClockTest(unittest.TestCase):
    def test_missing_duration_fails(self):
        kind, ok, _ = gate.content_clock_verdict(None, ZH_AUDIO)
        self.assertEqual(kind, "invalid")
        self.assertFalse(ok)

    def test_missing_audio_fails(self):
        kind, ok, _ = gate.content_clock_verdict(ZH_DURATION, None)
        self.assertEqual(kind, "invalid")
        self.assertFalse(ok)

    def test_zero_and_negative_values_fail(self):
        for duration, audio in ((0, 100), (100, 0), (-1, 100), (100, -1)):
            kind, ok, _ = gate.content_clock_verdict(duration, audio)
            self.assertEqual(kind, "invalid", (duration, audio))
            self.assertFalse(ok)

    def test_booleans_are_not_seconds(self):
        kind, ok, _ = gate.content_clock_verdict(True, True)
        self.assertEqual(kind, "invalid")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()

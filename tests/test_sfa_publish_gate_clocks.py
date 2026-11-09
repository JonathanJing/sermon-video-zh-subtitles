"""Clock rule for the published-page gate: synced strict, independent podcast 0.75-1.35x."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tools" / "ops" / "sfa_publish_gate.py"


def load():
    spec = importlib.util.spec_from_file_location("sfa_publish_gate", PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sfa_publish_gate"] = module
    spec.loader.exec_module(module)
    return module


class ClockTest(unittest.TestCase):
    def setUp(self):
        self.gate = load()

    def test_independent_podcast_allows_a_longer_natural_rate_dub(self):
        page = {"mediaType": "podcast"}
        target = {"capabilities": ["text", "captions", "audio"]}
        ok, detail = self.gate.content_clock(page, target, 3008.238, 3407.26)
        self.assertTrue(ok, detail)
        self.assertIn("ratio=1.133", detail)

    def test_independent_podcast_rejects_a_truncated_or_bloated_track(self):
        page = {"mediaType": "podcast"}
        target = {"capabilities": ["text", "captions", "audio"]}
        self.assertFalse(self.gate.content_clock(page, target, 3008.0, 2000.0)[0])
        self.assertFalse(self.gate.content_clock(page, target, 3008.0, 5000.0)[0])

    def test_podcast_with_alignment_keeps_the_strict_rule(self):
        page = {"mediaType": "podcast"}
        target = {"capabilities": ["text", "captions", "audio", "alignment"]}
        self.assertTrue(self.gate.content_clock(page, target, 3008.0, 3008.5)[0])
        self.assertFalse(self.gate.content_clock(page, target, 3008.0, 3200.0)[0])

    def test_non_podcast_page_keeps_the_strict_rule(self):
        page = {"mediaType": None}
        target = {"capabilities": ["text", "captions", "audio"]}
        self.assertFalse(self.gate.content_clock(page, target, 3008.0, 3100.0)[0])

    # The 2026-11-01 podcast dubs: the source window is 3476.16 s and each locale runs on its
    # own natural-rate clock. These are the real numbers the loosened rule must keep passing.
    def test_natural_rate_podcast_real_dubs_pass(self):
        page = {"mediaType": "podcast"}
        target = {"capabilities": ["text", "captions", "audio"]}
        for audio in (3469.72, 3471.81, 3564.58):
            ok, detail = self.gate.content_clock(page, target, 3476.16, audio)
            self.assertTrue(ok, detail)

    def test_independent_band_edges(self):
        page = {"mediaType": "podcast"}
        target = {"capabilities": ["text", "captions", "audio"]}
        self.assertTrue(self.gate.content_clock(page, target, 1000.0, 750.0)[0])
        self.assertTrue(self.gate.content_clock(page, target, 1000.0, 1350.0)[0])
        self.assertFalse(self.gate.content_clock(page, target, 1000.0, 749.9)[0])
        self.assertFalse(self.gate.content_clock(page, target, 1000.0, 1350.1)[0])

    def test_audio_of_another_episode_fails(self):
        page = {"mediaType": "podcast"}
        target = {"capabilities": ["text", "captions", "audio"]}
        self.assertFalse(self.gate.content_clock(page, target, 1000.0, 2400.0)[0])
        self.assertFalse(self.gate.content_clock(page, target, 3476.16, 1800.0)[0])

    def test_zero_or_negative_audio_fails(self):
        page = {"mediaType": "podcast"}
        target = {"capabilities": ["text", "captions", "audio"]}
        for duration, audio in ((0, 100), (100, 0), (-1, 100), (100, -1)):
            self.assertFalse(self.gate.content_clock(page, target, duration, audio)[0], (duration, audio))



if __name__ == "__main__":
    unittest.main()

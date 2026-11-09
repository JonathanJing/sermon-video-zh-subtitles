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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.content_pack import build_weekly_pack, prompt_context, retrieve
from backend.ollama_client import OllamaClient


class ContentPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = build_weekly_pack([
            {
                "segmentId": "seg_001",
                "startMs": 0,
                "endMs": 4200,
                "sourceTextEn": "God's people are standing at the edge of the promised land.",
                "targetTextZh": "神的百姓正站在应许之地的边缘。",
                "translationStatus": "machine_generated",
                "terms": [{"source": "promised land", "preferredZh": "应许之地", "status": "approved"}],
                "scriptureRefs": ["Numbers 13-14"],
            },
            {
                "segmentId": "seg_002",
                "startMs": 4300,
                "endMs": 8600,
                "sourceTextEn": "Grace leads us through the truth.",
                "targetTextZh": "恩典带领我们经过真理。",
                "translationStatus": "reviewed",
            },
        ], service_date="2026-09-05", source_id="saturday-service", audio_sha256="a" * 64, valid_until="2026-09-07")

    def test_machine_translation_is_not_injectable(self) -> None:
        hits = retrieve(
            self.pack,
            "God's people are standing at the edge of the promised land.",
            now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )
        self.assertEqual(hits[0]["segmentId"], "seg_001")
        self.assertIsNone(hits[0]["targetTextZh"])
        self.assertTrue(hits[0]["hasCandidateMachineTranslation"])
        self.assertEqual(prompt_context(hits)["approvedTerms"][0]["preferredZh"], "应许之地")
        self.assertEqual(prompt_context(hits)["verifiedScriptureRefs"], [])

    def test_reviewed_exact_translation_can_be_injected(self) -> None:
        hits = retrieve(
            self.pack,
            "Grace leads us through the truth.",
            now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )
        context = prompt_context(hits)
        self.assertTrue(hits[0]["exactMatch"])
        self.assertEqual(context["reviewedExactExamples"][0]["targetTextZh"], "恩典带领我们经过真理。")

    def test_partial_phrase_does_not_inject_whole_reviewed_translation(self) -> None:
        hits = retrieve(
            self.pack,
            "Grace leads us",
            now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )
        self.assertFalse(hits[0]["exactMatch"])
        self.assertTrue(hits[0]["phraseMatch"])
        self.assertFalse(hits[0]["canInjectTranslation"])
        self.assertIsNone(hits[0]["targetTextZh"])
        self.assertTrue(hits[0]["hasReviewedTranslation"])
        self.assertEqual(prompt_context(hits)["reviewedExactExamples"], [])

    def test_expired_weekly_pack_returns_no_hits(self) -> None:
        hits = retrieve(
            self.pack,
            "promised land",
            now=datetime(2026, 9, 8, tzinfo=timezone.utc),
        )
        self.assertEqual(hits, [])

    def test_prompt_keeps_current_source_authoritative(self) -> None:
        prompt = OllamaClient.build_prompt("Grace leads us through the truth.", {
            "approvedTerms": [{"source": "grace", "preferredZh": "恩典"}],
            "verifiedScriptureRefs": [],
            "reviewedExactExamples": [],
        })
        self.assertIn("CURRENT SOURCE below is the only source of truth", prompt)
        self.assertIn("grace => 恩典", prompt)


if __name__ == "__main__":
    unittest.main()

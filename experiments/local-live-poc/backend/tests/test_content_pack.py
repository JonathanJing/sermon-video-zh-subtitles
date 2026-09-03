from __future__ import annotations

import unittest
from datetime import datetime, timezone

from backend.content_pack import alignment_summary, build_weekly_pack, prompt_context, retrieve
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
                "sectionId": "opening",
                "sectionTitle": "At the border",
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
                "sectionId": "response",
                "sectionTitle": "Grace and truth",
            },
        ], service_date="2026-09-05", source_id="saturday-service", audio_sha256="a" * 64, valid_until="2026-09-07")

    def test_pack_is_an_ordered_sermon_map(self) -> None:
        self.assertEqual([entry["sequence"] for entry in self.pack["entries"]], [1, 2])
        self.assertEqual(self.pack["sermonMap"]["segmentCount"], 2)
        self.assertEqual(self.pack["sermonMap"]["sections"][1]["sectionTitle"], "Grace and truth")

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

    def test_reviewed_partial_match_is_reference_only_in_alignment_policy(self) -> None:
        hits = retrieve(
            self.pack,
            "Grace leads us",
            cursor_sequence=1,
            now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )
        context = prompt_context(hits, policy="saturday_alignment_v1")
        self.assertIsNone(hits[0]["targetTextZh"])
        self.assertEqual(context["reviewedExactExamples"], [])
        self.assertEqual(
            context["reviewedAlignedReferences"][0]["targetTextZh"],
            "恩典带领我们经过真理。",
        )
        self.assertEqual(alignment_summary(hits, 1)["suggestedCursor"], 2)
        self.assertEqual(alignment_summary(hits, 1)["strategy"], "local_window")

    def test_exact_match_can_recover_outside_cursor_window(self) -> None:
        segments = [
            {"segmentId": f"seg_{index:03d}", "sourceTextEn": f"Ordinary transition number {index}."}
            for index in range(1, 12)
        ]
        segments.append({
            "segmentId": "seg_012",
            "sourceTextEn": "A unique exact sentence about resurrection hope.",
        })
        pack = build_weekly_pack(
            segments,
            service_date="2026-09-05",
            source_id="saturday-service",
            audio_sha256="c" * 64,
            valid_until="2026-09-07",
        )
        hits = retrieve(
            pack,
            "A unique exact sentence about resurrection hope.",
            cursor_sequence=1,
            window_radius=3,
            now=datetime(2026, 9, 6, tzinfo=timezone.utc),
        )
        self.assertEqual(hits[0]["sequence"], 12)
        self.assertEqual(hits[0]["alignmentStrategy"], "global_fallback")

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
            "reviewedAlignedReferences": [{
                "sourceTextEn": "Grace carried us through the truth.",
                "targetTextZh": "恩典带领我们经过真理。",
            }],
        })
        self.assertIn("CURRENT SOURCE below is the only source of truth", prompt)
        self.assertIn("grace => 恩典", prompt)
        self.assertIn("another delivery of the sermon", prompt)
        self.assertIn("Never copy wording", prompt)


if __name__ == "__main__":
    unittest.main()

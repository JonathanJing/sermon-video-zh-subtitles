import copy
import json
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

from backend.ollama_client import OllamaClient
from backend.translation_units import TranslationUnitAssembler, is_contentless_fragment


def final(text, number=1, start=0, end=3000):
    return {
        "type": "asr.final",
        "segmentId": f"seg-{number:06d}",
        "sourceTextEn": text,
        "audioStartMs": start,
        "audioEndMs": end,
        "sequence": number * 10,
        "at": "2026-09-04T19:00:00Z",
    }


class TranslationUnitTests(unittest.TestCase):
    def test_lexical_admission_guard_only_filters_lone_closed_class_tokens(self):
        for text in ("The.", "A", "an!", "YOUR.", "of", "with.", "And.", "if", "because"):
            with self.subTest(text=text):
                self.assertTrue(is_contentless_fragment(text))
        for text in (
            "Amen.", "Jesus", "No!", "Stop.", "Why?", "one", "never",
            "The church.", "And God.", "Your family.", "I", "her", "his",
            "", "...", "42", "The 42.", "A 二.",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_contentless_fragment(text))

    def test_default_policy_preserves_each_original_final_immediately(self):
        assembler = TranslationUnitAssembler()
        source = final("We should protect your.")
        unit, = assembler.add(source, 10)
        self.assertEqual(unit.source_text_en, source["sourceTextEn"])
        self.assertEqual(unit.release_reason, "legacy_immediate")
        self.assertEqual(unit.event_metadata()["translationUnitHoldMs"], 0)
        self.assertFalse(assembler.pending)

    def test_only_open_tails_wait_and_ordinary_finals_keep_zero_extra_latency(self):
        complete = (
            "God loves you", "We meet rarely.", "I don't.", "Who can?",
            "He is always faithful.", "If you listen, you will understand.",
            "My family lives here.", "We serve with joy.", "Rarely.",
            "I saw her.", "This is his.", "What is this about?",
            "If you ask he will answer",
        )
        for text in complete:
            with self.subTest(text=text):
                assembler = TranslationUnitAssembler("bounded_semantic_v1")
                unit, = assembler.add(final(text), 10)
                self.assertEqual(unit.source_text_en, text)
                self.assertEqual(unit.ready_at, unit.first_final_at)
        for text in ("We should protect your.", "This approach doesn't.", "His concern is rarely.", "If you listen."):
            with self.subTest(text=text):
                assembler = TranslationUnitAssembler("bounded_semantic_v1")
                self.assertEqual(assembler.add(final(text), 10), [])
                self.assertTrue(assembler.pending)

    def test_adjacent_finals_merge_without_modifying_or_losing_provenance(self):
        assembler = TranslationUnitAssembler("bounded_semantic_v1")
        first = final("His concern is rarely.")
        second = final("Misplaced.", 2, 3000, 6000)
        originals = copy.deepcopy([first, second])
        self.assertEqual(assembler.add(first, 10), [])
        unit, = assembler.add(second, 13.1)
        self.assertEqual([first, second], originals)
        self.assertEqual(unit.source_text_en, "His concern is rarely Misplaced.")
        self.assertEqual(unit.source_segment_ids, ("seg-000001", "seg-000002"))
        self.assertEqual((unit.audio_start_ms, unit.audio_end_ms), (0, 6000))
        self.assertEqual(unit.first_final_at, 10)
        self.assertEqual(unit.last_final_at, 13.1)
        self.assertEqual(unit.segment_id, "seg-000002")
        self.assertEqual(unit.event_metadata()["translationUnitHoldMs"], 3100)
        self.assertFalse(unit.unresolved_tail)
        first["sourceTextEn"] = "changed outside the assembler"
        self.assertEqual(unit.source_finals[0].source_text_en, originals[0]["sourceTextEn"])
        with self.assertRaises(FrozenInstanceError):
            unit.source_finals[0].source_text_en = "changed"
        self.assertEqual(
            OllamaClient.build_prompt(unit.source_text_en, {}),
            "Translate this from English to Chinese (Simplified):\n"
            "English: His concern is rarely Misplaced.\nChinese (Simplified):",
        )

    def test_conditional_clause_can_join_a_new_subject(self):
        assembler = TranslationUnitAssembler("bounded_semantic_v1")
        self.assertEqual(assembler.add(final("If you listen."), 10), [])
        unit, = assembler.add(final("You will understand.", 2, 3000, 5000), 12)
        self.assertEqual(unit.source_text_en, "If you listen You will understand.")
        self.assertFalse(unit.unresolved_tail)

    def test_no_final_arriving_still_flushes_at_absolute_deadline(self):
        assembler = TranslationUnitAssembler("bounded_semantic_v1")
        assembler.add(final("This approach doesn't."), 10)
        self.assertEqual(assembler.deadline_at, 13.2)
        self.assertEqual(assembler.flush_due(13.19), [])
        unit, = assembler.flush_due(13.2)
        self.assertEqual(unit.release_reason, "max_wait")
        self.assertTrue(unit.unresolved_tail)
        self.assertEqual(unit.source_text_en, "This approach doesn't.")
        self.assertEqual(assembler.flush_due(15), [])

    def test_late_arrival_cannot_extend_deadline_or_join_expired_source(self):
        assembler = TranslationUnitAssembler("bounded_semantic_v1")
        assembler.add(final("We protect your."), 10)
        units = assembler.add(final("Family.", 2, 3000, 6000), 13.3)
        self.assertEqual([unit.release_reason for unit in units], ["max_wait", "no_open_tail"])
        self.assertEqual([unit.source_segment_ids for unit in units], [("seg-000001",), ("seg-000002",)])

    def test_upstream_queue_delay_does_not_restart_the_hold_budget(self):
        assembler = TranslationUnitAssembler("bounded_semantic_v1")
        unit, = assembler.add(final("We protect your."), 15, final_at=10)
        self.assertEqual(unit.first_final_at, 10)
        self.assertEqual(unit.ready_at, 15)
        self.assertEqual(unit.release_reason, "max_wait")
        self.assertEqual(unit.event_metadata()["translationUnitHoldMs"], 0)
        self.assertEqual(unit.event_metadata()["translationUnitQueueWaitMs"], 5000)
        self.assertEqual(unit.event_metadata()["translationUnitSourceFinalToReadyMs"], 5000)
        self.assertFalse(assembler.pending)

    def test_queue_delay_leaves_only_remaining_budget_for_semantic_hold(self):
        assembler = TranslationUnitAssembler("bounded_semantic_v1")
        self.assertEqual(assembler.add(final("We protect your."), 11.5, final_at=10), [])
        self.assertEqual(assembler.deadline_at, 13.2)
        unit, = assembler.flush_due(13.2)
        self.assertEqual(unit.event_metadata()["translationUnitHoldMs"], 1700)
        self.assertEqual(unit.event_metadata()["translationUnitQueueWaitMs"], 1500)
        self.assertEqual(unit.event_metadata()["translationUnitSourceFinalToReadyMs"], 3200)

    def test_silence_and_stop_flush_once_with_original_unfinished_source(self):
        for reason in ("silence", "stop", "asr_failed"):
            assembler = TranslationUnitAssembler("bounded_semantic_v1")
            source = final("He takes care of your.")
            assembler.add(source, 10)
            unit, = assembler.flush(10.5, reason)
            self.assertEqual(unit.source_text_en, source["sourceTextEn"])
            self.assertEqual(unit.release_reason, reason)
            self.assertTrue(unit.unresolved_tail)
            self.assertEqual(assembler.flush(11, reason), [])

    def test_segment_limit_prevents_an_unbounded_chain_of_open_tails(self):
        assembler = TranslationUnitAssembler("bounded_semantic_v1")
        assembler.add(final("He takes care of your."), 10)
        unit, = assembler.add(final("Family and.", 2, 3000, 6000), 12)
        self.assertEqual(unit.release_reason, "segment_limit")
        self.assertTrue(unit.unresolved_tail)
        self.assertFalse(assembler.pending)

    def test_audio_gap_and_duration_limits_do_not_join_unrelated_speech(self):
        for start, end, reason in ((3900, 6000, "audio_gap"), (3000, 6600, "audio_duration_limit")):
            with self.subTest(reason=reason):
                assembler = TranslationUnitAssembler("bounded_semantic_v1")
                assembler.add(final("We protect your."), 10)
                units = assembler.add(final("Family.", 2, start, end), 12)
                self.assertEqual(units[0].release_reason, reason)
                self.assertTrue(all(len(unit.source_segment_ids) == 1 for unit in units))

    def test_obvious_sentence_restarts_do_not_fabricate_a_missing_noun_or_verb(self):
        for first, second in (
            ("He takes care of your.", "Because he loves you."),
            ("This approach doesn't.", "It's not helpful."),
            ("I know that I won't.", "I'll be able to go."),
            ("Actually it was not.", "That was the title."),
        ):
            assembler = TranslationUnitAssembler("bounded_semantic_v1")
            assembler.add(final(first), 10)
            units = assembler.add(final(second, 2, 3000, 5000), 12)
            self.assertEqual([unit.source_text_en for unit in units], [first, second])
            self.assertEqual(units[0].release_reason, "incompatible_continuation")
            self.assertTrue(units[0].unresolved_tail)

    def test_nonfinal_empty_invalid_or_out_of_order_input_is_rejected(self):
        for source in (
            {**final("hello"), "type": "asr.partial"},
            final("  "), final("hello", start=3000, end=2000),
        ):
            with self.assertRaises(ValueError):
                TranslationUnitAssembler().add(source, 10)
        assembler = TranslationUnitAssembler()
        assembler.add(final("Hello."), 10)
        with self.assertRaises(ValueError):
            assembler.add(final("Hello again.", 2, 2000, 5000), 12)
        with self.assertRaises(ValueError):
            assembler.flush_due(9)
        with self.assertRaises(ValueError):
            assembler.flush_due(float("nan"))

    def test_limits_and_policy_are_validated(self):
        for config in ({"policy": "unrecognized"}, {"max_wait_ms": 0}, {"max_segments": 0}, {"max_audio_gap_ms": -1}):
            with self.assertRaises(ValueError):
                TranslationUnitAssembler(**config)

    def test_reviewed_live_dev_cases_remain_machine_only_and_source_linked(self):
        path = Path(__file__).with_name("fixtures") / "translation-unit-dev-20260904.jsonl"
        cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        self.assertEqual(len(cases), 3)
        for case in cases:
            with self.subTest(case=case["caseId"]):
                self.assertEqual(case["reviewStatus"], "machine_text_review_only")
                self.assertEqual(case["datasetRole"], "development_regression")
                self.assertFalse(case["humanGold"])
                self.assertFalse(case["untouchedTest"])
                self.assertEqual(len(case["provenance"]["eventsSha256"]), 64)
                assembler = TranslationUnitAssembler("bounded_semantic_v1")
                sources = case["sourceFinals"]
                start = datetime.fromisoformat(sources[0]["at"])
                units = []
                for source in sources:
                    elapsed = (datetime.fromisoformat(source["at"]) - start).total_seconds()
                    units.extend(assembler.add(source, elapsed))
                units.extend(assembler.flush(elapsed, "stop"))
                self.assertEqual([list(unit.source_segment_ids) for unit in units], case["expectedSourceGroups"])
                self.assertEqual([unit.source_text_en for unit in units], case["expectedUnitTexts"])
                self.assertEqual(
                    [part.source_text_en for unit in units for part in unit.source_finals],
                    [source["sourceTextEn"] for source in sources],
                )


if __name__ == "__main__":
    unittest.main()

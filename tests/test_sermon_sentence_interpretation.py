import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import sermon_sentence_interpretation as subject


def segment(text, words, *, start=0.0, gaps=None, chunk="block-00", segment_id=0):
    gaps = gaps or [0.1] * (len(words) - 1)
    cursor = start
    timed = []
    for index, word in enumerate(words):
        timed.append({"text": word, "start": cursor, "end": cursor + 0.4})
        cursor += 0.4
        if index < len(gaps):
            cursor += gaps[index]
    return {
        "id": segment_id,
        "referenceChunkId": chunk,
        "text": text,
        "start": timed[0]["start"],
        "end": timed[-1]["end"],
        "sentenceBoundarySource": "frozen_reference_punctuation",
        "wordTimes": timed,
    }


class SentenceInterpretationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "segments.json"
        self.segments = [
            segment("Do not be afraid.", ["Do", "not", "be", "afraid."], start=0.0, segment_id=0),
            segment("I am with you.", ["I", "am", "with", "you."], start=2.2, segment_id=1),
        ]
        self.source.write_text(json.dumps(self.segments), encoding="utf-8")
        self.manifest = subject.build_anchor_manifest(self.segments, source_path=self.source)

    def candidate(self):
        groups = []
        for index, unit in enumerate(self.manifest["sourceUnits"]):
            chinese = "不要害怕。" if index == 0 else "我与你同在。"
            groups.append({
                "translationGroupId": f"g{index + 1}",
                "sourceUnitIds": [unit["sourceUnitId"]],
                "chineseUtterances": [chinese],
                "chinese": chinese,
                "coverage": [{"sourceUnitId": unit["sourceUnitId"], "targetText": chinese}],
                "review": {
                    "status": "pass",
                    "sourceUnits": [{
                        "sourceUnitId": unit["sourceUnitId"],
                        "checks": {name: "pass" for name in subject.CHECKS},
                        "evidence": "逐项核对英文含义。",
                        "uncertainty": [],
                        "issues": [],
                    }],
                },
                "audio": {
                    "text": chinese,
                    "durationSeconds": 0.8,
                    "ratePolicy": subject.RATE_POLICY,
                    "playbackRate": 1.0,
                    "receiptSha256": str(index + 1) * 64,
                },
            })
        return {
            "schemaVersion": subject.CANDIDATE_SCHEMA,
            "anchorManifestSha256": subject.json_sha256(self.manifest),
            "translator": {"model": "translator", "promptVersion": subject.PROMPT_VERSION, "requestId": "translate-1"},
            "reviewer": {"model": "reviewer", "promptVersion": subject.REVIEW_PROMPT_VERSION, "requestId": "review-1"},
            "groups": groups,
            "humanReview": {
                "humanApproval": False,
                "reviewer": None,
                "reviewedAt": None,
                "reviewedSourceUnitIds": [],
                "englishTranscriptCompleteness": "pending",
                "sentenceAndPauseBoundaries": "pending",
                "translationCompleteness": "pending",
                "naturalSpeechAndPronunciation": "pending",
                "fullPlayback": "pending",
            },
        }

    def test_prepare_preserves_words_and_exposes_pause(self):
        self.assertEqual(self.manifest["counts"]["sourceWords"], 8)
        self.assertEqual(
            [word["text"] for unit in self.manifest["sourceUnits"] for word in unit["words"]],
            [word["text"] for item in self.segments for word in item["wordTimes"]],
        )
        first = self.manifest["sourceUnits"][0]
        self.assertAlmostEqual(first["boundary"]["pauseAfterSeconds"], 0.3)
        self.assertEqual(self.manifest["translationRequests"][0]["contextAfter"], "I am with you.")
        self.assertFalse(self.manifest["releaseEligible"])

    def test_long_sentence_splits_only_at_pause_and_keeps_word_ids(self):
        long = segment(
            "One two three, four five six seven.",
            ["One", "two", "three,", "four", "five", "six", "seven."],
            gaps=[0.1, 0.1, 0.8, 0.1, 0.1, 0.1],
        )
        self.source.write_text(json.dumps([long]), encoding="utf-8")
        manifest = subject.build_anchor_manifest(
            [long], source_path=self.source, max_unit_seconds=2.0, min_unit_seconds=0.5,
            internal_pause_seconds=0.35,
        )
        self.assertEqual(len(manifest["sourceUnits"]), 2)
        self.assertEqual(manifest["sourceUnits"][0]["english"], "One two three,")
        ids = [word_id for unit in manifest["sourceUnits"] for word_id in unit["sourceWordIds"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(manifest["issues"], [])

    def test_long_sentence_without_safe_pause_is_retained_and_flagged(self):
        long = segment("One two three four five.", ["One", "two", "three", "four", "five."])
        self.source.write_text(json.dumps([long]), encoding="utf-8")
        manifest = subject.build_anchor_manifest(
            [long], source_path=self.source, max_unit_seconds=1.0, min_unit_seconds=0.5,
            internal_pause_seconds=0.35,
        )
        self.assertEqual(len(manifest["sourceUnits"]), 1)
        self.assertIn("long_sentence_without_safe_pause_split", {issue["type"] for issue in manifest["issues"]})

    def test_clause_stable_v2_preserves_parent_words_and_records_split_evidence(self):
        long = segment(
            "One two, three four.",
            ["One", "two,", "three", "four."],
            gaps=[0.1, 0.8, 0.1],
        )
        self.source.write_text(json.dumps([long]), encoding="utf-8")
        manifest = subject.build_anchor_manifest(
            [long], source_path=self.source, max_unit_seconds=1.5, min_unit_seconds=0.5,
            internal_pause_seconds=0.35, unit_policy=subject.UNIT_POLICY_V2,
        )
        self.assertEqual(manifest["schemaVersion"], subject.ANCHOR_SCHEMA_V2)
        self.assertEqual(len(manifest["sourceUnits"]), 2)
        self.assertEqual(
            {unit["sourceSentenceId"] for unit in manifest["sourceUnits"]},
            {"block-00-s001"},
        )
        self.assertEqual(
            [word_id for unit in manifest["sourceUnits"] for word_id in unit["sourceWordIds"]],
            [f"block-00-w{index:04d}" for index in range(1, 5)],
        )
        evidence = manifest["sourceUnits"][0]["boundary"]["splitEvidence"]
        self.assertEqual(evidence["kind"], "punctuation_and_audible_pause")
        self.assertEqual(evidence["afterWordId"], "block-00-w0002")
        self.assertAlmostEqual(evidence["pauseSeconds"], 0.8)
        self.assertTrue(evidence["withinTargetSeconds"])
        self.assertEqual(manifest["issues"], [])

    def test_clause_stable_v2_prefers_later_semantic_boundary_over_duration_target(self):
        long = segment(
            "One two three, four five.",
            ["One", "two", "three,", "four", "five."],
        )
        self.source.write_text(json.dumps([long]), encoding="utf-8")
        manifest = subject.build_anchor_manifest(
            [long], source_path=self.source, max_unit_seconds=1.0, min_unit_seconds=0.5,
            internal_pause_seconds=0.35, unit_policy=subject.UNIT_POLICY_V2,
        )
        self.assertEqual(len(manifest["sourceUnits"]), 2)
        first = manifest["sourceUnits"][0]
        self.assertEqual(first["english"], "One two three,")
        self.assertGreater(first["durationSeconds"], manifest["policy"]["maxUnitSeconds"])
        self.assertFalse(first["boundary"]["splitEvidence"]["withinTargetSeconds"])
        self.assertEqual(manifest["issues"], [])

    def test_clause_stable_v2_flags_alignment_word_duration_outlier(self):
        raw = [{
            "id": 0,
            "referenceChunkId": "block-00",
            "text": "I think—I know.",
            "start": 0.0,
            "end": 7.0,
            "sentenceBoundarySource": "frozen_reference_punctuation",
            "wordTimes": [
                {"text": "I", "start": 0.0, "end": 0.2},
                {"text": "think—I", "start": 0.3, "end": 6.5},
                {"text": "know.", "start": 6.6, "end": 7.0},
            ],
        }]
        self.source.write_text(json.dumps(raw), encoding="utf-8")
        manifest = subject.build_anchor_manifest(
            raw, source_path=self.source, max_unit_seconds=8.0,
            unit_policy=subject.UNIT_POLICY_V2,
        )
        issue = next(item for item in manifest["issues"]
                     if item["type"] == "alignment_word_duration_outlier")
        self.assertEqual(issue["wordId"], "block-00-w0002")
        self.assertAlmostEqual(issue["durationSeconds"], 6.2)

    def test_clause_stable_v2_recovers_internal_pause_from_phone_clusters(self):
        raw = [{
            "id": 0,
            "referenceChunkId": "block-00",
            "text": "I think—I know.",
            "start": 0.0,
            "end": 7.0,
            "sentenceBoundarySource": "frozen_reference_punctuation",
            "wordTimes": [
                {"text": "I", "start": 0.0, "end": 0.2},
                {
                    "text": "think—I", "start": 0.3, "end": 6.5,
                    "spokenForms": ["think", "i"],
                    "phones": [
                        {"start": 0.3, "end": 0.6, "phone": "think"},
                        {"start": 6.3, "end": 6.5, "phone": "i"},
                    ],
                },
                {"text": "know.", "start": 6.6, "end": 7.0},
            ],
        }]
        self.source.write_text(json.dumps(raw), encoding="utf-8")
        manifest = subject.build_anchor_manifest(
            raw, source_path=self.source, max_unit_seconds=4.0,
            min_unit_seconds=0.5, unit_policy=subject.UNIT_POLICY_V2,
        )
        self.assertEqual([unit["english"] for unit in manifest["sourceUnits"]],
                         ["I think—", "I know."])
        self.assertEqual(manifest["counts"]["sourceWords"], 4)
        self.assertEqual(manifest["issues"], [])

    def test_v2_anchor_is_supported_by_translation_review_and_validation(self):
        self.manifest = subject.build_anchor_manifest(
            self.segments, source_path=self.source, unit_policy=subject.UNIT_POLICY_V2,
        )
        self.assertTrue(subject.is_supported_anchor_manifest(self.manifest))
        draft = {
            "schemaVersion": subject.DRAFT_SCHEMA,
            "anchorManifestSha256": subject.json_sha256(self.manifest),
            "groups": self.candidate()["groups"],
        }
        self.assertEqual(subject.translation_packet(self.manifest)["requests"],
                         self.manifest["translationRequests"])
        self.assertEqual(subject.review_packet(self.manifest, draft)["groups"][0]["source"][0]["english"],
                         "Do not be afraid.")
        self.assertTrue(subject.validate_candidate(
            self.manifest, self.candidate(),
        )["candidateReadyForHumanReview"])

    def test_prepare_rejects_data_that_differs_from_bound_file(self):
        changed = copy.deepcopy(self.segments)
        changed[0]["text"] = "Changed."
        with self.assertRaisesRegex(ValueError, "differs from the bound source"):
            subject.build_anchor_manifest(changed, source_path=self.source)

    def test_segment_text_must_match_frozen_word_sequence(self):
        changed = copy.deepcopy(self.segments)
        changed[0]["text"] = "Do be afraid."
        self.source.write_text(json.dumps(changed), encoding="utf-8")
        manifest = subject.build_anchor_manifest(changed, source_path=self.source)
        self.assertIn("segment_word_text_mismatch", {issue["type"] for issue in manifest["issues"]})

    def test_valid_candidate_builds_rolling_schedule_but_is_not_release_eligible(self):
        report = subject.validate_candidate(self.manifest, self.candidate())
        self.assertTrue(report["candidateReadyForHumanReview"])
        self.assertFalse(report["releaseEligible"])
        self.assertEqual(report["status"], "candidate_ready_for_human_listening_review")
        self.assertGreaterEqual(report["schedule"][0]["plannedStart"], self.manifest["sourceUnits"][0]["end"])
        self.assertEqual(report["checks"]["measuredNaturalTiming"], "pass")

    def test_one_source_unit_can_map_to_multiple_chinese_utterances(self):
        candidate = self.candidate()
        candidate["groups"][0]["chineseUtterances"] = ["不要", "害怕。"]
        report = subject.validate_candidate(self.manifest, candidate)
        self.assertTrue(report["candidateReadyForHumanReview"])
        self.assertEqual(report["groups"][0]["mappingKind"], "1:2")

    def test_adjacent_source_units_can_map_to_one_chinese_utterance(self):
        candidate = self.candidate()
        first, second = candidate["groups"]
        chinese = first["chinese"] + second["chinese"]
        candidate["groups"] = [{
            "translationGroupId": "g1-2",
            "sourceUnitIds": first["sourceUnitIds"] + second["sourceUnitIds"],
            "chineseUtterances": [chinese],
            "chinese": chinese,
            "coverage": first["coverage"] + second["coverage"],
            "review": {
                "status": "pass",
                "sourceUnits": first["review"]["sourceUnits"] + second["review"]["sourceUnits"],
            },
            "audio": {
                "text": chinese,
                "durationSeconds": 1.4,
                "ratePolicy": subject.RATE_POLICY,
                "playbackRate": 1.0,
                "receiptSha256": "a" * 64,
            },
        }]
        report = subject.validate_candidate(self.manifest, candidate)
        self.assertTrue(report["candidateReadyForHumanReview"])
        self.assertEqual(report["groups"][0]["mappingKind"], "2:1")

    def test_translation_and_review_packets_bind_context_without_translating_it(self):
        packet = subject.translation_packet(self.manifest)
        self.assertEqual(packet["requiredOutput"]["schemaVersion"], subject.DRAFT_SCHEMA)
        self.assertEqual(packet["requests"][0]["contextAfter"], "I am with you.")
        draft = {
            "schemaVersion": subject.DRAFT_SCHEMA,
            "anchorManifestSha256": subject.json_sha256(self.manifest),
            "groups": self.candidate()["groups"],
        }
        review = subject.review_packet(self.manifest, draft)
        self.assertEqual(review["draftSha256"], subject.json_sha256(draft))
        self.assertEqual(review["requiredChecks"], list(subject.CHECKS))

    def test_review_packet_rejects_draft_that_skips_a_source_unit(self):
        draft = {
            "schemaVersion": subject.DRAFT_SCHEMA,
            "anchorManifestSha256": subject.json_sha256(self.manifest),
            "groups": self.candidate()["groups"][:1],
        }
        with self.assertRaisesRegex(ValueError, "every source unit exactly once"):
            subject.review_packet(self.manifest, draft)

    def test_missing_source_unit_coverage_fails_closed(self):
        candidate = self.candidate()
        candidate["groups"] = candidate["groups"][:1]
        report = subject.validate_candidate(self.manifest, candidate)
        self.assertFalse(report["candidateReadyForHumanReview"])
        self.assertIn("source_unit_assignment_not_exact", {issue["type"] for issue in report["issues"]})

    def test_failed_semantic_check_blocks_candidate(self):
        candidate = self.candidate()
        candidate["groups"][0]["review"]["sourceUnits"][0]["checks"]["completeMeaning"] = "fail"
        report = subject.validate_candidate(self.manifest, candidate)
        self.assertEqual(report["checks"]["independentSemanticReview"], "fail")
        self.assertFalse(report["candidateReadyForHumanReview"])

    def test_audio_text_or_speed_change_is_rejected(self):
        for field, value in (("text", "删减版"), ("playbackRate", 1.2), ("ratePolicy", "fit_to_slot")):
            with self.subTest(field=field):
                candidate = self.candidate()
                candidate["groups"][0]["audio"][field] = value
                report = subject.validate_candidate(self.manifest, candidate)
                self.assertEqual(report["checks"]["measuredNaturalTiming"], "fail")
                self.assertIn("invalid_measured_natural_audio", {issue["type"] for issue in report["issues"]})

    def test_excessive_interpreter_lag_blocks_timing(self):
        candidate = self.candidate()
        for group in candidate["groups"]:
            group["audio"]["durationSeconds"] = 9.0
        report = subject.validate_candidate(self.manifest, candidate)
        self.assertEqual(report["checks"]["measuredNaturalTiming"], "fail")
        self.assertIn("rolling_interpretation_lag_exceeded", {issue["type"] for issue in report["issues"]})

    def test_non_independent_review_receipt_is_rejected(self):
        candidate = self.candidate()
        candidate["reviewer"]["requestId"] = candidate["translator"]["requestId"]
        report = subject.validate_candidate(self.manifest, candidate)
        self.assertEqual(report["checks"]["structure"], "fail")

    def test_all_human_gates_can_make_clean_candidate_release_eligible(self):
        candidate = self.candidate()
        candidate["humanReview"] = {
            "humanApproval": True,
            "reviewer": "operator",
            "reviewedAt": "2026-09-20T20:00:00Z",
            "reviewedSourceUnitIds": [unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]],
            "englishTranscriptCompleteness": "approved",
            "sentenceAndPauseBoundaries": "approved",
            "translationCompleteness": "approved",
            "naturalSpeechAndPronunciation": "approved",
            "fullPlayback": "approved",
        }
        report = subject.validate_candidate(self.manifest, candidate)
        self.assertTrue(report["releaseEligible"])
        self.assertEqual(report["status"], "approved_sentence_interpretation")

    def test_candidate_is_bound_to_exact_anchor_manifest(self):
        candidate = self.candidate()
        changed = copy.deepcopy(self.manifest)
        changed["sourceUnits"][0]["english"] = "Changed."
        with self.assertRaisesRegex(ValueError, "another anchor manifest"):
            subject.validate_candidate(changed, candidate)

    def test_anchor_issue_blocks_candidate_even_when_downstream_checks_pass(self):
        changed = copy.deepcopy(self.manifest)
        changed["issues"] = [{"type": "boundary_requires_resolution"}]
        candidate = self.candidate()
        candidate["anchorManifestSha256"] = subject.json_sha256(changed)
        report = subject.validate_candidate(changed, candidate)
        self.assertEqual(report["checks"]["sourceAnchors"], "fail")
        self.assertFalse(report["candidateReadyForHumanReview"])


if __name__ == "__main__":
    unittest.main()

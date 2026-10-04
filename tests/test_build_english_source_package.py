import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from scripts import build_english_source_package as subject
from scripts import sermon_sentence_interpretation as anchors
from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class EnglishSourcePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.segments_path = self.root / "segments.json"
        self.segments = [{
            "id": 0,
            "referenceChunkId": "block-00",
            "text": "Do not be afraid.",
            "start": 0.0,
            "end": 1.9,
            "sentenceBoundarySource": "frozen_reference_punctuation",
            "wordTimes": [
                {"text": "Do", "start": 0.0, "end": 0.3},
                {"text": "not", "start": 0.4, "end": 0.7},
                {"text": "be", "start": 0.8, "end": 1.1},
                {"text": "afraid.", "start": 1.2, "end": 1.9},
            ],
        }]
        write_json(self.segments_path, self.segments)
        self.manifest = anchors.build_anchor_manifest(
            self.segments,
            source_path=self.segments_path,
            unit_policy=anchors.UNIT_POLICY_V2,
        )
        self.manifest_path = self.root / "anchor-manifest.json"
        write_json(self.manifest_path, self.manifest)
        self.summary_path = self.root / "summary.json"
        write_json(self.summary_path, {
            "sourceDurationSeconds": 300.0,
            "sermonStartSeconds": 10.0,
            "sermonEndSeconds": 20.0,
            "models": {"referenceAsr": "gpt-transcribe"},
            "readingAligner": "mfa",
            "pipelineInputIdentity": {
                "sourceAudio": {"sha256": "1" * 64, "sizeBytes": 1000},
                "readingAligner": "mfa",
            },
        })
        self.approval_path = self.root / "approval.json"
        write_json(self.approval_path, {
            "status": "approved",
            "humanApproval": True,
            "sourceUrlHash": "2" * 64,
        })

    def schema_errors(self, filename: str, value: object) -> list:
        schema = json.loads((Path(__file__).parents[1] / "schemas" / filename).read_text())
        return list(Draft202012Validator(
            schema, format_checker=FormatChecker(),
        ).iter_errors(value))

    def build(self, *, review_path=None):
        return subject.build_package(
            self.segments_path,
            self.manifest_path,
            summary_path=self.summary_path,
            approval_evidence_path=self.approval_path,
            review_path=review_path,
            source_id="sermon-fixture",
            source_url_hash="2" * 64,
            service_date="2026-09-20",
        )

    def prepare_individual_long_clause_review(self, *, selected_failure=False,
                                              mismatched_units=False,
                                              deterministic_failure=False,
                                              malformed_sentences=False):
        self.segments.append({
            "id": 1,
            "referenceChunkId": "block-00",
            "text": "Keep this unchanged.",
            "start": 3.0,
            "end": 4.9,
            "sentenceBoundarySource": "frozen_reference_punctuation",
            "wordTimes": [
                {"text": "Keep", "start": 3.0, "end": 3.3},
                {"text": "this", "start": 3.5, "end": 3.8},
                {"text": "unchanged.", "start": 4.0, "end": 4.9},
            ],
        })
        write_json(self.segments_path, self.segments)
        self.manifest = anchors.build_anchor_manifest(
            self.segments,
            source_path=self.segments_path,
            unit_policy=anchors.UNIT_POLICY_V2,
        )
        selected_sentence_id = self.manifest["sourceUnits"][0]["sourceSentenceId"]
        issue = {
            "type": "clause_unit_exceeds_target_without_safe_boundary",
            "sourceSentenceId": selected_sentence_id,
            "durationSeconds": 1.9,
            "maximumSeconds": 1.0,
        }
        self.manifest["issues"] = [issue]
        write_json(self.manifest_path, self.manifest)

        source_sentence_ids = list(dict.fromkeys(
            unit["sourceSentenceId"] for unit in self.manifest["sourceUnits"]
        ))
        sentences = []
        for sentence_id in source_sentence_ids:
            unit_ids = [unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]
                        if unit["sourceSentenceId"] == sentence_id]
            is_selected = sentence_id == selected_sentence_id
            checks = {name: "pass" for name in subject.MACHINE_JUDGE_CHECKS}
            verdict = "pass" if is_selected else "fail"
            if is_selected and selected_failure:
                checks["meaningPreserved"] = "fail"
                verdict = "fail"
            if is_selected and mismatched_units:
                unit_ids = unit_ids + ["unexpected-unit"]
            sentences.append({
                "sourceSentenceId": sentence_id,
                "sourceUnitIds": unit_ids,
                "verdict": verdict,
                "risk": "low",
                "checks": checks,
                "evidence": "Fixture sentence review evidence.",
                "unresolvedIssues": [],
            })
        deterministic_checks = [{"checkId": "fixture-check", "status": "pass",
                                 "evidence": "Fixture deterministic evidence."}]
        if deterministic_failure:
            deterministic_checks[0]["status"] = "fail"
        judge = {
            "schemaVersion": subject.MACHINE_JUDGE_SCHEMA_VERSION,
            "reviewType": "model",
            "humanApproval": False,
            "status": "rejected_for_layer2_shadow",
            "layer2DevelopmentEligible": False,
            "productionTranslationEligible": False,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": subject.json_sha256(self.manifest),
            "downstreamInvalidationKey": "3" * 64,
            "implementationSha256": subject.file_sha256(
                Path(subject.__file__).with_name("judge_english_source_for_translation.py")),
            "model": subject.MACHINE_JUDGE_MODEL,
            "reasoningEffort": subject.MACHINE_JUDGE_REASONING_EFFORT,
            "promptVersion": subject.MACHINE_JUDGE_SCHEMA_VERSION,
            "requestIds": ["fixture-request"],
            "responseModels": [subject.MACHINE_JUDGE_MODEL],
            "reviewedAt": "2026-09-20T12:00:00Z",
            "thresholds": subject.MACHINE_JUDGE_THRESHOLDS,
            "deterministicReview": {
                "status": "fail" if deterministic_failure else "pass",
                "checks": deterministic_checks,
                "issues": [],
            },
            "reviewedSourceSentenceIds": source_sentence_ids,
            "reviewedManifestIssueJsonSha256s": [subject.json_sha256(item)
                                                 for item in self.manifest["issues"]],
            "sentences": sentences,
            "counts": {
                "sourceSentences": len(source_sentence_ids),
                "sourceUnits": len(self.manifest["sourceUnits"]),
                "manifestIssues": 1,
                "sentencePass": sum(item["verdict"] == "pass" for item in sentences),
                "sentenceFail": sum(item["verdict"] == "fail" for item in sentences),
                "highRiskSentences": 0,
            },
            "unresolvedIssues": [],
            "requestReceipts": [],
        }
        if malformed_sentences:
            judge["sentences"] = None
        judge_path = self.root / "rejected-machine-judge.json"
        write_json(judge_path, judge)
        judge_artifact = subject.artifact(judge_path, value=judge)

        review_path = self.root / "human-review.json"
        write_json(review_path, {
            "schemaVersion": subject.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": subject.json_sha256(self.manifest),
            "humanApproval": True,
            "reviewedBy": "Fixture reviewer",
            "reviewedAt": "2026-09-20T12:00:00Z",
            "reviewedSourceUnitIds": [unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]],
            "checks": {name: "approved" for name in subject.APPROVED_CHECKS},
        })
        return review_path, judge_artifact

    def test_package_waits_for_machine_judge_and_is_target_language_neutral(self):
        package = self.build()
        self.assertEqual(package["status"], "blocked")
        self.assertFalse(package["candidateTranslationEligible"])
        self.assertFalse(package["translationEligible"])
        self.assertIsNone(package["evidence"]["machineJudge"])
        self.assertEqual(package["alignment"]["provider"], "mfa")
        encoded = json.dumps(package, ensure_ascii=False)
        self.assertNotIn("translationSystemPrompt", encoded)
        self.assertNotIn("chineseUtterances", encoded)
        self.assertNotIn("promptPolicy", json.dumps(self.manifest))
        self.assertEqual(
            self.schema_errors("sermon-english-source-package-v1.schema.json", package), [],
        )

    def test_source_cli_records_timing_but_blocked_package_remains_blocked(self):
        ledger = self.root / "four-layer-progress.json"
        progress.save(ledger, progress.new_ledger("test-page", ["ko"]))
        output = self.root / "english-source-package.json"
        argv = ["source-package", "--aligned-segments", str(self.segments_path),
                "--anchor-manifest", str(self.manifest_path), "--summary", str(self.summary_path),
                "--approval-evidence", str(self.approval_path), "--source-id", "sermon-fixture",
                "--source-url-hash", "2" * 64, "--service-date", "2026-09-20",
                "--progress-ledger", str(ledger), "--out", str(output)]
        with patch.object(sys, "argv", argv):
            self.assertEqual(subject.main(), 2)
        self.assertEqual(json.loads(output.read_text())["status"], "blocked")
        events, damaged = accounting.read_events(self.root / "accounting")
        self.assertFalse(damaged)
        workload = next(event for event in events if event["event"] == "workload"
                        and event["stage"] == "four_layer.L1-04")
        self.assertEqual(workload["metrics"]["sourceUnits"], 1)
        self.assertFalse(workload["metrics"]["approvedForTranslation"])
        self.assertEqual(progress.load(ledger)["steps"]["L1-04"]["status"], "pending")

    def test_bound_human_review_promotes_layer_one_only(self):
        review_path = self.root / "review.json"
        review = {
            "schemaVersion": subject.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": subject.json_sha256(self.manifest),
            "humanApproval": True,
            "reviewedBy": "Fixture reviewer",
            "reviewedAt": "2026-09-20T12:00:00Z",
            "reviewedSourceUnitIds": [
                unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]
            ],
            "checks": {name: "approved" for name in subject.APPROVED_CHECKS},
        }
        write_json(review_path, review)
        self.assertEqual(
            self.schema_errors("sermon-english-source-review-v1.schema.json", review), [],
        )
        package = self.build(review_path=review_path)
        self.assertEqual(package["status"], "ready_for_translation")
        subject.validate_ready_package(package)
        self.assertTrue(package["translationEligible"])
        self.assertEqual(package["issues"], [])
        self.assertEqual(
            self.schema_errors("sermon-english-source-package-v1.schema.json", package), [],
        )

    def test_builder_blocks_window_beyond_known_media_duration(self):
        summary = json.loads(self.summary_path.read_text())
        summary['sermonEndSeconds'] = summary['sourceDurationSeconds'] + 1
        write_json(self.summary_path, summary)
        package = self.build()
        self.assertFalse(package['translationEligible'])
        self.assertIn('source_window_incoherent', [issue['type'] for issue in package['issues']])

    def test_long_intact_clause_needs_both_reviews_to_clear_production_gate(self):
        self.manifest["issues"] = [{
            "type": "clause_unit_exceeds_target_without_safe_boundary",
            "sourceSentenceId": self.manifest["sourceUnits"][0]["sourceSentenceId"],
            "durationSeconds": 1.9,
            "maximumSeconds": 1.0,
        }]
        write_json(self.manifest_path, self.manifest)
        review_path = self.root / "review-long-clause.json"
        write_json(review_path, {
            "schemaVersion": subject.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": subject.json_sha256(self.manifest),
            "humanApproval": True,
            "reviewedBy": "Fixture reviewer",
            "reviewedAt": "2026-09-20T12:00:00Z",
            "reviewedSourceUnitIds": [unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]],
            "checks": {name: "approved" for name in subject.APPROVED_CHECKS},
        })
        self.assertEqual(self.build(review_path=review_path)["status"], "blocked")
        with patch.object(subject, "_machine_judge_payload", return_value=(None, True)):
            approved = self.build(review_path=review_path)
            self.assertEqual(approved["status"], "ready_for_translation")
            self.assertEqual(approved["issues"], [])
            self.assertEqual(approved["anchors"]["issueCount"], 1)
            self.assertEqual(
                self.schema_errors("sermon-english-source-package-v1.schema.json", approved), [],
            )

    def test_bound_passing_sentence_clears_long_clause_when_another_sentence_fails(self):
        review_path, judge_artifact = self.prepare_individual_long_clause_review()
        with patch.object(subject, "_machine_judge_payload", return_value=(judge_artifact, False)):
            package = self.build(review_path=review_path)
            without_human_review = self.build()
        self.assertEqual(package["status"], "ready_for_translation")
        self.assertTrue(package["translationEligible"])
        self.assertEqual(package["issues"], [])
        self.assertEqual(package["anchors"]["issueCount"], 1)
        self.assertEqual(package["evidence"]["machineJudge"], judge_artifact)
        self.assertEqual(without_human_review["status"], "blocked")
        self.assertTrue(any(item.get("stage") == "anchors"
                            and item.get("detail") == self.manifest["issues"][0]
                            for item in without_human_review["issues"]))

    def test_bound_long_clause_remains_blocked_when_selected_sentence_fails(self):
        review_path, judge_artifact = self.prepare_individual_long_clause_review(
            selected_failure=True,
        )
        with patch.object(subject, "_machine_judge_payload", return_value=(judge_artifact, False)):
            package = self.build(review_path=review_path)
        self.assertEqual(package["status"], "blocked")
        self.assertFalse(package["translationEligible"])
        self.assertEqual(len(package["issues"]), 1)
        self.assertEqual(package["issues"][0]["detail"], self.manifest["issues"][0])
        self.assertEqual(package["evidence"]["machineJudge"], judge_artifact)

    def test_bound_long_clause_requires_exact_units_and_passing_deterministic_review(self):
        for kwargs in ({"mismatched_units": True}, {"deterministic_failure": True},
                       {"malformed_sentences": True}):
            with self.subTest(kwargs=kwargs):
                review_path, judge_artifact = self.prepare_individual_long_clause_review(**kwargs)
                with patch.object(subject, "_machine_judge_payload",
                                  return_value=(judge_artifact, False)):
                    package = self.build(review_path=review_path)
                self.assertEqual(package["status"], "blocked")
                self.assertFalse(package["translationEligible"])
                self.assertEqual(len(package["issues"]), 1)

    def test_versioned_human_override_opens_only_layer2_candidate_path(self):
        self.manifest["issues"] = [{
            "type": "clause_unit_exceeds_target_without_safe_boundary",
            "sourceSentenceId": self.manifest["sourceUnits"][0]["sourceSentenceId"],
            "durationSeconds": 1.9,
            "maximumSeconds": 1.0,
        }]
        write_json(self.manifest_path, self.manifest)
        judge_path = self.root / "rejected-judge.json"
        judge = {
            "status": "rejected_for_layer2_shadow",
            "layer2DevelopmentEligible": False,
            "productionTranslationEligible": False,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": subject.json_sha256(self.manifest),
            "sentences": [
                {"sourceSentenceId": "0-s000", "verdict": "fail", "risk": "high"},
                {"sourceSentenceId": "0-s001", "verdict": "pass", "risk": "low"},
            ],
        }
        write_json(judge_path, judge)
        judge_artifact = subject.artifact(judge_path, value=judge)
        review_path = self.root / "review-v2.json"
        review = {
            "schemaVersion": subject.REVIEW_SCHEMA_V2,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": subject.json_sha256(self.manifest),
            "humanApproval": True,
            "reviewedBy": "Fixture reviewer",
            "reviewedAt": "2026-09-20T12:00:00Z",
            "reviewedSourceUnitIds": [unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]],
            "checks": {name: "approved" for name in subject.APPROVED_CHECKS},
            "layer2CandidateOverride": {
                "decision": subject.LAYER2_CANDIDATE_OVERRIDE_DECISION,
                "scope": "layer2_candidate_only",
                "sourceId": "sermon-fixture",
                "machineJudge": {key: judge_artifact[key] for key in ("path", "sha256", "jsonSha256")},
                "acknowledgedFailureSentenceIds": ["0-s000"],
                "acknowledgedHighRiskSentenceIds": ["0-s000"],
                "acknowledgedAnchorIssueTypes": ["clause_unit_exceeds_target_without_safe_boundary"],
                "targetLocales": ["es", "ko", "zh-Hans"],
                "audioGeneration": False,
                "publication": False,
                "userInstructionItemId": "request-item",
                "authorizationItemId": "authorization-item",
                "userStatement": "Approve Layer 2 candidates only.",
            },
        }
        write_json(review_path, review)
        self.assertEqual(self.schema_errors("sermon-english-source-review-v2.schema.json", review), [])
        with patch.object(subject, "_machine_judge_payload", return_value=(judge_artifact, False)):
            package = self.build(review_path=review_path)
        self.assertEqual(package["status"], "candidate_ready_for_translation")
        self.assertTrue(package["candidateTranslationEligible"])
        self.assertFalse(package["translationEligible"])
        self.assertEqual(package["evidence"]["machineJudge"], judge_artifact)
        self.assertEqual(len(package["issues"]), 1)
        override = subject.validate_layer2_candidate_package(package, self.manifest)
        self.assertEqual(override["targetLocales"], ["es", "ko", "zh-Hans"])
        with self.assertRaises(ValueError):
            subject.validate_ready_package(package)
        changed = json.loads(json.dumps(package))
        changed["review"]["evidence"]["path"] = str(self.root / "other-review.json")
        with self.assertRaises(ValueError):
            subject.validate_layer2_candidate_package(changed, self.manifest)
            self.manifest["issues"].append({"type": "alignment_word_duration_outlier"})
            write_json(self.manifest_path, self.manifest)
            changed_review = json.loads(review_path.read_text())
            changed_review["anchorManifestJsonSha256"] = subject.json_sha256(self.manifest)
            write_json(review_path, changed_review)
            blocked = self.build(review_path=review_path)
            self.assertEqual(blocked["status"], "candidate_ready_for_translation")
            self.assertFalse(blocked["translationEligible"])
            self.assertIn("alignment_word_duration_outlier", {item["type"] for item in blocked["issues"]})

    def test_review_bound_to_other_anchor_is_rejected(self):
        review_path = self.root / "review.json"
        write_json(review_path, {
            "schemaVersion": subject.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": "f" * 64,
            "humanApproval": True,
            "reviewedBy": "Fixture reviewer",
            "reviewedAt": "2026-09-20T12:00:00Z",
            "reviewedSourceUnitIds": [
                unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]
            ],
            "checks": {name: "approved" for name in subject.APPROVED_CHECKS},
        })
        with self.assertRaisesRegex(ValueError, "different anchor manifest"):
            self.build(review_path=review_path)

    def test_source_identity_and_window_change_invalidation_key(self):
        original = self.build()
        changed_source = subject.build_package(
            self.segments_path,
            self.manifest_path,
            summary_path=self.summary_path,
            approval_evidence_path=self.approval_path,
            source_id="another-recording",
            source_url_hash="2" * 64,
            service_date="2026-09-20",
        )
        self.assertNotEqual(
            original["downstreamInvalidationKey"],
            changed_source["downstreamInvalidationKey"],
        )

        changed_summary = dict(json.loads(self.summary_path.read_text()))
        changed_summary["sermonEndSeconds"] = 21.0
        changed_summary_path = self.root / "changed-summary.json"
        write_json(changed_summary_path, changed_summary)
        changed_window = subject.build_package(
            self.segments_path,
            self.manifest_path,
            summary_path=changed_summary_path,
            approval_evidence_path=self.approval_path,
            source_id="sermon-fixture",
            source_url_hash="2" * 64,
            service_date="2026-09-20",
        )
        self.assertNotEqual(
            original["downstreamInvalidationKey"],
            changed_window["downstreamInvalidationKey"],
        )

    def test_invalid_service_date_and_review_time_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "real calendar date"):
            subject.build_package(
                self.segments_path,
                self.manifest_path,
                service_date="2026-02-30",
            )

        review_path = self.root / "review-invalid-time.json"
        write_json(review_path, {
            "schemaVersion": subject.REVIEW_SCHEMA_VERSION,
            "alignedSegmentsSha256": subject.file_sha256(self.segments_path),
            "anchorManifestJsonSha256": subject.json_sha256(self.manifest),
            "humanApproval": True,
            "reviewedBy": "Fixture reviewer",
            "reviewedAt": "2026-09-20T12:00:00",
            "reviewedSourceUnitIds": [
                unit["sourceUnitId"] for unit in self.manifest["sourceUnits"]
            ],
            "checks": {name: "approved" for name in subject.APPROVED_CHECKS},
        })
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.build(review_path=review_path)

    def test_layer_three_and_four_output_schemas_accept_explicit_unavailable_state(self):
        audio = {
            "schemaVersion": "sermon-target-language-audio-package-v1",
            "packageId": "ko-audio-fixture",
            "englishSourcePackageJsonSha256": "1" * 64,
            "targetLanguageCandidateJsonSha256": "2" * 64,
            "targetLanguageSpeechJobJsonSha256": "3" * 64,
            "targetLocale": "ko",
            "status": "audio_unavailable",
            "ratePolicy": "natural_no_time_stretch",
            "voice": None,
            "units": [],
            "track": None,
            "captions": None,
            "schedule": None,
            "machineScreening": {"status": "not_run", "model": None, "coverage": 0},
            "humanReview": {
                "status": "pending", "humanApproval": False,
                "reviewedBy": None, "reviewedAt": None, "fullPlayback": "pending",
            },
            "issues": [],
            "downstreamInvalidationKey": "4" * 64,
        }
        release = {
            "schemaVersion": "sermon-target-language-release-package-v1",
            "packageId": "ko-release-fixture",
            "pageId": "fixture-page",
            "sourceLocale": "en",
            "targetLocale": "ko",
            "targetLanguageCandidateJsonSha256": "2" * 64,
            "targetLanguageAudioPackageJsonSha256": None,
            "status": "candidate",
            "contentStatus": "human_reviewed",
            "audioStatus": "unavailable",
            "interfaceLocale": "ko",
            "contentLocale": "ko",
            "audioLocale": None,
            "assets": [{"role": "page", "path": "index.html", "sha256": "5" * 64}],
            "httpVerification": {"status": "not_run", "evidenceSha256": None},
            "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
            "venueAcceptance": {"status": "not_run", "evidenceSha256": None},
            "issues": [],
        }
        self.assertEqual(self.schema_errors(
            "sermon-target-language-audio-package-v1.schema.json", audio,
        ), [])
        self.assertEqual(self.schema_errors(
            "sermon-target-language-release-package-v1.schema.json", release,
        ), [])


if __name__ == "__main__":
    unittest.main()

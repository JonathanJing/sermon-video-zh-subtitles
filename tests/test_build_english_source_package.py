import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts import build_english_source_package as subject
from scripts import sermon_sentence_interpretation as anchors


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

    def test_candidate_is_target_language_neutral_and_schema_valid(self):
        package = self.build()
        self.assertEqual(package["status"], "candidate_ready_for_translation")
        self.assertTrue(package["candidateTranslationEligible"])
        self.assertFalse(package["translationEligible"])
        self.assertEqual(package["alignment"]["provider"], "mfa")
        encoded = json.dumps(package, ensure_ascii=False)
        self.assertNotIn("translationSystemPrompt", encoded)
        self.assertNotIn("chineseUtterances", encoded)
        self.assertNotIn("promptPolicy", json.dumps(self.manifest))
        self.assertEqual(
            self.schema_errors("sermon-english-source-package-v1.schema.json", package), [],
        )

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
        self.assertTrue(package["translationEligible"])
        self.assertEqual(package["issues"], [])
        self.assertEqual(
            self.schema_errors("sermon-english-source-package-v1.schema.json", package), [],
        )

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

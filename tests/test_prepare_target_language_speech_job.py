import copy
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from scripts import prepare_target_language_speech_job as subject
from scripts import sermon_sentence_interpretation as interpretation


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class TargetLanguageSpeechJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.anchor = {
            "schemaVersion": interpretation.ANCHOR_SCHEMA_V2,
            "sourceUnits": [
                {"sourceUnitId": "block-00-u001", "english": "Do not be afraid."},
                {"sourceUnitId": "block-00-u002", "english": "I am with you."},
            ],
        }
        self.candidate = {
            "schemaVersion": subject.CANDIDATE_SCHEMA,
            "sourceLocale": "en",
            "targetLocale": "ko",
            "anchorManifestSha256": interpretation.json_sha256(self.anchor),
            "translationPolicySha256": "1" * 64,
            "status": "human_translation_approved",
            "releaseEligible": False,
            "generation": {
                "translator": {"model": "translator", "promptVersion": "ko-v1", "requestIds": ["t1"]},
                "reviewer": {"model": "reviewer", "promptVersion": "ko-review-v1", "requestIds": ["r1"]},
            },
            "groups": [
                self.group("g1", "block-00-u001", "두려워하지 마십시오."),
                self.group("g2", "block-00-u002", "내가 당신과 함께 있습니다."),
            ],
            "modelReview": {"status": "pass", "reviewedGroupIds": ["g1", "g2"]},
            "humanReview": {
                "translation": "approved", "reviewer": "Korean reviewer",
                "reviewedAt": "2026-09-20T12:00:00Z", "reviewedGroupIds": ["g1", "g2"],
            },
        }
        self.adapter = {
            "schemaVersion": subject.ADAPTER_SCHEMA,
            "targetLocale": "ko",
            "adapterId": "ko-speech-poc",
            "adapterVersion": "v1",
            "model": "target-language-tts",
            "voice": "speaker-poc",
            "languageParameter": "Korean",
            "capabilityStatus": "unverified_poc",
            "normalizationPolicySha256": "2" * 64,
            "asrScreeningPolicySha256": "3" * 64,
            "subtitlePolicySha256": "4" * 64,
        }
        self.anchor_path = self.root / "anchor.json"
        self.candidate_path = self.root / "candidate.json"
        self.adapter_path = self.root / "adapter.json"
        write_json(self.anchor_path, self.anchor)
        write_json(self.candidate_path, self.candidate)
        write_json(self.adapter_path, self.adapter)

    @staticmethod
    def group(group_id: str, source_id: str, text: str) -> dict:
        return {
            "translationGroupId": group_id,
            "sourceUnitIds": [source_id],
            "targetUtterances": [text],
            "targetText": text,
            "coverage": [{"sourceUnitId": source_id, "targetText": text}],
            "semanticReview": {
                "status": "pass",
                "checks": {key: "pass" for key in subject.SEMANTIC_CHECKS},
                "evidence": "Compared with the frozen English unit.",
                "uncertainty": [],
                "issues": [],
            },
            "languageReview": {
                "status": "pass", "pluginId": "ko-sermon-v1", "policySha256": "5" * 64,
                "checks": [{"checkId": "ko-natural-speech", "status": "pass", "evidence": "Reviewed."}],
            },
        }

    def validate_schema(self, filename: str, value: object) -> list:
        schema = json.loads((Path(__file__).parents[1] / "schemas" / filename).read_text())
        return list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))

    def test_korean_candidate_and_prepared_job_match_published_contracts(self):
        self.assertEqual(self.validate_schema("sermon-target-language-candidate-v2.schema.json", self.candidate), [])
        job = subject.prepare_job(
            self.anchor_path, self.candidate_path, self.adapter_path, self.root / "speech-job",
        )
        self.assertEqual(job["status"], "prepared_adapter_validation_required")
        self.assertFalse(job["synthesisEligible"])
        self.assertFalse(job["releaseEligible"])
        self.assertEqual(job["units"][0]["text"], "두려워하지 마십시오.")
        self.assertEqual(job["outputContract"]["languageRoot"], "languages/ko")
        self.assertTrue(all(unit["outputRelativePath"].startswith("languages/ko/audio/")
                            for unit in job["units"]))
        self.assertEqual(self.validate_schema("sermon-target-language-speech-job-v1.schema.json", job), [])

    def test_verified_adapter_only_changes_synthesis_gate_not_release_gate(self):
        self.adapter["capabilityStatus"] = "verified"
        write_json(self.adapter_path, self.adapter)
        job = subject.prepare_job(
            self.anchor_path, self.candidate_path, self.adapter_path, self.root / "verified-job",
        )
        self.assertEqual(job["status"], "prepared_for_target_language_speech")
        self.assertTrue(job["synthesisEligible"])
        self.assertFalse(job["releaseEligible"])

    def test_layer_three_rejects_pending_human_translation_review(self):
        self.candidate["status"] = "machine_review_pass_human_review_pending"
        self.candidate["humanReview"] = {
            "translation": "pending", "reviewer": None, "reviewedAt": None, "reviewedGroupIds": [],
        }
        write_json(self.candidate_path, self.candidate)
        with self.assertRaisesRegex(ValueError, "Human translation approval"):
            subject.prepare_job(
                self.anchor_path, self.candidate_path, self.adapter_path, self.root / "blocked-job",
            )

    def test_candidate_rejects_locale_mismatch_and_cross_language_adapter(self):
        self.candidate["targetLocale"] = "en"
        with self.assertRaisesRegex(ValueError, "Invalid target locale"):
            subject.validate_target_candidate(self.anchor, self.candidate)
        changed = copy.deepcopy(self.adapter)
        changed["targetLocale"] = "zh-Hans"
        with self.assertRaisesRegex(ValueError, "locale differs"):
            subject.validate_adapter(changed, "ko")

    def test_candidate_rejects_missing_or_reordered_source_coverage(self):
        self.candidate["groups"].reverse()
        self.candidate["modelReview"]["reviewedGroupIds"].reverse()
        with self.assertRaisesRegex(ValueError, "every source unit exactly once and in order"):
            subject.validate_target_candidate(self.anchor, self.candidate)


if __name__ == "__main__":
    unittest.main()

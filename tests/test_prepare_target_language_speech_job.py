import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

from jsonschema import Draft202012Validator, FormatChecker

from scripts import prepare_target_language_speech_job as subject
from scripts import review_target_language_candidate as human_review
from scripts import validate_target_language_audio_unit as audio_integrity
from scripts import sermon_sentence_interpretation as interpretation
from scripts import target_language_policy as policy_tools


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
        self.source_package = {
            "schemaVersion": subject.SOURCE_PACKAGE_SCHEMA,
            "status": "ready_for_translation",
            "translationEligible": True,
            "anchors": {"artifact": {"jsonSha256": interpretation.json_sha256(self.anchor)}},
        }
        self.candidate = {
            "schemaVersion": subject.CANDIDATE_SCHEMA,
            "sourceLocale": "en",
            "targetLocale": "ko",
            "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source_package),
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
        self.registry = json.loads((Path(__file__).parents[1] / "config/speaker-voice-registry.json").read_text(encoding="utf-8"))
        speaker = self.registry["speakers"][0]
        capability = next(row for row in speaker["localeCapabilities"] if row["targetLocale"] == "ko")
        self.adapter = {
            "schemaVersion": subject.ADAPTER_SCHEMA,
            "targetLocale": "ko", "adapterId": "qwen3_tts_sft", "adapterVersion": "v1",
            "provider": self.registry["baseModel"]["provider"],
            "model": self.registry["baseModel"]["model"],
            "modelRevision": self.registry["baseModel"]["revision"],
            "voice": speaker["speakerKey"], "speakerId": speaker["speakerId"],
            "speakerKey": speaker["speakerKey"],
            "conditioningRef": speaker["checkpoint"]["checkpointRef"],
            "conditioningSha256": speaker["checkpoint"]["checkpointSha256"],
            "registryJsonSha256": interpretation.json_sha256(self.registry),
            "authorizationPurpose": "multilingual_voice_demo",
            "authorizationEvidenceSha256": interpretation.json_sha256(speaker["authorization"]["evidence"]),
            "capabilityEvidenceSha256": interpretation.json_sha256(capability["reviewEvidence"]),
            "languageParameter": capability["modelLanguage"],
            "capabilityStatus": "unverified_poc",
            "normalizationPolicySha256": "2" * 64,
            "asrScreeningPolicySha256": "3" * 64,
            "subtitlePolicySha256": "4" * 64,
        }
        policy_draft = json.loads((Path(__file__).parents[1] / "config/target-language-policies/ko.json").read_text(encoding="utf-8"))
        policy_draft.pop("componentSha256")
        for term in policy_draft["terminology"]["seriesNames"] + policy_draft["terminology"]["properNames"]:
            term["target"] = "synthetic-test-term"
            term["reviewStatus"] = "human_reviewed"
        policy_draft["scripture"].update({
            "editionId": "synthetic-test-edition", "citationUseStatus": "project_source_reviewed",
            "quoteCheckPolicy": "references_only",
        })
        policy_draft["languageReview"]["implementationStatus"] = "verified"
        self.policy = policy_tools.freeze_policy(policy_draft)
        identity = policy_tools.validate_policy(self.policy)
        self.candidate["translationPolicySha256"] = identity["translationPolicySha256"]
        for stage in ("translator", "reviewer"):
            self.candidate["generation"][stage]["model"] = self.policy[stage]["model"]
            self.candidate["generation"][stage]["promptVersion"] = self.policy[stage]["promptVersion"]
        for group in self.candidate["groups"]:
            group["languageReview"]["pluginId"] = self.policy["languageReview"]["pluginId"]
            group["languageReview"]["policySha256"] = identity["languageReviewPolicySha256"]
            group["languageReview"]["checks"] = [
                {"checkId": check_id, "status": "pass", "evidence": "Synthetic test review."}
                for check_id in self.policy["languageReview"]["requiredChecks"]
            ]
        self.human_review_receipt = {
            "schemaVersion": subject.HUMAN_REVIEW_RECEIPT_SCHEMA,
            "decision": "approved", "targetLocale": "ko",
            "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source_package),
            "anchorManifestJsonSha256": interpretation.json_sha256(self.anchor),
            "translationPolicySha256": self.candidate["translationPolicySha256"],
            "candidateJsonSha256": interpretation.json_sha256(self.candidate),
            "reviewer": self.candidate["humanReview"]["reviewer"],
            "reviewedAt": self.candidate["humanReview"]["reviewedAt"],
            "reviewedGroupIds": ["g1", "g2"],
            "groupReviews": [
                {"translationGroupId": group_id, "decision": "approved", "evidence": "Synthetic test review."}
                for group_id in ("g1", "g2")
            ],
        }
        self.source_package_path = self.root / "english-source-package.json"
        self.anchor_path = self.root / "anchor.json"
        self.candidate_path = self.root / "candidate.json"
        self.policy_path = self.root / "policy.json"
        self.human_review_receipt_path = self.root / "human-review-receipt.json"
        self.adapter_path = self.root / "adapter.json"
        self.registry_path = self.root / "registry.json"
        write_json(self.source_package_path, self.source_package)
        write_json(self.anchor_path, self.anchor)
        write_json(self.candidate_path, self.candidate)
        write_json(self.policy_path, self.policy)
        write_json(self.human_review_receipt_path, self.human_review_receipt)
        write_json(self.adapter_path, self.adapter)
        write_json(self.registry_path, self.registry)

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
            self.source_package_path, self.anchor_path, self.candidate_path,
            self.policy_path, self.human_review_receipt_path, self.adapter_path,
            self.registry_path, self.root / "speech-job",
        )
        self.assertEqual(job["status"], "prepared_adapter_validation_required")
        self.assertFalse(job["synthesisEligible"])
        self.assertFalse(job["releaseEligible"])
        self.assertEqual(job["units"][0]["text"], "두려워하지 마십시오.")
        self.assertEqual(job["outputContract"]["languageRoot"], "languages/ko")
        self.assertTrue(all(unit["outputRelativePath"].startswith("languages/ko/audio/")
                            for unit in job["units"]))
        self.assertEqual(job["schemaVersion"], "sermon-target-language-speech-job-v2")
        self.assertEqual(job["inputs"]["speakerRegistry"]["jsonSha256"], interpretation.json_sha256(self.registry))
        self.assertEqual(job["inputs"]["targetLanguagePolicy"]["jsonSha256"], interpretation.json_sha256(self.policy))
        self.assertEqual(job["inputs"]["humanReviewReceipt"]["jsonSha256"], interpretation.json_sha256(self.human_review_receipt))
        self.assertEqual(self.validate_schema("sermon-target-language-speech-job-v2.schema.json", job), [])

    def test_forged_verified_adapter_cannot_bypass_registry(self):
        self.adapter["capabilityStatus"] = "verified"
        write_json(self.adapter_path, self.adapter)
        with self.assertRaisesRegex(ValueError, "production authorization or human-reviewed"):
            subject.prepare_job(
                self.source_package_path, self.anchor_path, self.candidate_path,
                self.policy_path, self.human_review_receipt_path, self.adapter_path,
                self.registry_path, self.root / "forged-job",
            )
        self.assertFalse((self.root / "forged-job").exists())

    def test_synthetic_verified_registry_allows_preparation_but_not_release(self):
        job = self.make_verified_speech_job()
        self.assertEqual(job["status"], "prepared_for_target_language_speech")
        self.assertTrue(job["synthesisEligible"])
        self.assertFalse(job["releaseEligible"])
        self.assertEqual(self.validate_schema("sermon-target-language-speech-job-v2.schema.json", job), [])

    def make_verified_speech_job(self):
        speaker = self.registry["speakers"][0]
        speaker["authorization"]["purposes"].append("multilingual_dubbing")
        capability = next(row for row in speaker["localeCapabilities"] if row["targetLocale"] == "ko")
        capability["status"] = "human_reviewed"
        capability["reviewEvidence"] = ["synthetic-test-review-evidence"]
        self.adapter["authorizationPurpose"] = "multilingual_dubbing"
        self.adapter["capabilityStatus"] = "verified"
        self.adapter["registryJsonSha256"] = interpretation.json_sha256(self.registry)
        self.adapter["authorizationEvidenceSha256"] = interpretation.json_sha256(speaker["authorization"]["evidence"])
        self.adapter["capabilityEvidenceSha256"] = interpretation.json_sha256(capability["reviewEvidence"])
        write_json(self.adapter_path, self.adapter)
        write_json(self.registry_path, self.registry)
        job = subject.prepare_job(
            self.source_package_path, self.anchor_path, self.candidate_path,
            self.policy_path, self.human_review_receipt_path, self.adapter_path,
            self.registry_path, self.root / "verified-job",
        )
        return job

    def test_audio_unit_receipt_requires_full_decode_and_exact_job_binding(self):
        job = self.make_verified_speech_job()
        job_path = self.root / "verified-job/job.json"
        audio_path = job_path.parent / job["units"][0]["outputRelativePath"]
        audio_path.parent.mkdir(parents=True)
        with wave.open(str(audio_path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\0" * 32000)
        receipt = audio_integrity.build_receipt(job_path, 0, audio_path)
        self.assertEqual(receipt["fullDecode"], "pass")
        self.assertEqual(receipt["sampleRate"], 16000)
        self.assertEqual(receipt["channels"], 1)
        self.assertEqual(receipt["targetLocale"], "ko")
        self.assertEqual(self.validate_schema("sermon-target-language-audio-unit-receipt-v1.schema.json", receipt), [])
        audio_integrity.validate_receipt(job_path, 0, audio_path, receipt)
        receipt_path = self.root / "unit-receipt.json"
        script = Path(__file__).parents[1] / "scripts/validate_target_language_audio_unit.py"
        subprocess.run([sys.executable, str(script), "--job", str(job_path),
                        "--unit-index", "0", "--audio", str(audio_path), "--out", str(receipt_path)],
                       check=True, capture_output=True, text=True)
        saved = json.loads(receipt_path.read_text(encoding="utf-8"))
        audio_integrity.validate_receipt(job_path, 0, audio_path, saved)
        wrong_metadata = copy.deepcopy(receipt)
        wrong_metadata["sampleRate"] = 48000
        with self.assertRaisesRegex(ValueError, "metadata differs"):
            audio_integrity.validate_receipt(job_path, 0, audio_path, wrong_metadata)
        audio_path.write_bytes(audio_path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "another job, text, path, or audio"):
            audio_integrity.validate_receipt(job_path, 0, audio_path, receipt)
        with self.assertRaisesRegex(ValueError, "Audio path differs"):
            audio_integrity.build_receipt(job_path, 0, self.root / "wrong.wav")
        audio_path.write_bytes(b"RIFFbad")
        with self.assertRaises(subprocess.CalledProcessError):
            audio_integrity.build_receipt(job_path, 0, audio_path)

    def test_audio_unit_gate_rejects_pending_job_and_changed_text(self):
        pending = subject.prepare_job(
            self.source_package_path, self.anchor_path, self.candidate_path,
            self.policy_path, self.human_review_receipt_path, self.adapter_path,
            self.registry_path, self.root / "pending-job",
        )
        pending_path = self.root / "pending-job/job.json"
        audio_path = pending_path.parent / pending["units"][0]["outputRelativePath"]
        with self.assertRaisesRegex(ValueError, "not eligible"):
            audio_integrity.build_receipt(pending_path, 0, audio_path)
        job = self.make_verified_speech_job()
        job_path = self.root / "verified-job/job.json"
        job["units"][0]["text"] = "Altered target text"
        write_json(job_path, job)
        with self.assertRaisesRegex(ValueError, "approved text"):
            audio_integrity.build_receipt(job_path, 0, job_path.parent / job["units"][0]["outputRelativePath"])

    def test_pending_korean_policy_or_wrong_policy_hash_blocks_layer_three(self):
        pending = json.loads((Path(__file__).parents[1] / "config/target-language-policies/ko.json").read_text(encoding="utf-8"))
        pending_candidate = copy.deepcopy(self.candidate)
        pending_candidate["translationPolicySha256"] = policy_tools.validate_policy(pending)["translationPolicySha256"]
        with self.assertRaisesRegex(ValueError, "unresolved scripture"):
            subject.validate_policy_binding(pending_candidate, pending)
        changed = copy.deepcopy(self.candidate)
        changed["translationPolicySha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "another Target-Language Policy"):
            subject.validate_policy_binding(changed, self.policy)
        changed = copy.deepcopy(self.candidate)
        changed["groups"][0]["languageReview"]["policySha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "language review belongs to another policy"):
            subject.validate_policy_binding(changed, self.policy)

    def test_policy_binding_requires_generation_and_all_language_checks(self):
        changed = copy.deepcopy(self.candidate)
        changed["generation"]["reviewer"]["promptVersion"] = "stale-review-prompt"
        with self.assertRaisesRegex(ValueError, "reviewer generation differs from policy"):
            subject.validate_policy_binding(changed, self.policy)
        changed = copy.deepcopy(self.candidate)
        changed["groups"][0]["languageReview"]["checks"].pop()
        with self.assertRaisesRegex(ValueError, "does not cover every required policy check"):
            subject.validate_policy_binding(changed, self.policy)
        changed = copy.deepcopy(self.candidate)
        changed["groups"][0]["languageReview"]["checks"][0]["checkId"] = changed["groups"][0]["languageReview"]["checks"][1]["checkId"]
        with self.assertRaisesRegex(ValueError, "does not cover every required policy check"):
            subject.validate_policy_binding(changed, self.policy)

    def test_registry_or_checkpoint_drift_fails_before_job_output(self):
        wrong = copy.deepcopy(self.adapter)
        wrong["conditioningSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "model, checkpoint, or language"):
            subject.validate_adapter(wrong, "ko", self.registry)
        wrong = copy.deepcopy(self.adapter)
        wrong["modelRevision"] = "stale-revision"
        with self.assertRaisesRegex(ValueError, "model, checkpoint, or language"):
            subject.validate_adapter(wrong, "ko", self.registry)
        wrong = copy.deepcopy(self.adapter)
        wrong["registryJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "another Speaker Voice Registry"):
            subject.validate_adapter(wrong, "ko", self.registry)
        wrong = copy.deepcopy(self.adapter)
        wrong["authorizationEvidenceSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "authorization evidence changed"):
            subject.validate_adapter(wrong, "ko", self.registry)

    def test_human_review_receipt_rejects_stale_or_incomplete_approval(self):
        stale = copy.deepcopy(self.human_review_receipt)
        stale["candidateJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "does not bind"):
            subject.validate_human_review_receipt(self.source_package, self.anchor, self.candidate, stale)
        missing = copy.deepcopy(self.human_review_receipt)
        missing["groupReviews"].pop()
        with self.assertRaisesRegex(ValueError, "missing, rejected, or mismatched"):
            subject.validate_human_review_receipt(self.source_package, self.anchor, self.candidate, missing)
        rejected = copy.deepcopy(self.human_review_receipt)
        rejected["groupReviews"][0]["decision"] = "rejected"
        with self.assertRaisesRegex(ValueError, "missing, rejected, or mismatched"):
            subject.validate_human_review_receipt(self.source_package, self.anchor, self.candidate, rejected)
        altered_candidate = copy.deepcopy(self.candidate)
        altered_candidate["groups"][0]["targetText"] = "new text"
        with self.assertRaisesRegex(ValueError, "does not bind"):
            subject.validate_human_review_receipt(
                self.source_package, self.anchor, altered_candidate, self.human_review_receipt,
            )

    def machine_candidate(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["status"] = "machine_review_pass_human_review_pending"
        candidate["humanReview"] = {
            "translation": "pending", "reviewer": None,
            "reviewedAt": None, "reviewedGroupIds": [],
        }
        return candidate

    def test_review_worksheet_admits_new_candidate_and_receipt(self):
        machine = self.machine_candidate()
        worksheet = human_review.build_worksheet(self.source_package, self.anchor, machine, self.policy)
        self.assertEqual(worksheet["groupReviews"][0]["sourceUnits"][0]["english"], "Do not be afraid.")
        self.assertEqual(worksheet["groupReviews"][0]["coverage"], machine["groups"][0]["coverage"])
        worksheet["decision"] = "approved"
        worksheet["reviewer"] = "Korean reviewer"
        worksheet["reviewedAt"] = "2026-09-20T12:00:00Z"
        for row in worksheet["groupReviews"]:
            row["decision"] = "approved"
            row["evidence"] = "Reviewed English meaning and Korean text."
        approved, receipt = human_review.approve_worksheet(
            self.source_package, self.anchor, machine, self.policy, worksheet,
        )
        self.assertEqual(approved["status"], "human_translation_approved")
        self.assertEqual(receipt["candidateJsonSha256"], interpretation.json_sha256(approved))
        self.assertEqual(self.validate_schema("sermon-target-language-candidate-v2.schema.json", approved), [])
        self.assertEqual(self.validate_schema("sermon-target-language-human-review-receipt-v1.schema.json", receipt), [])
        write_json(self.candidate_path, approved)
        write_json(self.human_review_receipt_path, receipt)
        job = subject.prepare_job(
            self.source_package_path, self.anchor_path, self.candidate_path,
            self.policy_path, self.human_review_receipt_path, self.adapter_path,
            self.registry_path, self.root / "reviewed-job",
        )
        self.assertFalse(job["synthesisEligible"])

    def test_review_worksheet_rejects_stale_or_partial_review(self):
        machine = self.machine_candidate()
        base = human_review.build_worksheet(self.source_package, self.anchor, machine, self.policy)
        base["decision"] = "approved"
        base["reviewer"] = "Korean reviewer"
        base["reviewedAt"] = "2026-09-20T12:00:00Z"
        for row in base["groupReviews"]:
            row["decision"] = "approved"
            row["evidence"] = "Reviewed."
        stale = copy.deepcopy(base)
        stale["candidateJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "identity changed"):
            human_review.approve_worksheet(self.source_package, self.anchor, machine, self.policy, stale)
        partial = copy.deepcopy(base)
        partial["groupReviews"][0]["decision"] = "pending"
        with self.assertRaisesRegex(ValueError, "unapproved or unexplained"):
            human_review.approve_worksheet(self.source_package, self.anchor, machine, self.policy, partial)
        altered = copy.deepcopy(base)
        altered["groupReviews"][0]["targetText"] = "Changed after review."
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            human_review.approve_worksheet(self.source_package, self.anchor, machine, self.policy, altered)

    def test_human_review_cli_writes_immutable_pair(self):
        write_json(self.candidate_path, self.machine_candidate())
        script = Path(__file__).parents[1] / "scripts/review_target_language_candidate.py"
        common = [
            "--english-source-package", str(self.source_package_path),
            "--anchor", str(self.anchor_path),
            "--candidate", str(self.candidate_path),
            "--policy", str(self.policy_path),
        ]
        worksheet_path = self.root / "human-worksheet.json"
        subprocess.run([sys.executable, str(script), "prepare", *common,
                        "--out", str(worksheet_path)], check=True, capture_output=True, text=True)
        worksheet = json.loads(worksheet_path.read_text(encoding="utf-8"))
        worksheet["decision"] = "approved"
        worksheet["reviewer"] = "Korean reviewer"
        worksheet["reviewedAt"] = "2026-09-20T12:00:00Z"
        for row in worksheet["groupReviews"]:
            row["decision"] = "approved"
            row["evidence"] = "Reviewed against source."
        write_json(worksheet_path, worksheet)
        out = self.root / "human-approved"
        subprocess.run([sys.executable, str(script), "approve", *common,
                        "--worksheet", str(worksheet_path), "--out", str(out)],
                       check=True, capture_output=True, text=True)
        approved = json.loads((out / "candidate.approved.json").read_text(encoding="utf-8"))
        receipt = json.loads((out / "human-review-receipt.json").read_text(encoding="utf-8"))
        subject.validate_human_review_receipt(self.source_package, self.anchor, approved, receipt)
        repeated = subprocess.run([sys.executable, str(script), "approve", *common,
                                   "--worksheet", str(worksheet_path), "--out", str(out)],
                                  capture_output=True, text=True)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("immutable", repeated.stderr)

    def test_layer_three_rejects_pending_human_translation_review(self):
        self.candidate["status"] = "machine_review_pass_human_review_pending"
        self.candidate["humanReview"] = {
            "translation": "pending", "reviewer": None, "reviewedAt": None, "reviewedGroupIds": [],
        }
        write_json(self.candidate_path, self.candidate)
        with self.assertRaisesRegex(ValueError, "Human translation approval"):
            subject.prepare_job(
                self.source_package_path, self.anchor_path, self.candidate_path,
                self.policy_path, self.human_review_receipt_path, self.adapter_path,
                self.registry_path, self.root / "blocked-job",
            )

    def test_candidate_rejects_locale_mismatch_and_cross_language_adapter(self):
        self.candidate["targetLocale"] = "en"
        with self.assertRaisesRegex(ValueError, "Invalid target locale"):
            subject.validate_target_candidate(self.source_package, self.anchor, self.candidate)
        changed = copy.deepcopy(self.adapter)
        changed["targetLocale"] = "zh-Hans"
        with self.assertRaisesRegex(ValueError, "locale differs"):
            subject.validate_adapter(changed, "ko", self.registry)

    def test_candidate_rejects_missing_or_reordered_source_coverage(self):
        self.candidate["groups"].reverse()
        self.candidate["modelReview"]["reviewedGroupIds"].reverse()
        with self.assertRaisesRegex(ValueError, "every source unit exactly once and in order"):
            subject.validate_target_candidate(self.source_package, self.anchor, self.candidate)


if __name__ == "__main__":
    unittest.main()

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from scripts import prepare_target_language_speech_job as subject
from scripts import review_target_language_candidate as human_review
from scripts import validate_target_language_audio_unit as audio_integrity
from scripts import sermon_sentence_interpretation as interpretation
from scripts import target_language_policy as policy_tools
from scripts import four_layer_progress as progress
from scripts import sermon_accounting as accounting


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
        policy_draft["schemaVersion"] = policy_tools.POLICY_V2
        policy_draft["sourceScope"] = {
            "englishSourcePackageJsonSha256": interpretation.json_sha256(self.source_package),
            "anchorManifestSha256": interpretation.json_sha256(self.anchor),
            "usedSeriesNames": [], "usedProperNames": [], "termApprovalEvidence": [],
        }
        for term in policy_draft["terminology"]["seriesNames"] + policy_draft["terminology"]["properNames"]:
            term["target"] = "synthetic-test-term"
            term["reviewStatus"] = "human_reviewed"
        policy_draft["scripture"].update({
            "editionId": "synthetic-test-edition", "citationUseStatus": "project_source_reviewed",
            "quoteCheckPolicy": "references_only",
        })
        policy_draft["languageReview"]["implementationStatus"] = "verified"
        policy_draft["languageReview"]["pluginImplementationSha256"] = "a" * 64
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

    def test_speech_job_cli_records_timing_without_promoting_poc_capability(self):
        ledger = self.root / "four-layer-progress.json"
        progress.save(ledger, progress.new_ledger("test-page", ["ko"]))
        output = self.root / "timed-speech-job"
        argv = ["speech-job", "--english-source-package", str(self.source_package_path),
                "--anchor", str(self.anchor_path), "--candidate", str(self.candidate_path),
                "--policy", str(self.policy_path),
                "--human-review-receipt", str(self.human_review_receipt_path),
                "--adapter", str(self.adapter_path), "--speaker-registry", str(self.registry_path),
                "--progress-ledger", str(ledger), "--out", str(output)]
        with patch.object(sys, "argv", argv):
            subject.main()
        self.assertFalse(json.loads((output / "job.json").read_text())["synthesisEligible"])
        events, damaged = accounting.read_events(self.root / "accounting")
        self.assertFalse(damaged)
        stage = next(event for event in events if event["event"] == "stage_finished"
                     and event["stage"] == "four_layer.L3-01:ko")
        self.assertEqual(stage["status"], "completed")
        workload = next(event for event in events if event["event"] == "workload"
                        and event["stage"] == "four_layer.L3-01:ko")
        self.assertEqual(workload["metrics"]["speechUnits"], 2)
        self.assertEqual(progress.load(ledger)["steps"]["L3-01@ko"]["status"], "pending")

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

    def test_verified_override_requires_registered_provider(self):
        registry = copy.deepcopy(self.registry)
        speaker = registry["speakers"][0]
        speaker["authorization"]["purposes"].append("multilingual_dubbing")
        capability = next(row for row in speaker["localeCapabilities"] if row["targetLocale"] == "ko")
        reference = next(row for row in speaker["localeCapabilities"] if row["targetLocale"] == "vi")
        capability["adapterOverride"] = copy.deepcopy(reference["adapterOverride"])
        capability["adapterOverride"]["provider"] = "synthetic-provider"
        capability["status"] = "human_reviewed"
        capability["reviewEvidence"] = ["synthetic-test-review-evidence"]
        adapter = copy.deepcopy(self.adapter)
        adapter["adapterId"] = capability["adapterOverride"]["adapter"]
        adapter["provider"] = capability["adapterOverride"]["provider"]
        adapter["model"] = capability["adapterOverride"]["model"]
        adapter["modelRevision"] = capability["adapterOverride"]["revision"]
        adapter["conditioningRef"] = capability["adapterOverride"]["conditioningRef"]
        adapter["conditioningSha256"] = adapter["conditioningRef"].rsplit("/", 1)[-1]
        adapter["registryJsonSha256"] = interpretation.json_sha256(registry)
        adapter["capabilityEvidenceSha256"] = interpretation.json_sha256(capability["reviewEvidence"])
        adapter["authorizationPurpose"] = "multilingual_dubbing"
        adapter["capabilityStatus"] = "verified"
        subject.validate_adapter(adapter, "ko", registry)
        wrong = copy.deepcopy(adapter)
        wrong["provider"] = "wrong-provider"
        with self.assertRaisesRegex(ValueError, "provider differs from registry override"):
            subject.validate_adapter(wrong, "ko", registry)
        missing = copy.deepcopy(registry)
        next(row for row in missing["speakers"][0]["localeCapabilities"]
             if row["targetLocale"] == "ko")["adapterOverride"].pop("provider")
        adapter["registryJsonSha256"] = interpretation.json_sha256(missing)
        with self.assertRaisesRegex(ValueError, "production authorization or human-reviewed"):
            subject.validate_adapter(adapter, "ko", missing)

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

    def test_batch_attestation_expands_only_a_complete_pending_worksheet(self):
        machine = self.machine_candidate()
        pending = human_review.build_worksheet(self.source_package, self.anchor, machine, self.policy)
        filled = human_review.apply_batch_approval(
            pending, reviewer="Korean reviewer", reviewed_at="2026-09-20T12:00:00Z",
            evidence="Reviewed every group against the English source and scripture policy.",
        )
        self.assertEqual(pending["decision"], "pending")
        self.assertTrue(all(row["decision"] == "approved" for row in filled["groupReviews"]))
        approved, receipt = human_review.approve_worksheet(
            self.source_package, self.anchor, machine, self.policy, filled,
        )
        subject.validate_human_review_receipt(self.source_package, self.anchor, approved, receipt)
        self.assertEqual(len(receipt["groupReviews"]), len(machine["groups"]))
        for change in ("decision", "evidence"):
            altered = copy.deepcopy(pending)
            altered["groupReviews"][0][change] = "rejected" if change == "decision" else "prior note"
            with self.assertRaisesRegex(ValueError, "cannot override"):
                human_review.apply_batch_approval(
                    altered, reviewer="Korean reviewer", reviewed_at="2026-09-20T12:00:00Z",
                    evidence="Reviewed every group against the English source.",
                )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            human_review.apply_batch_approval(
                pending, reviewer="Korean reviewer", reviewed_at="2026-09-20T12:00:00",
                evidence="Reviewed every group against the English source.",
            )
        stale = copy.deepcopy(pending)
        stale["candidateJsonSha256"] = "0" * 64
        filled_stale = human_review.apply_batch_approval(
            stale, reviewer="Korean reviewer", reviewed_at="2026-09-20T12:00:00Z",
            evidence="Reviewed every group against the English source.",
        )
        with self.assertRaisesRegex(ValueError, "identity changed"):
            human_review.approve_worksheet(
                self.source_package, self.anchor, machine, self.policy, filled_stale,
            )

    def test_batch_review_cli_writes_the_same_bound_receipt(self):
        write_json(self.candidate_path, self.machine_candidate())
        script = Path(__file__).parents[1] / "scripts/review_target_language_candidate.py"
        common = [
            "--english-source-package", str(self.source_package_path),
            "--anchor", str(self.anchor_path),
            "--candidate", str(self.candidate_path),
            "--policy", str(self.policy_path),
        ]
        worksheet_path = self.root / "batch-worksheet.json"
        subprocess.run([sys.executable, str(script), "prepare", *common,
                        "--out", str(worksheet_path)], check=True, capture_output=True, text=True)
        output = self.root / "batch-approved"
        subprocess.run([sys.executable, str(script), "approve-batch", *common,
                        "--worksheet", str(worksheet_path), "--reviewer", "Korean reviewer",
                        "--reviewed-at", "2026-09-20T12:00:00Z",
                        "--full-review-evidence", "Reviewed every source and target group.",
                        "--out", str(output)], check=True, capture_output=True, text=True)
        approved = json.loads((output / "candidate.approved.json").read_text(encoding="utf-8"))
        receipt = json.loads((output / "human-review-receipt.json").read_text(encoding="utf-8"))
        subject.validate_human_review_receipt(self.source_package, self.anchor, approved, receipt)
        self.assertEqual([row["translationGroupId"] for row in receipt["groupReviews"]],
                         [row["translationGroupId"] for row in approved["groups"]])

    def test_group_receipts_keep_other_blocks_reviewed_across_candidate_revision(self):
        anchor = copy.deepcopy(self.anchor)
        anchor["sourceUnits"][1]["sourceUnitId"] = "block-01-u001"
        source = copy.deepcopy(self.source_package)
        source["anchors"]["artifact"]["jsonSha256"] = interpretation.json_sha256(anchor)
        policy_draft = copy.deepcopy(self.policy)
        policy_draft.pop("componentSha256")
        policy_draft["sourceScope"]["englishSourcePackageJsonSha256"] = interpretation.json_sha256(source)
        policy_draft["sourceScope"]["anchorManifestSha256"] = interpretation.json_sha256(anchor)
        policy = policy_tools.freeze_policy(policy_draft)
        first = self.machine_candidate()
        first["englishSourcePackageJsonSha256"] = interpretation.json_sha256(source)
        first["anchorManifestSha256"] = interpretation.json_sha256(anchor)
        first["translationPolicySha256"] = policy_tools.validate_policy(policy)["translationPolicySha256"]
        first["groups"][1] = self.group("g2", "block-01-u001", "내가 당신과 함께 있습니다.")
        first["groups"][1]["languageReview"] = copy.deepcopy(first["groups"][0]["languageReview"])
        make = lambda candidate, group_id: human_review.record_group_review(
            source, anchor, candidate, policy, group_id=group_id, decision="approved",
            evidence="Reviewed against the source and local context.",
            reviewer="Korean reviewer", reviewed_at="2026-09-20T12:00:00Z",
            context_scope="connected_blocks",
            context_evidence="Reviewed adjacent context; no cross-block reference or quotation.",
        )
        g1, old_g2 = make(first, "g1"), make(first, "g2")
        self.assertEqual(g1["contextGroupIds"], ["g1"])
        with self.assertRaisesRegex(ValueError, "explicit reviewed context evidence"):
            human_review.record_group_review(
                source, anchor, first, policy, group_id="g1", decision="approved",
                evidence="Reviewed.", reviewer="Korean reviewer",
                reviewed_at="2026-09-20T12:00:00Z", context_scope="connected_blocks",
            )
        revised = copy.deepcopy(first)
        revised["groups"][1]["targetText"] = "저는 당신과 함께 있습니다."
        revised["groups"][1]["targetUtterances"] = [revised["groups"][1]["targetText"]]
        revised["groups"][1]["coverage"][0]["targetText"] = revised["groups"][1]["targetText"]
        with self.assertRaisesRegex(ValueError, "identity or context changed: g2"):
            human_review.approve_group_receipts(source, anchor, revised, policy, [g1, old_g2])
        new_g2 = make(revised, "g2")
        approved, receipt, manifest = human_review.approve_group_receipts(
            source, anchor, revised, policy, [g1, new_g2],
        )
        subject.validate_human_review_receipt(source, anchor, approved, receipt)
        self.assertNotEqual(g1["originCandidateJsonSha256"], interpretation.json_sha256(revised))
        self.assertEqual([row["translationGroupId"] for row in manifest["groupReceipts"]],
                         ["g1", "g2"])

    def test_group_review_keeps_same_block_and_missing_group_fail_closed(self):
        machine = self.machine_candidate()
        make = lambda candidate, group_id, decision="approved": human_review.record_group_review(
            self.source_package, self.anchor, candidate, self.policy,
            group_id=group_id, decision=decision, evidence="Reviewed source and context.",
            reviewer="Korean reviewer", reviewed_at="2026-09-20T12:00:00Z",
        )
        g1, g2 = make(machine, "g1"), make(machine, "g2")
        with self.assertRaisesRegex(ValueError, "required per group"):
            human_review.approve_group_receipts(
                self.source_package, self.anchor, machine, self.policy, [g1],
            )
        rejected = make(machine, "g2", "rejected")
        with self.assertRaisesRegex(ValueError, "not approved"):
            human_review.approve_group_receipts(
                self.source_package, self.anchor, machine, self.policy, [g1, rejected],
            )
        revised = copy.deepcopy(machine)
        revised["groups"][1]["semanticReview"]["evidence"] = "Fresh model check."
        new_g2 = make(revised, "g2")
        with self.assertRaisesRegex(ValueError, "identity or context changed: g1"):
            human_review.approve_group_receipts(
                self.source_package, self.anchor, revised, self.policy, [g1, new_g2],
            )
        approved, receipt, _ = human_review.approve_group_receipts(
            self.source_package, self.anchor, machine, self.policy, [g1, g2],
        )
        subject.validate_human_review_receipt(self.source_package, self.anchor, approved, receipt)

    def test_group_review_cli_aggregates_only_complete_receipts(self):
        write_json(self.candidate_path, self.machine_candidate())
        script = Path(__file__).parents[1] / "scripts/review_target_language_candidate.py"
        common = [
            "--english-source-package", str(self.source_package_path),
            "--anchor", str(self.anchor_path),
            "--candidate", str(self.candidate_path),
            "--policy", str(self.policy_path),
        ]
        receipts = []
        for group_id in ("g1", "g2"):
            path = self.root / f"{group_id}-review.json"
            subprocess.run([sys.executable, str(script), "record-group", *common,
                            "--group-id", group_id, "--decision", "approved",
                            "--evidence", "Reviewed source and block context.",
                            "--reviewer", "Korean reviewer",
                            "--reviewed-at", "2026-09-20T12:00:00Z", "--out", str(path)],
                           check=True, capture_output=True, text=True)
            receipts.append(path)
        out = self.root / "assembled-group-review"
        subprocess.run([sys.executable, str(script), "approve-groups", *common,
                        *(part for path in receipts for part in ("--group-receipt", str(path))),
                        "--out", str(out)], check=True, capture_output=True, text=True)
        approved = json.loads((out / "candidate.approved.json").read_text())
        receipt = json.loads((out / "human-review-receipt.json").read_text())
        subject.validate_human_review_receipt(self.source_package, self.anchor, approved, receipt)
        self.assertTrue((out / "group-review-aggregation.json").is_file())

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

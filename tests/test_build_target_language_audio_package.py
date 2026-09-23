import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest import mock

from scripts import build_target_language_audio_package as subject
from scripts import prepare_clip_voice_authorization as clip_voice
from scripts import prepare_clip_voice_capability as clip_capability
from scripts import clip_timeline_map as timeline_map
from scripts import validate_target_language_audio_unit as unit_integrity
from scripts import prepare_target_language_speech_job as speech
from scripts import sermon_sentence_interpretation as interpretation
from tests import test_prepare_target_language_speech_job as base_tests


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def wav(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * round(seconds * 16000))


class AudioPackageTests(unittest.TestCase):
    def setUp(self):
        # Exercise the current v2 producer, policy, human receipt and registry
        # instead of fabricating a job that only resembles its old v1 shape.
        fixture = base_tests.TargetLanguageSpeechJobTests(
            "test_synthetic_verified_registry_allows_preparation_but_not_release")
        fixture.setUp()
        self.addCleanup(fixture.temporary.cleanup)
        self.root = fixture.root
        self.anchor = fixture.anchor
        self.anchor["sourceUnits"][0].update(start=0.0, end=0.1)
        self.anchor["sourceUnits"][1].update(start=0.3, end=0.7)
        self.clip_media_path = self.root / "synthetic-clip.wav"
        wav(self.clip_media_path, 0.7)
        clip_hash = subject.file_sha256(self.clip_media_path)
        approval_path = self.root / "synthetic-window-approval.json"
        window_approval = {
            "schemaVersion": "sermon-clip-window-approval-v1",
            "status": "approved", "humanApproval": True,
            "sourceMediaSha256": clip_hash,
            "startTime": "00:00:00", "endTime": "00:00:00.700",
            "originalRecordingWindow": "10:00.00-10:00.70",
        }
        write_json(approval_path, window_approval)
        self.source = fixture.source_package
        self.source["anchors"]["artifact"]["jsonSha256"] = subject.json_sha256(self.anchor)
        self.source["anchors"]["issueCount"] = 0
        self.source["source"] = {
            "media": {"sha256": clip_hash, "durationSeconds": 0.7},
            "approvedWindow": {"status": "approved", "humanApproval": True,
                               "startSeconds": 0.0, "endSeconds": 0.7,
                               "evidence": {"path": str(approval_path.resolve()),
                                            "sha256": subject.file_sha256(approval_path),
                                            "jsonSha256": subject.json_sha256(window_approval)}},
        }
        self.source["review"] = {"humanApproval": True, "checks": {
            "sourceIdentity": "approved", "transcriptCompleteness": "approved",
            "wordAlignment": "approved", "sentenceAndPauseBoundaries": "approved"}}
        self.candidate = fixture.candidate
        self.candidate["englishSourcePackageJsonSha256"] = subject.json_sha256(self.source)
        self.candidate["anchorManifestSha256"] = subject.json_sha256(self.anchor)
        # The fixture's v2 policy is bound to its original source. Re-freeze it
        # against this test's clip instead of weakening the production gate.
        policy_draft = copy.deepcopy(fixture.policy)
        policy_draft.pop("componentSha256")
        policy_draft["sourceScope"]["englishSourcePackageJsonSha256"] = subject.json_sha256(self.source)
        policy_draft["sourceScope"]["anchorManifestSha256"] = subject.json_sha256(self.anchor)
        fixture.policy = base_tests.policy_tools.freeze_policy(policy_draft)
        self.candidate["translationPolicySha256"] = base_tests.policy_tools.validate_policy(
            fixture.policy)["translationPolicySha256"]
        self.human_receipt = fixture.human_review_receipt
        self.human_receipt["englishSourcePackageJsonSha256"] = subject.json_sha256(self.source)
        self.human_receipt["anchorManifestJsonSha256"] = subject.json_sha256(self.anchor)
        self.human_receipt["translationPolicySha256"] = self.candidate["translationPolicySha256"]
        self.human_receipt["candidateJsonSha256"] = subject.json_sha256(self.candidate)
        write_json(fixture.source_package_path, self.source)
        write_json(fixture.anchor_path, self.anchor)
        write_json(fixture.candidate_path, self.candidate)
        write_json(fixture.policy_path, fixture.policy)
        write_json(fixture.human_review_receipt_path, self.human_receipt)
        self.job = fixture.make_verified_speech_job()
        self.adapter = fixture.adapter
        self.registry = fixture.registry
        self.policy = fixture.policy
        self.paths = {
            "source": fixture.source_package_path,
            "anchor": fixture.anchor_path,
            "candidate": fixture.candidate_path,
            "job": self.root / "verified-job/job.json",
            "adapter": fixture.adapter_path,
            "policy": fixture.policy_path,
            "human_receipt": fixture.human_review_receipt_path,
            "registry": fixture.registry_path,
        }
        self.asset_root = self.root / "evidence"
        self.asset_root.mkdir()
        self.voice = {
            "targetLocale": "ko", "provider": self.adapter["provider"],
            "model": self.adapter["model"], "modelRevision": self.adapter["modelRevision"],
            "voice": self.adapter["voice"], "speakerId": self.adapter["speakerId"],
            "checkpointSha256": self.adapter["conditioningSha256"],
            "targetLocaleCapability": "reviewed", "authorizationStatus": "authorized",
        }
        authorization_rel = "review/voice-authorization.json"
        self.authorization = {
            "schemaVersion": "sermon-clip-user-rights-attestation-v1",
            "scope": "fixture-clip-dev-app-and-audio_only",
            "englishSourcePackageJsonSha256": subject.json_sha256(self.source),
            "targetLocales": ["ko"], "speakerId": self.voice["speakerId"],
            "voiceCheckpointSha256": self.voice["checkpointSha256"],
            "permissionClaimed": True, "userStatement": "Synthetic fixture owner approval.",
            "attestedAt": "2026-09-23T10:00:00Z",
        }
        write_json(self.asset_root / authorization_rel, self.authorization)
        # Production purpose stays absent from the global registry. The new
        # job is verified only for this source, candidate and locale.
        self.registry["speakers"][0]["authorization"]["purposes"].remove("multilingual_dubbing")
        ko_capability = next(row for row in self.registry["speakers"][0]["localeCapabilities"]
                             if row["targetLocale"] == "ko")
        ko_capability["status"] = "unverified_poc"
        ko_capability["reviewEvidence"] = []
        self.adapter["authorizationPurpose"] = "multilingual_voice_demo"
        self.adapter["registryJsonSha256"] = subject.json_sha256(self.registry)
        self.adapter["capabilityEvidenceSha256"] = subject.json_sha256([])
        write_json(self.paths["registry"], self.registry)
        write_json(self.paths["adapter"], self.adapter)
        self.paths["clip_voice_authorization"] = self.root / "clip-voice-authorization.json"
        self.clip_auth = clip_voice.prepare(
            self.paths["source"], self.paths["candidate"], self.paths["adapter"],
            self.asset_root / authorization_rel, self.paths["clip_voice_authorization"])
        short_audio = self.root / "artifacts/synthetic/ko.mp3"
        long_audio = self.root / "artifacts/synthetic/ko.wav"
        short_audio.parent.mkdir(parents=True)
        short_audio.write_bytes(b"synthetic-short-voice-probe")
        long_audio.write_bytes(b"synthetic-long-voice-probe")
        short_hash = subject.file_sha256(short_audio)
        long_hash = subject.file_sha256(long_audio)
        short_approval_path = self.root / "short-demo-approval.json"
        long_approval_path = self.root / "long-probe-approval.json"
        long_manifest_path = self.root / "long-probe-manifest.json"
        probe_manifest = {"scriptJsonSha256": "b" * 64,
                          "fullDecodeCoverage": 1, "tracks": [{
            "targetLocale": "ko", "speakerId": self.voice["speakerId"],
            "checkpointSha256": self.voice["checkpointSha256"],
            "audioSha256": long_hash, "textSha256": "a" * 64,
            "fullDecode": "pass",
        }]}
        write_json(long_manifest_path, probe_manifest)
        self.short_approval = {
            "schemaVersion": "sermon-voice-short-demo-human-review-v1",
            "speakerId": self.voice["speakerId"],
            "checkpointSha256": self.voice["checkpointSha256"],
            "reviewer": "fixture owner", "reviewedAt": "2026-09-23T10:00:00Z",
            "tracks": [{"targetLocale": "ko", "mp3Path": "artifacts/synthetic/ko.mp3",
                        "mp3Sha256": short_hash, "decision": "approved_short_demo",
                        "reviewItems": ["pronunciation", "naturalness", "completeness",
                                        "voice_similarity"]}],
        }
        self.long_approval = {
            "schemaVersion": "sermon-voice-long-probe-human-review-v1",
            "englishSourcePackageJsonSha256": subject.json_sha256(self.source),
            "speakerId": self.voice["speakerId"],
            "checkpointSha256": self.voice["checkpointSha256"],
            "reviewer": "fixture owner", "reviewedAt": "2026-09-23T10:00:00Z",
            "manifestJsonSha256": subject.json_sha256(probe_manifest),
            "scriptJsonSha256": probe_manifest["scriptJsonSha256"],
            "tracks": [{"targetLocale": "ko", "audioPath": "artifacts/synthetic/ko.wav",
                        "audioSha256": long_hash, "expectedTextSha256": "a" * 64,
                        "decision": "approved_long_probe"}],
        }
        write_json(short_approval_path, self.short_approval)
        write_json(long_approval_path, self.long_approval)
        self.paths["clip_voice_capability"] = self.root / "clip-voice-capability.json"
        self.clip_cap = clip_capability.prepare(
            self.paths["source"], self.paths["adapter"], short_approval_path, short_audio,
            long_approval_path, long_manifest_path, long_audio,
            self.paths["clip_voice_capability"])
        self.paths["clip_timeline_map"] = self.root / "clip-timeline-map.json"
        self.clip_timeline = timeline_map.prepare(
            self.paths["source"], self.paths["anchor"], self.clip_media_path, 0.0,
            self.paths["clip_timeline_map"])
        self.job = speech.prepare_job(
            self.paths["source"], self.paths["anchor"], self.paths["candidate"],
            self.paths["policy"], self.paths["human_receipt"], self.paths["adapter"],
            self.paths["registry"], self.root / "clip-job",
            clip_voice_authorization_path=self.paths["clip_voice_authorization"],
            clip_voice_capability_path=self.paths["clip_voice_capability"],
            clip_timeline_map_path=self.paths["clip_timeline_map"],
        )
        self.paths["job"] = self.root / "clip-job/job.json"
        self.asset_root = self.root / "clip-job"
        write_json(self.asset_root / authorization_rel, self.authorization)
        self.manifest = {
            "schemaVersion": subject.RENDER_SCHEMA, "targetLocale": "ko",
            "englishSourcePackageJsonSha256": subject.json_sha256(self.source),
            "targetLanguageCandidateJsonSha256": subject.json_sha256(self.candidate),
            "targetLanguageSpeechJobJsonSha256": subject.json_sha256(self.job),
            "clipTimelineMapJsonSha256": subject.json_sha256(self.clip_timeline),
            "voice": self.voice, "units": [], "machineScreening": {
                "status": "pass", "model": "fixture-asr", "coverage": 1.0},
        }
        self.manifest["voiceAuthorization"] = self.artifact(authorization_rel, json_artifact=True)
        for index, unit in enumerate(self.job["units"]):
            audio_rel = unit["outputRelativePath"]
            audio_path = self.asset_root / audio_rel
            wav(audio_path, 0.2)
            text_hash = hashlib.sha256(unit["text"].encode()).hexdigest()
            audio_hash = subject.file_sha256(audio_path)
            receipt = unit_integrity.build_receipt(self.paths["job"], index, audio_path)
            receipt_rel = f"receipts/unit-{index:04d}.json"
            receipt_path = self.asset_root / receipt_rel
            write_json(receipt_path, receipt)
            self.manifest["units"].append({
                "textGroupId": unit["translationGroupId"], "targetTextSha256": text_hash,
                "audio": self.artifact(audio_rel), "durationSeconds": 0.2,
                "receipt": self.artifact(receipt_rel, json_artifact=True),
            })
        track_rel = "languages/ko/audio/track.wav"
        wav(self.asset_root / track_rel, 0.7)
        self.manifest["track"] = self.artifact(track_rel)
        schedule_rel = "languages/ko/synchronization/schedule.json"
        self.schedule = {
            "targetLocale": "ko", "timingKind": "measured_target_audio",
            "status": "pass", "issues": [], "trackDurationSeconds": 0.7,
            "policy": {"reactionLagSeconds": 0.05, "interUtteranceGapSeconds": 0.02,
                       "maxEndLagSeconds": 0.3},
            "entries": [
                {"textGroupId": "g1", "sourceUnitIds": ["block-00-u001"],
                 "plannedStart": 0.05, "plannedEnd": 0.25},
                {"textGroupId": "g2", "sourceUnitIds": ["block-00-u002"],
                 "plannedStart": 0.35, "plannedEnd": 0.55},
            ],
        }
        write_json(self.asset_root / schedule_rel, self.schedule)
        self.manifest["schedule"] = self.artifact(schedule_rel, json_artifact=True)
        captions_rel = "languages/ko/synchronization/captions.json"
        self.captions = {"cues": [
            {"textGroupId": "g1", "text": "두려워하지 마십시오.", "start": 0.05, "end": 0.25},
            {"textGroupId": "g2", "text": self.candidate["groups"][1]["targetText"],
             "start": 0.35, "end": 0.55},
        ]}
        write_json(self.asset_root / captions_rel, self.captions)
        self.manifest["captions"] = self.artifact(captions_rel)
        screening_rel = "review/machine-screening.json"
        self.screening = {
            "schemaVersion": "sermon-target-language-audio-screening-v1",
            "targetLocale": "ko", "targetLanguageSpeechJobJsonSha256": subject.json_sha256(self.job),
            "trackSha256": self.manifest["track"]["sha256"],
            "status": "pass", "model": "fixture-asr", "modelRevision": "fixture-v1",
            "minSimilarity": 0.88, "coverage": 1.0,
            "reviewedGroupIds": ["g1", "g2"],
            "unitAudioSha256s": [row["audio"]["sha256"] for row in self.manifest["units"]],
            "results": [{
                "textGroupId": unit["translationGroupId"],
                "targetTextSha256": hashlib.sha256(unit["text"].encode()).hexdigest(),
                "audioSha256": self.manifest["units"][index]["audio"]["sha256"],
                "recognized": unit["text"], "similarity": 1.0,
                "differences": [], "status": "pass",
            } for index, unit in enumerate(self.job["units"])],
            "humanListeningStatus": "pending",
        }
        write_json(self.asset_root / screening_rel, self.screening)
        self.manifest["machineScreeningReceipt"] = self.artifact(screening_rel, json_artifact=True)
        self.manifest_path = self.root / "render-manifest.json"
        write_json(self.manifest_path, self.manifest)

    @staticmethod
    def group(group_id: str, source_id: str, text: str) -> dict:
        return {
            "translationGroupId": group_id, "sourceUnitIds": [source_id],
            "targetUtterances": [text], "targetText": text,
            "coverage": [{"sourceUnitId": source_id, "targetText": text}],
            "semanticReview": {
                "status": "pass", "checks": {key: "pass" for key in speech.SEMANTIC_CHECKS},
                "evidence": "Fixture", "uncertainty": [], "issues": []},
            "languageReview": {"status": "pass", "pluginId": "fixture", "policySha256": "6" * 64,
                               "checks": [{"checkId": "fixture", "status": "pass", "evidence": "Fixture"}]},
        }

    def artifact(self, relative: str, *, json_artifact: bool = False) -> dict:
        path = self.asset_root / relative
        result = {"path": relative, "sha256": subject.file_sha256(path)}
        if json_artifact:
            result["jsonSha256"] = subject.json_sha256(subject.read_object(path))
        return result

    def build(self):
        write_json(self.manifest_path, self.manifest)
        return subject.build_package(self.paths, self.manifest_path, self.asset_root)

    def test_builds_machine_screened_package_but_never_human_approved(self):
        package = self.build()
        checked_in_registry = json.loads(
            (Path(__file__).parents[1] / "config/speaker-voice-registry.json").read_text(encoding="utf-8"))
        self.assertEqual(self.registry, checked_in_registry)
        self.assertEqual(self.job["schemaVersion"], "sermon-target-language-speech-job-v2")
        self.assertIn("clipVoiceAuthorization", self.job["inputs"])
        self.assertIn("clipVoiceCapability", self.job["inputs"])
        self.assertIn("clipTimelineMap", self.job["inputs"])
        self.assertNotIn("multilingual_dubbing", self.registry["speakers"][0]["authorization"]["purposes"])
        ko_status = next(row["status"] for row in self.registry["speakers"][0]["localeCapabilities"]
                         if row["targetLocale"] == "ko")
        self.assertEqual(ko_status, "unverified_poc")
        self.assertEqual(package["status"], "machine_screened")
        self.assertFalse(package["humanReview"]["humanApproval"])
        self.assertEqual([unit["textGroupId"] for unit in package["units"]], ["g1", "g2"])
        self.assertEqual(len(package["downstreamInvalidationKey"]), 64)

    def test_changed_candidate_rejected(self):
        self.candidate["groups"][0]["targetText"] = "다른 말"
        write_json(self.paths["candidate"], self.candidate)
        with self.assertRaises(ValueError):
            self.build()

    def test_source_human_gate_rejected(self):
        self.source["review"]["checks"]["wordAlignment"] = "pending"
        write_json(self.paths["source"], self.source)
        self.candidate["englishSourcePackageJsonSha256"] = subject.json_sha256(self.source)
        write_json(self.paths["candidate"], self.candidate)
        with self.assertRaisesRegex(ValueError, "human gates"):
            subject.validate_job(self.source, self.anchor, self.candidate,
                                 self.job, self.adapter, self.policy,
                                 self.human_receipt, self.registry, self.clip_auth,
                                 self.clip_cap, self.clip_timeline, self.paths)

    def test_cross_locale_rejected(self):
        self.manifest["targetLocale"] = "es"
        with self.assertRaisesRegex(ValueError, "locale mismatch"):
            self.build()

    def test_undocumented_policy_drift_rejected(self):
        self.policy["terminology"]["seriesNames"][0]["target"] = "changed fixture term"
        write_json(self.paths["policy"], self.policy)
        with self.assertRaises(ValueError):
            self.build()

    def test_independent_human_receipt_rejection_blocks_audio(self):
        self.human_receipt["decision"] = "rejected"
        write_json(self.paths["human_receipt"], self.human_receipt)
        with self.assertRaises(ValueError):
            self.build()

    def test_registry_capability_drift_rejected(self):
        self.registry["speakers"][0]["localeCapabilities"][1]["status"] = "unsupported"
        write_json(self.paths["registry"], self.registry)
        with self.assertRaises(ValueError):
            self.build()

    def test_global_demo_purpose_alone_cannot_verify_production(self):
        with self.assertRaisesRegex(ValueError, "production authorization"):
            speech.validate_adapter(self.adapter, "ko", self.registry)

    def test_clip_authorization_without_probe_review_cannot_verify(self):
        with self.assertRaisesRegex(ValueError, "human-reviewed locale capability"):
            speech.validate_adapter(
                self.adapter, "ko", self.registry,
                clip_voice_authorization=self.clip_auth,
                source_package=self.source, candidate=self.candidate)

    def test_short_demo_rejection_blocks_clip_capability(self):
        self.short_approval["tracks"][0]["decision"] = "rejected"
        path = Path(self.clip_cap["shortDemoApproval"]["path"])
        write_json(path, self.short_approval)
        self.clip_cap["shortDemoApproval"]["sha256"] = subject.file_sha256(path)
        self.clip_cap["shortDemoApproval"]["jsonSha256"] = subject.json_sha256(self.short_approval)
        write_json(self.paths["clip_voice_capability"], self.clip_cap)
        with self.assertRaisesRegex(ValueError, "Short demo approval"):
            self.build()

    def test_long_probe_audio_hash_drift_blocks_clip_capability(self):
        path = Path(self.clip_cap["longProbeAudio"]["path"])
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "evidence file hash mismatch"):
            self.build()

    def test_clip_capability_wrong_locale_rejected(self):
        self.clip_cap["targetLocale"] = "es"
        write_json(self.paths["clip_voice_capability"], self.clip_cap)
        with self.assertRaisesRegex(ValueError, "source, locale or checkpoint"):
            self.build()

    def test_job_clip_capability_hash_mismatch_rejected(self):
        self.job["inputs"]["clipVoiceCapability"]["jsonSha256"] = "9" * 64
        write_json(self.paths["job"], self.job)
        with self.assertRaisesRegex(ValueError, "clipVoiceCapability"):
            self.build()

    def test_wrong_anchor_offset_rejected(self):
        self.clip_timeline["anchorOffsetSeconds"] = 0.1
        write_json(self.paths["clip_timeline_map"], self.clip_timeline)
        with self.assertRaisesRegex(ValueError, "anchor offset"):
            self.build()

    def test_job_timeline_map_hash_mismatch_rejected(self):
        self.job["inputs"]["clipTimelineMap"]["jsonSha256"] = "9" * 64
        write_json(self.paths["job"], self.job)
        with self.assertRaisesRegex(ValueError, "clipTimelineMap"):
            self.build()

    def test_clip_receipt_wrong_candidate_rejected(self):
        self.clip_auth["targetLanguageCandidateJsonSha256"] = "8" * 64
        write_json(self.paths["clip_voice_authorization"], self.clip_auth)
        with self.assertRaisesRegex(ValueError, "source, candidate, locale or checkpoint"):
            self.build()

    def test_clip_receipt_wrong_locale_rejected(self):
        self.clip_auth["targetLocale"] = "es"
        write_json(self.paths["clip_voice_authorization"], self.clip_auth)
        with self.assertRaisesRegex(ValueError, "source, candidate, locale or checkpoint"):
            self.build()

    def test_clip_receipt_wrong_checkpoint_rejected(self):
        self.clip_auth["voiceCheckpointSha256"] = "8" * 64
        write_json(self.paths["clip_voice_authorization"], self.clip_auth)
        with self.assertRaisesRegex(ValueError, "source, candidate, locale or checkpoint"):
            self.build()

    def test_job_clip_receipt_hash_mismatch_rejected(self):
        self.job["inputs"]["clipVoiceAuthorization"]["jsonSha256"] = "9" * 64
        write_json(self.paths["job"], self.job)
        with self.assertRaisesRegex(ValueError, "clipVoiceAuthorization"):
            self.build()

    def test_job_registry_hash_mismatch_rejected(self):
        self.job["inputs"]["speakerRegistry"]["jsonSha256"] = "9" * 64
        write_json(self.paths["job"], self.job)
        with self.assertRaisesRegex(ValueError, "speakerRegistry"):
            self.build()

    def test_render_voice_must_match_registry_bound_adapter(self):
        self.voice["provider"] = "unregistered-provider"
        with self.assertRaisesRegex(ValueError, "Voice/checkpoint"):
            self.build()

    def test_wrong_job_unit_receipt_rejected(self):
        row = self.manifest["units"][0]
        path = self.asset_root / row["receipt"]["path"]
        receipt = subject.read_object(path)
        receipt["jobJsonSha256"] = "7" * 64
        write_json(path, receipt)
        row["receipt"] = self.artifact(row["receipt"]["path"], json_artifact=True)
        with self.assertRaisesRegex(ValueError, "belongs to another job"):
            self.build()

    def test_drifted_audio_hash_rejected(self):
        path = self.asset_root / self.manifest["units"][0]["audio"]["path"]
        path.write_bytes(path.read_bytes() + b"drift")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.build()

    def test_truncated_audio_with_updated_hash_fails_full_decode(self):
        row = self.manifest["units"][0]
        path = self.asset_root / row["audio"]["path"]
        path.write_bytes(path.read_bytes()[:-1000])
        row["audio"] = self.artifact(row["audio"]["path"])
        receipt_path = self.asset_root / row["receipt"]["path"]
        receipt = subject.read_object(receipt_path)
        receipt["audioSha256"] = row["audio"]["sha256"]
        write_json(receipt_path, receipt)
        row["receipt"] = self.artifact(row["receipt"]["path"], json_artifact=True)
        with self.assertRaises(ValueError):
            self.build()

    def test_schedule_overflow_rejected(self):
        self.schedule["policy"]["maxEndLagSeconds"] = 0.01
        rel = self.manifest["schedule"]["path"]
        write_json(self.asset_root / rel, self.schedule)
        self.manifest["schedule"] = self.artifact(rel, json_artifact=True)
        with self.assertRaisesRegex(ValueError, "overflow"):
            self.build()

    def test_schedule_uses_first_source_start_for_dubbed_onset(self):
        # The second English source unit ends with the clip. Its dubbed
        # utterance must start during that unit, not after the clip ends.
        self.schedule["entries"][1].update(plannedStart=0.75, plannedEnd=0.95)
        rel = self.manifest["schedule"]["path"]
        write_json(self.asset_root / rel, self.schedule)
        self.manifest["schedule"] = self.artifact(rel, json_artifact=True)
        with self.assertRaisesRegex(ValueError, "Schedule start"):
            self.build()

    def test_dubbed_track_cannot_extend_past_approved_clip(self):
        rel = self.manifest["track"]["path"]
        wav(self.asset_root / rel, 0.8)
        self.manifest["track"] = self.artifact(rel)
        self.schedule["trackDurationSeconds"] = 0.8
        schedule_rel = self.manifest["schedule"]["path"]
        write_json(self.asset_root / schedule_rel, self.schedule)
        self.manifest["schedule"] = self.artifact(schedule_rel, json_artifact=True)
        with self.assertRaisesRegex(ValueError, "approved 1x source clip"):
            self.build()

    def test_caption_translation_drift_rejected(self):
        self.captions["cues"][0]["text"] = "다른 자막"
        rel = self.manifest["captions"]["path"]
        write_json(self.asset_root / rel, self.captions)
        self.manifest["captions"] = self.artifact(rel)
        with self.assertRaisesRegex(ValueError, "Caption text"):
            self.build()

    def test_unverified_adapter_rejected(self):
        self.adapter["capabilityStatus"] = "unverified_poc"
        write_json(self.paths["adapter"], self.adapter)
        with self.assertRaises(ValueError):
            self.build()

    def test_authorization_for_another_clip_rejected(self):
        self.authorization["englishSourcePackageJsonSha256"] = "8" * 64
        rel = self.manifest["voiceAuthorization"]["path"]
        write_json(self.asset_root / rel, self.authorization)
        self.manifest["voiceAuthorization"] = self.artifact(rel, json_artifact=True)
        with self.assertRaisesRegex(ValueError, "Render voice authorization differs"):
            self.build()

    def test_cross_locale_track_rejected_even_with_valid_hash(self):
        rel = "languages/zh-Hans/audio/track.wav"
        wav(self.asset_root / rel, 0.7)
        self.manifest["track"] = self.artifact(rel)
        with self.assertRaisesRegex(ValueError, "another locale"):
            self.build()

    def test_screening_receipt_change_changes_package_invalidation_key(self):
        first = self.build()
        rel = self.manifest["machineScreeningReceipt"]["path"]
        self.screening["modelRevision"] = "fixture-v2"
        write_json(self.asset_root / rel, self.screening)
        self.manifest["machineScreeningReceipt"] = self.artifact(rel, json_artifact=True)
        second = self.build()
        self.assertNotEqual(first["packageId"], second["packageId"])
        self.assertNotEqual(first["downstreamInvalidationKey"], second["downstreamInvalidationKey"])

    def test_machine_screening_cannot_claim_another_audio_set(self):
        self.screening["unitAudioSha256s"][0] = "9" * 64
        rel = self.manifest["machineScreeningReceipt"]["path"]
        write_json(self.asset_root / rel, self.screening)
        self.manifest["machineScreeningReceipt"] = self.artifact(rel, json_artifact=True)
        with self.assertRaisesRegex(ValueError, "exact audio set"):
            self.build()

    def test_machine_screening_cannot_claim_another_delivered_track(self):
        rel = self.manifest["track"]["path"]
        path = self.asset_root / rel
        changed = bytearray(path.read_bytes())
        changed[-2:] = b"\x01\x00"
        path.write_bytes(changed)
        self.manifest["track"] = self.artifact(rel)
        with self.assertRaisesRegex(ValueError, "exact audio set"):
            self.build()

    def test_full_pcm_wav_decode_without_ffmpeg_tools(self):
        path = self.asset_root / self.manifest["track"]["path"]
        with mock.patch.object(subject.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(subject.probe_audio(path), (0.7, 16000, 1))
        decoded = unit_integrity.probe_full_decode(
            path, runner=mock.Mock(side_effect=FileNotFoundError()))
        self.assertEqual(decoded["codec"], "pcm_s16le")
        self.assertEqual(decoded["durationSeconds"], 0.7)

    def test_compacted_units_require_matching_trim_evidence(self):
        rel = "review/leading-silence-trim.json"
        receipt = {"schemaVersion": "sermon-formal-leading-silence-trim-v1",
                   "status": "measured_silence_removed", "targetLocale": "ko",
                   "targetLanguageSpeechJobJsonSha256": subject.json_sha256(self.job),
                   "sourceJobFileSha256": subject.file_sha256(self.paths["job"]),
                   "humanListeningStatus": "pending",
                   "units": [{"unitIndex": index, "textGroupId": row["textGroupId"],
                              "audioSha256": row["audio"]["sha256"],
                              "sourceAudioSha256": "a" * 64,
                              "removedLeadingSeconds": 0.1}
                             for index, row in enumerate(self.manifest["units"])]}
        write_json(self.asset_root / rel, receipt)
        self.manifest["silenceTrimEvidence"] = self.artifact(rel, json_artifact=True)
        self.build()
        receipt["units"][0]["audioSha256"] = "b" * 64
        write_json(self.asset_root / rel, receipt)
        self.manifest["silenceTrimEvidence"] = self.artifact(rel, json_artifact=True)
        with self.assertRaisesRegex(ValueError, "trim evidence differs from unit"):
            self.build()

    def test_edge_trim_duration_and_gap_evidence_are_checked(self):
        rel = "review/edge-silence-trim.json"
        schedule = json.loads((self.asset_root / self.manifest["schedule"]["path"]).read_text())
        receipt = {
            "schemaVersion": "sermon-formal-edge-silence-trim-v1",
            "status": "measured_silence_removed", "targetLocale": "ko",
            "targetLanguageSpeechJobJsonSha256": subject.json_sha256(self.job),
            "sourceJobFileSha256": subject.file_sha256(self.paths["job"]),
            "humanListeningStatus": "pending", "trimTrailing": True,
            "paddingSeconds": 0.04,
            "interUtteranceGapSeconds": schedule["policy"]["interUtteranceGapSeconds"],
            "reactionLagSeconds": schedule["policy"]["reactionLagSeconds"],
            "units": [{
                "unitIndex": index, "textGroupId": row["textGroupId"],
                "audioSha256": row["audio"]["sha256"],
                "sourceAudioSha256": "a" * 64,
                "removedLeadingSeconds": 0.1,
                "removedTrailingSeconds": 0.2,
                "originalDurationSeconds": row["durationSeconds"] + 0.3,
            } for index, row in enumerate(self.manifest["units"])],
        }
        write_json(self.asset_root / rel, receipt)
        self.manifest["silenceTrimEvidence"] = self.artifact(rel, json_artifact=True)
        self.build()
        receipt["units"][0]["removedTrailingSeconds"] = 0.21
        write_json(self.asset_root / rel, receipt)
        self.manifest["silenceTrimEvidence"] = self.artifact(rel, json_artifact=True)
        with self.assertRaisesRegex(ValueError, "Edge silence trim duration"):
            self.build()


if __name__ == "__main__":
    unittest.main()

"""Synthetic checks for human-pending pre-render and formal unit admission."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import render_formal_target_language_speech as formal
from scripts import render_speculative_target_language_speech as subject
from tests import test_prepare_target_language_speech_job as speech_fixture
from tests import test_render_formal_target_language_speech as formal_fixture


class FakeSynth:
    calls = []

    def __init__(self, checkpoint: Path, **kwargs):
        pass

    def __call__(self, text, language, speaker, *, seed):
        self.calls.append((text, language, speaker, seed))
        return [0.03] * 1280, 16000


class SpeculativeRenderTests(unittest.TestCase):
    def setUp(self):
        fixture = speech_fixture.TargetLanguageSpeechJobTests(
            "test_korean_candidate_and_prepared_job_match_published_contracts")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        fixture.candidate["status"] = "machine_review_pass_human_review_pending"
        fixture.candidate["humanReview"] = {
            "translation": "pending", "reviewer": None, "reviewedAt": None,
            "reviewedGroupIds": [],
        }
        speech_fixture.write_json(fixture.candidate_path, fixture.candidate)
        self.paths = {
            "source": fixture.source_package_path, "anchor": fixture.anchor_path,
            "candidate": fixture.candidate_path, "policy": fixture.policy_path,
            "adapter": fixture.adapter_path, "registry": fixture.registry_path,
        }
        self.policies = fixture.root / "operation-policies.json"
        policies = {
            "normalization": {"policy": "exact_human_approved_target_text_no_rewrite"},
            "asrScreening": {"policy": "synthetic"},
            "subtitle": {"policy": "synthetic"},
        }
        for name, field in (("normalization", "normalizationPolicySha256"),
                            ("asrScreening", "asrScreeningPolicySha256"),
                            ("subtitle", "subtitlePolicySha256")):
            fixture.adapter[field] = subject.identity.json_sha256(policies[name])
        speech_fixture.write_json(fixture.adapter_path, fixture.adapter)
        speech_fixture.write_json(self.policies, policies)
        self.checkpoint_map = fixture.root / "checkpoint-map.json"
        speech_fixture.write_json(self.checkpoint_map, {
            "schemaVersion": "sermon-speaker-checkpoint-map-v1",
            "checkpoints": [{"speakerId": fixture.adapter["speakerId"],
                             "checkpointRef": fixture.adapter["conditioningRef"],
                             "path": str(fixture.root / "checkpoint")}],
        })
        (fixture.root / "checkpoint").mkdir()
        self.out = fixture.root / "speculative"
        FakeSynth.calls = []

    def render(self, **kwargs):
        with patch.object(subject.demos, "validate_checkpoint",
                          return_value=self.fixture.root / "checkpoint"):
            return subject.render(self.paths, self.checkpoint_map, self.policies,
                                  self.out, synth_factory=FakeSynth, **kwargs)

    def test_pending_translation_renders_selected_units_without_formal_package(self):
        result = self.render(group_ids=["g1"])
        self.assertEqual(result["renderedGroupIds"], ["g1"])
        self.assertEqual(len(FakeSynth.calls), 1)
        manifest = subject.formal.package.read_object(self.out / "manifest.json")
        self.assertFalse(manifest["synthesisEligible"])
        self.assertFalse(manifest["releaseEligible"])
        self.assertFalse((self.out / "job.json").exists())
        self.assertFalse((self.out / "render-manifest.json").exists())
        self.assertEqual(self.render(group_ids=["g1"])["renderedGroupIds"], ["g1"])
        self.assertEqual(len(FakeSynth.calls), 1)
        self.assertEqual(self.render(group_ids=["g2"])["renderedGroupIds"], ["g2"])
        self.assertEqual(len(FakeSynth.calls), 2)

    def test_approved_or_failed_machine_candidate_cannot_enter_preview_lane(self):
        self.fixture.candidate["status"] = "human_translation_approved"
        self.fixture.candidate["humanReview"]["translation"] = "approved"
        speech_fixture.write_json(self.fixture.candidate_path, self.fixture.candidate)
        with self.assertRaisesRegex(ValueError, "human-pending"):
            self.render()
        self.fixture.candidate["status"] = "machine_review_pass_human_review_pending"
        self.fixture.candidate["humanReview"]["translation"] = "pending"
        self.fixture.candidate["modelReview"]["status"] = "fail"
        speech_fixture.write_json(self.fixture.candidate_path, self.fixture.candidate)
        with self.assertRaisesRegex(ValueError, "Independent model review"):
            self.render()

    def test_tampered_preview_audio_fails_closed(self):
        self.render(group_ids=["g1"])
        (self.out / "units/unit-0000.wav").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "audio changed"):
            self.render(group_ids=["g1"])

    def test_chinese_only_voice_purpose_cannot_render_korean_preview(self):
        self.fixture.adapter["authorizationPurpose"] = "chinese_dubbing"
        speech_fixture.write_json(self.fixture.adapter_path, self.fixture.adapter)
        with self.assertRaisesRegex(ValueError, "demo/Chinese voice purpose"):
            self.render(group_ids=["g1"])

    def test_committed_partial_audio_resumes_without_synthesis(self):
        self.render(group_ids=["g1"])
        audio = self.out / "units/unit-0000.wav"
        audio.rename(self.out / "units/unit-0000.partial.wav")
        self.render(group_ids=["g1"])
        self.assertTrue(audio.is_file())
        self.assertEqual(len(FakeSynth.calls), 1)


class FormalAdmissionTests(unittest.TestCase):
    def setUp(self):
        fixture = formal_fixture.FormalRenderTests(
            "test_two_units_full_decode_and_resume_without_synthesis")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.spec_root = fixture.root.parent / "speculative"
        self.spec_root.mkdir()
        pending = copy.deepcopy(fixture.context["candidate"])
        pending["status"] = "machine_review_pass_human_review_pending"
        pending["humanReview"] = {"translation": "pending", "reviewer": None,
                                  "reviewedAt": None, "reviewedGroupIds": []}
        context = dict(fixture.context, candidate=pending)
        preview_adapter = copy.deepcopy(context["adapter"])
        preview_adapter["authorizationPurpose"] = "multilingual_voice_demo"
        preview_adapter["capabilityStatus"] = "unverified_poc"
        context["adapter"] = preview_adapter
        subject.formal.write_json_atomic(self.spec_root / "candidate.json", pending)
        for name in ("source", "anchor", "policy", "adapter", "registry"):
            subject.formal.write_json_atomic(self.spec_root / f"{name}.json", context[name])
        subject.formal.write_json_atomic(self.spec_root / "manifest.json", {
            "schemaVersion": subject.MANIFEST_VERSION, "status": "preview_only",
            "synthesisEligible": False, "releaseEligible": False,
            "targetLocale": pending["targetLocale"],
            "candidateJsonSha256": subject.identity.json_sha256(pending),
            "sourceJsonSha256": subject.identity.json_sha256(context["source"]),
            "anchorJsonSha256": subject.identity.json_sha256(context["anchor"]),
            "translationPolicySha256": pending["translationPolicySha256"],
        })
        for index, group in enumerate(pending["groups"]):
            sound = subject.sound_identity(context, index, seed=42,
                                           dtype="bfloat16", attention="sdpa",
                                           instruct=None)
            audio = self.spec_root / f"units/unit-{index:04d}.wav"
            audio.parent.mkdir(exist_ok=True)
            formal.write_pcm16(audio, [0.03] * 1280, 16000)
            subject.formal.write_json_atomic(
                self.spec_root / f"receipts/unit-{index:04d}.json", {
                    "schemaVersion": subject.UNIT_VERSION, "status": "preview_only",
                    "candidateJsonSha256": subject.identity.json_sha256(pending),
                    "soundIdentity": sound, "audioSha256": subject.identity.sha256(audio),
                    "durationSeconds": 0.08, "fullDecode": "pass",
                })
        FakeSynth.calls = []

    def formal_render(self, context=None):
        return formal.render_units(context or self.fixture.context, self.fixture.paths,
                                   self.fixture.root,
                                   self.fixture.root / "checkpoint-map.json",
                                   speculative_from=self.spec_root,
                                   synth_factory=FakeSynth)

    def test_same_audio_is_reused_only_after_formal_job_validation(self):
        # Admission is called by render() after checked_context; this unit test
        # checks the per-unit identity and fresh formal receipt separately.
        rows = self.formal_render()
        self.assertEqual(len(rows), 2)
        self.assertEqual(FakeSynth.calls, [])
        for row in rows:
            receipt = formal.package.read_object(self.fixture.root / row["receipt"]["path"])
            self.assertEqual(receipt["fullDecode"], "pass")

    def test_changed_text_resynthesizes_only_changed_unit(self):
        self.fixture.context["candidate"]["groups"][1]["targetText"] = "Revised text."
        self.fixture.context["job"]["units"][1]["text"] = "Revised text."
        with patch.object(formal.integrity, "build_receipt",
                          return_value={"fullDecode": "pass", "durationSeconds": 0.08}):
            self.formal_render()
        self.assertEqual(len(FakeSynth.calls), 1)
        self.assertEqual(FakeSynth.calls[0][0], "Revised text.")

    def test_changed_audio_hash_is_rejected(self):
        (self.spec_root / "units/unit-0000.wav").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.formal_render()

    def test_formal_entrypoint_still_rejects_pending_translation(self):
        pending = formal.package.read_object(self.spec_root / "candidate.json")
        formal.write_json_atomic(self.fixture.paths["candidate"], pending)
        with self.assertRaises(ValueError):
            formal.render(self.fixture.paths,
                          self.fixture.root / "checkpoint-map.json",
                          self.fixture.root / "operation-policies.json",
                          speculative_from=self.spec_root,
                          synth_factory=FakeSynth)
        self.assertFalse((self.fixture.root / "render-manifest.json").exists())

    def test_changed_candidate_snapshot_is_rejected(self):
        (self.spec_root / "candidate.json").write_text("{}")
        with self.assertRaises(ValueError):
            self.formal_render()


if __name__ == "__main__":
    unittest.main()

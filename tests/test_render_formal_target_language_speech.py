"""Synthetic, no-model checks for the formal Layer 3 renderer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import render_formal_target_language_speech as subject
from tests import test_build_target_language_audio_package as fixture_module


class FakeSynth:
    calls = []

    def __init__(self, checkpoint: Path, **kwargs):
        self.checkpoint = checkpoint

    def __call__(self, text, language, speaker, *, seed):
        self.calls.append((text, language, speaker, seed))
        return [0.03] * 1280, 16000  # 80 ms


class FormalRenderTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.AudioPackageTests("test_builds_machine_screened_package_but_never_human_approved")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.asset_root
        self.paths = fixture.paths
        self.context = {name: subject.package.read_object(path)
                        for name, path in self.paths.items()}
        self.context["checkpoint"] = self.root / "fixture-model"
        self.context["checkpointMapFileSha256"] = "a" * 64
        self.context["operationPoliciesFileSha256"] = "c" * 64
        self.root.joinpath("fixture-model").mkdir()
        for index, unit in enumerate(fixture.job["units"]):
            self.root.joinpath(unit["outputRelativePath"]).unlink()
            self.root.joinpath(f"receipts/unit-{index:04d}.json").unlink()
        self.root.joinpath("languages/ko/audio/track.wav").unlink()
        self.root.joinpath("languages/ko/synchronization/schedule.json").unlink()
        self.root.joinpath("languages/ko/synchronization/captions.json").unlink()
        FakeSynth.calls = []

    def render_units(self):
        return subject.render_units(self.context, self.paths, self.root,
                                    self.root / "checkpoint-map.json",
                                    synth_factory=FakeSynth)

    def test_two_units_full_decode_and_resume_without_synthesis(self):
        rows = self.render_units()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(FakeSynth.calls), 2)
        for row in rows:
            self.assertEqual(subject.package.read_object(self.root / row["receipt"]["path"])
                             ["fullDecode"], "pass")
        self.assertEqual(self.render_units(), rows)
        self.assertEqual(len(FakeSynth.calls), 2)

    def test_changed_text_or_checkpoint_map_cannot_reuse_cached_wav(self):
        self.render_units()
        self.context["checkpointMapFileSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "Cached render identity differs"):
            self.render_units()
        self.context["checkpointMapFileSha256"] = "a" * 64
        self.context["job"]["units"][0]["text"] = "changed text"
        with self.assertRaisesRegex(ValueError, "Cached render identity differs"):
            self.render_units()

    def test_delivery_instruction_is_part_of_cached_audio_identity(self):
        subject.render_units(self.context, self.paths, self.root,
                             self.root / "checkpoint-map.json", synth_factory=FakeSynth,
                             instruct="Speak briskly but naturally.")
        with self.assertRaisesRegex(ValueError, "Cached render identity differs"):
            subject.render_units(self.context, self.paths, self.root,
                                 self.root / "checkpoint-map.json", synth_factory=FakeSynth,
                                 instruct="Speak slowly.")

    def test_tampered_audio_and_orphan_are_rejected(self):
        rows = self.render_units()
        (self.root / rows[0]["audio"]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Cached audio identity or hash changed"):
            self.render_units()

    def test_partial_commit_resumes_to_full_receipt(self):
        self.render_units()
        wav = self.root / self.context["job"]["units"][0]["outputRelativePath"]
        receipt = self.root / "receipts/unit-0000.json"
        receipt.unlink()
        self.assertEqual(len(self.render_units()), 2)
        self.assertTrue(receipt.exists())
        self.assertEqual(len(FakeSynth.calls), 2)

    def test_crash_between_committed_temp_and_final_wav_is_recoverable(self):
        self.render_units()
        wav = self.root / self.context["job"]["units"][0]["outputRelativePath"]
        partial = wav.with_suffix(".partial.wav")
        wav.rename(partial)
        (self.root / "receipts/unit-0000.json").unlink()
        self.assertEqual(len(self.render_units()), 2)
        self.assertTrue(wav.is_file())
        self.assertEqual(len(FakeSynth.calls), 2)

    def test_policy_content_hashes_are_checked(self):
        policies = {"normalization": {"version": "v1", "policy":
                    "exact_human_approved_target_text_no_rewrite"},
                    "asrScreening": {"version": "v1", "policy": "screen_all_units"},
                    "subtitle": {"version": "v1", "policy": "approved_text"}}
        fields = (("normalization", "normalizationPolicySha256"),
                  ("asrScreening", "asrScreeningPolicySha256"),
                  ("subtitle", "subtitlePolicySha256"))
        adapter = {field: subject.identity.json_sha256(policies[name])
                   for name, field in fields}
        job = {"adapter": adapter.copy()}
        subject.validate_operation_policies(policies, adapter, job)
        policies["subtitle"]["policy"] = "changed"
        with self.assertRaisesRegex(ValueError, "Audio operation policy content differs"):
            subject.validate_operation_policies(policies, adapter, job)

    def test_path_map_verifies_hash_and_preserves_job_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original/source.json"
            staged = root / "staged/source.json"
            staged.parent.mkdir()
            staged.write_text('{"value":1}\n')
            source = json.loads(staged.read_text())
            job_path = root / "job.json"
            job_path.write_text(json.dumps({"inputs": {"englishSourcePackage": {
                "path": str(original), "sha256": subject.identity.sha256(staged),
                "jsonSha256": subject.identity.json_sha256(source)}}}))
            before = subject.identity.sha256(job_path)
            path_map = root / "path-map.json"
            path_map.write_text(json.dumps({"schemaVersion": "sermon-deployment-path-map-v1",
                                            "paths": {str(original): str(staged)}}))
            subject.materialize_path_map(job_path, path_map)
            self.assertTrue(original.is_symlink())
            self.assertEqual(subject.identity.sha256(job_path), before)
            original.unlink()
            staged.write_text('{"value":2}\n')
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                subject.materialize_path_map(job_path, path_map)
            self.assertFalse(original.exists())

    def test_path_map_accepts_hash_bound_json_array_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "staged/source.json"
            evidence = root / "staged/segments.json"
            source.parent.mkdir()
            segments = [{"text": "source"}]
            evidence.write_text(json.dumps(segments))
            source.write_text(json.dumps({"segments": {
                "path": str(root / "original/segments.json"),
                "sha256": subject.identity.sha256(evidence),
                "jsonSha256": subject.identity.json_sha256(segments)}}))
            document = json.loads(source.read_text())
            job = root / "job.json"
            job.write_text(json.dumps({"inputs": {"englishSourcePackage": {
                "path": str(root / "original/source.json"),
                "sha256": subject.identity.sha256(source),
                "jsonSha256": subject.identity.json_sha256(document)}}}))
            mapping = root / "path-map.json"
            mapping.write_text(json.dumps({"schemaVersion": "sermon-deployment-path-map-v1",
                "paths": {str(root / "original/source.json"): str(source),
                          str(root / "original/segments.json"): str(evidence)}}))
            subject.materialize_path_map(job, mapping)
            self.assertTrue((root / "original/segments.json").is_symlink())

    def test_schedule_uses_first_source_start_and_reports_clip_overflow(self):
        rows = self.render_units()
        policy = dict(subject.DEFAULT_POLICY, reactionLagSeconds=0.4)
        plan = subject.schedule(self.context, rows, policy)
        self.assertEqual(plan["entries"][0]["plannedStart"], 0.4)
        self.assertEqual(plan["entries"][1]["plannedStart"], 0.7)
        self.assertEqual(plan["status"], "fail")  # 0.7 + 0.08 > 0.7 clip
        with self.assertRaisesRegex(ValueError, "exceeds 1x clip schedule"):
            subject.assemble(self.context, self.paths, self.root, rows, policy=policy)
        self.assertFalse((self.root / "render-manifest.json").exists())
        diagnostic = subject.package.read_object(self.root / "render-diagnostics.json")
        self.assertEqual(diagnostic["schedule"]["issues"][0]["textGroupId"], "g2")

    def test_in_bounds_assembly_preserves_text_and_has_no_review_claim(self):
        rows = self.render_units()
        plan_policy = {"reactionLagSeconds": 0.0, "interUtteranceGapSeconds": 0.0,
                       "maxEndLagSeconds": 8.0}
        manifest = subject.assemble(self.context, self.paths, self.root, rows,
                                    policy=plan_policy)
        self.assertEqual(manifest["machineScreening"],
                         {"status": "not_run", "model": None, "coverage": 0.0})
        self.assertEqual(manifest["units"][0]["targetTextSha256"],
                         hashlib.sha256(self.context["job"]["units"][0]["text"].encode()).hexdigest())
        captions = subject.package.read_object(self.root / manifest["captions"]["path"])
        self.assertEqual([row["text"] for row in captions["cues"]],
                         [group["targetText"] for group in self.context["candidate"]["groups"]])
        self.assertTrue((self.root / manifest["track"]["path"]).is_file())

    def test_fresh_full_length_delivery_can_use_hash_bound_mp3_track(self):
        rows = self.render_units()
        plan_policy = {"reactionLagSeconds": 0.0, "interUtteranceGapSeconds": 0.0,
                       "maxEndLagSeconds": 8.0}
        manifest = subject.assemble(self.context, self.paths, self.root, rows,
                                    policy=plan_policy, track_format="mp3")
        track = self.root / manifest["track"]["path"]
        self.assertEqual(track.suffix, ".mp3")
        self.assertEqual(manifest["track"]["sha256"], subject.identity.sha256(track))
        self.assertLess(track.stat().st_size,
                        (self.root / "languages/ko/audio/track.wav").stat().st_size)
        self.assertEqual(subject.integrity.probe_full_decode(track)["codec"], "mp3")
        with self.assertRaisesRegex(ValueError, "different track format"):
            subject.assemble(self.context, self.paths, self.root, rows,
                             policy=plan_policy, track_format="wav")


if __name__ == "__main__":
    unittest.main()

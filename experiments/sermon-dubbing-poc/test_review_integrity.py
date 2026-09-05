"""Regression fixtures for stale reviews and speaker misattribution; no media/model calls."""
import copy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from align_weekly_source import match_blocks
from build_speaker_bank import validate_speaker_identity
from check_weekly_timing import budgets, reviewed_anchors
from poc import sha256, write_json
from weekly_dubbing import read, validate_review


class ReviewIntegrityTests(unittest.TestCase):
    def fixture(self, work, approved_anchors=True):
        for name in ["audio", "render", "synchronization", "source-alignment", "saturday"]:
            (work / name).mkdir()
        inputs = {}
        for name in ["sourceAudio", "windowApproval", "readingPdf", "companionPdf", "readingQuality", "readingPdfQa", "companionPdfQa"]:
            path = work / "saturday" / name
            path.write_text("deterministic review fixture")
            inputs[name] = {"path": str(path), "sha256": sha256(path)}
        job = {"inputs": inputs, "voice": {"checkpointSha256": "fixture-checkpoint"}, "sourceId": "fixture-source", "sourceStartSeconds": 100,
               "sourceDurationSeconds": 10, "inheritedReview": {"generationComplete": True},
               "units": [{"text": "中文"}], "blocks": [{"id": 0, "en": "English source", "zh": "中文"}]}
        write_json(work / "job.json", job)
        job_hash = sha256(work / "job.json")
        alignment = {"jobSha256": job_hash, "sourceAudioSha256": inputs["sourceAudio"]["sha256"], "timeOrigin": "approved_sermon_clip_start",
                     "fullVideoOffsetSeconds": 100, "blocks": [{"blockId": 0, "start": 1, "end": 4, "issues": []}]}
        write_json(work / "source-alignment/report.json", alignment)
        if approved_anchors:
            self.write_anchor_review(work)
        (work / "render/chinese.raw.wav").write_bytes(b"render fixture")
        (work / "audio/zh-natural.mp3").write_bytes(b"natural audio fixture")
        (work / "synchronization/zh-synced.mp3").write_bytes(b"synced audio fixture")
        cues = [{"blockId": 0, "start": 0, "end": 3, "text": "中文"}]
        render = {"jobSha256": job_hash, "sha256": sha256(work / "render/chinese.raw.wav"), "cues": cues}
        write_json(work / "render/report.json", render)
        rows, failures = budgets(job["blocks"], alignment["blocks"], cues, 10)
        write_json(work / "synchronization/report.json", {"jobSha256": job_hash, "status": "natural_timing_fits", "blocks": rows, "failures": failures,
            "alignmentSha256": sha256(work / "source-alignment/report.json"), "anchorReviewSha256": sha256(work / "source-alignment/anchor-review.json") if approved_anchors else None})
        write_json(work / "synchronization/assembly.json", {"jobSha256": job_hash, "sha256": sha256(work / "synchronization/zh-synced.mp3"),
            "sourceNaturalMp3Sha256": sha256(work / "audio/zh-natural.mp3"), "sourceNaturalWavSha256": render["sha256"],
            "timingReportSha256": sha256(work / "synchronization/report.json"), "fullDecode": "pass"})
        write_json(work / "audio/asr-screening.json", {"jobSha256": job_hash, "results": [{"sha256": sha256(work / "audio/zh-natural.mp3"), "fullDecode": "pass", "screenedUnits": 1}]})
        write_json(work / "audio-review-synced.json", {"jobSha256": job_hash, "mp3Sha256": sha256(work / "synchronization/zh-synced.mp3"),
            "checkpointSha256": "fixture-checkpoint", "humanApproval": True, "reviewedBy": "synthetic fixture reviewer", "reviewedAt": "2026-09-05T00:00:00Z",
            "checks": dict.fromkeys(["speakerIdentity", "voiceSimilarity", "chineseFluency", "pronunciation", "noOmissionOrRepetition", "sameVideoSynchronization"], "pass")})
        write_json(work / "saturday/agent-generation-report.json", {"publication": {"artifacts": [{"gcsUri": "gs://fixture/" + name} for name in ["sermon_zh_en_reading.pdf", "sermon_interpretation_zh.pdf"]]}})
        return work

    def write_anchor_review(self, work):
        write_json(work / "source-alignment/anchor-review.json", {"alignmentSha256": sha256(work / "source-alignment/report.json"),
            "humanApproval": True, "reviewedBy": "synthetic fixture reviewer", "reviewedAt": "2026-09-05T00:00:00Z", "blocks": [{"blockId": 0, "start": 1, "end": 4}]})

    def test_unchanged_sync_still_delegates_to_original_saturday_gate(self):
        module = types.ModuleType("scripts.run_codex_local_sermon_production")
        module.local_completion_artifacts = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {module.__name__: module}):
            work = self.fixture(Path(tmp))
            validate_review(work)
            module.local_completion_artifacts.assert_called_once()
            self.assertEqual(read(work / "saturday-completion.json")["status"], "completed")

    def add_reviewed_placement(self, work):
        job, render = read(work / "job.json"), read(work / "render/report.json")
        path = work / "synchronization/placement-model-review.json"
        write_json(path, {"schemaVersion": "sermon-playback-placement-review-v1", "reviewType": "model", "model": "gpt-6-astra",
            "humanApproval": False, "status": "approved_for_candidate_playback", "reviewedBy": "synthetic model reviewer", "reviewedAt": "2026-09-05T00:00:00Z",
            "jobSha256": sha256(work / "job.json"), "renderSha256": sha256(work / "render/report.json"),
            "alignmentSha256": sha256(work / "source-alignment/report.json"), "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"],
            "unresolvedPlacementIssues": [], "evidence": [job["inputs"]["sourceAudio"]],
            "blocks": [{"blockId": 0, "sourceAnchorStart": 1, "playbackStart": .5, "status": "model_supported", "reason": "Synthetic source gap"}]})
        anchors = read(work / "source-alignment/report.json")["blocks"]
        rows, failures = budgets(job["blocks"], anchors, render["cues"], job["sourceDurationSeconds"], {0: .5})
        timing_path = work / "synchronization/report.json"
        write_json(timing_path, {**read(timing_path), "blocks": rows, "failures": failures, "placementReviewSha256": sha256(path)})
        assembly_path = work / "synchronization/assembly.json"
        write_json(assembly_path, {**read(assembly_path), "timingReportSha256": sha256(timing_path)})
        return path

    def test_human_reviewed_placement_reaches_original_saturday_gate(self):
        for completed in [True, False]:
            with self.subTest(saturday_complete=completed), tempfile.TemporaryDirectory() as tmp:
                module = types.ModuleType("scripts.run_codex_local_sermon_production")
                module.local_completion_artifacts = Mock(return_value=completed)
                work = self.fixture(Path(tmp))
                path = self.add_reviewed_placement(work)
                with patch.dict(sys.modules, {module.__name__: module}):
                    if completed:
                        validate_review(work)
                        self.assertEqual(read(work / "saturday-completion.json")["status"], "completed")
                    else:
                        with self.assertRaisesRegex(ValueError, "PDF / GCS completion"):
                            validate_review(work)
                        self.assertFalse((work / "saturday-completion.json").exists())
                module.local_completion_artifacts.assert_called_once()
                self.assertFalse(read(path)["humanApproval"])

    def test_changed_placement_or_missing_human_review_cannot_publish(self):
        for mutation in ["changed_review", "revoked_review", "deleted_review", "summary_hash", "human_review"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                work = self.fixture(Path(tmp))
                path = self.add_reviewed_placement(work)
                if mutation == "deleted_review":
                    path.unlink()
                elif mutation == "summary_hash":
                    timing_path = work / "synchronization/report.json"
                    write_json(timing_path, {**read(timing_path), "placementReviewSha256": "different-review"})
                    assembly_path = work / "synchronization/assembly.json"
                    write_json(assembly_path, {**read(assembly_path), "timingReportSha256": sha256(timing_path)})
                elif mutation == "human_review":
                    path = work / "audio-review-synced.json"
                    write_json(path, {**read(path), "humanApproval": False})
                else:
                    change = {"status": "revoked"} if mutation == "revoked_review" else {"reviewedAt": "2026-09-06T00:00:00Z"}
                    write_json(path, {**read(path), **change})
                with self.assertRaises(ValueError):
                    validate_review(work)
                self.assertFalse((work / "saturday-completion.json").exists())

    def test_stale_alignment_and_revoked_or_changed_review_cannot_publish(self):
        for mutation in ["alignment", "source_hash", "changed_review", "revoked_review", "deleted_review", "new_review", "render"]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                work = self.fixture(Path(tmp), approved_anchors=mutation != "new_review")
                approval_path = work / "source-alignment/anchor-review.json"
                if mutation == "deleted_review":
                    approval_path.unlink()
                elif mutation == "new_review":
                    self.write_anchor_review(work)
                elif mutation == "render":
                    (work / "render/chinese.raw.wav").write_bytes(b"changed render")
                elif mutation in {"alignment", "source_hash"}:
                    path = work / "source-alignment/report.json"
                    data = read(path)
                    if mutation == "source_hash":
                        data["sourceAudioSha256"] = "different-source"
                    else:
                        data["blocks"][0]["start"] = 2
                    write_json(path, data)
                else:
                    data = read(approval_path)
                    data["humanApproval" if mutation == "revoked_review" else "reviewedAt"] = False if mutation == "revoked_review" else "2026-09-06T00:00:00Z"
                    write_json(approval_path, data)
                with self.assertRaises(ValueError):
                    validate_review(work)
                self.assertFalse((work / "saturday-completion.json").exists())

    def test_manual_review_can_fill_a_completely_unmatched_block(self):
        blocks = [{"id": 0, "en": "No matching English", "zh": "中文"}]
        anchors, issues = match_blocks(blocks, [])
        self.assertEqual(issues[0]["reason"], "no_acoustic_text_match")
        cues = [{"blockId": 0, "start": 0, "end": 2}]
        self.assertEqual(budgets(blocks, reviewed_anchors(blocks, anchors), cues, 10)[1][0]["reason"], "missing_anchor_or_audio")
        corrected = reviewed_anchors(blocks, anchors, {"blocks": [{"blockId": 0, "start": 1, "end": 4}]})
        self.assertEqual(budgets(blocks, corrected, cues, 10)[1], [])

    def test_missing_unknown_and_duplicate_manual_anchors_are_rejected(self):
        blocks = [{"id": 0}, {"id": 1}]
        valid = [{"blockId": 0, "start": 0, "end": 1}, {"blockId": 1, "start": 2, "end": 3}]
        for changes in [valid[:1], valid + valid[:1], valid + [{"blockId": 9, "start": 4, "end": 5}]]:
            with self.assertRaises(ValueError):
                reviewed_anchors(blocks, [], {"blocks": changes})

    def test_voice_bank_rejects_another_speakers_folder_or_checkpoint(self):
        manifest = {"speaker": "Jared Kirkwood", "speakerKey": "jared_kirkwood"}
        training = {**manifest, "status": "training_smoke_completed"}
        validate_speaker_identity(manifest, training, "jared_kirkwood", "Jared Kirkwood")
        for index in [0, 1]:
            records = copy.deepcopy([manifest, training])
            records[index].update(speaker="Christine Caine", speakerKey="christine_caine")
            with self.assertRaises(ValueError):
                validate_speaker_identity(*records, "jared_kirkwood", "Jared Kirkwood")


if __name__ == "__main__":
    unittest.main()

"""Playback-placement boundaries and review binding; no real media/model calls."""
import copy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from check_weekly_timing import budgets, load_anchors, load_placements
from poc import sha256, write_json
from run_weekly_dubbing import validate_candidate, validate_timing
from test_resume_integrity import candidate_fixture, modify, snapshot
import test_review_integrity as review_fixtures
from weekly_dubbing import read, validate_review


def placement_review(work, job, block_id=1, anchor_start=5, playback_start=4.2):
    evidence = work / "gap-evidence.json"
    write_json(evidence, {"status": "synthetic_acoustic_gap_fixture", "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"]})
    path = work / "synchronization/placement-model-review.json"
    write_json(path, {"schemaVersion": "sermon-playback-placement-review-v1", "reviewType": "model", "model": "gpt-6-astra",
        "humanApproval": False, "status": "approved_for_candidate_playback", "reviewedBy": "fixture model reviewer", "reviewedAt": "2026-09-06T00:00:00Z",
        "jobSha256": sha256(work / "job.json"), "renderSha256": sha256(work / "render/report.json"),
        "alignmentSha256": sha256(work / "source-alignment/report.json"), "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"],
        "unresolvedPlacementIssues": [], "evidence": [{"path": str(evidence), "sha256": sha256(evidence)}],
        "blocks": [{"blockId": block_id, "sourceAnchorStart": anchor_start, "playbackStart": playback_start,
            "status": "model_supported", "reason": "Fixture permits a short lead inside the prior acoustic gap"}]})
    return path


class PlaybackPlacementTests(unittest.TestCase):
    def fixture(self, work, start=4.2):
        candidate_fixture(work)
        job, render = read(work / "job.json"), read(work / "render/report.json")
        path = placement_review(work, job, playback_start=start)
        anchors, _ = load_anchors(work, job, sha256(work / "job.json"))
        return job, render, anchors, path

    def save_timing(self, work, job, render, anchors):
        placements, digest = load_placements(work, job, render, anchors)
        rows, failures = budgets(job["blocks"], anchors, render["cues"], job["sourceDurationSeconds"], placements)
        modify(work, "synchronization/report.json", lambda d: d.update(blocks=rows, failures=failures,
            status="needs_timing_review" if failures else "natural_timing_fits", placementReviewSha256=digest))

    def test_reviewed_lead_keeps_source_anchor_and_old_audio_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            job, render, anchors, path = self.fixture(work)
            before, old_anchors = snapshot(work), copy.deepcopy(anchors)
            with patch("subprocess.run", side_effect=AssertionError("No model/SSH calls")):
                placements, digest = load_placements(work, job, render, anchors)
                rows, failures = budgets(job["blocks"], anchors, render["cues"], 10, placements)
            self.assertEqual(placements, {1: 4.2})
            self.assertEqual(digest, sha256(path))
            self.assertEqual(failures, [])
            self.assertEqual(rows[1]["videoStart"], 4.2)
            self.assertEqual(rows[1]["sourceAnchorStart"], 5)
            self.assertEqual(rows[1]["playbackLeadSeconds"], .8)
            self.assertEqual(rows[1]["placementReviewType"], "model")
            self.assertEqual(anchors, old_anchors)
            self.assertEqual(snapshot(work), before)

    def test_one_second_and_previous_english_end_are_hard_boundaries(self):
        for start, accepted in [(4, True), (4.2, True), (5, True), (3.9999, False), (5.01, False), (-.1, False), (None, False), ("4.2", False), (float("nan"), False), (float("inf"), False)]:
            with self.subTest(start=start), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, render, anchors, _ = self.fixture(work, start)
                if accepted:
                    self.assertEqual(load_placements(work, job, render, anchors)[0], {1: start})
                else:
                    with self.assertRaises(ValueError):
                        load_placements(work, job, render, anchors)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            job, render, anchors, path = self.fixture(work, 4.2)
            anchors[0]["end"] = 4.3
            with self.assertRaisesRegex(ValueError, "prior source speech"):
                load_placements(work, job, render, anchors)
            anchors[0]["end"] = 3
            modify(work, "synchronization/placement-model-review.json", lambda d: d["blocks"][0].update(playbackStart=3.99))
            with self.assertRaisesRegex(ValueError, "one second"):
                load_placements(work, job, render, anchors)

    def test_boolean_is_not_a_playback_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            job, render, anchors, _ = self.fixture(work)
            anchors[0]["start"] = 1.5
            placement_review(work, job, block_id=0, anchor_start=1.5, playback_start=True)
            with self.assertRaises(ValueError):
                load_placements(work, job, render, anchors)

    def test_following_lead_tightens_prior_chinese_budget_and_can_block_assembly(self):
        blocks = [{"id": 0, "en": "First", "zh": "第一"}, {"id": 1, "en": "Second", "zh": "第二"}]
        anchors = [{"blockId": 0, "start": 0, "end": 4, "issues": []}, {"blockId": 1, "start": 5, "end": 9, "issues": []}]
        cues = [{"blockId": 0, "start": 0, "end": 4.6}, {"blockId": 1, "start": 5.05, "end": 7.05}]
        before = copy.deepcopy((anchors, cues))
        self.assertEqual(budgets(blocks, anchors, cues, 10)[1], [])
        rows, failures = budgets(blocks, anchors, cues, 10, {1: 4.2})
        self.assertEqual(rows[0]["videoEnd"], 4.2)
        self.assertEqual(rows[0]["availableSeconds"], 4.2)
        self.assertEqual(rows[0]["naturalSeconds"], 4.6)
        self.assertEqual(rows[1]["availableSeconds"], 5.8)
        self.assertEqual(failures, [{"blockId": 0, "reason": "natural_chinese_exceeds_video_slot", "overflowSeconds": .4}])
        self.assertEqual((anchors, cues), before)

    def test_point_eight_second_tail_example_preserves_measured_english_anchor(self):
        blocks = [{"id": 53, "en": "Previous English", "zh": "上一段"}, {"id": 54, "en": "Final English", "zh": "末段"}]
        anchors = [{"blockId": 53, "start": 1760, "end": 1767.9, "issues": []}, {"blockId": 54, "start": 1768.88, "end": 1770, "issues": []}]
        cues = [{"blockId": 53, "start": 0, "end": 7}, {"blockId": 54, "start": 7.45, "end": 13.65}]
        rows, failures = budgets(blocks, anchors, cues, 1775, {54: 1768.08})
        self.assertEqual(failures, [])
        self.assertEqual(rows[1]["sourceAnchorStart"], 1768.88)
        self.assertEqual(rows[1]["videoStart"], 1768.08)
        self.assertEqual(rows[1]["playbackLeadSeconds"], .8)
        self.assertEqual(anchors[1]["start"], 1768.88)
        self.assertEqual(rows[0]["videoEnd"], 1768.08)

    def test_model_identity_and_frozen_input_hashes_cannot_be_changed(self):
        changes = [{"schemaVersion": "other-schema"}, {"reviewType": "human"}, {"model": "other-model"}, {"humanApproval": True},
            {"status": "pending"}, {"reviewedBy": None}, {"reviewedAt": None}, {"jobSha256": "other-job"},
            {"renderSha256": "other-render"}, {"alignmentSha256": "other-alignment"}, {"sourceAudioSha256": "other-source"},
            {"unresolvedPlacementIssues": ["gap uncertain"]}, {"evidence": []}]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, render, anchors, path = self.fixture(work)
                data = read(path)
                data.update(change)
                write_json(path, data)
                with self.assertRaises(ValueError):
                    load_placements(work, job, render, anchors)

    def test_every_placement_needs_distinct_evidence_and_known_supported_block(self):
        changes = [lambda d: d.update(blocks=[]), lambda d: d["blocks"][0].update(blockId=999),
            lambda d: d["blocks"].append(copy.deepcopy(d["blocks"][0])), lambda d: d["blocks"][0].update(status="pending"),
            lambda d: d["blocks"][0].update(reason=""), lambda d: d["blocks"][0].update(sourceAnchorStart=4.9),
            lambda d: d["evidence"].append(copy.deepcopy(d["evidence"][0])), lambda d: d["evidence"][0].update(sha256="stale")]
        for i, change in enumerate(changes):
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, render, anchors, path = self.fixture(work)
                data = read(path)
                change(data)
                write_json(path, data)
                with self.assertRaises(ValueError):
                    load_placements(work, job, render, anchors)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            job, render, anchors, _ = self.fixture(work)
            (work / "gap-evidence.json").write_text("changed acoustic gap evidence")
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                load_placements(work, job, render, anchors)

    def test_replaced_job_render_or_alignment_invalidates_saved_review(self):
        for target in ["job.json", "render/report.json", "source-alignment/report.json"]:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, render, anchors, _ = self.fixture(work)
                modify(work, target, lambda d: d.update(replacedFixture=True))
                with self.assertRaisesRegex(ValueError, "incomplete or stale"):
                    load_placements(work, job, render, anchors)

    def test_changed_added_removed_or_revoked_placement_invalidates_timing(self):
        for mode in ["changed", "added", "removed", "revoked", "summary_hash", "summary_budget"]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                job, render, anchors, path = self.fixture(work)
                if mode != "added":
                    self.save_timing(work, job, render, anchors)
                    validate_timing(work, job, render)
                if mode == "changed":
                    modify(work, "synchronization/placement-model-review.json", lambda d: d.update(reviewedAt="2026-09-07T00:00:00Z"))
                elif mode == "removed":
                    path.unlink()
                elif mode == "revoked":
                    modify(work, "synchronization/placement-model-review.json", lambda d: d.update(status="revoked"))
                elif mode == "summary_hash":
                    modify(work, "synchronization/report.json", lambda d: d.update(placementReviewSha256="old-review"))
                elif mode == "summary_budget":
                    modify(work, "synchronization/report.json", lambda d: d["blocks"][0].update(videoEnd=5))
                with self.assertRaises(ValueError):
                    validate_timing(work, job, render)

    def test_valid_placement_candidate_does_not_approve_human_audio_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            job, render, anchors, path = self.fixture(work)
            self.save_timing(work, job, render, anchors)
            with patch("subprocess.run", side_effect=AssertionError("No model/SSH calls")):
                validate_candidate(work)
            self.assertFalse(read(path)["humanApproval"])
            self.assertFalse(read(work / "audio-review.json")["humanApproval"])
            with self.assertRaisesRegex(ValueError, "Human audio review"):
                validate_review(work)

    def test_legacy_approved_release_without_placements_keeps_original_completion_gate(self):
        module = types.ModuleType("scripts.run_codex_local_sermon_production")
        module.local_completion_artifacts = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {module.__name__: module}):
            work = review_fixtures.ReviewIntegrityTests().fixture(Path(tmp))
            job, render = read(work / "job.json"), read(work / "render/report.json")
            anchors, _ = load_anchors(work, job, sha256(work / "job.json"))
            self.assertEqual(load_placements(work, job, render, anchors), ({}, None))
            validate_review(work)
            module.local_completion_artifacts.assert_called_once()
            self.assertEqual(read(work / "saturday-completion.json")["status"], "completed")


if __name__ == "__main__":
    unittest.main()

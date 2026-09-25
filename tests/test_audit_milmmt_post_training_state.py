import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_milmmt_post_training_state.py"
SPEC = importlib.util.spec_from_file_location("audit_milmmt_post_training_state", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuditMiLMMTStateTest(unittest.TestCase):
    def test_audit_keeps_provider_output_training_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = [
                MODULE.DATASET_ROOT / "train.jsonl",
                MODULE.DATASET_ROOT / "dev.jsonl",
                MODULE.CANARY_PATH,
                MODULE.PROMOTED_PATH,
                MODULE.PRE_FILTER_PATH,
                MODULE.V3_ROOT / "train.jsonl",
            ]
            for relative in inputs:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            split = root / MODULE.SPLIT_PATH
            split.parent.mkdir(parents=True, exist_ok=True)
            split.write_text(json.dumps({"sermons": [], "candidateCount": 0}))

            report = MODULE.audit(root)
            self.assertEqual(report["authorizationGates"]["externalStudentTrainingEligibility"], "blocked")
            self.assertEqual(
                report["authorizationGates"]["providerOutputForExternalStudent"],
                "blocked_pending_explicit_authorization",
            )
            self.assertEqual(
                report["authorizationGates"]["sourceTrainingRights"],
                "requires_separate_authorization_receipt",
            )

    def test_length_distribution_exposes_long_chunk_only_canary(self):
        rows = [{"id": str(i), "sermonId": "s", "en": "word " * 140,
                 "startMs": i * 60000, "endMs": i * 60000 + 55000,
                 "teacherPipeline": {"humanApprovalClaimed": False}} for i in range(500)]
        result = MODULE.corpus_summary(rows)
        self.assertEqual(result["englishWords"]["p50"], 140)
        self.assertEqual(result["durationBins"]["gt40"], 500)
        self.assertEqual(result["durationBins"]["le8"], 0)
        self.assertFalse(result["humanApprovalVerified"])

    def test_conflicting_correction_is_not_hidden_by_repetition(self):
        base = [{"id": "s_1", "sermonId": "s", "en": "A gave B.", "zh": "甲给乙。"}]
        promoted = [{"id": "c_1", "sourceSegmentId": "s_1", "sourceSermonId": "s",
                     "sourceEn": "A  gave B.", "v2ReviewedTargetZh": "乙给甲。",
                     "trainingEligibility": "eligible_v2_sol_corrected"}]
        result = MODULE.corrective_conflicts(base, promoted)
        self.assertEqual(result["conflictingCorrectionRows"], 1)
        self.assertEqual(result["conflicts"][0]["baseIds"], ["s_1"])
        self.assertNotIn("乙给甲", json.dumps(result, ensure_ascii=False))
        repeated = [{"input": "A", "output": "old"}] + [{"input": "A", "output": "new"}] * 3
        supervision = MODULE.supervision_groups(repeated, "input", "output")
        self.assertEqual(supervision["sourceGroupsWithMultipleTargets"], 1)
        self.assertEqual(supervision["extraSourceExposures"], 3)

    def test_metadata_audit_keeps_untouched_bilingual_artifacts_sealed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_id = "heldout"
            source_path = root / MODULE.V4_SOURCE_ROOT / video_id / "segments.en.jsonl"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b'{"id":"s1","en":"sealed source"}\n')
            source_hash = MODULE.file_evidence(source_path)["sha256"]
            manifest = {"candidateCount": 1, "sermons": [{"videoId": video_id,
                "split": "untouched_final_v4", "segmentCount": 1,
                "sourcePath": str(source_path.relative_to(root)), "sourceSha256": source_hash}]}
            manifest_path = root / MODULE.SPLIT_PATH
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(manifest))
            report_dir = root / MODULE.V4_REFERENCE_ROOT / video_id
            report_dir.mkdir(parents=True)
            (report_dir / "run-report.json").write_text(json.dumps({
                "status": MODULE.FINAL_REPORT_STATUS, "sourceSha256": source_hash,
                "segmentCount": 1, "selectedSegmentIds": ["s1"], "humanApprovalClaimed": False}))
            (report_dir / "selective-audio-audit-report.json").write_text(json.dumps({
                "status": "selective_audio_audit_completed", "totalSegmentCount": 1,
                "selectedSegmentCount": 1, "decisionCounts": {"audio_evidence_supports_caption": 1}}))
            final_path = report_dir / "segments.codex.final.jsonl"
            final_path.write_text("this must never be read")
            original_open = Path.open

            def forbid_final(path, *args, **kwargs):
                if path == final_path:
                    raise AssertionError("untouched bilingual content was opened")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", forbid_final):
                result = MODULE.audit_v4(root, {video_id}, set())
            self.assertTrue(result["allSourceHashesMatch"])
            self.assertEqual(result["textReviewCompletedSermons"], 1)
            self.assertEqual(result["solHighAudioCompletedSermons"], 0)
            self.assertEqual(result["existingTrainDevOverlap"], [video_id])
            self.assertFalse(result["untouchedBilingualArtifactsOpened"])

            source_path.write_bytes(b'{"id":"s1","en":"changed"}\n')
            result = MODULE.audit_v4(root, set(), set())
            self.assertFalse(result["allSourceHashesMatch"])
            (report_dir / "run-report.json").unlink()
            result = MODULE.audit_v4(root, set(), set())
            self.assertEqual(result["textReviewCompletedSermons"], 0)
            self.assertTrue(result["missingReportsOrSources"])

    def test_empty_hash_prefix_is_not_a_hash_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonempty"
            path.write_text("data")
            result = MODULE.file_evidence(path)
            self.assertNotEqual(result["sha256"], MODULE.digest(""))
            self.assertEqual(result["nonemptyLineCount"], 1)

    def test_overlay_reports_source_reintroduced_after_audio_exclusion(self):
        promoted = [{"id": "c1", "sourceSegmentId": "s1", "sourceSermonId": "s",
                     "sourceEn": "English", "v2ReviewedTargetZh": "中文",
                     "trainingEligibility": "eligible_v2_sol_reviewed"}]
        prior = [{"id": "s1", "severity": "needs_audio_review",
                  "audioAuditStatus": "completed_model_only_supports_caption"}]
        report = MODULE.corrective_conflicts([], promoted, prior)
        self.assertEqual(report["promotedRowsAbsentFromAdmittedBase"], 1)
        self.assertEqual(report["unadmittedSources"][0]["severity"], "needs_audio_review")


if __name__ == "__main__":
    unittest.main()

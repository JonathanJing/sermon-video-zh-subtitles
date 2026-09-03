import copy
import importlib.util
from pathlib import Path
import sys
import unittest


EXPORT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_sermon_parallel_review_bundle.py"
EXPORT_SPEC = importlib.util.spec_from_file_location("export_sermon_parallel_review_bundle", EXPORT_PATH)
export = importlib.util.module_from_spec(EXPORT_SPEC)
assert EXPORT_SPEC.loader is not None
sys.modules[EXPORT_SPEC.name] = export
EXPORT_SPEC.loader.exec_module(export)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_sermon_parallel_quality_catalog.py"
SPEC = importlib.util.spec_from_file_location("build_sermon_parallel_quality_catalog", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class BuildSermonParallelQualityCatalogTest(unittest.TestCase):
    def item(self, boundary_approved=False, priority="normal"):
        item = {
            "schemaVersion": export.REVIEW_SCHEMA_VERSION,
            "reviewItemId": "s_seg_1",
            "sermonId": "s",
            "segmentId": "s_seg_1",
            "split": "poc",
            "priority": priority,
            "issues": [export.GENERIC_NORMAL_ISSUE] if hasattr(export, "GENERIC_NORMAL_ISSUE") else ["human_approval_required_for_all_poc_segments"],
            "source": {
                "captionKind": "youtube_automatic",
                "reviewStatus": "unreviewed_raw",
                "manifestSha256": "a" * 64,
                "cuesSha256": "b" * 64,
                "textSha256": export.corpus.sha256_bytes(b"Hello"),
                "cueIds": ["cue_1"],
                "startMs": 0,
                "endMs": 1000,
                "english": "Hello",
            },
            "candidate": {
                "chinese": "你好",
                "chineseSha256": export.corpus.sha256_bytes("你好".encode()),
                "contentType": "sermon",
                "scriptureRefs": [],
                "scriptureAlignments": [],
                "properNouns": [],
                "modelFlags": [],
                "modelNotes": [],
                "teacher": {"provider": "openai", "model": "gpt-5.6-sol", "promptVersions": ["v1"], "provenance": "gpt_isolated_nontrainable"},
                "modelReviewStatus": "model_reviewed_requires_human",
            },
            "boundary": {
                "status": "approved_human_boundary" if boundary_approved else "model_candidate_requires_human_review",
                "contentScope": "sermon_only",
                "approvedByHuman": boundary_approved,
                "startCueId": "cue_1",
                "endCueId": "cue_1",
                "boundarySha256": "c" * 64,
            },
            "reviewStatus": "pending_human",
            "trainingEligibility": "blocked",
        }
        item["reviewPayloadSha256"] = export.review_payload_sha256(item)
        return item

    def decision(self, item):
        value = export.decision_template(item)
        value.update(
            {
                "status": "approved",
                "reviewer": "Reviewer",
                "reviewerRole": "bilingual_reviewer",
                "reviewedAt": "2026-08-31T12:00:00-07:00",
                "audioChecked": True,
                "englishDecision": "keep",
                "chineseDecision": "keep",
                "scriptureChecked": True,
                "properNounsChecked": True,
                "numbersChecked": True,
                "adjudicationComplete": True,
            }
        )
        return value

    def test_normal_item_becomes_silver_only_after_boundary_approval(self):
        blocked = mod.released_segment(self.item(False), None)
        self.assertEqual(blocked["qualityTier"], "isolated_reference")
        silver = mod.released_segment(self.item(True), None)
        self.assertEqual(silver["qualityTier"], "silver_automatic_candidate")
        self.assertEqual(silver["trainingEligibility"], "blocked")

    def test_human_content_requires_boundary_for_gold(self):
        item = self.item(False)
        reviewed = mod.released_segment(item, self.decision(item))
        self.assertEqual(reviewed["qualityTier"], "human_reviewed_boundary_blocked")
        approved_item = self.item(True)
        gold = mod.released_segment(approved_item, self.decision(approved_item))
        self.assertEqual(gold["qualityTier"], "gold_human_reviewed")
        self.assertEqual(gold["reviewStatus"], "human_approved")

    def test_decision_hash_binding_rejects_mutated_item(self):
        item = self.item(True)
        decision = self.decision(item)
        mutated = copy.deepcopy(item)
        mutated["candidate"]["chinese"] = "改变"
        mutated["candidate"]["chineseSha256"] = export.corpus.sha256_bytes("改变".encode())
        mutated["reviewPayloadSha256"] = export.review_payload_sha256(mutated)
        with self.assertRaises(ValueError):
            mod.validate_human_decision(mutated, decision)

    def test_silver_calibration_rejects_nonapproved_normal_decision(self):
        item = self.item(True)
        decision = self.decision(item)
        decision["status"] = "changes_required"
        decision["materialErrorTypes"] = []
        silver, risk = mod.calibration_summaries(
            [item], {item["reviewItemId"]: decision}
        )
        self.assertEqual(silver["status"], "fail")
        self.assertEqual(silver["normalNonApproved"], 1)
        self.assertEqual(risk["status"], "pass")

    def test_silver_calibration_is_pending_until_all_normals_are_reviewed(self):
        items = [self.item(True), self.item(True)]
        items[1]["reviewItemId"] = "s_seg_2"
        items[1]["segmentId"] = "s_seg_2"
        items[1]["reviewPayloadSha256"] = export.review_payload_sha256(items[1])
        decision = self.decision(items[0])
        silver, risk = mod.calibration_summaries(
            items, {items[0]["reviewItemId"]: decision}
        )
        self.assertEqual(silver["status"], "pending")
        self.assertEqual(risk["status"], "pending")


if __name__ == "__main__":
    unittest.main()

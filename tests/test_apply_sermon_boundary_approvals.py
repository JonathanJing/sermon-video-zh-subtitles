import importlib.util
from pathlib import Path
import sys
import unittest


PREPARE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_sermon_boundary_reviews.py"
PREPARE_SPEC = importlib.util.spec_from_file_location("prepare_sermon_boundary_reviews", PREPARE_PATH)
prepare = importlib.util.module_from_spec(PREPARE_SPEC)
assert PREPARE_SPEC.loader is not None
sys.modules[PREPARE_SPEC.name] = prepare
PREPARE_SPEC.loader.exec_module(prepare)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "apply_sermon_boundary_approvals.py"
SPEC = importlib.util.spec_from_file_location("apply_sermon_boundary_approvals", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ApplySermonBoundaryApprovalsTest(unittest.TestCase):
    def setUp(self):
        self.cues = [
            {"cueId": "cue_1", "startMs": 0, "endMs": 1000, "text": "Hello."},
            {"cueId": "cue_2", "startMs": 1000, "endMs": 2000, "text": "Sermon."},
            {"cueId": "cue_3", "startMs": 2000, "endMs": 3000, "text": "Amen."},
        ]
        receipt = {
            "sourceManifest": {"sha256": "a" * 64},
            "sourceCues": {"sha256": "b" * 64},
        }
        v1 = {
            "startCueId": "cue_2",
            "startMs": 1000,
            "startReason": "old",
            "endCueId": "cue_3",
            "endMs": 3000,
            "endReason": "end",
            "promptVersion": "v1",
        }
        v2 = {
            "startCueId": "cue_1",
            "startMs": 0,
            "startReason": "complete",
            "endCueId": "cue_3",
            "endMs": 3000,
            "endReason": "end",
            "confidence": 0.9,
        }
        self.packet = prepare.build_packet(
            video_id="video",
            source_receipt=receipt,
            boundary_v1=v1,
            boundary_v2=v2,
            cues=self.cues,
        )
        self.decision = {
            **prepare.decision_template(self.packet),
            "status": "approved",
            "selectedStartCueId": "cue_1",
            "selectedEndCueId": "cue_3",
            "approver": "Human Reviewer",
            "approvedAt": "2026-08-30T12:00:00-07:00",
            "audioReviewCompleted": True,
            "decisionReason": "Checked against source audio.",
        }

    def apply(self, decision=None, source_hash=None):
        return mod.validate_decision(
            packet=self.packet,
            decision=decision or self.decision,
            cues=self.cues,
            actual_source_cues_sha256=source_hash or "b" * 64,
        )

    def test_valid_decision_produces_hash_bound_human_approval(self):
        approval = self.apply()
        self.assertTrue(approval["approvedByHuman"])
        self.assertEqual(approval["status"], "approved_human_boundary")
        self.assertEqual(approval["startCueId"], "cue_1")
        self.assertEqual(approval["trainingEligibility"], "blocked")

    def test_pending_template_is_rejected(self):
        with self.assertRaises(ValueError):
            self.apply(prepare.decision_template(self.packet))

    def test_wrong_source_hash_is_rejected(self):
        with self.assertRaises(ValueError):
            self.apply(source_hash="c" * 64)

    def test_unreviewed_cue_is_rejected(self):
        decision = dict(self.decision)
        decision["selectedStartCueId"] = "cue_999"
        with self.assertRaises(ValueError):
            self.apply(decision)

    def test_timezone_is_required(self):
        decision = dict(self.decision)
        decision["approvedAt"] = "2026-08-30T12:00:00"
        with self.assertRaises(ValueError):
            self.apply(decision)


if __name__ == "__main__":
    unittest.main()

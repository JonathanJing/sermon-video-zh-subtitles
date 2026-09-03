import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_sermon_boundary_reviews.py"
SPEC = importlib.util.spec_from_file_location("prepare_sermon_boundary_reviews", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class PrepareSermonBoundaryReviewsTest(unittest.TestCase):
    def cues(self):
        return [
            {"cueId": "cue_1", "startMs": 0, "endMs": 1000, "text": "Welcome."},
            {"cueId": "cue_2", "startMs": 1000, "endMs": 2000, "text": "Today I"},
            {"cueId": "cue_3", "startMs": 2000, "endMs": 3000, "text": "begin the sermon."},
            {"cueId": "cue_4", "startMs": 3000, "endMs": 4000, "text": "Amen."},
            {"cueId": "cue_5", "startMs": 4000, "endMs": 5000, "text": "Music."},
        ]

    def packet(self):
        receipt = {
            "sourceManifest": {"sha256": "a" * 64},
            "sourceCues": {"sha256": "b" * 64},
        }
        v1 = {
            "startCueId": "cue_3",
            "startMs": 2000,
            "startReason": "fragment",
            "endCueId": "cue_4",
            "endMs": 4000,
            "endReason": "prayer",
            "promptVersion": "v1",
        }
        v2 = {
            "startCueId": "cue_2",
            "startMs": 1000,
            "startReason": "complete unit",
            "endCueId": "cue_4",
            "endMs": 4000,
            "endReason": "prayer",
            "confidence": 0.9,
        }
        return mod.build_packet(
            video_id="video",
            source_receipt=receipt,
            boundary_v1=v1,
            boundary_v2=v2,
            cues=self.cues(),
        )

    def test_packet_is_hash_bound_and_never_approved(self):
        packet = self.packet()
        self.assertEqual(packet["status"], "requires_operator_review")
        self.assertFalse(packet["approvedByHuman"])
        self.assertTrue(packet["candidateChanged"]["start"])
        mod.validate_review_packet(packet)

    def test_packet_hash_detects_mutation(self):
        packet = self.packet()
        packet["boundaryCandidateV2"]["startCueId"] = "cue_1"
        with self.assertRaises(ValueError):
            mod.validate_review_packet(packet)

    def test_decision_template_cannot_be_mistaken_for_approval(self):
        template = mod.decision_template(self.packet())
        self.assertEqual(template["status"], "pending_operator_input")
        self.assertEqual(template["selectedStartCueId"], "")
        self.assertFalse(template["audioReviewCompleted"])
        self.assertTrue(template["reviewPayloadSha256"])

    def test_markdown_marks_both_candidates_without_claiming_approval(self):
        markdown = mod.render_review_markdown(self.packet())
        self.assertIn("requires_operator_review", markdown)
        self.assertIn("`cue_3`", markdown)
        self.assertIn("v2", markdown)
        self.assertNotIn("approved_human_boundary", markdown)


if __name__ == "__main__":
    unittest.main()

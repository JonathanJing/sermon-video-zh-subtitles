import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_sermon_parallel_review_bundle.py"
SPEC = importlib.util.spec_from_file_location("export_sermon_parallel_review_bundle", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ExportSermonParallelReviewBundleTest(unittest.TestCase):
    def item(self):
        item = {
            "schemaVersion": mod.REVIEW_SCHEMA_VERSION,
            "reviewItemId": "s_seg_1",
            "sermonId": "s",
            "segmentId": "s_seg_1",
            "split": "poc",
            "priority": "normal",
            "issues": ["human_approval_required_for_all_poc_segments"],
            "source": {
                "captionKind": "youtube_automatic",
                "reviewStatus": "unreviewed_raw",
                "manifestSha256": "a" * 64,
                "cuesSha256": "b" * 64,
                "textSha256": mod.corpus.sha256_bytes(b"Hello"),
                "cueIds": ["cue_1"],
                "startMs": 0,
                "endMs": 1000,
                "english": "Hello",
            },
            "candidate": {
                "chinese": "你好",
                "chineseSha256": mod.corpus.sha256_bytes("你好".encode()),
                "contentType": "sermon",
                "scriptureRefs": [],
                "scriptureAlignments": [],
                "properNouns": [],
                "modelFlags": [],
                "modelNotes": [],
                "teacher": {
                    "provider": "openai",
                    "model": "gpt-5.6-sol",
                    "promptVersions": ["v1"],
                    "provenance": "gpt_isolated_nontrainable",
                },
                "modelReviewStatus": "model_reviewed_requires_human",
            },
            "boundary": {
                "status": "model_candidate_requires_human_review",
                "contentScope": "sermon_only",
                "approvedByHuman": False,
                "startCueId": "cue_1",
                "endCueId": "cue_1",
                "boundarySha256": "c" * 64,
            },
            "reviewStatus": "pending_human",
            "trainingEligibility": "blocked",
        }
        item["reviewPayloadSha256"] = mod.review_payload_sha256(item)
        return item

    def test_review_item_hash_detects_mutation(self):
        item = self.item()
        mod.validate_review_item(item)
        item["candidate"]["chinese"] = "篡改"
        with self.assertRaises(ValueError):
            mod.validate_review_item(item)

    def test_decision_template_is_prefilled_but_not_approved(self):
        template = mod.decision_template(self.item())
        self.assertEqual(template["status"], "pending_human_input")
        self.assertEqual(template["approvedEnglish"], "Hello")
        self.assertEqual(template["approvedChinese"], "你好")
        self.assertFalse(template["audioChecked"])


if __name__ == "__main__":
    unittest.main()

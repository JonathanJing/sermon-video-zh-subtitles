"""CUV evidence must survive the existing spoken-review acceptance boundary."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

POC = Path(__file__).resolve().parents[1] / "experiments/sermon-dubbing-poc"
sys.path.insert(0, str(POC))
from apply_spoken_review import CHECKS, SCHEMA, make_units, reviewed_blocks
from spoken_text import NUMBER_VERSION, VERSION


class CuvDubbingGateTests(unittest.TestCase):
    def test_new_cuv_units_keep_closing_quotes_with_their_spoken_sentence(self):
        text = "「" + "经文" * 60 + "。」"
        blocks = [{"id": 0, "en": "Fixture quotation.", "zh": text}]
        current = make_units(blocks, pronunciation_rule_version=VERSION)
        previous = make_units(blocks, pronunciation_rule_version=NUMBER_VERSION)
        self.assertEqual([u["text"] for u in current], [text])
        self.assertEqual([u["text"] for u in previous], [text[:-1], "」"])

    def test_cuv_extension_cannot_use_legacy_checks_to_accept_unverified_text(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            block = {"id": 0, "en": "Do not be afraid.", "zh": "不要害怕。"}
            job = parent / "job.json"
            job.write_text(json.dumps({"blocks": [block]}))
            proof = parent / "legacy-proof.txt"
            proof.write_text("Existing narrative review evidence")
            sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            review = {"schemaVersion": SCHEMA, "parentJobSha256": sha(job),
                "reviewType": "model", "model": "gpt-6-astra", "humanApproval": False,
                "status": "approved_for_synthesis", "reviewedAt": "2026-09-13T00:00:00Z",
                "reviewedBy": "fixture", "authority": "user_directed_conversation_review",
                "reviewedBlockIds": [0], "checks": dict.fromkeys(CHECKS, "pass"),
                "unresolvedTextIssues": [], "evidence": [{"path": str(proof), "sha256": sha(proof)}],
                "blocks": []}
            path = parent / "review.json"
            path.write_text(json.dumps(review))
            self.assertEqual(reviewed_blocks(parent, path), [block])
            # All old checks still pass, but an invalid new CUV proof must fail.
            review["cuvTranslation"] = {"schemaVersion": "sermon-cuv-translation-v1",
                "report": {"path": str(proof), "sha256": "0" * 64}}
            path.write_text(json.dumps(review))
            with self.assertRaisesRegex(ValueError, "Bound input changed"):
                reviewed_blocks(parent, path)


if __name__ == "__main__":
    unittest.main()

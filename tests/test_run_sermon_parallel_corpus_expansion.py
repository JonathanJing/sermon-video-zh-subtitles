import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_sermon_parallel_corpus_expansion.py"
SPEC = importlib.util.spec_from_file_location("run_sermon_parallel_corpus_expansion", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class ExpansionTest(unittest.TestCase):
    def test_audit_schema_has_three_severities(self):
        schema = mod.audit_schema()
        enum = schema["properties"]["segments"]["items"]["properties"]["severity"]["enum"]
        self.assertEqual(enum, ["pass", "needs_audio_review", "must_fix"])

    def test_selection_refuses_poc_and_test(self):
        rows = [
            {"videoId": "p", "split": "poc", "splitRankSha256": "0"},
            {"videoId": "t", "split": "test", "splitRankSha256": "1"},
            {"videoId": "d", "split": "dev", "splitRankSha256": "2"},
            {"videoId": "r", "split": "train", "splitRankSha256": "3"},
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            selected, completed = mod.select_pending(rows, Path(tempdir), 10)
        self.assertFalse(completed)
        self.assertEqual([item["videoId"] for item in selected], ["d", "r"])

    def test_explicit_selection_is_still_checked_by_split_preflight(self):
        rows = [
            {"videoId": "test-only", "split": "test", "splitRankSha256": "1"},
            {"videoId": "train-only", "split": "train", "splitRankSha256": "2"},
        ]
        by_id = {item["videoId"]: item for item in rows}
        self.assertNotIn(by_id["test-only"]["split"], mod.ALLOWED_SPLITS)
        self.assertIn(by_id["train-only"]["split"], mod.ALLOWED_SPLITS)

    def test_completed_audit_requires_hash_bindings(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            final = {
                "id": "v_seg_0001",
                "sermonId": "v",
                "split": "train",
                "en": "God is good.",
                "zh": "神是良善的。",
                "sourceTextSha256": mod.corpus.sha256_bytes(b"God is good."),
            }
            mod.corpus.write_jsonl(root / "segments.zh.final.jsonl", [final])
            mod.corpus.write_jsonl(
                root / "model-second-pass-audit.jsonl",
                [
                    {
                        "segmentId": final["id"],
                        "inputBindings": mod.segment_binding(final),
                    }
                ],
            )
            mod.corpus.write_json(
                root / "model-second-pass-report.json",
                {"auditStatus": "completed_model_only_no_state_change"},
            )
            self.assertTrue(mod.audit_is_complete(root))
            audit = json.loads((root / "model-second-pass-audit.jsonl").read_text())
            audit["inputBindings"]["candidateChineseSha256"] = "wrong"
            mod.corpus.write_jsonl(root / "model-second-pass-audit.jsonl", [audit])
            self.assertFalse(mod.audit_is_complete(root))


if __name__ == "__main__":
    unittest.main()

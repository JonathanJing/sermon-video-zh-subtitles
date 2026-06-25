import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "write_worker_caption_first_plan.py"
SPEC = importlib.util.spec_from_file_location("write_worker_caption_first_plan", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class WriteWorkerCaptionFirstPlanTest(unittest.TestCase):
    def test_default_plan_publishes_captions_without_notes(self):
        report = mod.build_report(args_for())

        self.assertEqual(report["status"], "ok")
        self.assertEqual(
            report["stages"],
            [
                "model-access",
                "prepare",
                "translate",
                "export-captions",
                "validate-offline",
                "upload-playback",
                "upload-manifest",
                "promote",
            ],
        )
        self.assertFalse(report["notesIncluded"])
        self.assertTrue(report["promoteBeforeNotes"])
        self.assertEqual(report["translationMode"], "fresh_model_call")
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        rendered = json.dumps(report)
        self.assertNotIn("projects/PROJECT/secrets", rendered)

    def test_include_insights_appends_notes_after_promote(self):
        report = mod.build_report(args_for(include_insights=True))

        self.assertEqual(report["stages"][-2:], ["promote", "notes"])
        self.assertTrue(report["notesIncluded"])
        self.assertTrue(report["promoteBeforeNotes"])

    def test_translations_jsonl_marks_replay_mode_without_model_access(self):
        report = mod.build_report(args_for(translations_jsonl="/tmp/saved.jsonl"))

        self.assertEqual(report["translationMode"], "saved_jsonl_replay")
        self.assertNotIn("model-access", report["stages"])
        self.assertEqual(report["stages"][0], "prepare")
        self.assertEqual(report["stages"][-1], "promote")

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "worker-plan.json"
            original_argv = mod.__import__("sys").argv if False else sys.argv
            try:
                sys.argv = ["write_worker_caption_first_plan.py", "--out", str(out)]
                exit_code = mod.main()
            finally:
                sys.argv = original_argv

            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(written["status"], "ok")


def args_for(**overrides):
    values = {
        "sunday": "2026-06-28",
        "live_url": "https://www.youtube.com/watch?v=abc123",
        "session_id": "caption-first-plan",
        "artifact_bucket": "sermon-zh-artifacts-ai-for-god",
        "artifact_prefix": "sundays",
        "include_insights": False,
        "translations_jsonl": None,
        "out": None,
    }
    values.update(overrides)
    return Namespace(**values)


if __name__ == "__main__":
    unittest.main()

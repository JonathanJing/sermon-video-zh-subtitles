import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT_PATH = SCRIPT_DIR / "verify_youtube_sermon_caption_corpus.py"
SPEC = importlib.util.spec_from_file_location("verify_youtube_sermon_caption_corpus", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class VerifyYoutubeSermonCaptionCorpusTest(unittest.TestCase):
    def test_distribution_uses_interpolated_percentiles(self):
        result = mod.distribution([0.9, 1.0, 1.1])

        self.assertEqual(result["count"], 3)
        self.assertEqual(result["minimum"], 0.9)
        self.assertEqual(result["median"], 1.0)
        self.assertEqual(result["p95"], 1.09)
        self.assertEqual(result["maximum"], 1.1)

    def test_pending_asr_entry_is_metadata_only_and_requires_authorization(self):
        row = {
            "id": "video-id",
            "title": "A sermon",
            "webpage_url": "https://www.youtube.com/watch?v=video-id",
            "upload_date": "20260830",
            "duration": 1200,
            "classification": "standalone_main_sermon_vod",
            "observedAt": "2026-08-30T00:00:00Z",
            "englishCaptionStatus": "none",
            "manualEnglishCaptionTracks": [],
            "automaticEnglishCaptionTracks": [],
        }

        result = mod.pending_asr_entry(row, inventory=Path("inventory.jsonl"))

        self.assertEqual(result["status"], "pending_authorization")
        self.assertEqual(result["requiredNextStage"], "authorized_media_download_then_asr")
        self.assertFalse(result["mediaDownloaded"])
        self.assertNotIn("transcript", json.dumps(result).lower())

    def test_batch_audit_rejects_duplicate_completion_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            payload = {
                "status": "ok",
                "completedIds": ["one", "one"],
                "failed": [],
                "mediaDownloaded": False,
                "authenticatedSessionUsed": False,
            }
            (report_dir / "batch-1.json").write_text(json.dumps(payload), encoding="utf-8")
            errors = []

            result = mod.verify_batch_reports(report_dir, eligible_ids={"one"}, errors=errors)

            self.assertEqual(result["successfulCompletionEvents"], 2)
            self.assertIn("one", result["duplicateCompletionIds"])
            self.assertIn("duplicate_batch_completion_ids", {error["code"] for error in errors})


if __name__ == "__main__":
    unittest.main()

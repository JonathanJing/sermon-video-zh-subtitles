"""Source text is exported without regenerating audio or inventing alignment."""
import copy
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

import build_weekly_app as app
from test_build_weekly_app import app_fixture
from test_resume_integrity import snapshot
from weekly_dubbing import read


class BilingualTranscriptTests(unittest.TestCase):
    def test_real_export_keeps_frozen_english_and_audio_with_string_block_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            before = snapshot(work)
            with contextlib.redirect_stdout(io.StringIO()):
                app.build(root / "unused", root / "build", weekly_jobs=[work], review_preview=True)
            week = read(root / "build/public/weekly.json")["weeks"][0]
            blocks = week["transcript"]["blocks"]
            self.assertEqual([b["english"] for b in blocks], [b["en"] for b in read(work / "job.json")["blocks"]])
            self.assertEqual([b["blockId"] for b in blocks], ["0", "1"])
            self.assertEqual(blocks[0]["sourceTextOrigin"], "job.blocks")
            self.assertEqual(blocks[0]["reviewState"], "unspecified")
            self.assertEqual(week["tracks"][0]["cues"], read(work / "audio/library.json")["tracks"][0]["cues"])
            self.assertEqual(snapshot(work), before)

    def test_missing_english_is_not_back_translated_and_review_is_not_promoted(self):
        job = {"blocks": [{"id": 0, "zh": "中文", "en": " "}], "inheritedReview": {"readingQuality": "pass"}}
        result = app.bilingual_transcript(job, [{"cues": [{"blockId": 0}]}])
        self.assertNotIn("english", result["blocks"][0])
        self.assertEqual(result["blocks"][0]["reviewState"], "reading_quality_pass")

    def test_conflicting_or_unknown_ids_fail(self):
        job = {"blocks": [{"id": 0, "en": "Source"}]}
        for value in [True, {}, " ", "\n", "x" * 129]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.bilingual_transcript({"blocks": [{"id": value}]}, [])
        duplicate = copy.deepcopy(job)
        duplicate["blocks"].append({"id": "0", "en": "Another"})
        with self.assertRaises(ValueError):
            app.bilingual_transcript(duplicate, [])
        with self.assertRaises(ValueError):
            app.bilingual_transcript(job, [{"cues": [{"blockId": "other"}]}])

    def test_legacy_unlinked_cues_remain_unlinked(self):
        tracks = [{"cues": [{"text": "中文"}]}]
        app.bilingual_transcript({"blocks": [{"id": 0, "en": "Source"}]}, tracks)
        self.assertNotIn("blockId", tracks[0]["cues"][0])

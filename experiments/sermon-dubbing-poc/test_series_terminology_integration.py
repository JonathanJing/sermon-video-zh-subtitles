"""Synthetic dubbing/page integration; no paid models, media render or publish."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_weekly_app as app
import weekly_dubbing as weekly
from poc import sha256, write_json
import test_saturday_bridge as fixtures
from test_build_weekly_app import app_fixture
from scripts.series_terminology import context


class SeriesIntegrationTests(unittest.TestCase):
    def test_prepare_blocks_wrong_title_or_mismatched_outline_before_job_write(self):
        fixture = fixtures.SaturdayBridgeTests()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, _, _, run = fixture.fixture(root)
            pipeline = run / "pipeline"
            reading = pipeline / "reading-edition-v2/reading_blocks.final.json"
            quality = pipeline / "reading-edition-v2/reading_quality_report.json"
            outline = pipeline / "sermon-interpretation/insights/openai-notes.json"
            names = context()
            write_json(quality, {"status": "pass", "seriesTerminology": names})
            rows = [{"id": 0, "en": 'Our series titled "When Life Doesn’t Make Sense".', "zh": "我们的系列《当生活没有意义》。"}]
            write_json(reading, rows)
            auth = root / "authorization.json"
            write_json(auth, {"schemaVersion": "sermon-voice-authorization-v1", "statement": "Synthetic test authorization",
                "status": "confirmed_by_user", "purposes": ["chinese_dubbing"], "sources": [{"sourceId": fixture.source, "sha256": sha256(pipeline / "source_clip.m4a")}]})
            args = (run, root / "voice", root / "job", fixture.week, "标题", "Eric Geiger", "诗篇 1", auth)
            with patch.object(weekly, "probe", return_value={"durationSeconds": 10}):
                with self.assertRaisesRegex(ValueError, "Series title needs text review"):
                    weekly.prepare(*args)
                self.assertFalse((root / "job").exists())
                rows[0]["zh"] = "我们的系列《当生活令人费解》。"
                write_json(reading, rows)
                with self.assertRaisesRegex(ValueError, "Reading and outline series terminology differ"):
                    weekly.prepare(*args)
                write_json(outline, {**weekly.read(outline), "seriesTerminology": names})
                job = weekly.prepare(*args)
            self.assertEqual(job["blocks"][0]["zh"], rows[0]["zh"])
            self.assertEqual(job["units"][0]["text"], rows[0]["zh"])
            self.assertEqual(job["inputs"]["readingQuality"]["sha256"], sha256(quality))

    def test_page_uses_canonical_name_and_preserves_audio_and_subtitle_cues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = app_fixture(root)
            public = root / "public"
            (public / "media").mkdir(parents=True)
            before = weekly.read(work / "audio/library.json")["tracks"][0]
            page = app.weekly_job(work, public, preview=True, series="When Life Doesn't Make Sense")
            self.assertEqual(page["series"], "当生活令人费解")
            self.assertIn("当生活令人费解", page["title"])
            self.assertEqual(page["tracks"][0]["cues"], before["cues"])
            self.assertEqual(page["tracks"][0]["sha256"], before["sha256"])


if __name__ == "__main__":
    unittest.main()

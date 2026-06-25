import importlib.util
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "offline_live_sermon_subtitles.py"
SPEC = importlib.util.spec_from_file_location("offline_live_sermon_subtitles", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class OfflineLiveSermonSubtitlesTest(unittest.TestCase):
    def test_default_langs_prefer_stable_original_captions(self):
        self.assertEqual(mod.DEFAULT_LANGS, ["en-orig", "en"])

    def test_default_asr_model_uses_gpt_4o_transcribe(self):
        self.assertEqual(mod.DEFAULT_ASR_MODEL, "gpt-4o-transcribe")

    def test_parse_time_to_ms_supports_seconds_and_vtt_time(self):
        self.assertEqual(mod.parse_time_to_ms("23.5"), 23500)
        self.assertEqual(mod.parse_time_to_ms("00:23:25.000"), 1_405_000)
        self.assertEqual(mod.parse_time_to_ms("23:25.250"), 1_405_250)

    def test_vtt_parse_slice_and_offset(self):
        text = """WEBVTT

00:23:24.000 --> 00:23:26.000
Before and into sermon

00:23:30.000 --> 00:23:33.500
Sermon cue

00:54:30.000 --> 00:54:33.000
After sermon
"""

        cues = mod.parse_vtt(text)
        self.assertEqual(len(cues), 3)

        sliced = mod.slice_live_cues(cues, start_ms=1_405_000, duration_ms=1_858_000)
        self.assertEqual(len(sliced), 2)
        self.assertEqual(sliced[0].start_ms, 0)
        self.assertEqual(sliced[0].text, "Before and into sermon")
        self.assertEqual(sliced[1].start_ms, 5_000)

        offset = mod.offset_cues([sliced[1]], 1_405_000)
        self.assertEqual(mod.format_vtt_time(offset[0].start_ms), "00:23:30.000")
        self.assertEqual(mod.format_srt_time(offset[0].end_ms), "00:23:33,500")

    def test_render_vtt_and_srt(self):
        cues = [mod.Cue(start_ms=0, end_ms=1500, text="你好\n世界")]
        self.assertTrue(mod.render_vtt(cues).startswith("WEBVTT"))
        self.assertIn("00:00:00.000 --> 00:00:01.500", mod.render_vtt(cues))
        self.assertIn("00:00:00,000 --> 00:00:01,500", mod.render_srt(cues))

    def test_title_similarity_matches_same_sermon(self):
        live = "The Cure for Our Rebellion - Eric Geiger | Mariners Church"
        vod = "The Cure for Our Rebellion - Eric Geiger | Mariners Church"
        other = "Misplaced Fear - Eric Geiger | Mariners Church"
        self.assertEqual(mod.title_similarity(live, vod), 1.0)
        self.assertLess(mod.title_similarity(live, other), 0.6)

    def test_download_subtitles_reuses_existing_lang_file_on_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            existing = raw_dir / "V6OKiwbjDZE.en.vtt"
            existing.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n", encoding="utf-8")
            original_run = mod.subprocess.run
            try:
                mod.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
                    returncode=0,
                    stdout="",
                    stderr="",
                )
                downloaded, warnings = mod.download_subtitles(
                    yt_dlp="yt-dlp",
                    url="https://youtube.test/watch?v=V6OKiwbjDZE",
                    raw_dir=raw_dir,
                    langs=["en"],
                )
            finally:
                mod.subprocess.run = original_run

            self.assertEqual(downloaded, [existing])
            self.assertIn("Reused existing VTT file for lang=en.", warnings)


if __name__ == "__main__":
    unittest.main()

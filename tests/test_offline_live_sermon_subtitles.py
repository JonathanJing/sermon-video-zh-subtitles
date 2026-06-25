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

    def test_rejects_realtime_model_for_offline_asr(self):
        with self.assertRaises(SystemExit):
            mod.validate_asr_model("gpt-realtime-translate")

    def test_rejects_non_required_model_for_offline_asr(self):
        with self.assertRaises(SystemExit):
            mod.validate_asr_model("gpt-4o-mini-transcribe")

    def test_caption_route_decision_records_captions_first_path(self):
        route = mod.caption_route_decision(
            live_meta={"subtitles": {"en": [{}]}, "automatic_captions": {"es": [{}]}},
            sermon_meta=None,
            requested_langs=["en-orig", "en"],
            selected_source_kind="live_archive",
        )

        self.assertEqual(route["strategy"], "captions_first_then_asr")
        self.assertEqual(route["decision"], "use_caption_track")
        self.assertFalse(route["asrFallbackRequired"])
        self.assertFalse(route["audioExtractionAttempted"])
        self.assertEqual(route["liveCaptionLangs"], ["en", "es"])

    def test_caption_route_decision_records_asr_fallback_reason(self):
        route = mod.caption_route_decision(
            live_meta={"subtitles": {}, "automatic_captions": {}},
            sermon_meta=None,
            requested_langs=["en-orig", "en"],
            selected_source_kind="none",
        )

        self.assertEqual(route["decision"], "use_asr_fallback")
        self.assertTrue(route["asrFallbackRequired"])
        self.assertEqual(route["fallbackReason"], "no_requested_caption_track")

    def test_download_section_spec_uses_sermon_window(self):
        self.assertEqual(
            mod.download_section_spec(start_ms=1_405_000, duration_ms=1_858_000),
            "*00:23:25-00:54:23",
        )
        self.assertIsNone(mod.download_section_spec(start_ms=0, duration_ms=None))

    def test_parse_time_accepts_chinese_fullwidth_colon(self):
        self.assertEqual(mod.parse_time_to_ms("17：08"), 1_028_000)

    def test_slice_live_cues_uses_manual_sermon_start_and_end_window(self):
        cues = [
            mod.Cue(start_ms=1_000_000, end_ms=1_025_000, text="before sermon"),
            mod.Cue(start_ms=1_028_000, end_ms=1_035_000, text="sermon opens"),
            mod.Cue(start_ms=2_950_000, end_ms=2_954_000, text="sermon closes"),
            mod.Cue(start_ms=2_955_000, end_ms=2_958_000, text="boundary after sermon"),
            mod.Cue(start_ms=2_960_000, end_ms=2_970_000, text="after sermon"),
        ]
        start_ms = mod.parse_time_to_ms("17:08")
        end_ms = mod.parse_time_to_ms("49:15")

        sliced = mod.slice_live_cues(cues, start_ms, end_ms - start_ms)

        self.assertEqual([cue.text for cue in sliced], ["sermon opens", "sermon closes"])
        self.assertEqual(sliced[0].start_ms, 0)
        self.assertEqual(sliced[0].end_ms, 7_000)
        self.assertEqual(sliced[1].start_ms, 1_922_000)

    def test_cues_from_transcription_segments(self):
        cues = mod.cues_from_transcription_response(
            {
                "segments": [
                    {"start": 0.25, "end": 2.5, "text": " Jesus is our mediator. "},
                    {"start": 2.5, "end": 5.0, "text": "He brings mercy."},
                ]
            },
            fallback_duration_ms=None,
        )

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start_ms, 250)
        self.assertEqual(cues[0].end_ms, 2500)
        self.assertEqual(cues[0].text, "Jesus is our mediator.")

    def test_cues_from_plain_transcription_text(self):
        cues = mod.cues_from_transcription_response(
            {"text": "Jesus is our mediator."},
            fallback_duration_ms=5000,
        )

        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].end_ms, 5000)
        self.assertEqual(cues[0].text, "Jesus is our mediator.")

    def test_long_asr_audio_is_split_and_offset(self):
        calls = []

        def fake_split(audio_path, chunk_dir, index, start_ms, duration_ms):
            calls.append((index, start_ms, duration_ms))
            chunk = chunk_dir / f"chunk-{index}.m4a"
            chunk.parent.mkdir(parents=True, exist_ok=True)
            chunk.write_text("audio", encoding="utf-8")
            return chunk

        def fake_transcribe(audio_path, api_key, model, fallback_duration_ms):
            return [mod.Cue(start_ms=0, end_ms=fallback_duration_ms, text=audio_path.stem)]

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "sermon.m4a"
            audio.write_text("audio", encoding="utf-8")
            original_split = mod.split_audio_chunk
            original_transcribe = mod.transcribe_single_audio_to_cues
            try:
                mod.split_audio_chunk = fake_split
                mod.transcribe_single_audio_to_cues = fake_transcribe
                cues = mod.transcribe_audio_chunks_to_cues(
                    audio_path=audio,
                    api_key="key",
                    model="gpt-4o-transcribe",
                    fallback_duration_ms=1_450_000,
                )
            finally:
                mod.split_audio_chunk = original_split
                mod.transcribe_single_audio_to_cues = original_transcribe

        self.assertEqual(calls, [(0, 0, 600_000), (1, 600_000, 600_000), (2, 1_200_000, 250_000)])
        self.assertEqual([cue.start_ms for cue in cues], [0, 600_000, 1_200_000])
        self.assertEqual([cue.end_ms for cue in cues], [600_000, 1_200_000, 1_450_000])

    def test_gpt_4o_transcribe_uses_json_response_format(self):
        fields = mod.transcription_request_fields("gpt-4o-transcribe")

        self.assertIn(("response_format", "json"), fields)
        self.assertNotIn(("response_format", "verbose_json"), fields)
        self.assertNotIn(("timestamp_granularities[]", "segment"), fields)

    def test_whisper_style_transcription_can_request_segments(self):
        fields = mod.transcription_request_fields("whisper-1")

        self.assertIn(("response_format", "verbose_json"), fields)
        self.assertIn(("timestamp_granularities[]", "segment"), fields)

    def test_rejects_raw_api_key_material_for_asr_secret_reference(self):
        with self.assertRaises(SystemExit):
            mod.validate_secret_resource_name("sk-this-looks-like-raw-key-material")

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

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sermon_pipeline.py"
SPEC = importlib.util.spec_from_file_location("sermon_pipeline", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class SermonPipelineTest(unittest.TestCase):
    def test_load_glossary_accepts_zh_terms_alias(self):
        with tempfile.TemporaryDirectory() as tempdir:
            glossary_path = Path(tempdir) / "glossary.json"
            glossary_path.write_text(
                '{"terms":["Numbers","Moses"],"zhTerms":{"Numbers":"民数记","Moses":"摩西"}}',
                encoding="utf-8",
            )

            glossary = mod.load_glossary(glossary_path)

        self.assertEqual(glossary["terms"], ["Numbers", "Moses"])
        self.assertEqual(glossary["zh_term_map"]["Numbers"], "民数记")
        self.assertEqual(glossary["zh_term_map"]["Moses"], "摩西")

    def test_normalize_zh_terms_replaces_bible_terms(self):
        glossary = {"terms": ["Numbers", "Moses"], "zh_term_map": {"Numbers": "民数记", "Moses": "摩西"}}

        result = mod.normalize_zh_terms("Numbers 里 Moses 的故事", glossary)

        self.assertEqual(result, "民数记 里 摩西 的故事")

    def test_shape_durations_clamps_overlaps_and_short_segments(self):
        shaped = mod.shape_durations(
            [
                {"id": 7, "start": 0.0, "end": 0.4, "text": "A"},
                {"id": 8, "start": 0.8, "end": 2.0, "text": "B"},
            ]
        )

        self.assertEqual([item["id"] for item in shaped], [0, 1])
        self.assertLessEqual(shaped[0]["end"], shaped[1]["start"])
        self.assertGreaterEqual(shaped[1]["end"] - shaped[1]["start"], 1.0)

    def test_qa_report_counts_hard_failures(self):
        en_segments = [
            {"id": 0, "start": 0.0, "end": 2.0, "text": "Moses speaks."},
            {"id": 1, "start": 1.5, "end": 3.0, "text": ""},
        ]
        zh_segments = [
            {"id": 0, "start": 0.0, "end": 2.0, "text": "Moses speaks.", "zh": "Moses 说话。"},
            {"id": 2, "start": 1.5, "end": 3.0, "text": "", "zh": ""},
        ]
        glossary = {"terms": ["Moses"], "zh_term_map": {"Moses": "摩西"}}

        report = mod.qa_report(en_segments, zh_segments, glossary)

        self.assertEqual(report["hardFailures"]["emptyEnglish"], 1)
        self.assertEqual(report["hardFailures"]["emptyChinese"], 1)
        self.assertEqual(report["hardFailures"]["overlaps"], 1)
        self.assertEqual(report["hardFailures"]["translationIdMismatchCount"], 1)
        self.assertEqual(report["latinBibleTermWarnings"][0]["term"], "Moses")

    def test_chinese_line_wrapping_does_not_insert_spaces_inside_words(self):
        rendered = mod.render_subtitle_text(
            "她兴奋极了，因为刚刚在电影《雷神4：爱与雷霆》中得到了一个角色。",
            "zh",
        )

        self.assertIn("得到了", rendered.replace("\n", ""))
        self.assertNotIn("得到 了", rendered)

    def test_ffmpeg_commands_do_not_read_stdin(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source.m4a"
            source.write_text("audio", encoding="utf-8")

            with mock.patch.object(mod, "run") as fake_run:
                mod.cut_chunk(source, root / "chunk.m4a", 0.0, 30.0)
                mod.clip_and_normalize(source, root / "clip.m4a", 0.0, 60.0)

        commands = [call.args[0] for call in fake_run.call_args_list]
        self.assertEqual(len(commands), 2)
        for command in commands:
            self.assertEqual(command[0], "ffmpeg")
            self.assertIn("-nostdin", command)
            self.assertIn("-ar", command)
            self.assertEqual(command[command.index("-ar") + 1], "44100")
            self.assertIn("-ac", command)
            self.assertEqual(command[command.index("-ac") + 1], "1")

    def test_clip_rebuilds_incomplete_cached_output(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source.m4a"
            clip = root / "clip.m4a"
            source.write_text("audio", encoding="utf-8")
            clip.write_text("partial", encoding="utf-8")

            with mock.patch.object(mod, "ffprobe_duration", return_value=1494.3), mock.patch.object(
                mod, "run"
            ) as fake_run:
                mod.clip_and_normalize(source, clip, 1765.0, 3524.0)

        fake_run.assert_called_once()

    def test_reasoning_effort_is_sent_for_correction_and_translation(self):
        segments = [{"id": 0, "start": 0.0, "end": 2.0, "text": "God loves us."}]
        gpt4o_chunks = [{"start": 0.0, "end": 2.0, "text": "God loves us."}]
        glossary = {"terms": [], "zh_term_map": {}}

        with tempfile.TemporaryDirectory() as tempdir:
            outdir = Path(tempdir)
            correction_response = {
                "choices": [{"message": {"content": '{"segments":[{"id":0,"text":"God loves us."}]}'}}]
            }
            translation_response = {
                "model": "gpt-5.6",
                "choices": [{"message": {"content": '{"id":0,"zh":"神爱我们。"}'}}],
            }
            with mock.patch.object(mod, "chat_json", side_effect=[correction_response, translation_response]) as request:
                corrected = mod.correct_english(
                    "key",
                    segments,
                    gpt4o_chunks,
                    outdir,
                    "gpt-5.6",
                    glossary,
                    240.0,
                    reasoning_effort="high",
                )
                mod.translate_chinese(
                    "key",
                    corrected,
                    outdir,
                    "gpt-5.6",
                    glossary,
                    reasoning_effort="high",
                )

        self.assertEqual(request.call_args_list[0].args[1]["reasoning_effort"], "high")
        self.assertEqual(request.call_args_list[1].args[1]["reasoning_effort"], "high")
        self.assertNotIn("temperature", request.call_args_list[0].args[1])
        self.assertNotIn("temperature", request.call_args_list[1].args[1])
        self.assertIn("minimally correct", request.call_args_list[0].args[1]["messages"][0]["content"])
        self.assertIn("Previous and next English", request.call_args_list[1].args[1]["messages"][0]["content"])

    def test_transcribe_gpt4o_chunks_reencodes_wav_after_unsupported_audio_error(self):
        with tempfile.TemporaryDirectory() as tempdir:
            outdir = Path(tempdir)
            clip = outdir / "clip.m4a"
            clip.write_text("audio", encoding="utf-8")
            chunk = outdir / "chunks_reference" / "chunk_0000.m4a"
            fallback = outdir / "chunks_reference" / "chunk_0000.wav"

            calls = []

            def fake_cut_chunk(_source, dest, _start, _duration):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text("m4a", encoding="utf-8")

            def fake_reencode(_source, dest):
                dest.write_text("wav", encoding="utf-8")

            def fake_transcribe(_api_key, _model, _prompt, audio_path, **_kwargs):
                calls.append(Path(audio_path))
                if Path(audio_path).suffix == ".m4a":
                    raise RuntimeError("HTTP 400: Audio file might be corrupted or unsupported")
                return {"text": "Recovered transcript"}

            with mock.patch.object(mod, "ffprobe_duration", return_value=30.0), \
                 mock.patch.object(mod, "cut_chunk", side_effect=fake_cut_chunk), \
                 mock.patch.object(mod, "reencode_transcription_fallback", side_effect=fake_reencode), \
                 mock.patch.object(mod, "transcribe_openai_audio", side_effect=fake_transcribe):
                chunks = mod.transcribe_gpt4o_chunks(
                    "key",
                    clip,
                    outdir,
                    45.0,
                    "gpt-4o-transcribe",
                    {"terms": [], "zh_term_map": {}},
                )

        self.assertEqual(chunks[0]["text"], "Recovered transcript")
        self.assertEqual(calls, [chunk, fallback])

    def test_gpt_transcribe_uses_prompt_keywords_and_languages_array(self):
        fields = mod.transcription_request_fields(
            "gpt-transcribe",
            response_format="json",
            prompt="English Christian sermon at Mariners Church.",
            keywords=["Mariners Church", "Numbers", "bad\nkeyword"],
            languages=["en"],
        )

        self.assertEqual(fields["languages[]"], ["en"])
        self.assertEqual(fields["keywords[]"], ["Mariners Church", "Numbers"])
        self.assertNotIn("language", fields)
        self.assertEqual(fields["prompt"], "English Christian sermon at Mariners Church.")

    def test_legacy_transcription_model_keeps_singular_language(self):
        fields = mod.transcription_request_fields(
            "whisper-1",
            response_format="verbose_json",
            prompt="English sermon.",
            keywords=["Numbers"],
            languages=["en"],
        )

        self.assertEqual(fields["language"], "en")
        self.assertNotIn("languages[]", fields)
        self.assertNotIn("keywords[]", fields)

    def test_reference_chunks_become_reading_only_internal_segments(self):
        segments = mod.reference_chunks_to_reading_segments(
            [
                {
                    "id": 0,
                    "start": 0.0,
                    "end": 60.0,
                    "text": "First sentence. Second sentence. Third sentence.",
                }
            ]
        )

        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[-1]["end"], 60.0)
        self.assertTrue(all(item["timingQuality"] == "synthetic_not_for_subtitles" for item in segments))

    def test_reading_segment_target_supports_compact_bilingual_pdf_blocks(self):
        text = " ".join(
            f"Sentence {index} carries a complete sermon thought for the reading edition."
            for index in range(12)
        )

        segments = mod.reference_chunks_to_reading_segments(
            [{"id": 0, "start": 0.0, "end": 120.0, "text": text}],
            target_chars=420,
        )

        self.assertGreaterEqual(len(segments), 3)
        self.assertTrue(all(len(item["text"]) <= 420 for item in segments))


if __name__ == "__main__":
    unittest.main()

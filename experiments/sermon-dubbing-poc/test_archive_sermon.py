import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

import prepare_archive_sermon as archive
from poc import sha256, write_json
from prepare_same_video import read


class ArchiveCaptionTests(unittest.TestCase):
    def fixture(self, root):
        audio, captions = root / "real.m4a", root / "real.en.vtt"
        audio.write_bytes(b"test audio")
        captions.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello &amp; welcome.\n\n00:00:02.000 --> 00:00:04.000\nThis is a sermon.\n")
        return {"schemaVersion": archive.SCHEMA, "sourceId": "abcdefghijk", "week": "2026-09-06",
            "canonicalURL": "https://www.youtube.com/watch?v=abcdefghijk", "durationSeconds": 5,
            "sermonOnly": True, "sourceEvidenceReference": "fixture-only", "audio": {"path": str(audio), "sha256": sha256(audio), "sourceId": "abcdefghijk"},
            "captions": {"path": str(captions), "sha256": sha256(captions), "sourceId": "abcdefghijk", "language": "en", "kind": "manual"}}

    def probe(self, path):
        return {"durationSeconds": 5, "streams": [{"codec_type": "audio"}]}

    def test_audio_caption_intake_keeps_truthful_provenance_and_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            result = archive.initialize(source, root / "run", "Title · Series", "Speaker", self.probe)
            rows = read(root / "run/pipeline/segments_timed_en_raw.json")
            self.assertEqual(rows[0]["text"], "Hello & welcome. This is a sermon.")
            self.assertEqual(rows[0]["sourceCaptionIds"], [0, 1])
            self.assertFalse(result["asrPerformed"])
            self.assertFalse(result["humanApproval"])
            self.assertEqual(archive.validate(read(root / "run" / archive.CONTRACT), self.probe), rows)
            self.assertEqual(len(result["commands"]), 5)
            self.assertIn("2", result["commands"][1])
            self.assertFalse((root / "run/pipeline/asr_reference.json").exists())
            with self.assertRaisesRegex(ValueError, "new archive"):
                archive.initialize(source, root / "run", "Title", "Speaker", self.probe)

    def test_unreviewed_intake_cannot_be_sealed_or_admitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive.initialize(self.fixture(root), root / "run", "Title", "Speaker", self.probe)
            for action in (archive.seal_reviewed, archive.validate_handoff):
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    action(root / "run", media_probe=self.probe)
            self.assertFalse((root / "run" / archive.HANDOFF_NAME).exists())

    def reviewed_fixture(self, root):
        from scripts.build_sermon_reading_edition_with_openai import build_semantic_blocks, reading_quality_report, write_block_srt
        from scripts.generate_notes_with_openai import segments_from_srt, merge_aligned_segments, build_note_slices, summarize_slices
        run = root / "run"
        archive.initialize(self.fixture(root), run, "Title", "Speaker", self.probe)
        pipeline = run / "pipeline"
        english = read(pipeline / "segments_timed_en_corrected.json")
        chinese = [{**row, "zh": "大家好，欢迎各位。这是一篇证道。"} for row in english]
        write_json(pipeline / "segments_timed_zh.json", chinese)
        draft = build_semantic_blocks(english, chinese, preferred_seconds=24, preferred_english_chars=420,
            hard_seconds=55, hard_english_chars=840)
        reading = pipeline / "reading-edition-v2"
        write_json(reading / "reading_blocks.draft.json", draft)
        final = [{**row, "zh": row["draftZh"]} for row in draft]
        write_json(reading / "reading_blocks.final.json", final)
        quality = reading_quality_report(final)
        self.assertEqual(quality["status"], "pass")
        write_json(reading / "reading_quality_report.json", {**quality, "model": "gpt-6-astra", "reasoningEffort": "medium", "passes": 2,
            "sourcePipeline": str(pipeline), "layoutTargets": {"preferredSeconds": 24, "preferredEnglishCharacters": 420, "hardSeconds": 55, "hardEnglishCharacters": 840}})
        for field in ("en", "zh"):
            write_block_srt(reading / f"sermon_{field}_reading_revised.srt", final, field)
        aligned = merge_aligned_segments(segments_from_srt((reading / "sermon_zh_reading_revised.srt").read_text(), lang="zh"),
            segments_from_srt((reading / "sermon_en_reading_revised.srt").read_text(), lang="en"))
        write_json(pipeline / "sermon-interpretation/insights/openai-notes.json", {"status": "ready", "sermonDate": "2026-09-06",
            "sermonTitle": "Title", "speaker": "Speaker", "slices": summarize_slices(build_note_slices(aligned)), "sourceSegmentCount": len(aligned)})
        return run

    def test_successful_seal_binds_real_reading_contract_and_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.reviewed_fixture(Path(tmp))
            def fixture_renderer(command, **kwargs):
                output = Path(command[command.index("--out") + 1])
                output.write_bytes(b"%PDF-1.4 fixture renderer output")
                qa = Path(command[command.index("--qa-out") + 1]) if "--qa-out" in command else output.with_suffix(".qa.json")
                write_json(qa, {"status": "pass"})
            render = Mock(side_effect=fixture_renderer)
            source, inputs = archive.seal_reviewed(run, media_probe=self.probe, runner=render)
            self.assertEqual(render.call_count, 2)
            self.assertEqual(source["sourceId"], "abcdefghijk")
            self.assertEqual(inputs["readingPdf"]["sha256"], sha256(Path(inputs["readingPdf"]["path"])))
            self.assertFalse(read(run / archive.HANDOFF_NAME)["humanApproval"])
            # Simulate interruption after atomic PDF bundle rename and before
            # writing the handoff. Recovery must bind the existing PDF bytes.
            (run / archive.HANDOFF_NAME).unlink()
            recovered = archive.seal_reviewed(run, media_probe=self.probe,
                runner=Mock(side_effect=AssertionError("Recovery must reuse rendered PDFs")))
            self.assertEqual(recovered, (source, inputs))
            self.assertEqual(archive.seal_reviewed(run, media_probe=self.probe, runner=Mock(side_effect=AssertionError("Sealed run must not render again"))), (source, inputs))
            for key in ("reading", "outline", "readingPdf", "sourceCaptions"):
                target = Path(inputs[key]["path"])
                original = target.read_bytes()
                target.write_bytes(original + b" ")
                with self.subTest(key=key), self.assertRaises(ValueError):
                    archive.validate_handoff(run, media_probe=self.probe)
                target.write_bytes(original)
            self.assertEqual(archive.validate_handoff(run, media_probe=self.probe), (source, inputs))
            handoff_path = run / archive.HANDOFF_NAME
            handoff = read(handoff_path)
            alternate = run / "unrelated.pdf"
            alternate.write_bytes(b"unrelated PDF")
            handoff["inputs"]["readingPdf"] = {"path": str(alternate), "sha256": sha256(alternate)}
            write_json(handoff_path, handoff)
            with self.assertRaisesRegex(ValueError, "handoff input changed"):
                archive.validate_handoff(run, media_probe=self.probe)

    def test_caption_receipt_cannot_claim_asr_review_or_different_source_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = self.reviewed_fixture(Path(tmp))
            path = run / "pipeline/caption-source-receipt.json"
            original = read(path)
            for key, value in {"asrPerformed": True, "humanApproval": True, "englishCorrection": "model",
                "audioSha256": "0" * 64, "captionSha256": "0" * 64, "segmentsSha256": "0" * 64}.items():
                write_json(path, {**original, key: value})
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Caption source receipt"):
                    archive.reviewed_inputs(run, media_probe=self.probe)
            write_json(path, original)
            archive.reviewed_inputs(run, media_probe=self.probe)

    def test_translation_accounting_records_usage_without_changing_model_settings(self):
        from scripts.sermon_accounting import record_api_attempt, read_events
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "run"
            archive.initialize(self.fixture(root), run, "Title", "Speaker", self.probe)
            def translated(*args, **kwargs):
                record_api_attempt("gpt-6-astra", {"usage": {"prompt_tokens": 11, "completion_tokens": 7}}, .01)
                return []
            with patch.object(archive, "validate", wraps=lambda source: archive.caption_segments(Path(source["captions"]["path"]), 5)), \
                 patch("scripts.sermon_pipeline.load_env"), patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}), \
                 patch("scripts.sermon_pipeline.translate_chinese", side_effect=translated) as translate:
                archive.translate(run)
            self.assertEqual(translate.call_args.args[3], "gpt-6-astra")
            self.assertEqual(translate.call_args.kwargs, {"reasoning_effort": "medium", "workers": 4})
            events, damaged = read_events(run / "pipeline/accounting")
            self.assertFalse(damaged)
            api = [event for event in events if event["event"] == "api_attempt"]
            self.assertEqual(len(api), 1)
            self.assertEqual(api[0]["usage"]["inputTokens"], 11)
            self.assertEqual(api[0]["usage"]["outputTokens"], 7)

    def test_v2_splits_sentences_inside_cues_without_changing_words(self):
        from scripts.build_sermon_reading_edition_with_openai import build_source_segment_units, build_semantic_blocks, join_english
        rows = [{"id": i, "start": i * 4, "end": i * 4 + 4, "text": "We trust God. He stays with us. We can",
            "sourceCaptionIds": [i]} for i in range(30)]
        # Complete the repeated cue fragments with authentic adjacent words.
        for row in rows[1:]:
            row["text"] = "pray together. " + row["text"]
        rows[-1]["text"] += " pray together."
        segments = archive.sentence_segments(rows)
        self.assertEqual(join_english([r["text"] for r in rows]), join_english([r["text"] for r in segments]))
        self.assertTrue(all(r["timingQuality"] == "synthetic_caption_sentence_layout_only" for r in segments))
        self.assertEqual({i for r in segments for i in r["sourceCaptionIds"]}, set(range(30)))
        self.assertTrue(all(set(r["sourceCaptionHashes"]) == {str(i) for i in r["sourceCaptionIds"]} for r in segments))
        units = build_source_segment_units(segments)
        self.assertEqual(len(units), len(segments))
        self.assertLessEqual(max(len(r["en"]) for r in units), 420)
        blocks = build_semantic_blocks(segments, [{**r, "zh": "测试。"} for r in segments],
            preferred_seconds=24, preferred_english_chars=420, hard_seconds=55, hard_english_chars=840)
        self.assertLess(max(r["end"] - r["start"] for r in blocks), 55)
        self.assertNotEqual(segments[0]["end"] % 4, 0, "Sentence boundary uses explicitly synthetic cue interpolation")

    def test_v2_contract_is_explicit_and_v1_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            legacy = archive.validate(source, self.probe)
            source["schemaVersion"] = archive.SCHEMA_V2
            with self.assertRaisesRegex(ValueError, "segmentation contract"):
                archive.validate(source, self.probe)
            source["segmentation"] = archive.SEGMENTATION_V2.copy()
            archive.initialize(source, root / "run", "Title", "Speaker", self.probe)
            current = read(root / "run/pipeline/segments_timed_en_raw.json")
            self.assertEqual(current[0]["text"], legacy[0]["text"])
            self.assertNotIn("timingQuality", legacy[0])
            self.assertEqual(current[0]["timingQuality"], "synthetic_caption_sentence_layout_only")
            self.assertEqual(read(root / "run/pipeline/summary.json")["timingPrecision"], "synthetic_caption_sentence_layout_only")
            self.assertEqual(archive.validate(self.fixture(root), self.probe), legacy)

    def test_extreme_unpunctuated_span_requires_explicit_review(self):
        rows = [{"id": i, "start": i * 10, "end": i * 10 + 10, "text": "words without a sentence boundary",
            "sourceCaptionIds": [i]} for i in range(8)]
        with self.assertRaisesRegex(ValueError, "explicit review at cue 0"):
            archive.sentence_segments(rows)

    def test_wrong_identity_hash_stream_or_overlapping_captions_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.fixture(root)
            source["captions"]["sourceId"] = "other-video"
            with self.assertRaisesRegex(ValueError, "identity"):
                archive.validate(source, self.probe)
            source = self.fixture(root)
            Path(source["audio"]["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash"):
                archive.validate(source, self.probe)
            source = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "audio stream"):
                archive.validate(source, lambda path: {"durationSeconds": 5, "streams": []})
            captions = Path(source["captions"]["path"])
            captions.write_text(captions.read_text().replace("00:00:02.000 -->", "00:00:01.000 -->"))
            with self.assertRaisesRegex(ValueError, "Overlapping"):
                archive.caption_segments(captions, 5)


if __name__ == "__main__":
    unittest.main()

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_post_live_subtitle_generation.py"
SPEC = importlib.util.spec_from_file_location("run_post_live_subtitle_generation", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def make_args(**overrides):
    values = {
        "sunday": "2026-06-28",
        "state_file": "",
        "out": Path("artifacts/post-live-subtitle-generation/report.json"),
        "work_root": Path("/tmp/post-live-test"),
        "slug": "mariners_MEZHufeQBjc",
        "start_time": "00:22:10",
        "end_time": "00:55:36",
        "sermon_title": None,
        "speaker": None,
        "glossary": None,
        "zh_model": "gpt-5.6",
        "en_correction_model": "gpt-5.6",
        "reasoning_effort": "high",
        "reference_model": "gpt-transcribe",
        "timing_model": "whisper-1",
        "output_mode": "reading",
        "reading_edition_provider": "openai",
        "reading_edition_model": "gpt-5.6-sol",
        "reading_edition_reasoning_effort": "high",
        "reading_segment_target_chars": 420,
        "reading_preferred_seconds": 24.0,
        "reading_preferred_english_chars": 420,
        "reading_hard_seconds": 55.0,
        "reading_hard_english_chars": 840,
        "audio_format": "bestaudio[ext=m4a]/bestaudio",
        "yt_dlp": "yt-dlp",
        "youtube_cookies": None,
        "metadata_json": None,
        "api_key_secret": None,
        "gcs_bucket": None,
        "gcs_prefix": "sundays",
        "plan_only": True,
        "dry_run": False,
        "allow_non_post_live": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def write_state(path: Path, *, sunday: str = "2026-06-28", url: str = "https://www.youtube.com/watch?v=MEZHufeQBjc"):
    payload = {
        "schemaVersion": 1,
        "updatedAt": "2026-06-27T17:22:00-07:00",
        "lastStatus": "source_detected",
        "lastSunday": sunday,
        "lastSelectedSource": {
            "kind": "youtube-streams",
            "service": "sat530",
            "state": "was_live",
            "title": "Mariners Saturday Service",
            "url": url,
            "urlHash": "abc123",
        },
        "lastGenerationRequest": {
            "triggerSource": "live-source-monitor",
            "sunday": sunday,
            "liveUrl": url,
            "sourceKind": "youtube-streams",
            "service": "sat530",
        },
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class PostLiveSubtitleGenerationTest(unittest.TestCase):
    def test_plan_waits_when_capture_state_has_no_url(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "state.json"
            state_path.write_text(json.dumps({"lastSunday": "2026-06-28"}), encoding="utf-8")

            report = mod.run_post_live_generation(make_args(state_file=str(state_path)))

        self.assertEqual(report["status"], "waiting_for_source")
        self.assertEqual(report["reason"], "captured_state_has_no_live_url")

    def test_plan_waits_until_metadata_is_post_live(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "state.json"
            write_state(state_path)

            report = mod.run_post_live_generation(
                make_args(state_file=str(state_path)),
                metadata_loader=lambda _: {"id": "MEZHufeQBjc", "live_status": "is_live", "is_live": True},
            )

        self.assertEqual(report["status"], "waiting_for_post_live")
        self.assertIn("not post_live", report["reason"])

    def test_plan_builds_pipeline_command_after_post_live(self):
        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "state.json"
            write_state(state_path)

            report = mod.run_post_live_generation(
                make_args(state_file=str(state_path), work_root=Path(tempdir)),
                metadata_loader=lambda _: {
                    "id": "MEZHufeQBjc",
                    "title": "A Bronze Snake and God's Love - Steve Bang Lee | Mariners Church",
                    "live_status": "post_live",
                    "media_type": "livestream",
                    "was_live": True,
                },
            )

        self.assertEqual(report["status"], "planned")
        command = report["pipelineCommand"]
        self.assertIn("scripts/sermon_pipeline.py", command[1])
        self.assertIn("--zh-model", command)
        self.assertEqual(command[command.index("--zh-model") + 1], "gpt-5.6")
        self.assertEqual(command[command.index("--en-correction-model") + 1], "gpt-5.6")
        self.assertEqual(command[command.index("--reasoning-effort") + 1], "high")
        self.assertEqual(command[command.index("--reference-model") + 1], "gpt-transcribe")
        self.assertEqual(command[command.index("--output-mode") + 1], "reading")
        self.assertEqual(command[command.index("--reading-segment-target-chars") + 1], "420")
        self.assertNotIn("--timing-model", command)
        self.assertEqual(report["readingEditionCommand"][report["readingEditionCommand"].index("--provider") + 1], "openai")
        self.assertEqual(report["readingEditionCommand"][report["readingEditionCommand"].index("--model") + 1], "gpt-5.6-sol")
        self.assertEqual(report["readingEditionCommand"][report["readingEditionCommand"].index("--reasoning-effort") + 1], "high")
        self.assertTrue(any("reading-edition-v2" in item for item in report["readingEditionCommand"]))
        self.assertIsNone(report["mobilePdfCommand"])
        self.assertIn("render_mobile_pdf_from_srt.py", report["readingPdfCommand"][1])
        self.assertEqual(
            report["readingPdfCommand"][report["readingPdfCommand"].index("--title") + 1],
            "A Bronze Snake and God's Love",
        )
        self.assertEqual(
            report["readingPdfCommand"][report["readingPdfCommand"].index("--speaker") + 1],
            "Steve Bang Lee",
        )
        self.assertEqual(
            report["readingPdfCommand"][report["readingPdfCommand"].index("--sermon-date") + 1],
            "2026-06-28",
        )
        self.assertEqual(
            report["readingPdfCommand"][report["readingPdfCommand"].index("--sermon-window") + 1],
            "00:22:10-00:55:36",
        )
        self.assertIn("--layout", report["readingPdfCommand"])
        self.assertEqual(report["readingPdfCommand"][report["readingPdfCommand"].index("--layout") + 1], "reading")
        self.assertTrue(any("sermon_zh_reading_revised.srt" in item for item in report["readingPdfCommand"]))
        self.assertTrue(any("sermon_en_reading_revised.srt" in item for item in report["readingPdfCommand"]))
        self.assertTrue(any("sermon_zh_en_reading.pdf" in item for item in report["readingPdfCommand"]))
        self.assertEqual(
            report["readingPdfCommand"][report["readingPdfCommand"].index("--source-url") + 1],
            "https://www.youtube.com/watch?v=MEZHufeQBjc",
        )
        self.assertEqual(
            report["readingPdfCommand"][report["readingPdfCommand"].index("--source-offset-seconds") + 1],
            "1330.0",
        )
        self.assertTrue(any(path.endswith("reading-edition-v2/reading_quality_report.json") for path in report["outputs"]))
        self.assertFalse(any(path.endswith("sermon_zh_mobile.pdf") for path in report["outputs"]))
        self.assertTrue(any(path.endswith("sermon_zh_en_reading.pdf") for path in report["outputs"]))
        self.assertTrue(str(report["deliveryReadingPdf"]).endswith(
            "2026-06-28-A-Bronze-Snake-and-God-s-Love-Steve-Bang-Lee-中英对照阅读版.pdf"
        ))
        self.assertEqual(
            report["readingEditionCommand"][
                report["readingEditionCommand"].index("--preferred-english-chars") + 1
            ],
            "420",
        )

    def test_run_downloads_audio_and_invokes_pipeline(self):
        calls = []

        def fake_runner(command, check):
            calls.append(command)
            if command[0] == "yt-dlp":
                template = Path(command[command.index("-o") + 1])
                template.parent.mkdir(parents=True, exist_ok=True)
                (template.parent / "source_audio.m4a").write_text("audio", encoding="utf-8")
            elif "sermon_pipeline.py" in command[1]:
                outdir = Path(command[command.index("--outdir") + 1])
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / "segments_timed_en_corrected.json").write_text(
                    json.dumps([{"id": 0, "start": 0, "end": 2.5, "text": "For God so loved the world."}]),
                    encoding="utf-8",
                )
                (outdir / "segments_timed_zh.json").write_text(
                    json.dumps([{"id": 0, "start": 0, "end": 2.5, "text": "For God so loved the world.", "zh": "神爱世人。"}]),
                    encoding="utf-8",
                )
                (outdir / "summary.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
            elif "build_sermon_reading_edition_with_openai.py" in command[1]:
                outdir = Path(command[command.index("--outdir") + 1])
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / "sermon_zh_reading_revised.srt").write_text(
                    "1\n00:00:01,000 --> 00:00:02,500\n神爱世人。\n",
                    encoding="utf-8",
                )
                (outdir / "sermon_en_reading_revised.srt").write_text(
                    "1\n00:00:01,000 --> 00:00:02,500\nFor God so loved the world.\n",
                    encoding="utf-8",
                )
                (outdir / "reading_quality_report.json").write_text(
                    json.dumps({"status": "pass", "failures": []}), encoding="utf-8"
                )
            elif "render_mobile_pdf_from_srt.py" in command[1]:
                pdf_path = Path(command[command.index("--out") + 1])
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                pdf_path.write_bytes(b"%PDF-1.4\n")
                pdf_path.with_suffix(".qa.json").write_text(
                    json.dumps({"status": "pass", "allPagesChecked": True}), encoding="utf-8"
                )
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tempdir:
            state_path = Path(tempdir) / "state.json"
            write_state(state_path)

            report = mod.run_post_live_generation(
                make_args(state_file=str(state_path), work_root=Path(tempdir), plan_only=False),
                metadata_loader=lambda _: {
                    "id": "MEZHufeQBjc",
                    "live_status": "post_live",
                    "media_type": "livestream",
                    "was_live": True,
                },
                runner=fake_runner,
            )

        self.assertEqual(report["status"], "completed")
        self.assertEqual(calls[0][0], "yt-dlp")
        self.assertIn("sermon_pipeline.py", calls[1][1])
        self.assertIn("build_sermon_reading_edition_with_openai.py", calls[2][1])
        self.assertIn("render_mobile_pdf_from_srt.py", calls[3][1])
        self.assertIn("--layout", calls[3])
        self.assertEqual(calls[3][calls[3].index("--layout") + 1], "reading")
        self.assertTrue(any("reading-edition-v2" in item for item in report["readingEditionCommand"]))
        self.assertIsNone(report["mobilePdfCommand"])
        self.assertTrue(any("sermon_zh_en_reading.pdf" in item for item in report["readingPdfCommand"]))
        self.assertTrue(str(report["readingQualityReport"]).endswith("reading-edition-v2/reading_quality_report.json"))
        self.assertTrue(any(path.endswith("中英对照阅读版.pdf") for path in report["outputs"]))

    def test_subtitle_mode_keeps_whisper_as_explicit_opt_in(self):
        args = make_args(output_mode="subtitles")
        command = mod.build_pipeline_command(
            args,
            Path("/tmp/download"),
            Path("/tmp/pipeline"),
            "https://www.youtube.com/watch?v=MEZHufeQBjc",
        )

        self.assertEqual(command[command.index("--output-mode") + 1], "subtitles")
        self.assertEqual(command[command.index("--timing-model") + 1], "whisper-1")

    def test_newest_downloaded_audio_ignores_partial_and_ytdl_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            download_dir = Path(tempdir)
            (download_dir / "source_audio.m4a.part").write_text("partial", encoding="utf-8")
            (download_dir / "source_audio.m4a.ytdl").write_text("meta", encoding="utf-8")
            expected = download_dir / "source_audio.m4a"
            expected.write_text("audio", encoding="utf-8")

            actual = mod.newest_downloaded_audio(download_dir)

        self.assertEqual(actual, expected)

    def test_timecode_to_seconds_accepts_hms_and_ms(self):
        self.assertEqual(mod.timecode_to_seconds("00:22:10"), 1330.0)
        self.assertEqual(mod.timecode_to_seconds("22:10"), 1330.0)

    def test_generic_live_title_is_not_used_as_sermon_title(self):
        args = make_args(sermon_title=None, speaker=None)

        title, speaker = mod.reading_pdf_metadata(
            args,
            metadata={"title": "Mariners Online Worship Service | Worship & Message! | Join Us Now!"},
            source={"title": "Manual authorized source 1"},
        )

        self.assertEqual(title, "主日证道")
        self.assertIsNone(speaker)

    def test_operator_confirmed_pdf_metadata_wins(self):
        args = make_args(sermon_title="耶稣是谁", speaker="Eric Geiger")

        title, speaker = mod.reading_pdf_metadata(
            args,
            metadata={"title": "Generic Live Service"},
        )

        self.assertEqual(title, "耶稣是谁")
        self.assertEqual(speaker, "Eric Geiger")

    def test_pipeline_resume_fingerprint_covers_window_audio_glossary_and_models(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            audio = root / "source_audio.m4a"
            glossary = root / "glossary.json"
            audio.write_bytes(b"audio-v1")
            glossary.write_text('{"Steve Bang Lee":"Steve Bang Lee"}', encoding="utf-8")
            base_args = make_args(glossary=glossary)

            base = mod.stable_payload_hash(mod.build_pipeline_input_identity(base_args, audio))
            changed_window = mod.stable_payload_hash(
                mod.build_pipeline_input_identity(
                    make_args(glossary=glossary, start_time="00:23:00"),
                    audio,
                )
            )
            changed_model = mod.stable_payload_hash(
                mod.build_pipeline_input_identity(
                    make_args(glossary=glossary, zh_model="gpt-5.6-new"),
                    audio,
                )
            )
            audio.write_bytes(b"audio-v2")
            changed_audio = mod.stable_payload_hash(mod.build_pipeline_input_identity(base_args, audio))
            audio.write_bytes(b"audio-v1")
            glossary.write_text('{"Steve Bang Lee":"李牧师"}', encoding="utf-8")
            changed_glossary = mod.stable_payload_hash(mod.build_pipeline_input_identity(base_args, audio))

        self.assertEqual(len({base, changed_window, changed_model, changed_audio, changed_glossary}), 5)

    def test_pipeline_summary_requires_expected_input_fingerprint(self):
        with tempfile.TemporaryDirectory() as tempdir:
            summary_path = Path(tempdir) / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "outputMode": "reading",
                        "models": {"referenceAsr": "gpt-transcribe"},
                        "readingSegmentTargetCharacters": 420,
                        "pipelineInputFingerprint": "fingerprint-v1",
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                mod.pipeline_summary_matches(
                    summary_path,
                    output_mode="reading",
                    reference_model="gpt-transcribe",
                    expected_input_fingerprint="fingerprint-v1",
                )
            )
            self.assertFalse(
                mod.pipeline_summary_matches(
                    summary_path,
                    output_mode="reading",
                    reference_model="gpt-transcribe",
                    expected_input_fingerprint="fingerprint-v2",
                )
            )

    def test_reading_resume_fingerprint_covers_upstream_text_and_editing_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            pipeline = Path(tempdir)
            english = pipeline / "segments_timed_en_corrected.json"
            chinese = pipeline / "segments_timed_zh.json"
            english.write_text('[{"id":1,"text":"Grace"}]', encoding="utf-8")
            chinese.write_text('[{"id":1,"zh":"恩典"}]', encoding="utf-8")

            base_args = make_args()
            base = mod.stable_payload_hash(
                mod.build_reading_input_identity(
                    base_args,
                    pipeline,
                    pipeline_input_fingerprint="pipeline-v1",
                )
            )
            chinese.write_text('[{"id":1,"zh":"神的恩典"}]', encoding="utf-8")
            changed_text = mod.stable_payload_hash(
                mod.build_reading_input_identity(
                    base_args,
                    pipeline,
                    pipeline_input_fingerprint="pipeline-v1",
                )
            )
            changed_model = mod.stable_payload_hash(
                mod.build_reading_input_identity(
                    make_args(reading_edition_model="gpt-5.6-sol-new"),
                    pipeline,
                    pipeline_input_fingerprint="pipeline-v1",
                )
            )
            changed_pipeline = mod.stable_payload_hash(
                mod.build_reading_input_identity(
                    base_args,
                    pipeline,
                    pipeline_input_fingerprint="pipeline-v2",
                )
            )

        self.assertEqual(len({base, changed_text, changed_model, changed_pipeline}), 4)

    def test_reading_report_requires_matching_input_fingerprint(self):
        with tempfile.TemporaryDirectory() as tempdir:
            report_path = Path(tempdir) / "reading_quality_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "layoutTargets": mod.reading_layout_targets(make_args()),
                        "readingInputFingerprint": "reading-v1",
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(
                mod.reading_report_matches_inputs(
                    report_path,
                    make_args(),
                    expected_input_fingerprint="reading-v1",
                )
            )
            self.assertFalse(
                mod.reading_report_matches_inputs(
                    report_path,
                    make_args(),
                    expected_input_fingerprint="reading-v2",
                )
            )

    def test_upload_outputs_preserves_pipeline_relative_paths(self):
        with tempfile.TemporaryDirectory() as tempdir:
            pipeline = Path(tempdir) / "pipeline"
            reading = pipeline / "reading-edition-v2"
            reading.mkdir(parents=True)
            (pipeline / "sermon_zh_en_reading.qa.json").write_text('{"status":"pass"}', encoding="utf-8")
            (reading / "reading_quality_report.json").write_text('{"status":"pass"}', encoding="utf-8")

            with mock.patch.object(mod, "upload_file_to_gcs") as uploader:
                uploaded = mod.upload_outputs(
                    make_args(gcs_bucket="sermon-artifacts"),
                    pipeline,
                )

        destinations = [call.args[1] for call in uploader.call_args_list]
        self.assertIn(
            "gs://sermon-artifacts/sundays/2026-06-28/post-live-subtitles/"
            "mariners_MEZHufeQBjc/pipeline/sermon_zh_en_reading.qa.json",
            destinations,
        )
        self.assertIn(
            "gs://sermon-artifacts/sundays/2026-06-28/post-live-subtitles/"
            "mariners_MEZHufeQBjc/pipeline/reading-edition-v2/reading_quality_report.json",
            destinations,
        )
        self.assertEqual({item["gcsUri"] for item in uploaded}, set(destinations))


if __name__ == "__main__":
    unittest.main()

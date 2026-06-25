import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import scripts.run_realtime_audio_source_preflight as mod


class RealtimeAudioSourcePreflightTest(unittest.TestCase):
    def test_audio_url_preflight_redacts_query_without_prepare(self):
        report = mod.run_preflight(
            args_for(audio_url="https://audio.example.test/live.m3u8?token=secret-runtime")
        )

        rendered = json.dumps(report)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["source"]["kind"], "authorized_audio_url")
        self.assertEqual(report["source"]["display"], "https://audio.example.test/live.m3u8")
        self.assertIn("prepare_audio", report["warnings"])
        self.assertNotIn("secret-runtime", rendered)

    def test_invalid_audio_url_fails(self):
        report = mod.run_preflight(args_for(audio_url="file:///tmp/audio.wav"))

        self.assertEqual(report["status"], "failed")
        self.assertIn("source_plan", report["failedChecks"])

    def test_audio_file_prepare_runs_ffmpeg_and_verifies_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "source.wav"
            audio.write_bytes(b"fake wav")
            out_dir = root / "out"

            def fake_run(command, **kwargs):
                output = Path(command[-1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"0" * mod.MIN_PREPARED_AUDIO_BYTES)
                return completed(0)

            with patch.object(mod.subprocess, "run", side_effect=fake_run):
                report = mod.run_preflight(
                    args_for(audio_file=audio, out_dir=out_dir, prepare_audio=True)
                )

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["source"]["kind"], "authorized_audio_file")
        self.assertEqual(report["commandResults"][0]["status"], "ok")
        self.assertEqual(report["warnings"], [])
        self.assertFalse(report["apiKeyMaterialIncluded"])

    def test_empty_prepared_audio_marks_report_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "source.wav"
            audio.write_bytes(b"fake wav")
            out_dir = root / "out"

            def fake_run(command, **kwargs):
                output = Path(command[-1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"RIFF")
                return completed(0)

            with patch.object(mod.subprocess, "run", side_effect=fake_run):
                report = mod.run_preflight(
                    args_for(audio_file=audio, out_dir=out_dir, prepare_audio=True)
                )

        self.assertEqual(report["status"], "failed")
        self.assertIn("prepared_audio_nonempty", report["failedChecks"])

    def test_prepare_failure_marks_report_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "source.wav"
            audio.write_bytes(b"fake wav")

            with patch.object(mod.subprocess, "run", return_value=completed(1, stderr="bad audio")):
                report = mod.run_preflight(args_for(audio_file=audio, prepare_audio=True))

        self.assertEqual(report["status"], "failed")
        self.assertIn("prepare_audio", report["failedChecks"])

    def test_youtube_preflight_redacts_query(self):
        report = mod.run_preflight(
            args_for(youtube_url="https://www.youtube.com/watch?v=abc123&token=runtime-only")
        )

        rendered = json.dumps(report)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["source"]["kind"], "authorized_youtube_source")
        self.assertNotIn("runtime-only", rendered)


def args_for(
    *,
    audio_file=None,
    audio_url=None,
    youtube_url=None,
    out_dir=None,
    prepare_audio=False,
):
    return Namespace(
        audio_file=audio_file,
        audio_url=audio_url,
        youtube_url=youtube_url,
        sunday="2026-06-28",
        out_dir=out_dir or Path("artifacts/realtime-audio-source-preflight-test"),
        out=None,
        yt_dlp="yt-dlp",
        ffmpeg="ffmpeg",
        sample_rate=24000,
        prepare_audio=prepare_audio,
    )


def completed(returncode, stdout="", stderr=""):
    class Completed:
        pass

    item = Completed()
    item.returncode = returncode
    item.stdout = stdout
    item.stderr = stderr
    return item


if __name__ == "__main__":
    unittest.main()

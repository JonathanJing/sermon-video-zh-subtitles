import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "realtime_media_worker.py"
SPEC = importlib.util.spec_from_file_location("realtime_media_worker", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
import sys

sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def base_args(**overrides):
    values = {
        "audio_file": None,
        "youtube_url": None,
        "replay_jsonl": None,
        "sunday": "2026-06-28",
        "backend_url": None,
        "session_id": None,
        "event_token": None,
        "create_backend_session": False,
        "admin_token": None,
        "internal_task_token": None,
        "event_log_dir": Path("/tmp/sermon-realtime-events-test"),
        "out_dir": Path("artifacts/realtime-media-worker-test"),
        "yt_dlp": "yt-dlp",
        "ffmpeg": "ffmpeg",
        "sample_rate": 24000,
        "model": "gpt-realtime-translate",
        "target_language": "zh-CN",
        "dry_run": False,
        "prepare_audio": False,
        "max_replay_events": 200,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RealtimeMediaWorkerTest(unittest.TestCase):
    def test_audio_file_plan_normalizes_to_mono_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "sermon.m4a"
            audio.write_bytes(b"fake audio")
            args = base_args(audio_file=audio, out_dir=root / "out")

            plan = mod.build_audio_source_plan(args)

            self.assertEqual(plan.kind, "authorized_audio_file")
            self.assertEqual(plan.normalized_audio_path, root / "out" / "source.normalized.wav")
            command = plan.commands[0]
            self.assertIn("-ac", command)
            self.assertIn("1", command)
            self.assertIn("-ar", command)
            self.assertIn("24000", command)

    def test_rejects_non_youtube_url_for_youtube_source(self):
        with self.assertRaises(SystemExit):
            mod.validate_youtube_url("https://example.com/watch?v=abc123")

    def test_youtube_plan_redacts_query_string(self):
        args = base_args(
            youtube_url="https://www.youtube.com/watch?v=abc123&secret=not-for-report",
            out_dir=Path("/tmp/realtime-worker-out"),
        )

        plan = mod.build_audio_source_plan(args)

        self.assertEqual(plan.kind, "authorized_youtube_source")
        self.assertEqual(plan.display_source, "https://www.youtube.com/watch")
        self.assertIn("--extract-audio", plan.commands[0])
        self.assertNotIn("secret=not-for-report", plan.display_source)

    def test_replay_jsonl_writes_sanitized_local_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay = root / "replay.jsonl"
            replay.write_text(
                '{"type":"caption_delta","text":"神爱世人","Authorization":"Bearer secret","apiKey":"sk-secret"}\n',
                encoding="utf-8",
            )
            args = base_args(
                replay_jsonl=replay,
                event_log_dir=root / "events",
                out_dir=root / "out",
            )

            report = mod.run_worker(args)

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["eventsPosted"], 4)
            archive_path = root / "events" / f"{report['sessionId']}.jsonl"
            text = archive_path.read_text(encoding="utf-8")
            self.assertIn('"type": "session_started"', text)
            self.assertIn('"type": "caption_delta"', text)
            self.assertIn('"text": "神爱世人"', text)
            self.assertNotIn("Authorization", text)
            self.assertNotIn("sk-secret", text)

    def test_dry_run_does_not_create_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay = root / "replay.jsonl"
            replay.write_text('{"type":"caption_delta","text":"x"}\n', encoding="utf-8")
            args = base_args(
                replay_jsonl=replay,
                event_log_dir=root / "events",
                dry_run=True,
            )

            report = mod.run_worker(args)

            self.assertEqual(report["status"], "planned")
            self.assertEqual(report["eventsPosted"], 0)
            self.assertFalse((root / "events").exists())

    def test_ensure_command_output_dirs_uses_ytdlp_output_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = [
                "yt-dlp",
                "-o",
                str(root / "nested" / "youtube-source.%(ext)s"),
                "https://www.youtube.com/watch?v=abc123",
            ]

            mod.ensure_command_output_dirs(command)

            self.assertTrue((root / "nested").is_dir())
            self.assertFalse((Path("https:")).exists())


if __name__ == "__main__":
    unittest.main()

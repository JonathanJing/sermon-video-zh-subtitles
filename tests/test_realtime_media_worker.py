import importlib.util
import io
import json
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
        "connect_openai": False,
        "api_key_secret": None,
        "openai_api_key_env": "OPENAI_API_KEY",
        "openai_safety_identifier": "sermon-realtime-media-worker",
        "chunk_ms": 100,
        "max_audio_seconds": None,
        "no_realtime_throttle": True,
        "openai_close_timeout": 1.0,
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

    def test_dry_run_report_redacts_url_query_from_commands(self):
        args = base_args(
            youtube_url="https://www.youtube.com/watch?v=abc123&secret=not-for-report",
            out_dir=Path("/tmp/realtime-worker-out"),
            connect_openai=True,
            dry_run=True,
        )

        report = mod.run_worker(args)
        rendered = json.dumps(report)

        self.assertEqual(report["openaiRealtime"]["websocketEndpoint"], mod.OPENAI_TRANSLATION_WS_BASE)
        self.assertFalse(report["openaiRealtime"]["apiKeyMaterialIncluded"])
        self.assertNotIn("secret=not-for-report", rendered)

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

    def test_maps_openai_translation_events_to_realtime_payloads(self):
        caption = mod.openai_event_to_realtime_payload(
            {
                "type": "session.output_transcript.delta",
                "delta": "神爱世人",
                "item_id": "seg_1",
            }
        )
        source = mod.openai_event_to_realtime_payload(
            {
                "type": "session.input_transcript.delta",
                "delta": "God loved the world",
                "item_id": "seg_1",
            }
        )

        self.assertEqual(caption["type"], "caption_delta")
        self.assertEqual(caption["zh"], "神爱世人")
        self.assertEqual(caption["source"], "openai_realtime_translation_ws")
        self.assertEqual(source["type"], "input_transcript_delta")
        self.assertEqual(source["en"], "God loved the world")

    def test_raw_pcm_command_for_audio_file_streams_s16le_to_stdout(self):
        args = base_args(audio_file=Path("/tmp/sermon.wav"))
        plan = mod.AudioSourcePlan(
            kind="authorized_audio_file",
            source="/tmp/sermon.wav",
            display_source="sermon.wav",
            normalized_audio_path=Path("/tmp/out.wav"),
            commands=[],
            warnings=[],
        )

        command = mod.raw_pcm_command(args=args, plan=plan)

        self.assertEqual(command[:4], ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel"])
        self.assertIn("-f", command)
        self.assertIn("s16le", command)
        self.assertEqual(command[-1], "pipe:1")

    def test_relay_openai_translation_sends_pcm_and_publishes_deltas(self):
        class FakeWs:
            def __init__(self):
                self.sent = []
                self.closed = False
                self.incoming = [
                    json.dumps({"type": "session.output_transcript.delta", "delta": "神爱世人", "item_id": "seg_1"}),
                    json.dumps({"type": "session.input_transcript.delta", "delta": "God loved the world", "item_id": "seg_1"}),
                    json.dumps({"type": "session.closed"}),
                ]

            def send(self, payload):
                self.sent.append(json.loads(payload))

            def recv(self):
                return self.incoming.pop(0) if self.incoming else json.dumps({"type": "session.closed"})

            def close(self):
                self.closed = True

        class FakeProc:
            def __init__(self):
                self.stdout = io.BytesIO(b"\x00\x01" * 2400)

            def wait(self, timeout=None):
                return 0

        events = []
        sink = SimpleNamespace(
            session_id="rt_test",
            emit=lambda payload: events.append(payload) or {"id": len(events)},
        )
        fake_ws = FakeWs()
        args = base_args(
            audio_file=Path("/tmp/sermon.wav"),
            connect_openai=True,
            chunk_ms=100,
            no_realtime_throttle=True,
        )
        plan = mod.AudioSourcePlan(
            kind="authorized_audio_file",
            source="/tmp/sermon.wav",
            display_source="sermon.wav",
            normalized_audio_path=Path("/tmp/out.wav"),
            commands=[],
            warnings=[],
        )

        stats = mod.relay_openai_translation(
            args=args,
            plan=plan,
            sink=sink,
            api_key="sk-test",
            ws_factory=lambda url, headers: fake_ws,
            popen_factory=lambda *args, **kwargs: FakeProc(),
        )

        sent_types = [payload["type"] for payload in fake_ws.sent]
        self.assertEqual(sent_types[0], "session.update")
        self.assertIn("session.input_audio_buffer.append", sent_types)
        self.assertEqual(sent_types[-1], "session.close")
        self.assertTrue(fake_ws.closed)
        self.assertEqual(stats["captionEventsPosted"], 1)
        self.assertEqual(stats["inputTranscriptEventsPosted"], 1)
        self.assertEqual(events[0]["type"], "caption_delta")
        self.assertEqual(events[1]["type"], "input_transcript_delta")


if __name__ == "__main__":
    unittest.main()

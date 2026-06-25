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
        "audio_url": None,
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
        "report_out": None,
        "yt_dlp": "yt-dlp",
        "ffmpeg": "ffmpeg",
        "sample_rate": 24000,
        "model": "gpt-realtime-translate",
        "target_language": "zh",
        "dry_run": False,
        "connect_openai": False,
        "api_key_secret": None,
        "openai_api_key_env": "OPENAI_API_KEY",
        "openai_safety_identifier": "sermon-realtime-media-worker",
        "disable_input_transcript_sidecar": True,
        "input_transcript_session_model": mod.DEFAULT_REALTIME_INPUT_TRANSCRIPT_SESSION_MODEL,
        "input_transcript_model": mod.DEFAULT_REALTIME_INPUT_TRANSCRIPT_MODEL,
        "input_transcript_language": mod.DEFAULT_REALTIME_INPUT_TRANSCRIPT_LANGUAGE,
        "input_transcript_delay": mod.DEFAULT_REALTIME_INPUT_TRANSCRIPT_DELAY,
        "input_transcript_commit_ms": 2000,
        "disable_input_transcript_audio_api_fallback": False,
        "input_transcript_fallback_model": mod.DEFAULT_INPUT_TRANSCRIPT_FALLBACK_MODEL,
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

    def test_rejects_non_http_audio_url(self):
        with self.assertRaises(SystemExit):
            mod.validate_audio_url("file:///tmp/sermon.wav")

    def test_rejects_wrong_realtime_translation_model(self):
        with self.assertRaises(SystemExit):
            mod.validate_realtime_translation_model("gpt-realtime-2", "zh")

    def test_rejects_wrong_realtime_target_language(self):
        with self.assertRaises(SystemExit):
            mod.validate_realtime_translation_model("gpt-realtime-translate", "es")

    def test_rejects_wrong_input_transcript_fallback_model(self):
        with self.assertRaises(SystemExit):
            mod.validate_input_transcript_fallback_model("gpt-4o-mini-transcribe")

    def test_audio_url_plan_redacts_query_string(self):
        args = base_args(
            audio_url="https://audio.example.test/live/sermon.m3u8?token=not-for-report",
            out_dir=Path("/tmp/realtime-worker-out"),
        )

        plan = mod.build_audio_source_plan(args)

        self.assertEqual(plan.kind, "authorized_audio_url")
        self.assertEqual(plan.display_source, "https://audio.example.test/live/sermon.m3u8")
        self.assertIsNone(plan.normalized_audio_path)
        self.assertEqual(plan.commands, [])
        self.assertNotIn("token=not-for-report", plan.display_source)

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
        with tempfile.TemporaryDirectory() as tmp:
            report_out = Path(tmp) / "worker-report.json"
            args = base_args(
                youtube_url="https://www.youtube.com/watch?v=abc123&secret=not-for-report",
                out_dir=Path("/tmp/realtime-worker-out"),
                connect_openai=True,
                dry_run=True,
                report_out=report_out,
            )

            report = mod.run_worker(args)
            rendered = json.dumps(report)
            saved = report_out.read_text(encoding="utf-8")

            self.assertEqual(report["openaiRealtime"]["websocketEndpoint"], mod.OPENAI_TRANSLATION_WS_BASE)
            self.assertFalse(report["openaiRealtime"]["apiKeyMaterialIncluded"])
            self.assertNotIn("secret=not-for-report", rendered)
            self.assertNotIn("secret=not-for-report", saved)

    def test_audio_url_dry_run_report_redacts_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_out = Path(tmp) / "worker-report.json"
            args = base_args(
                audio_url="https://audio.example.test/live/sermon.m3u8?token=not-for-report",
                connect_openai=True,
                dry_run=True,
                report_out=report_out,
            )

            report = mod.run_worker(args)
            rendered = json.dumps(report)
            saved = report_out.read_text(encoding="utf-8")

            self.assertEqual(report["source"]["kind"], "authorized_audio_url")
            self.assertEqual(report["source"]["display"], "https://audio.example.test/live/sermon.m3u8")
            self.assertNotIn("token=not-for-report", rendered)
            self.assertNotIn("token=not-for-report", saved)

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
                "latency_ms": 740,
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
        self.assertEqual(caption["latencyMs"], 740)
        self.assertEqual(source["type"], "input_transcript_delta")
        self.assertEqual(source["en"], "God loved the world")

    def test_maps_nested_openai_response_latency_to_realtime_payload(self):
        caption = mod.openai_event_to_realtime_payload(
            {
                "type": "session.output_transcript.delta",
                "delta": "神爱世人",
                "item_id": "seg_1",
                "response": {"latency_ms": 1280},
            }
        )

        self.assertEqual(caption["latencyMs"], 1280)

    def test_maps_nested_openai_output_transcript_payloads(self):
        caption = mod.openai_event_to_realtime_payload(
            {
                "type": "session.output_transcript.done",
                "response": {
                    "id": "resp_1",
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "output_transcript": "神爱世人。",
                                }
                            ]
                        }
                    ],
                },
            }
        )

        self.assertEqual(caption["type"], "caption_final")
        self.assertEqual(caption["zh"], "神爱世人。")
        self.assertEqual(caption["segmentId"], "resp_1")
        self.assertTrue(caption["final"])

    def test_maps_nested_openai_output_transcript_delta_object(self):
        caption = mod.openai_event_to_realtime_payload(
            {
                "type": "session.output_transcript.delta",
                "output_transcript": {
                    "delta": "神爱世人",
                },
                "response": {
                    "id": "resp_delta_1",
                },
            }
        )

        self.assertEqual(caption["type"], "caption_delta")
        self.assertEqual(caption["zh"], "神爱世人")
        self.assertEqual(caption["delta"], "神爱世人")
        self.assertEqual(caption["segmentId"], "resp_delta_1")

    def test_maps_nested_openai_input_transcription_payloads(self):
        source = mod.openai_event_to_realtime_payload(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item": {
                    "id": "item_1",
                    "content": [
                        {
                            "type": "input_audio",
                            "transcript": "God loved the world.",
                        }
                    ],
                },
            }
        )

        self.assertEqual(source["type"], "input_transcript_final")
        self.assertEqual(source["en"], "God loved the world.")
        self.assertEqual(source["segmentId"], "item_1")
        self.assertTrue(source["final"])

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

    def test_raw_pcm_command_for_audio_url_streams_s16le_to_stdout(self):
        args = base_args(audio_url="https://audio.example.test/live/sermon.m3u8?token=runtime-only")
        plan = mod.AudioSourcePlan(
            kind="authorized_audio_url",
            source=args.audio_url,
            display_source="https://audio.example.test/live/sermon.m3u8",
            normalized_audio_path=None,
            commands=[],
            warnings=[],
        )

        command = mod.raw_pcm_command(args=args, plan=plan)

        self.assertEqual(command[:4], ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel"])
        self.assertIn("https://audio.example.test/live/sermon.m3u8?token=runtime-only", command)
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
            disable_input_transcript_sidecar=True,
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
        self.assertEqual(stats["eventTypeCounts"]["session.output_transcript.delta"], 1)
        self.assertEqual(stats["eventTypeCounts"]["session.input_transcript.delta"], 1)
        self.assertEqual(events[0]["type"], "caption_delta")
        self.assertEqual(events[1]["type"], "input_transcript_delta")

    def test_relay_openai_translation_can_publish_parallel_input_transcript_sidecar(self):
        class FakeWs:
            def __init__(self, incoming):
                self.sent = []
                self.closed = False
                self.incoming = list(incoming)

            def send(self, payload):
                self.sent.append(json.loads(payload))

            def recv(self):
                if not self.incoming:
                    raise RuntimeError("socket closed")
                return self.incoming.pop(0)

            def close(self):
                self.closed = True

        class FakeProc:
            def __init__(self):
                self.stdout = io.BytesIO(b"\x00\x01" * 2400)

            def wait(self, timeout=None):
                return 0

        translation_ws = FakeWs(
            [
                json.dumps({"type": "session.output_transcript.delta", "delta": "神爱世人", "item_id": "zh_1"}),
                json.dumps({"type": "session.closed"}),
            ]
        )
        transcription_ws = FakeWs(
            [
                json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.delta",
                        "delta": "God loved the world",
                        "item_id": "en_1",
                    }
                ),
                json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.completed",
                        "transcript": "God loved the world.",
                        "item_id": "en_1",
                    }
                ),
            ]
        )

        def fake_ws_factory(url, headers):
            return translation_ws if "/translations" in url else transcription_ws

        events = []
        sink = SimpleNamespace(
            session_id="rt_test",
            emit=lambda payload: events.append(payload) or {"id": len(events)},
        )
        args = base_args(
            audio_file=Path("/tmp/sermon.wav"),
            connect_openai=True,
            chunk_ms=100,
            disable_input_transcript_sidecar=False,
            input_transcript_commit_ms=100,
            no_realtime_throttle=True,
            openai_close_timeout=0.01,
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
            ws_factory=fake_ws_factory,
            popen_factory=lambda *args, **kwargs: FakeProc(),
        )

        self.assertEqual(events[0]["type"], "caption_delta")
        self.assertEqual(events[1]["type"], "input_transcript_delta")
        self.assertEqual(events[1]["source"], "openai_realtime_transcription_ws")
        self.assertEqual(events[2]["type"], "input_transcript_final")
        self.assertEqual(stats["captionEventsPosted"], 1)
        self.assertEqual(stats["inputTranscriptEventsPosted"], 2)
        self.assertEqual(stats["inputTranscriptSidecar"]["model"], "gpt-realtime-whisper")
        transcription_sent_types = [payload["type"] for payload in transcription_ws.sent]
        self.assertEqual(transcription_sent_types[0], "session.update")
        self.assertIn("input_audio_buffer.append", transcription_sent_types)
        self.assertIn("input_audio_buffer.commit", transcription_sent_types)

    def test_relay_openai_translation_uses_audio_api_fallback_for_missing_input_transcript(self):
        class FakeWs:
            def __init__(self):
                self.sent = []
                self.closed = False
                self.incoming = [
                    json.dumps({"type": "session.output_transcript.delta", "delta": "神爱世人", "item_id": "zh_1"}),
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

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "sermon.wav"
            audio.write_bytes(b"fake wav")
            events = []
            sink = SimpleNamespace(
                session_id="rt_test",
                emit=lambda payload: events.append(payload) or {"id": len(events)},
            )
            args = base_args(
                audio_file=audio,
                connect_openai=True,
                chunk_ms=100,
                no_realtime_throttle=True,
                disable_input_transcript_sidecar=True,
            )
            plan = mod.AudioSourcePlan(
                kind="authorized_audio_file",
                source=str(audio),
                display_source="sermon.wav",
                normalized_audio_path=None,
                commands=[],
                warnings=[],
            )
            original_transcribe = mod.request_audio_transcription
            try:
                mod.request_audio_transcription = lambda **kwargs: "God loved the world."
                stats = mod.relay_openai_translation(
                    args=args,
                    plan=plan,
                    sink=sink,
                    api_key="sk-test",
                    ws_factory=lambda url, headers: FakeWs(),
                    popen_factory=lambda *args, **kwargs: FakeProc(),
                )
            finally:
                mod.request_audio_transcription = original_transcribe

        self.assertEqual(events[0]["type"], "caption_delta")
        self.assertEqual(events[1]["type"], "input_transcript_final")
        self.assertEqual(events[1]["source"], "openai_audio_transcription_fallback")
        self.assertEqual(events[1]["model"], "gpt-4o-transcribe")
        self.assertEqual(stats["inputTranscriptEventsPosted"], 1)
        self.assertEqual(stats["inputTranscriptFallback"]["status"], "ok")

    def test_worker_counts_openai_caption_and_input_transcript_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "sermon.wav"
            audio.write_bytes(b"fake wav")
            args = base_args(
                audio_file=audio,
                connect_openai=True,
                event_log_dir=root / "events",
                no_realtime_throttle=True,
            )
            original_resolve_key = mod.resolve_openai_api_key
            original_relay = mod.relay_openai_translation
            try:
                mod.resolve_openai_api_key = lambda raw_key, secret: "sk-test"
                mod.relay_openai_translation = lambda **kwargs: {
                    "model": "gpt-realtime-translate",
                    "targetLanguage": "zh",
                    "audioChunksSent": 1,
                    "bytesSent": 4800,
                    "openaiEventsReceived": 2,
                    "captionEventsPosted": 1,
                    "inputTranscriptEventsPosted": 1,
                    "eventTypeCounts": {"session.output_transcript.delta": 1},
                }

                report = mod.run_worker(args)
            finally:
                mod.resolve_openai_api_key = original_resolve_key
                mod.relay_openai_translation = original_relay

            self.assertEqual(report["eventsPosted"], 5)
            self.assertEqual(report["openaiRealtime"]["captionEventsPosted"], 1)
            self.assertEqual(report["openaiRealtime"]["inputTranscriptEventsPosted"], 1)
            self.assertEqual(report["openaiRealtime"]["eventTypeCounts"]["session.output_transcript.delta"], 1)


if __name__ == "__main__":
    unittest.main()

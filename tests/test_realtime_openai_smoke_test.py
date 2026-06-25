import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "realtime_openai_smoke_test.py"
SPEC = importlib.util.spec_from_file_location("realtime_openai_smoke_test", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def base_args(**overrides):
    values = {
        "audio_file": Path("/tmp/authorized-sermon.wav"),
        "api_key_secret": "projects/example/secrets/openai-api-key/versions/latest",
        "backend_url": "http://127.0.0.1:8080",
        "sunday": "2026-06-28",
        "admin_token": None,
        "internal_task_token": None,
        "max_audio_seconds": 8.0,
        "target_language": "zh",
        "model": "gpt-realtime-translate",
        "out": Path("artifacts/realtime-openai-smoke/report.json"),
        "worker_report_out": Path("artifacts/realtime-openai-smoke/worker-report.json"),
        "session_validation_out": Path("artifacts/realtime-openai-smoke/realtime-session-validation.json"),
        "skip_session_validation": False,
        "event_log_dir": Path("/tmp/sermon-realtime-smoke-events"),
        "realtime_event_gcs_prefix": None,
        "sse_timeout_seconds": 4.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSseResponse:
    def __init__(self, lines):
        self.lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self.lines)


class RealtimeOpenAiSmokeTest(unittest.TestCase):
    def test_has_openai_caption_and_input_requires_realtime_sources(self):
        events = [
            {"type": "caption_delta", "source": "openai_realtime_translation_ws", "zh": "神爱世人"},
            {"type": "input_transcript_delta", "source": "manual", "en": "God loved the world"},
        ]

        self.assertFalse(mod.has_openai_caption_and_input(events))

        events.append(
            {
                "type": "input_transcript_final",
                "source": "openai_realtime_translation_ws",
                "en": "God loved the world",
            }
        )
        self.assertTrue(mod.has_openai_caption_and_input(events))

    def test_worker_args_from_smoke_args_enables_backend_and_openai_relay(self):
        args = base_args()

        worker_args = mod.worker_args_from_smoke_args(args)

        self.assertTrue(worker_args.create_backend_session)
        self.assertTrue(worker_args.connect_openai)
        self.assertFalse(worker_args.dry_run)
        self.assertFalse(worker_args.prepare_audio)
        self.assertEqual(worker_args.api_key_secret, "projects/example/secrets/openai-api-key/versions/latest")
        self.assertEqual(worker_args.openai_safety_identifier, "sermon-realtime-smoke-test")
        self.assertEqual(worker_args.max_audio_seconds, 8.0)
        self.assertTrue(worker_args.disable_input_transcript_sidecar)
        self.assertEqual(worker_args.input_transcript_session_model, "gpt-realtime-2")
        self.assertEqual(worker_args.input_transcript_model, "gpt-realtime-whisper")

    def test_realtime_events_jsonl_uri_uses_sanitized_session_id(self):
        uri = mod.realtime_events_gcs_uri(
            prefix="gs://sermon-zh-artifacts/realtime-events/",
            sunday="2026-06-28",
            session_id="rt bad/id",
        )

        self.assertEqual(uri, "gs://sermon-zh-artifacts/realtime-events/2026-06-28/rt_bad_id.jsonl")

    def test_realtime_events_jsonl_uri_uses_local_event_log_without_gcs_prefix(self):
        args = base_args(event_log_dir=Path("/tmp/smoke-events"), realtime_event_gcs_prefix=None)

        uri = mod.realtime_events_jsonl_uri(args=args, session_id="rt bad/id")

        self.assertEqual(uri, "/tmp/smoke-events/rt_bad_id.jsonl")

    def test_read_sse_events_stops_after_caption_and_input_events(self):
        lines = [
            ": heartbeat\n",
            'data: {"type":"media_worker_started","source":"realtime_media_worker"}\n',
            'data: {"type":"caption_delta","source":"openai_realtime_translation_ws","zh":"神爱世人"}\n',
            'data: {"type":"input_transcript_delta","source":"openai_realtime_translation_ws","en":"God loved the world"}\n',
            'data: {"type":"caption_final","source":"openai_realtime_translation_ws","zh":"extra"}\n',
        ]
        captured = {}

        def fake_urlopen(url, timeout):
            captured["url"] = url
            captured["timeout"] = timeout
            return FakeSseResponse(lines)

        original_urlopen = mod.urlopen
        try:
            mod.urlopen = fake_urlopen
            events = mod.read_sse_events(
                backend_url="http://127.0.0.1:8080/",
                session_id="rt session",
                timeout_seconds=3.0,
                max_events=80,
            )
        finally:
            mod.urlopen = original_urlopen

        self.assertEqual(captured["timeout"], 3.0)
        self.assertIn("/api/realtime/sessions/rt%20session/events?cursor=0", captured["url"])
        self.assertEqual(len(events), 3)
        self.assertTrue(mod.has_openai_caption_and_input(events))

    def test_run_smoke_reports_ok_when_worker_and_sse_have_transcripts(self):
        args = base_args(realtime_event_gcs_prefix="gs://sermon-zh-artifacts/realtime-events")
        fake_worker_report = {
            "status": "ok",
            "sessionId": "rt_smoke",
            "openaiRealtime": {
                "audioChunksSent": 2,
                "openaiEventsReceived": 4,
                "captionEventsPosted": 1,
                "inputTranscriptEventsPosted": 1,
                "eventTypeCounts": {
                    "session.output_transcript.delta": 1,
                    "session.input_transcript.delta": 1,
                },
                "inputTranscriptFallback": {"enabled": True, "model": "gpt-4o-transcribe", "eventsPosted": 0},
            },
        }
        fake_events = [
            {"type": "caption_delta", "source": "openai_realtime_translation_ws", "zh": "神爱世人"},
            {
                "type": "input_transcript_delta",
                "source": "openai_realtime_translation_ws",
                "en": "God loved the world",
            },
        ]
        seen = {}

        original_run_worker = mod.realtime_media_worker.run_worker
        original_read_sse_events = mod.read_sse_events
        original_run_session_validation = mod.run_session_validation
        try:
            def fake_run_worker(worker_args):
                seen["worker_args"] = worker_args
                return fake_worker_report

            def fake_read_sse_events(**kwargs):
                seen["sse_kwargs"] = kwargs
                return fake_events

            def fake_run_session_validation(**kwargs):
                seen["validation_kwargs"] = kwargs
                return {
                    "status": "ok",
                    "report": "artifacts/realtime-openai-smoke/realtime-session-validation.json",
                    "failedChecks": [],
                    "counts": {"events": 4, "inputTranscriptEvents": 1, "realtimeCaptionEvents": 1},
                }

            mod.realtime_media_worker.run_worker = fake_run_worker
            mod.read_sse_events = fake_read_sse_events
            mod.run_session_validation = fake_run_session_validation

            report = mod.run_smoke(args)
        finally:
            mod.realtime_media_worker.run_worker = original_run_worker
            mod.read_sse_events = original_read_sse_events
            mod.run_session_validation = original_run_session_validation

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["sessionId"], "rt_smoke")
        self.assertEqual(
            report["realtimeEventsJsonl"],
            "gs://sermon-zh-artifacts/realtime-events/2026-06-28/rt_smoke.jsonl",
        )
        self.assertEqual(report["sse"]["captionEvents"], 1)
        self.assertEqual(report["sse"]["inputTranscriptEvents"], 1)
        self.assertEqual(report["sessionValidation"]["status"], "ok")
        self.assertEqual(report["openaiRealtime"]["eventTypeCounts"]["session.input_transcript.delta"], 1)
        self.assertEqual(report["openaiRealtime"]["inputTranscriptFallback"]["model"], "gpt-4o-transcribe")
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])
        self.assertTrue(seen["worker_args"].connect_openai)
        self.assertEqual(seen["worker_args"].event_log_dir, Path("/tmp/sermon-realtime-smoke-events"))
        self.assertEqual(seen["sse_kwargs"]["session_id"], "rt_smoke")
        self.assertTrue(seen["validation_kwargs"]["should_validate"])

    def test_run_smoke_requires_input_transcript_for_ok_status(self):
        args = base_args(skip_session_validation=True)
        fake_worker_report = {
            "status": "ok",
            "sessionId": "rt_smoke",
            "openaiRealtime": {
                "audioChunksSent": 2,
                "openaiEventsReceived": 3,
                "captionEventsPosted": 1,
                "inputTranscriptEventsPosted": 0,
            },
        }
        fake_events = [
            {"type": "caption_delta", "source": "openai_realtime_translation_ws", "zh": "神爱世人"},
        ]
        original_run_worker = mod.realtime_media_worker.run_worker
        original_read_sse_events = mod.read_sse_events
        try:
            mod.realtime_media_worker.run_worker = lambda worker_args: fake_worker_report
            mod.read_sse_events = lambda **kwargs: fake_events

            report = mod.run_smoke(args)
        finally:
            mod.realtime_media_worker.run_worker = original_run_worker
            mod.read_sse_events = original_read_sse_events

        self.assertEqual(report["status"], "missing_input_transcript")
        self.assertFalse(report["inputTranscriptAvailable"])
        self.assertIn("openai_input_transcript_unavailable", report["warnings"])

    def test_run_smoke_reports_worker_failed_before_transcript_status(self):
        args = base_args(skip_session_validation=True)
        original_run_worker = mod.realtime_media_worker.run_worker
        original_read_sse_events = mod.read_sse_events
        try:
            mod.realtime_media_worker.run_worker = lambda worker_args: {"status": "failed", "sessionId": "rt_smoke"}
            mod.read_sse_events = lambda **kwargs: []

            report = mod.run_smoke(args)
        finally:
            mod.realtime_media_worker.run_worker = original_run_worker
            mod.read_sse_events = original_read_sse_events

        self.assertEqual(report["status"], "worker_failed")
        self.assertEqual(report["sse"]["eventsRead"], 0)

    def test_run_smoke_marks_validation_failed_when_session_jsonl_fails(self):
        args = base_args()
        fake_worker_report = {
            "status": "ok",
            "sessionId": "rt_smoke",
            "openaiRealtime": {
                "audioChunksSent": 2,
                "openaiEventsReceived": 4,
                "captionEventsPosted": 1,
                "inputTranscriptEventsPosted": 1,
            },
        }
        fake_events = [
            {"type": "caption_delta", "source": "openai_realtime_translation_ws", "zh": "神爱世人"},
            {
                "type": "input_transcript_final",
                "source": "openai_audio_transcription_fallback",
                "en": "God loved the world",
            },
        ]
        original_run_worker = mod.realtime_media_worker.run_worker
        original_read_sse_events = mod.read_sse_events
        original_run_session_validation = mod.run_session_validation
        try:
            mod.realtime_media_worker.run_worker = lambda worker_args: fake_worker_report
            mod.read_sse_events = lambda **kwargs: fake_events
            mod.run_session_validation = lambda **kwargs: {
                "status": "failed",
                "report": "artifacts/realtime-openai-smoke/realtime-session-validation.json",
                "failedChecks": ["realtime_model"],
                "counts": {"events": 2},
            }

            report = mod.run_smoke(args)
        finally:
            mod.realtime_media_worker.run_worker = original_run_worker
            mod.read_sse_events = original_read_sse_events
            mod.run_session_validation = original_run_session_validation

        self.assertEqual(report["status"], "validation_failed")
        self.assertIn("session_validation_failed", report["warnings"])
        self.assertEqual(report["sessionValidation"]["failedChecks"], ["realtime_model"])

    def test_run_session_validation_writes_report_for_local_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_jsonl = root / "rt_smoke.jsonl"
            out = root / "validation.json"
            rows = [
                {
                    "id": 1,
                    "type": "media_worker_started",
                    "source": "realtime_media_worker",
                    "sessionId": "rt_smoke",
                    "model": "gpt-realtime-translate",
                    "targetLanguage": "zh",
                    "audioSourceKind": "authorized_audio_file",
                },
                {
                    "id": 2,
                    "type": "input_transcript_final",
                    "source": "openai_audio_transcription_fallback",
                    "sessionId": "rt_smoke",
                    "en": "God loved the world",
                    "segmentId": "seg_1",
                },
                {
                    "id": 3,
                    "type": "caption_delta",
                    "source": "openai_realtime_translation_ws",
                    "sessionId": "rt_smoke",
                    "model": "gpt-realtime-translate",
                    "zh": "神爱世人",
                    "segmentId": "seg_1",
                },
            ]
            events_jsonl.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
            args = base_args(session_validation_out=out)

            summary = mod.run_session_validation(args=args, events_uri=str(events_jsonl), should_validate=True)

            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["counts"]["events"], 3)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "ok")
            self.assertEqual(written["models"], ["gpt-realtime-translate"])

    def test_main_writes_report_and_returns_nonzero_without_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "authorized.wav"
            audio.write_bytes(b"fake audio")
            out = root / "report.json"
            argv = [
                "realtime_openai_smoke_test.py",
                "--audio-file",
                str(audio),
                "--api-key-secret",
                "projects/example/secrets/openai-api-key/versions/latest",
                "--backend-url",
                "http://127.0.0.1:8080",
                "--sunday",
                "2026-06-28",
                "--out",
                str(out),
            ]

            original_argv = mod.sys.argv
            original_run_smoke = mod.run_smoke
            stdout = io.StringIO()
            original_stdout = mod.sys.stdout
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                mod.run_smoke = lambda args: {
                    "schemaVersion": 1,
                    "status": "no_transcript",
                    "sessionId": "rt_smoke",
                }

                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout
                mod.run_smoke = original_run_smoke

            self.assertEqual(exit_code, 3)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "no_transcript")
            self.assertIn('"status": "no_transcript"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

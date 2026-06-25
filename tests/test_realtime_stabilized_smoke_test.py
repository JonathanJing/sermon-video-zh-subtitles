import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_PATH = SCRIPT_DIR / "realtime_stabilized_smoke_test.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("realtime_stabilized_smoke_test", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def args_for(root: Path, **overrides):
    values = {
        "audio_file": root / "authorized.wav",
        "audio_url": None,
        "youtube_url": None,
        "api_key_secret": "projects/example/secrets/openai-api-key/versions/latest",
        "backend_url": "http://127.0.0.1:8080",
        "sunday": "2026-06-28",
        "admin_token": None,
        "internal_task_token": None,
        "max_audio_seconds": 8.0,
        "target_language": "zh",
        "realtime_model": "gpt-realtime-translate",
        "stable_model": "gpt-5.4-mini",
        "batch_size": 4,
        "max_windows": 12,
        "stable_min_age_seconds": 0,
        "event_log_dir": root / "events",
        "realtime_event_gcs_prefix": None,
        "read_events_from_gcs": False,
        "sse_timeout_seconds": 4.0,
        "out": root / "report.json",
        "worker_report_out": root / "worker-report.json",
        "stable_out_dir": root / "stable",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RealtimeStabilizedSmokeTest(unittest.TestCase):
    def test_worker_args_reuses_existing_backend_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = args_for(root)

            worker_args = mod.worker_args_from_args(args, "rt_test", "secret-event-token")

            self.assertEqual(worker_args.session_id, "rt_test")
            self.assertEqual(worker_args.event_token, "secret-event-token")
            self.assertFalse(worker_args.create_backend_session)
            self.assertTrue(worker_args.connect_openai)
            self.assertEqual(worker_args.openai_safety_identifier, "sermon-realtime-stabilized-smoke-test")

    def test_run_stabilized_smoke_posts_stable_correction_without_leaking_token_or_secret_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = args_for(root)
            args.audio_file.write_bytes(b"fake audio")
            event_rows = [
                {
                    "id": 1,
                    "sessionId": "rt_test",
                    "type": "session_started",
                    "model": "gpt-realtime-translate",
                    "targetLanguage": "zh",
                    "audioSourceKind": "authorized_audio_file",
                },
                {
                    "id": 2,
                    "sessionId": "rt_test",
                    "type": "caption_final",
                    "source": "openai_realtime_translation_ws",
                    "segmentId": "seg_1",
                    "text": "耶稣是中保。",
                    "zh": "耶稣是中保。",
                    "final": True,
                    "latencyMs": 480,
                },
                {
                    "id": 3,
                    "sessionId": "rt_test",
                    "type": "input_transcript_final",
                    "source": "openai_realtime_translation_ws",
                    "segmentId": "seg_1",
                    "text": "Jesus is our mediator.",
                    "en": "Jesus is our mediator.",
                    "final": True,
                    "createdAt": "2026-06-25T06:30:00+00:00",
                },
            ]
            calls = {}

            def fake_create_backend_local_session(session_args, audio_source_kind=None):
                calls["session_args"] = session_args
                calls["audio_source_kind"] = audio_source_kind
                return {"sessionId": "rt_test", "eventToken": "secret-event-token"}

            def fake_run_worker(worker_args):
                calls["worker_args"] = worker_args
                return {
                    "status": "ok",
                    "sessionId": worker_args.session_id,
                    "openaiRealtime": {
                        "audioChunksSent": 2,
                        "openaiEventsReceived": 4,
                        "captionEventsPosted": 1,
                        "inputTranscriptEventsPosted": 1,
                    },
                }

            def fake_read_sse_events(**kwargs):
                calls["sse_kwargs"] = kwargs
                return [
                    {"type": "caption_final", "source": "openai_realtime_translation_ws", "zh": "耶稣是中保。"},
                    {
                        "type": "input_transcript_final",
                        "source": "openai_realtime_translation_ws",
                        "en": "Jesus is our mediator.",
                    },
                ]

            def fake_read_events_text(uri):
                calls.setdefault("events_uri", uri)
                return "\n".join(json.dumps(row, ensure_ascii=False) for row in event_rows) + "\n"

            def fake_stabilize_batch(batch, api_key, model):
                self.assertEqual(api_key, "sk-test")
                self.assertEqual(model, "gpt-5.4-mini")
                self.assertEqual(batch[0]["id"], "seg_1")
                return [{"id": "seg_1", "zh": "耶稣是我们的中保。", "note": "术语稳定。"}]

            def fake_post_stable_corrections(**kwargs):
                calls["post_kwargs"] = kwargs
                self.assertEqual(kwargs["event_token"], "secret-event-token")
                event_rows.append(
                    {
                        "id": 4,
                        "sessionId": "rt_test",
                        "type": "caption_final",
                        "source": "gpt-5.4-mini-stable-correction",
                        "model": "gpt-5.4-mini",
                        "segmentId": "seg_1",
                        "text": "耶稣是我们的中保。",
                        "zh": "耶稣是我们的中保。",
                        "en": "Jesus is our mediator.",
                        "final": True,
                    }
                )
                return 1

            originals = (
                mod.realtime_media_worker.create_backend_local_session,
                mod.realtime_media_worker.run_worker,
                mod.realtime_openai_smoke_test.read_sse_events,
                mod.read_events_text,
                mod.access_secret,
                mod.stabilize_batch,
                mod.post_stable_corrections,
            )
            try:
                mod.realtime_media_worker.create_backend_local_session = fake_create_backend_local_session
                mod.realtime_media_worker.run_worker = fake_run_worker
                mod.realtime_openai_smoke_test.read_sse_events = fake_read_sse_events
                mod.read_events_text = fake_read_events_text
                mod.access_secret = lambda secret: "sk-test"
                mod.stabilize_batch = fake_stabilize_batch
                mod.post_stable_corrections = fake_post_stable_corrections

                report = mod.run_stabilized_smoke(args)
            finally:
                (
                    mod.realtime_media_worker.create_backend_local_session,
                    mod.realtime_media_worker.run_worker,
                    mod.realtime_openai_smoke_test.read_sse_events,
                    mod.read_events_text,
                    mod.access_secret,
                    mod.stabilize_batch,
                    mod.post_stable_corrections,
                ) = originals

            rendered = json.dumps(report, ensure_ascii=False)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["stableCorrection"]["postedStableCorrections"], 1)
            self.assertEqual(report["validation"]["status"], "ok")
            self.assertEqual(calls["worker_args"].session_id, "rt_test")
            self.assertEqual(calls["worker_args"].event_token, "secret-event-token")
            self.assertIn("/rt_test.jsonl", calls["events_uri"])
            self.assertNotIn("secret-event-token", rendered)
            self.assertNotIn("projects/example/secrets", rendered)
            self.assertFalse(report["eventTokenIncluded"])
            self.assertFalse(report["secretResourceNamesIncluded"])

    def test_main_writes_report_and_returns_nonzero_on_failed_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "authorized.wav"
            audio.write_bytes(b"fake audio")
            out = root / "report.json"
            argv = [
                "realtime_stabilized_smoke_test.py",
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
            original_stdout = mod.sys.stdout
            original_run = mod.run_stabilized_smoke
            stdout = io.StringIO()
            try:
                mod.sys.argv = argv
                mod.sys.stdout = stdout
                mod.run_stabilized_smoke = lambda args: {
                    "schemaVersion": 1,
                    "status": "validation_failed",
                    "sessionId": "rt_test",
                }

                exit_code = mod.main()
            finally:
                mod.sys.argv = original_argv
                mod.sys.stdout = original_stdout
                mod.run_stabilized_smoke = original_run

            self.assertEqual(exit_code, 3)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "validation_failed")
            self.assertIn('"status": "validation_failed"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_PATH = SCRIPT_DIR / "run_realtime_live_session.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("run_realtime_live_session", SCRIPT_PATH)
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
        "target_language": "zh",
        "realtime_model": "gpt-realtime-translate",
        "stable_model": "gpt-5.5-mini",
        "max_audio_seconds": 8.0,
        "event_log_dir": root / "events",
        "realtime_event_gcs_prefix": None,
        "read_events_from_gcs": False,
        "stable_min_age_seconds": 0,
        "stabilizer_interval_seconds": 0.01,
        "stabilizer_batch_size": 4,
        "stabilizer_max_windows": 40,
        "max_stabilizer_iterations": 0,
        "final_stabilizer_iterations": 2,
        "require_stable_correction": True,
        "out": root / "report.json",
        "worker_report_out": root / "worker-report.json",
        "stable_out_dir": root / "stable",
        "state_file": root / "stable" / "state.json",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RunRealtimeLiveSessionTest(unittest.TestCase):
    def test_parse_args_rejects_wrong_realtime_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "authorized.wav"
            audio.write_bytes(b"fake audio")
            original_argv = sys.argv
            try:
                sys.argv = [
                    "run_realtime_live_session.py",
                    "--audio-file",
                    str(audio),
                    "--api-key-secret",
                    "projects/example/secrets/openai-api-key/versions/latest",
                    "--backend-url",
                    "http://127.0.0.1:8080",
                    "--sunday",
                    "2026-06-28",
                    "--realtime-model",
                    "gpt-realtime-2",
                ]
                with self.assertRaises(SystemExit):
                    mod.parse_args()
            finally:
                sys.argv = original_argv

    def test_parse_args_rejects_wrong_stable_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "authorized.wav"
            audio.write_bytes(b"fake audio")
            original_argv = sys.argv
            try:
                sys.argv = [
                    "run_realtime_live_session.py",
                    "--audio-file",
                    str(audio),
                    "--api-key-secret",
                    "projects/example/secrets/openai-api-key/versions/latest",
                    "--backend-url",
                    "http://127.0.0.1:8080",
                    "--sunday",
                    "2026-06-28",
                    "--stable-model",
                    "gpt-realtime-translate",
                ]
                with self.assertRaises(SystemExit):
                    mod.parse_args()
            finally:
                sys.argv = original_argv

    def test_worker_args_keep_event_token_in_memory_for_same_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = args_for(root)

            worker_args = mod.worker_args_from_args(args, "rt_live", "secret-event-token")

            self.assertEqual(worker_args.session_id, "rt_live")
            self.assertEqual(worker_args.event_token, "secret-event-token")
            self.assertFalse(worker_args.create_backend_session)
            self.assertTrue(worker_args.connect_openai)
            self.assertEqual(worker_args.openai_safety_identifier, "sermon-realtime-live-session")

    def test_stabilizer_iteration_waits_when_event_archive_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = args_for(root)

            report = mod.run_stabilizer_iteration(
                args,
                api_key="sk-test",
                session_id="rt_live",
                event_token="secret-event-token",
                events_uri=str(root / "missing.jsonl"),
            )

            self.assertEqual(report["status"], "no_events_yet")
            self.assertNotIn("secret-event-token", json.dumps(report))

    def test_run_live_session_posts_stable_correction_without_leaking_token_or_secret_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = args_for(root)
            args.audio_file.write_bytes(b"fake audio")
            event_rows = [
                {
                    "id": 1,
                    "type": "session_started",
                    "model": "gpt-realtime-translate",
                    "targetLanguage": "zh",
                    "audioSourceKind": "authorized_audio_file",
                },
                {
                    "id": 2,
                    "type": "caption_final",
                    "source": "openai_realtime_translation_ws",
                    "segmentId": "seg_1",
                    "text": "耶稣是中保。",
                    "zh": "耶稣是中保。",
                    "final": True,
                },
                {
                    "id": 3,
                    "type": "input_transcript_final",
                    "source": "openai_realtime_translation_ws",
                    "segmentId": "seg_1",
                    "text": "Jesus is our mediator.",
                    "en": "Jesus is our mediator.",
                    "final": True,
                    "createdAt": "2026-06-25T06:30:00+00:00",
                },
            ]
            calls = {"posts": 0}

            def fake_create_backend_local_session(session_args, audio_source_kind=None):
                calls["session_args"] = session_args
                calls["audio_source_kind"] = audio_source_kind
                return {"sessionId": "rt_live", "eventToken": "secret-event-token"}

            def fake_run_worker(worker_args):
                calls["worker_args"] = worker_args
                return {
                    "schemaVersion": 1,
                    "status": "ok",
                    "sessionId": worker_args.session_id,
                    "eventsPosted": 4,
                    "openaiRealtime": {
                        "audioChunksSent": 2,
                        "captionEventsPosted": 1,
                        "inputTranscriptEventsPosted": 1,
                        "apiKeyMaterialIncluded": False,
                        "secretResourceNamesIncluded": False,
                    },
                }

            def fake_read_events_text(uri):
                calls["events_uri"] = uri
                return "\n".join(json.dumps(row, ensure_ascii=False) for row in event_rows) + "\n"

            def fake_stabilize_batch(batch, api_key, model):
                self.assertEqual(api_key, "sk-test")
                self.assertEqual(model, "gpt-5.5-mini")
                self.assertEqual(batch[0]["id"], "seg_1")
                return [{"id": "seg_1", "zh": "耶稣是我们的中保。", "note": "术语稳定。"}]

            def fake_post_stable_corrections(**kwargs):
                calls["posts"] += 1
                self.assertEqual(kwargs["event_token"], "secret-event-token")
                event_rows.append(
                    {
                        "id": 4,
                        "type": "caption_final",
                        "source": "gpt-5.5-mini-stable-correction",
                        "model": "gpt-5.5-mini",
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
                mod.read_events_text,
                mod.access_secret,
                mod.stabilize_batch,
                mod.post_stable_corrections,
                mod.time.sleep,
            )
            try:
                mod.realtime_media_worker.create_backend_local_session = fake_create_backend_local_session
                mod.realtime_media_worker.run_worker = fake_run_worker
                mod.read_events_text = fake_read_events_text
                mod.access_secret = lambda secret: "sk-test"
                mod.stabilize_batch = fake_stabilize_batch
                mod.post_stable_corrections = fake_post_stable_corrections
                mod.time.sleep = lambda _seconds: None

                report = mod.run_live_session(args)
            finally:
                (
                    mod.realtime_media_worker.create_backend_local_session,
                    mod.realtime_media_worker.run_worker,
                    mod.read_events_text,
                    mod.access_secret,
                    mod.stabilize_batch,
                    mod.post_stable_corrections,
                    mod.time.sleep,
                ) = originals

            rendered = json.dumps(report, ensure_ascii=False)
            state = json.loads(args.state_file.read_text(encoding="utf-8"))

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["stableCorrection"]["postedStableCorrections"], 1)
            self.assertEqual(calls["posts"], 1)
            self.assertEqual(state["postedSegmentIds"], ["seg_1"])
            self.assertEqual(calls["worker_args"].session_id, "rt_live")
            self.assertEqual(calls["worker_args"].event_token, "secret-event-token")
            self.assertEqual(calls["audio_source_kind"], "authorized_audio_file")
            self.assertIn("/rt_live.jsonl", calls["events_uri"])
            self.assertNotIn("secret-event-token", rendered)
            self.assertNotIn("projects/example/secrets", rendered)
            self.assertFalse(report["eventTokenIncluded"])
            self.assertFalse(report["secretResourceNamesIncluded"])

    def test_stable_correction_failure_is_non_blocking_unless_required(self):
        for require_stable_correction, expected_status in [(False, "ok"), (True, "stabilizer_failed")]:
            with self.subTest(require_stable_correction=require_stable_correction):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    args = args_for(
                        root,
                        require_stable_correction=require_stable_correction,
                        final_stabilizer_iterations=1,
                    )
                    args.audio_file.write_bytes(b"fake audio")

                    def fake_create_backend_local_session(session_args, audio_source_kind=None):
                        self.assertEqual(audio_source_kind, "authorized_audio_file")
                        return {"sessionId": "rt_live", "eventToken": "secret-event-token"}

                    def fake_run_worker(worker_args):
                        return {
                            "schemaVersion": 1,
                            "status": "ok",
                            "sessionId": worker_args.session_id,
                            "eventsPosted": 2,
                            "openaiRealtime": {
                                "captionEventsPosted": 1,
                                "inputTranscriptEventsPosted": 1,
                                "apiKeyMaterialIncluded": False,
                                "secretResourceNamesIncluded": False,
                            },
                        }

                    def fake_safe_iteration(*_args, **_kwargs):
                        return {
                            "schemaVersion": 1,
                            "status": "failed",
                            "sessionId": "rt_live",
                            "error": mod.sanitize_live_error(
                                "bad sk-secret123 at projects/p/secrets/openai-api-key/versions/latest"
                            ),
                            "apiKeyMaterialIncluded": False,
                            "secretResourceNamesIncluded": False,
                        }

                    originals = (
                        mod.realtime_media_worker.create_backend_local_session,
                        mod.realtime_media_worker.run_worker,
                        mod.access_secret,
                        mod.safe_run_stabilizer_iteration,
                        mod.time.sleep,
                    )
                    try:
                        mod.realtime_media_worker.create_backend_local_session = fake_create_backend_local_session
                        mod.realtime_media_worker.run_worker = fake_run_worker
                        mod.access_secret = lambda secret: "sk-test"
                        mod.safe_run_stabilizer_iteration = fake_safe_iteration
                        mod.time.sleep = lambda _seconds: None

                        report = mod.run_live_session(args)
                    finally:
                        (
                            mod.realtime_media_worker.create_backend_local_session,
                            mod.realtime_media_worker.run_worker,
                            mod.access_secret,
                            mod.safe_run_stabilizer_iteration,
                            mod.time.sleep,
                        ) = originals

                    rendered = json.dumps(report)
                    self.assertEqual(report["status"], expected_status)
                    if require_stable_correction:
                        self.assertEqual(report["stableCorrection"]["warnings"], [])
                    else:
                        self.assertIn("stable_correction_failed_non_blocking", report["stableCorrection"]["warnings"])
                    self.assertNotIn("sk-secret123", rendered)
                    self.assertNotIn("openai-api-key", rendered)


if __name__ == "__main__":
    unittest.main()

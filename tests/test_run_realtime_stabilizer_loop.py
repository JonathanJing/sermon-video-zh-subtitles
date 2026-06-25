import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT_PATH = SCRIPT_DIR / "run_realtime_stabilizer_loop.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("run_realtime_stabilizer_loop", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def args_for(root: Path, **overrides):
    values = {
        "input_jsonl": root / "events.jsonl",
        "api_key_secret": "projects/p/secrets/openai-api-key/versions/latest",
        "backend_url": "http://127.0.0.1:8080",
        "session_id": "rt_test",
        "event_token": "secret-event-token",
        "admin_token": None,
        "internal_task_token": None,
        "model": "gpt-5.5-mini",
        "batch_size": 4,
        "max_windows": 20,
        "min_age_seconds": 4.0,
        "interval_seconds": 6.0,
        "once": True,
        "max_iterations": 0,
        "out_dir": root / "out",
        "state_file": root / "state.json",
        "model_preflight_out": root / "out" / "rt_test.model-access-preflight.json",
        "skip_model_preflight": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RunRealtimeStabilizerLoopTest(unittest.TestCase):
    def test_model_preflight_fails_before_loop_without_secret_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(Path(tmp))
            original_smoke = mod.responses_smoke
            try:
                def fake_smoke(model, api_key):
                    self.assertEqual(model, "gpt-5.5-mini")
                    self.assertEqual(api_key, "sk-test")
                    return {
                        "status": "failed",
                        "model": model,
                        "endpoint": "responses",
                        "httpStatus": 400,
                        "error": "bad sk-secret123 from projects/p/secrets/openai-api-key/versions/latest",
                    }

                mod.responses_smoke = fake_smoke
                report = mod.run_model_preflight(args, api_key="sk-test")
            finally:
                mod.responses_smoke = original_smoke

        rendered = json.dumps(report)
        self.assertEqual(report["status"], "failed")
        self.assertIn("responses_model:gpt-5.5-mini", report["failedChecks"])
        self.assertNotIn("sk-test", rendered)
        self.assertNotIn("sk-secret123", rendered)
        self.assertNotIn("openai-api-key", rendered)

    def test_model_preflight_can_be_skipped_for_local_debug(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = args_for(Path(tmp), skip_model_preflight=True)

            report = mod.run_model_preflight(args, api_key="sk-test")

        self.assertEqual(report["status"], "ok")
        observed = report["checks"][0]["observed"]
        self.assertEqual(observed["status"], "skipped")
        self.assertEqual(observed["endpoint"], "responses")

    def test_parse_args_rejects_realtime_model_for_stable_correction(self):
        original_argv = sys.argv
        try:
            sys.argv = [
                "run_realtime_stabilizer_loop.py",
                "--input-jsonl",
                "events.jsonl",
                "--api-key-secret",
                "projects/p/secrets/openai-api-key/versions/latest",
                "--backend-url",
                "http://127.0.0.1:8080",
                "--session-id",
                "rt_test",
                "--event-token",
                "event-token",
                "--model",
                "gpt-realtime-translate",
            ]
            with self.assertRaises(SystemExit):
                mod.parse_args()
        finally:
            sys.argv = original_argv

    def test_filter_ready_candidates_skips_posted_and_too_new_windows(self):
        now = datetime(2026, 6, 25, 6, 30, 10, tzinfo=timezone.utc)
        candidates = [
            {"id": "old", "createdAt": "2026-06-25T06:30:00+00:00"},
            {"id": "new", "createdAt": "2026-06-25T06:30:08+00:00"},
            {"id": "posted", "createdAt": "2026-06-25T06:29:00+00:00"},
            {"id": "no_time", "en": "Ready without timestamp."},
        ]

        ready = mod.filter_ready_candidates(
            candidates,
            posted_ids={"posted"},
            min_age_seconds=4,
            now=now,
        )

        self.assertEqual([item["id"] for item in ready], ["old", "no_time"])

    def test_resolve_input_jsonl_preserves_gcs_uri(self):
        uri = "gs://sermon-zh-artifacts-ai-for-god/realtime-events/2026-06-28/rt_browser.jsonl"

        self.assertEqual(mod.resolve_input_jsonl(uri), uri)
        self.assertEqual(
            mod.display_input_path(uri).name,
            "gcs-gs___sermon-zh-artifacts-ai-for-god_realtime-events_2026-06-28_rt_browser_jsonl.jsonl",
        )

    def test_run_iteration_posts_only_new_ready_corrections_and_writes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = args_for(root, min_age_seconds=0)
            args.input_jsonl.write_text(
                "\n".join(
                    [
                        json.dumps({"id": 1, "type": "caption_final", "segmentId": "seg_1", "text": "耶稣是中保。"}),
                        json.dumps(
                            {
                                "id": 2,
                                "type": "input_transcript_final",
                                "segmentId": "seg_1",
                                "text": "Jesus is our mediator.",
                                "createdAt": "2026-06-25T06:30:00+00:00",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            calls = []

            def fake_stabilize(batch, api_key, model):
                self.assertEqual(api_key, "sk-test")
                self.assertEqual(model, "gpt-5.5-mini")
                self.assertEqual(batch[0]["id"], "seg_1")
                return [{"id": "seg_1", "zh": "耶稣是我们的中保。", "note": "术语修正。"}]

            def fake_post(**kwargs):
                calls.append(kwargs)
                return 1

            report = mod.run_iteration(
                args,
                api_key="sk-test",
                now=datetime(2026, 6, 25, 6, 30, 10, tzinfo=timezone.utc),
                stabilize_fn=fake_stabilize,
                post_fn=fake_post,
            )

            state = json.loads(args.state_file.read_text(encoding="utf-8"))
            output = json.loads((args.out_dir / "rt_test.stable-corrections.latest.json").read_text(encoding="utf-8"))
            rendered_report = json.dumps(report)

            self.assertEqual(report["postedStableCorrections"], 1)
            self.assertEqual(report["correctedWindows"], 1)
            self.assertEqual(state["postedSegmentIds"], ["seg_1"])
            self.assertEqual(output["segments"][0]["stableZh"], "耶稣是我们的中保。")
            self.assertEqual(calls[0]["event_token"], "secret-event-token")
            self.assertNotIn("projects/p/secrets", rendered_report)
            self.assertNotIn("secret-event-token", rendered_report)

            second = mod.run_iteration(
                args,
                api_key="sk-test",
                now=datetime(2026, 6, 25, 6, 30, 20, tzinfo=timezone.utc),
                stabilize_fn=fake_stabilize,
                post_fn=fake_post,
            )

            self.assertEqual(second["readyWindows"], 0)
            self.assertEqual(second["postedStableCorrections"], 0)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_source_monitor.py"
SPEC = importlib.util.spec_from_file_location("live_source_monitor", SCRIPT_PATH)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def base_args(**overrides):
    values = {
        "sunday": "2026-06-28",
        "service": "auto",
        "expected_title": "The Cure for Our Rebellion - Eric Geiger | Mariners Church",
        "manual_url": [],
        "mariners_online_url": mod.DEFAULT_MARINERS_ONLINE_URL,
        "youtube_streams_url": mod.DEFAULT_YOUTUBE_STREAMS_URL,
        "fixture_json": None,
        "out": Path("artifacts/live-source-monitor/report.json"),
        "timezone": "America/Los_Angeles",
        "now": "2026-06-28T08:24:00-07:00",
        "min_confidence": 0.70,
        "operator_alert_time": "09:58",
        "backend_url": "http://127.0.0.1:8080",
        "post_generate": False,
        "admin_token": None,
        "internal_task_token": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def write_fixture(root, sources):
    path = Path(root) / "sources.json"
    path.write_text(json.dumps({"sources": sources}, ensure_ascii=False), encoding="utf-8")
    return path


class LiveSourceMonitorTest(unittest.TestCase):
    def test_selects_830_source_when_same_sermon_is_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = write_fixture(
                tmp,
                [
                    {
                        "kind": "youtube-streams",
                        "service": "830",
                        "url": "https://www.youtube.com/watch?v=early",
                        "state": "live",
                        "title": "The Cure for Our Rebellion - Eric Geiger | Mariners Church",
                    },
                    {
                        "kind": "youtube-streams",
                        "service": "1000",
                        "url": "https://www.youtube.com/watch?v=ten",
                        "state": "upcoming",
                        "sameSermonConfidence": 0.95,
                    },
                ],
            )

            report = mod.run_monitor(base_args(fixture_json=fixture))

        self.assertEqual(report["status"], "source_detected")
        self.assertEqual(report["selectedSource"]["service"], "830")
        self.assertEqual(report["selectedSource"]["kind"], "youtube-streams")
        self.assertFalse(report["operatorAlert"])
        self.assertIsNone(report["fallbackReason"])
        self.assertEqual(report["generationRequest"]["liveUrl"], "https://www.youtube.com/watch?v=early")
        self.assertEqual(report["generationRequest"]["triggerSource"], "live-source-monitor")
        self.assertFalse(report["apiKeyMaterialIncluded"])
        self.assertFalse(report["secretResourceNamesIncluded"])

    def test_falls_forward_to_1000_when_830_is_not_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = write_fixture(
                tmp,
                [
                    {
                        "kind": "youtube-streams",
                        "service": "830",
                        "url": "https://www.youtube.com/watch?v=early",
                        "state": "live",
                        "sameSermonConfidence": 0.2,
                    },
                    {
                        "kind": "youtube-streams",
                        "service": "1000",
                        "url": "https://www.youtube.com/watch?v=ten",
                        "state": "upcoming",
                        "sameSermonConfidence": 0.91,
                    },
                ],
            )

            report = mod.run_monitor(base_args(fixture_json=fixture, now="2026-06-28T09:50:00-07:00"))

        self.assertEqual(report["status"], "source_detected")
        self.assertEqual(report["selectedSource"]["service"], "1000")
        self.assertIn("8:30 source missing", report["fallbackReason"])
        self.assertFalse(report["operatorAlert"])
        self.assertEqual(report["generationRequest"]["service"], "1000")

    def test_alerts_operator_after_deadline_when_no_source_is_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = write_fixture(
                tmp,
                [
                    {
                        "kind": "mariners-online",
                        "service": "830",
                        "url": "https://example.test/830",
                        "state": "unavailable",
                    },
                    {
                        "kind": "youtube-streams",
                        "service": "1000",
                        "url": "https://example.test/1000",
                        "state": "available",
                        "sameSermonConfidence": 0.1,
                    },
                ],
            )

            report = mod.run_monitor(base_args(fixture_json=fixture, now="2026-06-28T09:59:00-07:00"))

        self.assertEqual(report["status"], "fallback")
        self.assertEqual(report["selectedSource"]["kind"], "operator-audio")
        self.assertEqual(report["selectedSource"]["state"], "fallback")
        self.assertTrue(report["operatorAlert"])
        self.assertIsNone(report["generationRequest"])
        self.assertIn("iPad mic", report["fallbackReason"])

    def test_manual_url_is_used_when_automatic_sources_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = write_fixture(
                tmp,
                [
                    {
                        "kind": "youtube-streams",
                        "service": "830",
                        "url": "https://example.test/early",
                        "state": "unavailable",
                    }
                ],
            )

            report = mod.run_monitor(
                base_args(
                    fixture_json=fixture,
                    manual_url=["https://authorized.example.test/audio"],
                    now="2026-06-28T09:59:00-07:00",
                )
            )

        self.assertEqual(report["status"], "source_detected")
        self.assertEqual(report["selectedSource"]["kind"], "manual-url")
        self.assertEqual(report["selectedSource"]["service"], "manual")
        self.assertFalse(report["operatorAlert"])
        self.assertEqual(report["generationRequest"]["liveUrl"], "https://authorized.example.test/audio")
        self.assertIn("operator-provided", report["selectedSource"]["evidence"])

    def test_fetch_candidate_extracts_title_and_scores_expected_sermon(self):
        html = """
        <html><head><title>The Cure for Our Rebellion - Eric Geiger | Mariners Church</title></head>
        <body>Upcoming live service</body></html>
        """

        candidate = mod.fetch_candidate(
            kind="youtube-streams",
            service="830",
            url="https://www.youtube.com/@marinerschurch/streams",
            expected_title="The Cure for Our Rebellion - Eric Geiger | Mariners Church",
            fetcher=lambda url: html,
        )

        self.assertEqual(candidate.state, "upcoming")
        self.assertEqual(candidate.title, "The Cure for Our Rebellion - Eric Geiger | Mariners Church")
        self.assertGreaterEqual(candidate.same_sermon_confidence, 0.99)

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = write_fixture(
                root,
                [
                    {
                        "kind": "youtube-streams",
                        "service": "830",
                        "url": "https://www.youtube.com/watch?v=early",
                        "state": "live",
                        "sameSermonConfidence": 0.9,
                    }
                ],
            )
            out = root / "report.json"
            original_parse_args = mod.parse_args
            original_log_event = mod.log_event
            try:
                mod.parse_args = lambda: base_args(fixture_json=fixture, out=out)
                mod.log_event = lambda *args, **kwargs: None
                with contextlib.redirect_stdout(io.StringIO()):
                    exit_code = mod.main()
            finally:
                mod.parse_args = original_parse_args
                mod.log_event = original_log_event

            saved = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(saved["status"], "source_detected")
        self.assertEqual(saved["selectedSource"]["urlHash"], mod.stable_hash("https://www.youtube.com/watch?v=early"))

    def test_post_generation_request_sends_selected_source_without_returning_tokens(self):
        captured = {}

        class FakeResponse:
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"status":"planned","sessionId":"worker-test"}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        report = {
            "sunday": "2026-06-28",
            "generationRequest": {
                "triggerSource": "live-source-monitor",
                "sunday": "2026-06-28",
                "liveUrl": "https://www.youtube.com/watch?v=early",
                "sourceKind": "youtube-streams",
                "service": "830",
                "sameSermonConfidence": 0.93,
            },
        }
        args = base_args(
            backend_url="https://caption.example.test/",
            admin_token="test-admin-token",
            internal_task_token="test-task-token",
        )
        original_urlopen = mod.urlopen
        try:
            mod.urlopen = fake_urlopen
            result = mod.post_generation_request(report, args)
        finally:
            mod.urlopen = original_urlopen

        self.assertEqual(result["status"], "posted")
        self.assertEqual(result["statusCode"], 202)
        self.assertEqual(
            captured["url"],
            "https://caption.example.test/api/admin/sundays/2026-06-28/generate",
        )
        self.assertEqual(captured["body"]["liveUrl"], "https://www.youtube.com/watch?v=early")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-admin-token")
        self.assertEqual(captured["headers"]["X-internal-task-token"], "test-task-token")
        rendered = json.dumps(result)
        self.assertFalse(result["authMaterialIncluded"])
        self.assertNotIn("test-admin-token", rendered)
        self.assertNotIn("test-task-token", rendered)

    def test_post_generation_request_skips_without_selected_source(self):
        result = mod.post_generation_request({"sunday": "2026-06-28", "generationRequest": None}, base_args())

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_generation_request")


if __name__ == "__main__":
    unittest.main()

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
        "state_file": Path("artifacts/live-source-monitor/state.json"),
        "notify_webhook_url": None,
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

    def test_saturday_auto_falls_forward_to_530_when_400_is_not_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = write_fixture(
                tmp,
                [
                    {
                        "kind": "youtube-streams",
                        "service": "sat400",
                        "url": "https://www.youtube.com/watch?v=four",
                        "state": "available",
                        "sameSermonConfidence": 0.1,
                    },
                    {
                        "kind": "youtube-streams",
                        "service": "sat530",
                        "url": "https://www.youtube.com/watch?v=fivethirty",
                        "state": "live",
                        "sameSermonConfidence": 0.91,
                    },
                ],
            )

            report = mod.run_monitor(
                base_args(
                    service="sat-auto",
                    fixture_json=fixture,
                    now="2026-06-27T17:21:00-07:00",
                )
            )

        self.assertEqual(report["status"], "source_detected")
        self.assertEqual(report["selectedSource"]["service"], "sat530")
        self.assertIn("5:30 Saturday", report["fallbackReason"])
        self.assertEqual(report["generationRequest"]["service"], "sat530")

    def test_saturday_default_candidates_do_not_use_generic_mariners_page(self):
        original_fetcher = mod.default_fetcher
        original_metadata = mod.youtube_video_metadata
        try:
            mod.default_fetcher = lambda url: "<html><body>Upcoming service</body></html>"
            mod.youtube_video_metadata = lambda url: None
            candidates = mod.fetch_default_candidates(
                base_args(service="sat-auto", sunday="2026-06-28"),
                checked_at="2026-06-27T17:21:00-07:00",
            )
        finally:
            mod.default_fetcher = original_fetcher
            mod.youtube_video_metadata = original_metadata

        self.assertEqual([candidate.kind for candidate in candidates], ["youtube-streams", "youtube-streams"])

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

    def test_fetch_youtube_streams_candidate_prefers_actual_watch_url(self):
        channel_html = """
        <html><head><title>Mariners Church - Live</title></head>
        <body>Live now <a href="/watch?v=MEZHufeQBjc">watch</a></body></html>
        """
        video_html = """
        <html><head><title>Mariners Online Worship Service</title></head>
        <body>{"live_status":"post_live","media_type":"livestream"}</body></html>
        """

        original_metadata = mod.youtube_video_metadata
        try:
            mod.youtube_video_metadata = lambda url: {
                "title": "Mariners Online Worship Service",
                "live_status": "post_live",
                "media_type": "livestream",
                "release_timestamp": 1782606065,
            }
            candidate = mod.fetch_candidate(
                kind="youtube-streams",
                service="sat530",
                url="https://www.youtube.com/@marinerschurch/streams",
                expected_title=None,
                fetcher=lambda url: video_html if "watch?v=MEZHufeQBjc" in url else channel_html,
            )
        finally:
            mod.youtube_video_metadata = original_metadata

        self.assertEqual(candidate.url, "https://www.youtube.com/watch?v=MEZHufeQBjc")
        self.assertEqual(candidate.state, "was_live")
        self.assertEqual(candidate.evidence, "yt-dlp-watch-metadata")

    def test_fetch_youtube_streams_skips_stale_first_watch_url(self):
        channel_html = """
        <html><body>
          <a href="/watch?v=OLDOLDOLD01">old</a>
          <a href="/watch?v=MEZHufeQBjc">live</a>
        </body></html>
        """

        def fake_fetcher(url):
            if "OLDOLDOLD01" in url:
                return "<html><head><title>Old Sermon</title></head><body>regular upload</body></html>"
            if "MEZHufeQBjc" in url:
                return '<html><head><title>Mariners Live</title></head><body>{"live_status":"post_live"}</body></html>'
            return channel_html

        def fake_metadata(url):
            if "OLDOLDOLD01" in url:
                return {"title": "Old Sermon", "live_status": "not_live", "media_type": "video"}
            return {
                "title": "Mariners Live",
                "live_status": "post_live",
                "media_type": "livestream",
                "release_timestamp": 1782606065,
            }

        original_metadata = mod.youtube_video_metadata
        try:
            mod.youtube_video_metadata = fake_metadata
            candidate = mod.fetch_candidate(
                kind="youtube-streams",
                service="sat530",
                url="https://www.youtube.com/@marinerschurch/streams",
                expected_title=None,
                fetcher=fake_fetcher,
            )
        finally:
            mod.youtube_video_metadata = original_metadata

        self.assertEqual(candidate.url, "https://www.youtube.com/watch?v=MEZHufeQBjc")
        self.assertEqual(candidate.state, "was_live")

    def test_fetch_youtube_streams_rejects_unvalidated_watch_urls(self):
        channel_html = '<html><body><a href="/watch?v=OLDOLDOLD01">old</a></body></html>'

        original_metadata = mod.youtube_video_metadata
        try:
            mod.youtube_video_metadata = lambda url: {
                "title": "Old Sermon",
                "live_status": "not_live",
                "media_type": "video",
            }
            candidate = mod.fetch_candidate(
                kind="youtube-streams",
                service="sat530",
                url="https://www.youtube.com/@marinerschurch/streams",
                expected_title=None,
                fetcher=lambda url: "<html><body>regular upload</body></html>" if "watch?v=" in url else channel_html,
            )
        finally:
            mod.youtube_video_metadata = original_metadata

        self.assertEqual(candidate.url, "https://www.youtube.com/@marinerschurch/streams")
        self.assertEqual(candidate.state, "unavailable")
        self.assertEqual(candidate.evidence, "watch-page-validation-failed")

    def test_fetch_youtube_streams_rejects_wrong_service_date(self):
        channel_html = '<html><body><a href="/watch?v=FsUijL9uB1I">old</a></body></html>'
        old_sunday_timestamp = 1782055264
        original_metadata = mod.youtube_video_metadata
        try:
            mod.youtube_video_metadata = lambda url: {
                "title": "Old Mariners Live",
                "live_status": "post_live",
                "media_type": "livestream",
                "release_timestamp": old_sunday_timestamp,
            }
            candidate = mod.fetch_candidate(
                kind="youtube-streams",
                service="sat530",
                url="https://www.youtube.com/@marinerschurch/streams",
                expected_title=None,
                fetcher=lambda url: channel_html,
                target_date=__import__("datetime").date(2026, 6, 27),
                timezone="America/Los_Angeles",
            )
        finally:
            mod.youtube_video_metadata = original_metadata

        self.assertEqual(candidate.state, "unavailable")
        self.assertEqual(candidate.evidence, "watch-page-validation-failed")

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
                mod.parse_args = lambda: base_args(fixture_json=fixture, out=out, state_file=root / "state.json")
                mod.log_event = lambda *args, **kwargs: None
                with contextlib.redirect_stdout(io.StringIO()):
                    exit_code = mod.main()
            finally:
                mod.parse_args = original_parse_args
                mod.log_event = original_log_event

            saved = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(saved["status"], "source_detected")
        self.assertIn("notification", saved)
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

    def test_notification_dedupes_selected_source(self):
        report = {
            "status": "source_detected",
            "sunday": "2026-06-28",
            "checkedAt": "2026-06-27T17:21:00-07:00",
            "selectedSource": {
                "kind": "youtube-streams",
                "service": "sat530",
                "state": "live",
                "url": "https://www.youtube.com/watch?v=MEZHufeQBjc",
                "urlHash": "abc123",
            },
            "fallbackReason": None,
        }

        first = mod.build_notification(report, {})
        delivered = {**first, "delivery": {"status": "posted", "statusCode": 204}}
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            mod.write_state(state_path, report, {}, delivered)
            state = mod.read_state(state_path)
        second = mod.build_notification(report, state)

        self.assertTrue(first["shouldNotify"])
        self.assertFalse(second["shouldNotify"])
        self.assertEqual(second["reason"], "already_notified")
        self.assertEqual(state["lastSelectedSource"]["url"], "https://www.youtube.com/watch?v=MEZHufeQBjc")

    def test_state_persists_generation_request_for_post_live_worker(self):
        report = {
            "status": "source_detected",
            "sunday": "2026-06-28",
            "checkedAt": "2026-06-27T17:21:00-07:00",
            "operatorAlert": False,
            "selectedSource": {
                "kind": "youtube-streams",
                "service": "sat530",
                "state": "was_live",
                "url": "https://www.youtube.com/watch?v=MEZHufeQBjc",
                "urlHash": "abc123",
            },
            "generationRequest": {
                "triggerSource": "live-source-monitor",
                "sunday": "2026-06-28",
                "liveUrl": "https://www.youtube.com/watch?v=MEZHufeQBjc",
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            mod.write_state(state_path, report, {}, {"shouldNotify": False})
            state = mod.read_state(state_path)

        self.assertEqual(state["lastStatus"], "source_detected")
        self.assertEqual(state["lastSelectedSource"]["urlHash"], "abc123")
        self.assertEqual(state["lastGenerationRequest"]["liveUrl"], "https://www.youtube.com/watch?v=MEZHufeQBjc")
        self.assertFalse(state["apiKeyMaterialIncluded"])
        self.assertFalse(state["secretResourceNamesIncluded"])

    def test_failed_notification_delivery_does_not_dedupe(self):
        report = {
            "status": "source_detected",
            "sunday": "2026-06-28",
            "checkedAt": "2026-06-27T17:21:00-07:00",
            "selectedSource": {
                "kind": "youtube-streams",
                "service": "sat530",
                "state": "live",
                "url": "https://www.youtube.com/watch?v=MEZHufeQBjc",
                "urlHash": "abc123",
            },
            "fallbackReason": None,
        }
        notification = mod.build_notification(report, {})
        failed = {**notification, "delivery": {"status": "failed", "statusCode": 500}}

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            mod.write_state(state_path, report, {}, failed)
            state = mod.read_state(state_path)

        retry = mod.build_notification(report, state)
        self.assertTrue(retry["shouldNotify"])
        self.assertEqual(retry["reason"], "new_state")

    def test_state_can_round_trip_through_gcs_uri(self):
        stored = {}

        def fake_write(uri, text):
            stored["uri"] = uri
            stored["text"] = text

        def fake_read(uri):
            self.assertEqual(uri, "gs://bucket/source-monitor/state.json")
            return stored["text"]

        report = {
            "status": "source_detected",
            "sunday": "2026-06-28",
            "checkedAt": "2026-06-27T17:21:00-07:00",
            "operatorAlert": False,
            "selectedSource": {"urlHash": "abc123"},
        }
        notification = {"dedupeKey": "source_detected:2026-06-28:abc123", "delivery": {"status": "posted"}}
        original_write = mod.write_gcs_text
        original_read = mod.read_gcs_text
        try:
            mod.write_gcs_text = fake_write
            mod.read_gcs_text = fake_read
            mod.write_state("gs://bucket/source-monitor/state.json", report, {}, notification)
            state = mod.read_state("gs://bucket/source-monitor/state.json")
        finally:
            mod.write_gcs_text = original_write
            mod.read_gcs_text = original_read

        self.assertEqual(stored["uri"], "gs://bucket/source-monitor/state.json")
        self.assertEqual(state["notifications"]["source_detected:2026-06-28:abc123"], report["checkedAt"])

    def test_fallback_notification_waits_until_operator_alert(self):
        report = {
            "status": "fallback",
            "sunday": "2026-06-28",
            "checkedAt": "2026-06-27T17:49:00-07:00",
            "operatorAlert": False,
            "selectedSource": {"kind": "operator-audio", "service": "manual", "state": "fallback"},
        }

        notification = mod.build_notification(report, {})

        self.assertFalse(notification["shouldNotify"])
        self.assertEqual(notification["reason"], "waiting_for_alert_deadline")


if __name__ == "__main__":
    unittest.main()

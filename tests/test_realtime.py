import unittest
import tempfile
import json
from pathlib import Path

import backend.realtime as realtime
from backend.realtime import (
    OPENAI_TRANSLATION_CALLS_URL,
    OPENAI_TRANSLATION_CLIENT_SECRET_URL,
    RealtimeEventArchive,
    RealtimeSessionStore,
    create_openai_translation_session,
    sanitize_event,
)


class RealtimeSessionStoreTest(unittest.TestCase):
    def test_create_session_sets_current_and_validates_event_token(self):
        store = RealtimeSessionStore()
        session = store.create(sunday="2026-06-28")

        self.assertEqual(store.current_session_id(), session.session_id)
        self.assertTrue(store.validate_event_token(session.session_id, session.event_token))
        self.assertFalse(store.validate_event_token(session.session_id, "wrong-token"))

    def test_appends_and_reads_caption_events_after_cursor(self):
        store = RealtimeSessionStore()
        session = store.create(sunday="2026-06-28")
        first = store.append_event(session.session_id, {"type": "caption_delta", "text": "神爱世人"})
        second = store.append_event(session.session_id, {"type": "caption_final", "text": "神爱世人。", "final": True})

        events = store.wait_for_events(session.session_id, after_id=first["id"], timeout=0)
        self.assertEqual([event["id"] for event in events], [second["id"]])
        self.assertEqual(events[0]["text"], "神爱世人。")
        self.assertTrue(events[0]["final"])

    def test_sanitize_event_drops_untrusted_fields(self):
        event = sanitize_event(
            {
                "type": "caption_delta",
                "text": "hello",
                "apiKey": "sk-secret",
                "Authorization": "Bearer secret",
                "latencyMs": "1200",
            }
        )

        self.assertEqual(event["text"], "hello")
        self.assertEqual(event["latencyMs"], 1200)
        self.assertNotIn("apiKey", event)
        self.assertNotIn("Authorization", event)

    def test_archive_writes_sanitized_jsonl_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = RealtimeEventArchive(Path(tmp))
            store = RealtimeSessionStore(archive)
            session = store.create(sunday="2026-06-28")
            store.append_event(
                session.session_id,
                {
                    "type": "caption_delta",
                    "text": "神爱世人",
                    "Authorization": "Bearer secret",
                    "apiKey": "sk-secret",
                },
            )

            path = archive.path_for(session.session_id)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('"type": "session_started"', lines[0])
            self.assertIn('"text": "神爱世人"', lines[1])
            self.assertNotIn("Authorization", path.read_text(encoding="utf-8"))
            self.assertNotIn("sk-secret", path.read_text(encoding="utf-8"))

    def test_archive_status_reports_directory(self):
        store = RealtimeSessionStore(RealtimeEventArchive("/tmp/realtime-test"))

        self.assertTrue(store.archive_status()["enabled"])
        self.assertEqual(store.archive_status()["directory"], "/tmp/realtime-test")

    def test_create_openai_translation_session_uses_client_secret_endpoint(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"client_secret":{"value":"ek_test","expires_at":123}}'

        original_urlopen = realtime.urlopen
        try:
            def fake_urlopen(request, timeout):
                captured["url"] = request.full_url
                captured["headers"] = dict(request.header_items())
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                captured["timeout"] = timeout
                return FakeResponse()

            realtime.urlopen = fake_urlopen
            data = create_openai_translation_session(
                api_key="sk-test",
                model="gpt-realtime-translate",
                target_language="zh-CN",
            )
        finally:
            realtime.urlopen = original_urlopen

        self.assertEqual(captured["url"], OPENAI_TRANSLATION_CLIENT_SECRET_URL)
        self.assertEqual(captured["payload"]["session"]["model"], "gpt-realtime-translate")
        self.assertEqual(captured["payload"]["session"]["audio"]["output"]["language"], "zh-CN")
        self.assertEqual(data["client_secret"]["value"], "ek_test")

    def test_translation_calls_endpoint_is_dedicated_webrtc_url(self):
        self.assertEqual(
            OPENAI_TRANSLATION_CALLS_URL,
            "https://api.openai.com/v1/realtime/translations/calls",
        )


if __name__ == "__main__":
    unittest.main()

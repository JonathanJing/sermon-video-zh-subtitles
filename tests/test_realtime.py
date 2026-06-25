import unittest
import tempfile
from pathlib import Path

from backend.realtime import RealtimeEventArchive, RealtimeSessionStore, sanitize_event


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


if __name__ == "__main__":
    unittest.main()

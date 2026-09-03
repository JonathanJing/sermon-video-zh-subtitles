from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backend.session_store import SessionStore, SessionStoreError


class SessionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = SessionStore(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_recording_lifecycle_writes_replayable_artifacts(self) -> None:
        created = self.store.create({"audioMimeType": "audio/webm;codecs=opus"})
        session_id = created["sessionId"]
        directory = Path(created["directory"])

        self.store.append_event(session_id, {"sequence": 1, "type": "session_started"})
        self.store.append_audio(session_id, 1, b"first")
        self.store.append_audio(session_id, 2, b"second")
        completed = self.store.finalize(session_id, {"durationMs": 2500})

        self.assertEqual(completed["status"], "completed")
        self.assertEqual((directory / "recording.webm").read_bytes(), b"firstsecond")
        self.assertEqual(
            completed["audioSha256"],
            hashlib.sha256(b"firstsecond").hexdigest(),
        )
        event = json.loads((directory / "events.jsonl").read_text().strip())
        self.assertEqual(event["type"], "session_started")

    def test_finalize_is_idempotent(self) -> None:
        created = self.store.create({"audioMimeType": "audio/mp4"})
        first = self.store.finalize(created["sessionId"], {"durationMs": 10})
        second = self.store.finalize(created["sessionId"], {"durationMs": 999})
        self.assertEqual(first, second)
        self.assertTrue(first["audioPath"].endswith("recording.m4a"))

    def test_out_of_order_writes_fail_closed(self) -> None:
        created = self.store.create({"audioMimeType": "audio/webm"})
        with self.assertRaisesRegex(SessionStoreError, "audio sequence must be 1"):
            self.store.append_audio(created["sessionId"], 2, b"late")
        with self.assertRaisesRegex(SessionStoreError, "event sequence must be 1"):
            self.store.append_event(created["sessionId"], {"sequence": 2})


if __name__ == "__main__":
    unittest.main()

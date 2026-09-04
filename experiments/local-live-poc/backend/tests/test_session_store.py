from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import wave
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
        self.store.append_pcm_frames(session_id, 1, 2, bytes(6400))
        completed = self.store.finalize(session_id, {"durationMs": 2500})

        self.assertEqual(completed["status"], "completed")
        self.assertEqual((directory / "recording.webm").read_bytes(), b"firstsecond")
        self.assertEqual(
            completed["audioSha256"],
            hashlib.sha256(b"firstsecond").hexdigest(),
        )
        event = json.loads((directory / "events.jsonl").read_text().strip())
        self.assertEqual(event["type"], "session_started")
        self.assertEqual(completed["pcmFrameCount"], 2)
        self.assertEqual(len(completed["pcmSha256"]), 64)
        with wave.open(completed["asrWavPath"], "rb") as audio:
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getnframes(), 3200)

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

    def test_gateway_can_assign_event_sequence(self) -> None:
        created = self.store.create({"audioMimeType": "audio/webm"})
        first = self.store.append_event(
            created["sessionId"], {"sequence": 99, "type": "browser_event"}, assign_sequence=True
        )
        second = self.store.append_event(
            created["sessionId"], {"type": "model_event"}, assign_sequence=True
        )
        self.assertEqual(first["event"]["sequence"], 1)
        self.assertEqual(first["event"]["clientSequence"], 99)
        self.assertEqual(second["event"]["sequence"], 2)

    def test_storage_health_runs_write_probe_and_checks_free_space(self) -> None:
        healthy = self.store.health(probe_write=True)
        self.assertTrue(healthy["available"])
        self.assertGreater(healthy["freeBytes"], 0)
        self.assertEqual(list(Path(self.temporary.name).glob(".storage-probe-*")), [])
        constrained = self.store.health(minimum_free_bytes=healthy["freeBytes"] + 1)
        self.assertFalse(constrained["available"])

    def test_recover_incomplete_preserves_artifacts_without_claiming_completion(self) -> None:
        created = self.store.create({"audioMimeType": "audio/webm"})
        self.store.append_audio(created["sessionId"], 1, b"recoverable-audio")
        self.store.append_pcm_frames(created["sessionId"], 1, 1, bytes(3200))

        recovered = self.store.recover_incomplete()

        self.assertEqual(len(recovered), 1)
        session = recovered[0]
        self.assertEqual(session["status"], "incomplete")
        self.assertEqual(session["recoveryReason"], "gateway_restart_before_finalize")
        self.assertEqual(session["durationMs"], 1000)
        self.assertEqual(len(session["audioSha256"]), 64)
        self.assertEqual(len(session["pcmSha256"]), 64)
        self.assertTrue(Path(session["asrWavPath"]).is_file())


if __name__ == "__main__":
    unittest.main()

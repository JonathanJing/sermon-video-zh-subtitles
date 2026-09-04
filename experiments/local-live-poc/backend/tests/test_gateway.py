from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.content_pack import build_weekly_pack, write_pack
from backend.gateway import GatewayState, create_server


class GatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        pack_path = Path(self.temporary.name) / "weekly-pack.json"
        pack = build_weekly_pack([{
            "segmentId": "seg_001",
            "sourceTextEn": "The promised land is before them.",
            "targetTextZh": "应许之地就在他们面前。",
            "translationStatus": "machine_generated",
            "terms": [{"source": "promised land", "preferredZh": "应许之地", "status": "approved"}],
        }], service_date="2099-09-05", source_id="saturday-service", audio_sha256="b" * 64, valid_until="2099-09-07")
        write_pack(pack, pack_path)
        state = GatewayState(
            str(pack_path),
            "",
            session_root=str(Path(self.temporary.name) / "sessions"),
        )
        state.ollama.status = lambda: {"available": True, "configuredModel": None, "installedModels": []}
        state.asr.status = lambda: {"available": True, "provider": "test-asr"}
        self.state = state
        self.server = create_server("127.0.0.1", 0, state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def raw_request(self, path: str, data: bytes) -> tuple[int, dict]:
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/octet-stream"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_health_reports_pack_and_degraded_model(self) -> None:
        status, payload = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["contentPack"]["entryCount"], 1)
        self.assertTrue(payload["sessionStorage"]["available"])
        self.assertGreater(payload["sessionStorage"]["freeBytes"], 0)

    def test_health_does_not_require_an_optional_content_pack(self) -> None:
        self.state.pack = None
        self.state.ollama.status = lambda: {
            "available": True,
            "configuredModel": "test-model",
            "configuredModelInstalled": True,
            "installedModels": ["test-model"],
        }
        status, payload = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertIsNone(payload["contentPack"])

    def test_session_folder_persists_audio_events_and_manifest(self) -> None:
        status, created = self.request("/api/sessions/start", {
            "audioMimeType": "audio/webm;codecs=opus",
            "audioDeviceLabel": "Test microphone",
        })
        self.assertEqual(status, 201)
        session_id = created["sessionId"]
        directory = Path(created["directory"])
        self.assertTrue(directory.is_dir())

        status, event_result = self.request(f"/api/sessions/{session_id}/events", {
            "schemaVersion": 1,
            "sequence": 1,
            "at": "2099-09-05T12:00:00Z",
            "type": "session_started",
        })
        self.assertEqual(status, 200)
        self.assertEqual(event_result["eventCount"], 1)

        status, audio_result = self.raw_request(
            f"/api/sessions/{session_id}/audio?sequence=1",
            b"test-audio-chunk",
        )
        self.assertEqual(status, 200)
        self.assertEqual(audio_result["audioChunkCount"], 1)

        status, finalized = self.request(f"/api/sessions/{session_id}/finalize", {
            "durationMs": 1234,
            "stoppedAt": "2099-09-05T12:00:01Z",
        })
        self.assertEqual(status, 200)
        self.assertEqual(finalized["status"], "completed")
        self.assertEqual(finalized["audioBytes"], len(b"test-audio-chunk"))
        self.assertEqual((directory / "recording.webm").read_bytes(), b"test-audio-chunk")
        event = json.loads((directory / "events.jsonl").read_text().strip())
        self.assertEqual(event["type"], "session_started")
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["eventCount"], 1)
        self.assertEqual(len(manifest["audioSha256"]), 64)

    def test_session_rejects_out_of_order_audio(self) -> None:
        _, created = self.request("/api/sessions/start", {"audioMimeType": "audio/webm"})
        status, payload = self.raw_request(
            f"/api/sessions/{created['sessionId']}/audio?sequence=2",
            b"out-of-order",
        )
        self.assertEqual(status, 400)
        self.assertIn("sequence must be 1", payload["message"])

    def test_session_can_finalize_as_recoverable_incomplete(self) -> None:
        _, created = self.request("/api/sessions/start", {"audioMimeType": "audio/webm"})
        status, finalized = self.request(f"/api/sessions/{created['sessionId']}/finalize", {
            "durationMs": 100,
            "status": "incomplete",
        })
        self.assertEqual(status, 200)
        self.assertEqual(finalized["status"], "incomplete")

    def test_retrieve_returns_approved_term_but_not_machine_translation(self) -> None:
        status, payload = self.request("/api/context/retrieve", {
            "sourceTextEn": "They are approaching the promised land.",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["promptContext"]["approvedTerms"][0]["preferredZh"], "应许之地")
        self.assertIsNone(payload["hits"][0]["targetTextZh"])

    def test_retrieve_returns_alignment_cursor_for_replay(self) -> None:
        status, payload = self.request("/api/context/retrieve", {
            "sourceTextEn": "They are approaching the promised land.",
            "cursorSequence": 1,
            "contextPolicy": "saturday_alignment_v1",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["alignment"]["strategy"], "local_window")
        self.assertEqual(payload["alignment"]["previousCursor"], 1)
        self.assertEqual(payload["alignment"]["suggestedCursor"], 1)

    def test_none_policy_skips_pack(self) -> None:
        status, payload = self.request("/api/context/retrieve", {
            "sourceTextEn": "They are approaching the promised land.",
            "contextPolicy": "none",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["hits"], [])
        self.assertEqual(payload["promptContext"]["approvedTerms"], [])
        self.assertEqual(payload["alignment"]["strategy"], "no_match")

    def test_translation_without_model_fails_open_for_recording(self) -> None:
        status, payload = self.request("/api/translate", {
            "sourceTextEn": "The promised land is before them.",
            "cursorSequence": 1,
            "contextPolicy": "saturday_alignment_v1",
        })
        self.assertEqual(status, 503)
        self.assertTrue(payload["recordingShouldContinue"])
        self.assertEqual(payload["fallback"], "show_english_only")
        self.assertEqual(payload["requestedContextPolicy"], "saturday_alignment_v1")
        self.assertEqual(payload["alignment"]["suggestedCursor"], 1)
        self.assertEqual(len(payload["contextHitIds"]), 1)

    def test_translation_success_returns_the_frontend_contract(self) -> None:
        self.state.ollama.translate = lambda source_text, context: {
            "targetTextZh": "应许之地就在他们面前。",
            "model": "test-model",
            "promptVersion": "milmmt-a0-v1",
            "metrics": {"totalDurationMs": 12},
        }
        status, payload = self.request("/api/translate", {
            "sourceTextEn": "The promised land is before them.",
            "contextPolicy": "none",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["targetTextZh"], "应许之地就在他们面前。")
        self.assertEqual(payload["contextPolicy"], "none")
        self.assertEqual(payload["contextHitIds"], [])

    def test_invalid_retrieval_limit_is_rejected(self) -> None:
        status, payload = self.request("/api/context/retrieve", {
            "sourceTextEn": "promised land",
            "limit": 99,
        })
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_request")

    def test_invalid_cursor_is_rejected(self) -> None:
        status, payload = self.request("/api/context/retrieve", {
            "sourceTextEn": "promised land",
            "cursorSequence": 0,
        })
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_request")

    def test_invalid_context_policy_is_rejected(self) -> None:
        status, payload = self.request("/api/context/retrieve", {
            "sourceTextEn": "promised land",
            "contextPolicy": "vector_magic",
        })
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()

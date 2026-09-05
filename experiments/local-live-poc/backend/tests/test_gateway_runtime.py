import json
import os
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

from websockets.sync.client import connect

from backend.gateway import GatewayState, create_server, parser
from backend.live_server import LiveSocketService
from backend.runtime_identity import validate_frontend_origin
from backend.session_store import SessionStoreError


class RuntimeConfigurationTest(unittest.TestCase):
    def test_flags_have_reversible_defaults_and_accept_an_isolated_origin(self):
        with patch.dict(os.environ, {}, clear=True):
            defaults = parser().parse_args([])
            candidate = parser().parse_args([
                "--translation-unit-policy", "bounded_semantic_v1",
                "--source-fragment-policy", "off",
                "--frontend-origin", "http://127.0.0.1:5174",
            ])
        self.assertEqual(defaults.translation_unit_policy, "legacy")
        self.assertEqual(defaults.source_fragment_policy, "content_words")
        self.assertEqual(defaults.frontend_origin, "http://127.0.0.1:4173")
        self.assertEqual(candidate.translation_unit_policy, "bounded_semantic_v1")
        self.assertEqual(candidate.source_fragment_policy, "off")
        self.assertEqual(candidate.frontend_origin, "http://127.0.0.1:5174")

    def test_frontend_origin_must_be_an_http_loopback_origin(self):
        for origin in ("http://localhost:5174", "http://127.0.0.1:5174", "http://[::1]:5174"):
            self.assertEqual(validate_frontend_origin(origin), origin)
        for origin in (
            "https://localhost:5174", "http://example.org:5174", "http://192.168.1.2:5174",
            "http://127.0.0.1.evil.test:5174", "http://user:password@localhost:5174",
            "http://localhost:5174/page", "http://localhost:5174?token=secret",
            "http://localhost:5174#fragment", "http://localhost:0", "http://localhost:65536",
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                validate_frontend_origin(origin)

    def test_capture_is_immutable_and_session_cannot_supply_its_own_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = GatewayState(
                session_root=temporary, ollama_model="configured-model",
                vad_threshold_rms=450, translation_unit_policy="bounded_semantic_v1",
                source_fragment_policy="off", frontend_origin="http://127.0.0.1:5174",
            )
            state.ollama._json = Mock(side_effect=AssertionError("identity must not make network calls"))
            captured = state.capture_runtime_identity(
                provider_versions={"ollama": "verified-version", "credential": "secret-marker"},
                translation_model_digest="sha256:verified-model",
            )
            self.assertEqual(captured["configuration"]["sourceFragmentPolicy"], "off")
            self.assertEqual(captured["configuration"]["translationUnitPolicy"], "bounded_semantic_v1")
            self.assertEqual(captured["configuration"]["frontendOrigin"], "http://127.0.0.1:5174")
            self.assertEqual(captured["configuration"]["translationModelDigest"], "sha256:verified-model")
            self.assertNotIn("secret-marker", json.dumps(captured))
            original_fingerprint = captured["fingerprintSha256"]
            captured["configuration"]["vadThresholdRms"] = -1
            state.vad_threshold_rms = 999
            session = state.create_session({"runtimeIdentity": {"forged": True}})
            saved = session["metadata"]["runtimeIdentity"]
            self.assertEqual(saved["configuration"]["vadThresholdRms"], 450)
            self.assertEqual(saved["fingerprintSha256"], original_fingerprint)
            self.assertNotIn("forged", saved)
            self.assertEqual(saved, state.capture_runtime_identity())

    def test_session_runtime_log_location_is_server_owned(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = GatewayState(session_root=temporary)
            with patch.dict(os.environ, {"LOCAL_LIVE_RUNTIME_LOG_DIRECTORY": "/private/runtime/run-one"}):
                session = state.create_session({"runtimeLogDirectory": "forged"})
                self.assertEqual(session["metadata"]["runtimeLogDirectory"], "/private/runtime/run-one")
            with patch.dict(os.environ, {}, clear=True):
                session = state.create_session({"runtimeLogDirectory": "forged"})
                self.assertIsNone(session["metadata"]["runtimeLogDirectory"])

    def test_health_uses_captured_identity_and_explicit_origin_for_cors(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = GatewayState(session_root=temporary, frontend_origin="http://127.0.0.1:5174")
            state.asr.status = lambda: {"available": True}
            state.ollama.status = lambda: {"configuredModelInstalled": True}
            captured = state.capture_runtime_identity()
            server = create_server("127.0.0.1", 0, state)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/health",
                    headers={"Origin": "http://127.0.0.1:5174"},
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://127.0.0.1:5174")
                    health = json.load(response)
                self.assertEqual(health["runtimeIdentity"], captured)
                self.assertEqual(health["liveStream"]["translationUnitPolicy"], "legacy")
                self.assertEqual(health["liveStream"]["sourceFragmentPolicy"], "content_words")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_state_rejects_unknown_candidate_policies(self):
        with tempfile.TemporaryDirectory() as temporary:
            for kwargs in ({"translation_unit_policy": "unknown"}, {"source_fragment_policy": "unknown"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    GatewayState(session_root=temporary, **kwargs)

    def test_claimed_but_unregistered_stream_cannot_be_finalized(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = GatewayState(session_root=temporary)
            session = state.sessions.create({"audioMimeType": "audio/webm"})
            state.live_pipelines[session["sessionId"]] = None
            with self.assertRaises(SessionStoreError):
                state.finalize_session(session["sessionId"], {"status": "completed"})


class PipelineStub:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        self.kwargs["send"]({"type": "stream.ready"})

    def stop(self):
        self.kwargs["send"]({"type": "stream.closed", "workerDrained": True})
        return {"workerDrained": True}


class RuntimeSocketConfigurationTest(unittest.TestCase):
    def test_flags_reach_pipeline_and_duplicate_socket_cannot_publish_or_end_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = GatewayState(
                session_root=temporary, translation_unit_policy="bounded_semantic_v1",
                source_fragment_policy="off", frontend_origin="http://127.0.0.1:5174",
            )
            publisher = Mock()
            publisher.start_session.return_value = "https://captions.example.invalid/s/test"
            state.public_caption_publisher = publisher
            session = state.sessions.create({"audioMimeType": "audio/webm"})
            start = json.dumps({
                "type": "stream.start", "sessionId": session["sessionId"],
                "contextPolicy": "none", "encoding": "pcm_s16le",
                "sampleRateHz": 16000, "channels": 1, "frameDurationMs": 100,
            })
            with patch("backend.live_server.LivePipeline", side_effect=PipelineStub) as factory:
                service = LiveSocketService(state, "127.0.0.1", 0)
                port = service.server.socket.getsockname()[1]
                service.start()
                try:
                    with connect(f"ws://127.0.0.1:{port}/api/live", origin=state.frontend_origin) as owner:
                        owner.send(start)
                        ready = json.loads(owner.recv(timeout=2))
                        self.assertEqual(ready["type"], "stream.ready")
                        self.assertEqual(factory.call_args.kwargs["translation_unit_policy"], "bounded_semantic_v1")
                        self.assertEqual(factory.call_args.kwargs["source_fragment_policy"], "off")
                        published_before = publisher.publish.call_count
                        with connect(f"ws://127.0.0.1:{port}/api/live", origin=state.frontend_origin) as duplicate:
                            duplicate.send(start)
                            self.assertEqual(json.loads(duplicate.recv(timeout=2))["type"], "stream.error")
                        self.assertEqual(publisher.publish.call_count, published_before)
                        publisher.end_session.assert_not_called()
                        self.assertEqual(factory.call_count, 1)
                        self.assertTrue(state.caption_hub.snapshot(ready["viewer"]["token"])["sessionActive"])
                        owner.send(json.dumps({"type": "stream.stop"}))
                        self.assertEqual(json.loads(owner.recv(timeout=2))["type"], "stream.closed")
                finally:
                    service.stop()


if __name__ == "__main__":
    unittest.main()

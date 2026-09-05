"""Provider selection across real local HTTP/WS with fake ASR and translators.

PCM and browser-recording bytes are synthetic persistence fixtures, not acoustic
or codec acceptance evidence. No test starts or contacts a real model service.
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from websockets.sync.client import connect

from backend.content_pack import PackValidationError, build_weekly_pack, write_pack
from backend.gateway import GatewayState, create_server
from backend.live_server import LiveSocketService
from backend.milmmt_v41_client import MANIFEST_SHA, MODEL_ID, PROVIDER_ID, WEIGHTS_SHA
from backend.ollama_client import OllamaError


SPEECH = struct.pack("<1600h", *([1000] * 1600))
SILENCE = bytes(3200)
RECORDING_CHUNKS = (b"browser-recovery-fixture-one", b"-still-recording-after-model-error")


class FakeAsr:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"available": True, "provider": "synthetic-provider-selection-asr"}

    def transcribe(self, pcm, sample_rate_hz=16000):
        self.calls.append((pcm, sample_rate_hz))
        text = "Grace leads us through the truth." if len(self.calls) == 1 else "We can keep hearing the live English."
        return {"sourceTextEn": text, "latencyMs": 1, "audioDurationMs": len(pcm) // 32}


def read_events(session):
    return [json.loads(line) for line in Path(session["eventPath"]).read_text().splitlines()]


class ProviderFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        firebase = patch("backend.gateway.FirebasePublisherConfig.from_environment", return_value=None)
        firebase.start()
        self.addCleanup(firebase.stop)
        git = patch("backend.runtime_identity._git_identity", return_value={"revision": "a" * 40, "dirty": False, "available": True})
        git.start()
        self.addCleanup(git.stop)

    def make_state(self, *, context_pack=False):
        v41_status = {"available": True, "ready": True, "busy": False,
            "configuredModel": MODEL_ID, "configuredModelInstalled": True,
            "experimental": True, "releaseEligible": False, "startSupported": True,
            "modelSha256": WEIGHTS_SHA, "packageSha256": MANIFEST_SHA,
            "runtimePackages": {"mlx": "fake-mlx", "mlx-lm": "fake-mlx-lm"}}
        v41 = SimpleNamespace(model=MODEL_ID, status=Mock(return_value=v41_status),
            translate=Mock(), start_runtime=Mock(return_value=v41_status))
        options = {"session_root": str(self.root / "sessions"), "ollama_model": "original-default-q8",
                   "source_fragment_policy": "off"}
        if context_pack:
            pack = build_weekly_pack([{"segmentId": "seg_001", "sourceTextEn": "The promised land is before them.",
                "targetTextZh": "机器候选中文不可进入提示。", "translationStatus": "machine_generated",
                "terms": [{"source": "promised land", "preferredZh": "应许之地", "status": "approved"}]}],
                service_date="2099-09-05", source_id="fixture", audio_sha256="b" * 64, valid_until="2099-09-07")
            path = self.root / "pack.json"
            write_pack(pack, path)
            options.update(pack_path=str(path), default_context_policy="weekly_terms_v1")
        with patch("backend.gateway.MilmmtV41Client", return_value=v41):
            state = GatewayState(**options)
        state.asr = FakeAsr()
        state.ollama._json = Mock(side_effect=AssertionError("real Ollama I/O forbidden"))
        state.ollama.status = Mock(return_value={"available": True, "configuredModelInstalled": True,
                                                "configuredModel": state.ollama.model, "installedModels": [state.ollama.model]})

        def translated(provider, source, context, on_partial=None):
            text = "实验译文。" if provider == PROVIDER_ID else "默认译文。"
            if on_partial:
                on_partial(text[:2], text[:2])
                on_partial(text[2:], text)
            return {"targetTextZh": text, "model": MODEL_ID if provider == PROVIDER_ID else state.ollama.model,
                    "translationProvider": "untrusted-client-field", "contextPolicy": "none", "metrics": {}}

        state.v41.translate.side_effect = lambda source, context, on_partial=None: translated(PROVIDER_ID, source, context, on_partial)
        state.ollama.translate = Mock(side_effect=lambda source, context, on_partial=None: translated("ollama", source, context, on_partial))
        state.caption_hub = Mock(wraps=state.caption_hub)
        state.public_caption_publisher = Mock()
        state.public_caption_publisher.start_session.return_value = "https://fixture.invalid/s/fixture-token"
        state.public_caption_publisher.status.return_value = {"configured": True, "mode": "fake"}
        return state

    def serve_http(self, state):
        httpd = create_server("127.0.0.1", 0, state)
        thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()

        def cleanup():
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.addCleanup(cleanup)
        return httpd

    def request(self, httpd, path, payload=None, *, raw=None):
        body = raw if raw is not None else None if payload is None else json.dumps(payload).encode()
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
        try:
            connection.request("GET" if body is None else "POST", path, body=body,
                headers={"Content-Type": "application/octet-stream" if raw is not None else "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def serve_ws(self, state):
        service = LiveSocketService(state, "127.0.0.1", 0)
        service.start()
        self.addCleanup(service.stop)
        return f"ws://127.0.0.1:{service.server.socket.getsockname()[1]}/api/live"

    @staticmethod
    def start_message(session, **overrides):
        return json.dumps({"type": "stream.start", "sessionId": session["sessionId"], "contextPolicy": "none",
            "encoding": "pcm_s16le", "sampleRateHz": 16000, "channels": 1, "frameDurationMs": 100, **overrides})

    @staticmethod
    def utterance(socket, first_sequence=1):
        frames = [SPEECH] * 4 + [SILENCE] * 7
        for sequence, frame in enumerate(frames, first_sequence):
            socket.send(struct.pack(">I", sequence) + frame)
        return b"".join(frames)

    def receive_until(self, socket, events, event_type):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            event = json.loads(socket.recv(timeout=max(0.1, deadline - time.monotonic())))
            events.append(event)
            if event["type"] == event_type:
                return event
        self.fail(f"did not receive {event_type}")

    @staticmethod
    def assert_no_sharing(state):
        for component in (state.caption_hub, state.public_caption_publisher):
            component.start_session.assert_not_called()
            component.publish.assert_not_called()
            component.end_session.assert_not_called()


class SelectionContractTests(ProviderFixture):
    def test_default_is_ollama_and_only_two_named_providers_are_accepted(self):
        state = self.make_state()
        self.assertEqual(state.resolve_translation_provider(None), "ollama")
        for provider in ("ollama", PROVIDER_ID):
            self.assertEqual(state.resolve_translation_provider(provider), provider)
        for provider in ("", "other", False, {}, ["ollama"]):
            with self.subTest(provider=provider), self.assertRaises(PackValidationError):
                state.resolve_translation_provider(provider)
        session = state.create_session({"audioMimeType": "audio/webm"})
        self.assertEqual(session["metadata"]["translationProvider"], "ollama")
        self.assertEqual(session["metadata"]["runtimeIdentity"]["schemaVersion"], "local-live-runtime-identity-v1")

    def test_v41_session_overwrites_forged_identity_release_and_sharing_flags(self):
        state = self.make_state()
        metadata = {"translationProvider": PROVIDER_ID, "audioMimeType": "audio/webm", "contextPolicy": "none",
            "runtimeIdentity": {"forged": True}, "experimental": False, "releaseEligible": True, "publicSharingAllowed": True}
        original = copy.deepcopy(metadata)
        session = state.create_session(metadata)
        stored = state.sessions.get_recording(session["sessionId"])["metadata"]
        self.assertEqual(metadata, original)
        self.assertEqual(stored["translationProvider"], PROVIDER_ID)
        self.assertEqual(stored["contextPolicy"], "none")
        self.assertTrue(stored["experimental"])
        self.assertFalse(stored["releaseEligible"])
        self.assertFalse(stored["publicSharingAllowed"])
        identity = stored["runtimeIdentity"]
        self.assertNotIn("forged", identity)
        self.assertEqual(identity["schemaVersion"], "local-live-runtime-identity-v2")
        config = identity["configuration"]
        expected = {"translationProvider": PROVIDER_ID, "translationModelDigest": WEIGHTS_SHA,
            "translationExpectedModelDigest": WEIGHTS_SHA, "translationMaxNewTokens": 512,
            "translationAddSpecialTokens": False, "translationGreedy": True, "translationTemperature": 0,
            "translationTopK": None, "translationEosTokenIds": "1,106", "translationCachePolicy": "new_per_request",
            "translationExperimental": True, "translationReleaseEligible": False, "publicSharingAllowed": False}
        self.assertEqual({key: config.get(key) for key in expected}, expected)

    def test_expected_identity_is_not_presented_as_loaded_model_when_v41_is_not_ready(self):
        state = self.make_state()
        state.v41.status.return_value = {**state.v41.status.return_value, "ready": False, "available": False}
        session = state.create_session({"translationProvider": PROVIDER_ID})
        config = session["metadata"]["runtimeIdentity"]["configuration"]
        self.assertIsNone(config["translationModelDigest"])
        self.assertEqual(config["translationExpectedModelDigest"], WEIGHTS_SHA)

    def test_v41_rejects_context_while_base_keeps_approved_term_contract(self):
        state = self.make_state(context_pack=True)
        source = "The promised land is before them."
        baseline = state.translate(source, None, "weekly_terms_v1")
        self.assertEqual(baseline["translationProvider"], "ollama")
        context = state.ollama.translate.call_args.args[1]
        self.assertTrue(context["approvedTerms"])
        self.assertNotIn("机器候选中文", json.dumps(context, ensure_ascii=False))
        state.v41.translate.assert_not_called()
        for policy in ("english_alignment_v1", "weekly_terms_v1", "saturday_alignment_v1"):
            with self.subTest(policy=policy), self.assertRaises(PackValidationError):
                state.create_session({"translationProvider": PROVIDER_ID, "contextPolicy": policy})
            with self.subTest(policy=policy), self.assertRaises(PackValidationError):
                state.translate(source, None, policy, translation_provider=PROVIDER_ID)
        self.assertEqual(state.create_session({"translationProvider": PROVIDER_ID})["metadata"]["contextPolicy"], "none")

    def test_sync_and_stream_translation_route_explicit_provider_without_switching_default(self):
        state = self.make_state()
        baseline = state.translate("First source", None, "none")
        candidate = state.translate("Second source", None, "none", translation_provider=PROVIDER_ID)
        callback = Mock()
        streamed = state.translate_stream("Third source", None, "none", callback, translation_provider=PROVIDER_ID)
        self.assertEqual(baseline["translationProvider"], "ollama")
        self.assertEqual(candidate["translationProvider"], PROVIDER_ID)
        self.assertEqual(streamed["translationProvider"], PROVIDER_ID)
        self.assertEqual(state.ollama.translate.call_count, 1)
        self.assertEqual(state.v41.translate.call_count, 2)
        self.assertTrue(callback.called)
        self.assertTrue(all(not value for value in state.v41.translate.call_args.args[1].values()))
        state.translate("Still default", None, "none")
        self.assertEqual(state.ollama.translate.call_count, 2)

    def test_resume_ignores_attempt_to_replace_stored_v41_provider_or_runtime_identity(self):
        state = self.make_state()
        session = state.create_session({"translationProvider": PROVIDER_ID, "audioMimeType": "audio/webm"})
        state.sessions.append_audio(session["sessionId"], 1, RECORDING_CHUNKS[0])
        state.sessions.recover_incomplete()
        resumed = state.resume_session(session["sessionId"], {"availableAudioChunks": 1,
            "translationProvider": "ollama", "runtimeIdentity": {"forged": True}, "publicSharingAllowed": True})
        self.assertEqual(resumed["metadata"]["translationProvider"], PROVIDER_ID)
        self.assertFalse(resumed["metadata"]["publicSharingAllowed"])
        event = next(row for row in reversed(read_events(session)) if row["type"] == "stream.resume_requested")
        self.assertEqual(event["runtimeIdentity"]["schemaVersion"], "local-live-runtime-identity-v2")
        self.assertEqual(event["runtimeIdentity"]["configuration"]["translationProvider"], PROVIDER_ID)
        self.assertNotIn("forged", event["runtimeIdentity"])
        self.assertEqual(Path(session["audioPath"]).read_bytes(), RECORDING_CHUNKS[0])


class ProviderHttpTests(ProviderFixture):
    def test_health_adds_provider_mapping_without_removing_default_ollama_fields(self):
        state = self.make_state()
        httpd = self.serve_http(state)
        status, result = self.request(httpd, "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(result["defaultTranslationProvider"], "ollama")
        self.assertEqual(result["ollama"], state.ollama.status.return_value)
        self.assertIn("ollamaWarmup", result)
        self.assertEqual(set(result["translationProviders"]), {"ollama", PROVIDER_ID})
        self.assertTrue(result["translationProviders"][PROVIDER_ID]["experimental"])
        self.assertFalse(result["translationProviders"][PROVIDER_ID]["releaseEligible"])

    def test_rest_translate_routes_selected_provider_and_defaults_to_base(self):
        state = self.make_state()
        httpd = self.serve_http(state)
        for requested, expected in ((None, "ollama"), (PROVIDER_ID, PROVIDER_ID)):
            payload = {"sourceTextEn": "Grace leads us.", "contextPolicy": "none"}
            if requested is not None:
                payload["translationProvider"] = requested
            status, result = self.request(httpd, "/api/translate", payload)
            self.assertEqual(status, 200)
            self.assertEqual(result["translationProvider"], expected)
        self.assertEqual(state.ollama.translate.call_count, 1)
        self.assertEqual(state.v41.translate.call_count, 1)
        status, _ = self.request(httpd, "/api/translate", {"sourceTextEn": "Source", "translationProvider": "other"})
        self.assertEqual(status, 400)
        state.v41.translate.side_effect = OllamaError("fixture v41 unavailable")
        status, result = self.request(httpd, "/api/translate", {"sourceTextEn": "Source", "translationProvider": PROVIDER_ID})
        self.assertEqual(status, 503)
        self.assertTrue(result["recordingShouldContinue"])
        self.assertEqual(result["fallback"], "show_english_only")
        self.assertEqual(state.ollama.translate.call_count, 1)

    def test_start_endpoint_runs_on_http_worker_and_refuses_when_real_stream_is_active(self):
        state = self.make_state()
        httpd = self.serve_http(state)
        thread_ids = []
        state.v41.start_runtime.side_effect = lambda: thread_ids.append(threading.get_ident()) or state.v41.status.return_value
        path = f"/api/translation/providers/{PROVIDER_ID}/start"
        status, result = self.request(httpd, path, {})
        self.assertEqual(status, 200)
        self.assertEqual(result["translationProvider"], PROVIDER_ID)
        self.assertEqual(len(thread_ids), 1)
        self.assertNotEqual(thread_ids[0], threading.get_ident())
        session = state.create_session({})
        with connect(self.serve_ws(state), origin=state.frontend_origin, close_timeout=2) as socket:
            socket.send(self.start_message(session))
            self.assertEqual(json.loads(socket.recv(timeout=2))["type"], "stream.ready")
            self.assertEqual(self.request(httpd, path, {})[0], 409)
            self.assertEqual(state.v41.start_runtime.call_count, 1)
            socket.send(json.dumps({"type": "stream.stop"}))
            self.receive_until(socket, [], "stream.closed")

    def test_start_refuses_a_socket_claim_before_its_pipeline_is_registered(self):
        state = self.make_state()
        httpd = self.serve_http(state)
        session = state.create_session({})
        claimed = threading.Event()
        release = threading.Event()
        stream_position = state.sessions.stream_position

        def paused_position(session_id):
            claimed.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release claimed stream")
            return stream_position(session_id)

        with patch.object(state.sessions, "stream_position", side_effect=paused_position):
            with connect(self.serve_ws(state), origin=state.frontend_origin, close_timeout=2) as socket:
                socket.send(self.start_message(session))
                try:
                    self.assertTrue(claimed.wait(timeout=2))
                    with state.live_lock:
                        self.assertIn(session["sessionId"], state.live_pipelines)
                        self.assertIsNone(state.live_pipelines[session["sessionId"]])
                    status, result = self.request(httpd, f"/api/translation/providers/{PROVIDER_ID}/start", {})
                    self.assertEqual(status, 409)
                    self.assertEqual(result["error"], "recording_active")
                    state.v41.start_runtime.assert_not_called()
                finally:
                    release.set()
                self.receive_until(socket, [], "stream.ready")
                socket.send(json.dumps({"type": "stream.stop"}))
                self.receive_until(socket, [], "stream.closed")

    def test_start_reserves_against_other_tabs_without_holding_live_lock(self):
        state = self.make_state()
        httpd = self.serve_http(state)
        url = self.serve_ws(state)
        sessions = [state.create_session({"translationProvider": provider}) for provider in ("ollama", PROVIDER_ID)]
        entered = threading.Event()
        release = threading.Event()

        def paused_start():
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release model startup")
            return state.v41.status.return_value

        state.v41.start_runtime.side_effect = paused_start
        path = f"/api/translation/providers/{PROVIDER_ID}/start"
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.request, httpd, path, {})
            try:
                self.assertTrue(entered.wait(timeout=2))
                unlocked = state.live_lock.acquire(blocking=False)
                if unlocked:
                    state.live_lock.release()
                self.assertTrue(unlocked, "model startup must not hold the stream lock")
                status, result = self.request(httpd, path, {})
                self.assertEqual(status, 409)
                self.assertEqual(result["error"], "translation_runtime_starting")
                for session in sessions:
                    with self.subTest(provider=session["metadata"]["translationProvider"]):
                        with connect(url, origin=state.frontend_origin, close_timeout=2) as socket:
                            socket.send(self.start_message(session))
                            event = json.loads(socket.recv(timeout=2))
                            self.assertEqual(event["type"], "stream.error")
                            self.assertEqual(event["error"], "translation_runtime_starting")
                        self.assertNotIn(session["sessionId"], state.live_pipelines)
                # Browser recording persistence remains available during startup.
                status, _ = self.request(httpd, f"/api/sessions/{sessions[0]['sessionId']}/audio?sequence=1", raw=RECORDING_CHUNKS[0])
                self.assertEqual(status, 200)
                self.assertEqual(state.v41.start_runtime.call_count, 1)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=2)[0], 200)
        self.assertFalse(state.translation_runtime_starting)
        with connect(url, origin=state.frontend_origin, close_timeout=2) as socket:
            socket.send(self.start_message(sessions[0]))
            self.receive_until(socket, [], "stream.ready")
            socket.send(json.dumps({"type": "stream.stop"}))
            self.receive_until(socket, [], "stream.closed")

    def test_failed_start_releases_reservation_for_a_retry(self):
        state = self.make_state()
        httpd = self.serve_http(state)
        path = f"/api/translation/providers/{PROVIDER_ID}/start"
        state.v41.start_runtime.side_effect = [OllamaError("fixture startup failed"), state.v41.status.return_value]
        status, result = self.request(httpd, path, {})
        self.assertEqual(status, 503)
        self.assertEqual(result["error"], "translation_unavailable")
        self.assertFalse(state.translation_runtime_starting)
        self.assertEqual(self.request(httpd, path, {})[0], 200)
        self.assertEqual(state.v41.start_runtime.call_count, 2)
        self.assertFalse(state.translation_runtime_starting)


class ProviderWebSocketTests(ProviderFixture):
    def test_v41_socket_uses_stored_provider_and_disables_all_sharing_despite_client_flags(self):
        state = self.make_state()
        session = state.create_session({"translationProvider": PROVIDER_ID})
        events = []
        with connect(self.serve_ws(state), origin=state.frontend_origin, close_timeout=2) as socket:
            # Deliberately omit translationProvider. Client sharing flags cannot
            # override the provider and sharing decision stored by the server.
            socket.send(self.start_message(session, experimental=False, releaseEligible=True, publicSharingAllowed=True))
            ready = self.receive_until(socket, events, "stream.ready")
            self.assertEqual(ready["viewer"]["urls"], [])
            self.assertEqual(ready["viewer"]["disabledReason"], "experimental_local_only")
            self.utterance(socket)
            final = self.receive_until(socket, events, "translation.final")
            self.assertEqual(final["translationProvider"], PROVIDER_ID)
            self.assertEqual(final["targetTextZh"], "实验译文。")
            socket.send(json.dumps({"type": "stream.stop"}))
            self.receive_until(socket, events, "stream.closed")
        state.ollama.translate.assert_not_called()
        self.assertEqual(state.v41.translate.call_count, 1)
        self.assert_no_sharing(state)

    def test_socket_cannot_replace_stored_provider_in_either_direction(self):
        state = self.make_state()
        url = self.serve_ws(state)
        for stored, requested in ((PROVIDER_ID, "ollama"), ("ollama", PROVIDER_ID)):
            session = state.create_session({"translationProvider": stored})
            with self.subTest(stored=stored), connect(url, origin=state.frontend_origin, close_timeout=2) as socket:
                socket.send(self.start_message(session, translationProvider=requested))
                self.assertEqual(json.loads(socket.recv(timeout=2))["type"], "stream.error")
            self.assertEqual(state.sessions.get_recording(session["sessionId"])["metadata"]["translationProvider"], stored)
            self.assertNotIn(session["sessionId"], state.live_pipelines)
        state.ollama.translate.assert_not_called()
        state.v41.translate.assert_not_called()
        self.assert_no_sharing(state)

    def test_default_ollama_socket_still_translates_and_shares_to_lan_and_public_viewers(self):
        state = self.make_state()
        session = state.create_session({})
        events = []
        with connect(self.serve_ws(state), origin=state.frontend_origin, close_timeout=2) as socket:
            socket.send(self.start_message(session))
            ready = self.receive_until(socket, events, "stream.ready")
            self.assertTrue(ready["viewer"]["urls"])
            self.assertEqual(ready["viewer"]["publicUrl"], state.public_caption_publisher.start_session.return_value)
            self.assertTrue(state.caption_hub.snapshot(ready["viewer"]["token"])["sessionActive"])
            self.utterance(socket)
            final = self.receive_until(socket, events, "translation.final")
            self.assertEqual(final["translationProvider"], "ollama")
            self.assertEqual(final["targetTextZh"], "默认译文。")
            socket.send(json.dumps({"type": "stream.stop"}))
            self.receive_until(socket, events, "stream.closed")
        state.v41.translate.assert_not_called()
        state.caption_hub.start_session.assert_called_once()
        self.assertTrue(state.caption_hub.publish.called)
        state.caption_hub.end_session.assert_called_once_with(session["sessionId"])
        state.public_caption_publisher.start_session.assert_called_once()
        self.assertTrue(state.public_caption_publisher.publish.called)
        state.public_caption_publisher.end_session.assert_called_once_with(session["sessionId"])

    def test_translation_failure_preserves_recording_and_asr_then_continues_next_segment(self):
        state = self.make_state()
        success = state.v41.translate.side_effect
        attempts = []

        def fail_once(source, context, on_partial=None):
            attempts.append(source)
            if len(attempts) == 1:
                raise OllamaError("fixture v41 model unavailable")
            return success(source, context, on_partial)

        state.v41.translate.side_effect = fail_once
        httpd = self.serve_http(state)
        session = state.create_session({"translationProvider": PROVIDER_ID, "audioMimeType": "audio/webm"})
        session_id = session["sessionId"]
        events = []
        with connect(self.serve_ws(state), origin=state.frontend_origin, close_timeout=2) as socket:
            socket.send(self.start_message(session))
            self.receive_until(socket, events, "stream.ready")
            self.assertEqual(self.request(httpd, f"/api/sessions/{session_id}/audio?sequence=1", raw=RECORDING_CHUNKS[0])[0], 200)
            pcm = self.utterance(socket)
            failed = self.receive_until(socket, events, "translation.failed")
            self.assertTrue(failed["recordingShouldContinue"])
            self.assertEqual(self.request(httpd, f"/api/sessions/{session_id}/audio?sequence=2", raw=RECORDING_CHUNKS[1])[0], 200)
            pcm += self.utterance(socket, 12)
            translated = self.receive_until(socket, events, "translation.final")
            self.assertEqual(translated["sourceTextEn"], "We can keep hearing the live English.")
            self.assertEqual(translated["translationProvider"], PROVIDER_ID)
            socket.send(json.dumps({"type": "stream.stop"}))
            closed = self.receive_until(socket, events, "stream.closed")
            self.assertTrue(closed["workerDrained"])
        persisted = read_events(session)
        self.assertEqual(len([row for row in persisted if row["type"] == "asr.final"]), 2)
        self.assertEqual(len([row for row in persisted if row["type"] == "translation.failed"]), 1)
        self.assertEqual(len([row for row in persisted if row["type"] == "translation.final"]), 1)
        self.assertEqual(len(state.asr.calls), 2)
        state.ollama.translate.assert_not_called()
        self.assertEqual(Path(session["audioPath"]).read_bytes(), b"".join(RECORDING_CHUNKS))
        self.assertEqual(Path(session["asrPcmPath"]).read_bytes(), pcm)
        finalized = state.finalize_session(session_id, {"durationMs": 2200})
        self.assertEqual(finalized["pcmFrameCount"], 22)
        self.assertEqual(finalized["audioSha256"], hashlib.sha256(b"".join(RECORDING_CHUNKS)).hexdigest())
        self.assertEqual(finalized["pcmSha256"], hashlib.sha256(pcm).hexdigest())
        self.assert_no_sharing(state)


if __name__ == "__main__":
    unittest.main()

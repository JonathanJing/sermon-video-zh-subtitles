from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from websockets.sync.server import serve

from backend.gateway import GatewayState, create_server
from backend.live_server import LiveSocketService
from backend.ollama_client import OllamaError


SCRIPT = Path(__file__).parents[2] / "scripts" / "replay-audio-e2e.py"
SPEC = importlib.util.spec_from_file_location("replay_audio_e2e", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeAsr:
    def status(self):
        return {"available": True, "provider": "test-fake-asr"}

    def transcribe(self, pcm, sample_rate_hz=16000):
        return {"sourceTextEn": "Grace leads us.", "latencyMs": 1}


class AudioReplayProtocolTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.wav"
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(struct.pack("<8800h", *([1200] * 8800)))
        with patch.dict("os.environ", {"LOCAL_LIVE_FIREBASE_DATABASE_URL": "", "LOCAL_LIVE_FIREBASE_VIEWER_URL": ""}):
            self.state = GatewayState(session_root=str(self.root / "sessions"))
        self.state.asr = FakeAsr()
        self.state.ollama.status = lambda: {"available": True, "configuredModelInstalled": True, "configuredModel": "test-fake-translator"}
        self.state.translate_stream = lambda source, cursor, policy, on_partial: {
            "targetTextZh": "恩典引领我们。", "model": "test-fake-translator",
            "alignment": {"confidence": "none"},
        }
        self.live = LiveSocketService(self.state, "127.0.0.1", 0)
        self.state.ws_port = self.live.server.socket.getsockname()[1]
        self.live.start()
        self.http = create_server("127.0.0.1", 0, self.state)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.live.stop()
        self.http.shutdown()
        self.http.server_close()
        self.http_thread.join(timeout=2)
        self.temporary.cleanup()

    def run_replay(self, **kwargs):
        return MODULE.run_replay(self.source, self.url, self.root / "report.json", **kwargs)

    def test_real_rest_ws_protocol_preserves_window_hashes_drain_and_evidence_boundary(self):
        result = self.run_replay(source_start_seconds=0.05, duration_seconds=0.35)
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["framesSent"], 4)
        self.assertEqual(result["audio"]["paddingSampleCount"], 800)
        self.assertGreaterEqual(result["transmitElapsedMs"], 380)
        self.assertEqual(result["eventCounts"]["asr.final"], 1)
        self.assertEqual(result["eventCounts"]["translation.final"], 1)
        self.assertNotIn("caption_rendered", result["eventCounts"])
        self.assertFalse(result["browserRenderValidated"])
        manifest = json.loads(Path(result["manifest"]["manifestPath"]).read_text())
        self.assertEqual(manifest["metadata"]["mode"], "audio_file_replay")
        self.assertEqual(manifest["metadata"]["sourceAudio"]["sourceStartSample"], 800)
        with wave.open(result["manifest"]["audioPath"], "rb") as recovery:
            actual = recovery.readframes(recovery.getnframes())
        self.assertEqual(actual, struct.pack("<5600h", *([1200] * 5600)) + bytes(1600))
        self.assertEqual(Path(result["eventLogPath"]).read_text().count('"type": "stream.closed"'), 1)

    def test_translation_failure_keeps_recovery_and_marks_incomplete(self):
        def fail(*args):
            raise OllamaError("test model unavailable")
        self.state.translate_stream = fail
        result = self.run_replay()
        self.assertEqual(result["status"], "failed")
        self.assertIn("translation.failed", result["errors"])
        self.assertEqual(result["manifest"]["status"], "incomplete")
        self.assertTrue(result["checks"]["recoveryHash"])
        self.assertTrue(result["checks"]["pcmHash"])

    def test_existing_active_gateway_is_rejected_before_creating_session(self):
        self.state.live_health = lambda: {"activeStreamCount": 1, "degraded": False, "streams": []}
        result = self.run_replay()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("active stream" in error for error in result["errors"]))
        self.assertEqual(list((self.root / "sessions").iterdir()), [])

    def test_early_socket_close_cannot_finalize_an_incomplete_stream_as_completed(self):
        def close_early(socket):
            socket.recv(timeout=2)
            socket.send(json.dumps({"type": "stream.ready"}))
            socket.close()

        with serve(close_early, "127.0.0.1", 0, origins=[MODULE.ORIGIN]) as fake:
            thread = threading.Thread(target=fake.serve_forever, daemon=True)
            thread.start()
            self.state.ws_port = fake.socket.getsockname()[1]
            result = self.run_replay()
            fake.shutdown()
            thread.join(timeout=2)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["streamClosed"])
        self.assertIn("finalizeSkipped", result)
        manifest = self.state.sessions.get_recording(result["sessionId"])
        self.assertGreater(manifest["audioBytes"], 0)
        self.assertEqual(manifest["pcmFrameCount"], 0)

    def test_invalid_audio_format_fails_before_starting_session(self):
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(bytes(4800))
        result = self.run_replay()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("16000 Hz mono PCM16" in error for error in result["errors"]))
        self.assertEqual(list((self.root / "sessions").iterdir()), [])

    def test_drain_timeout_keeps_recovery_without_claiming_finalization(self):
        def never_close_event(socket):
            socket.recv(timeout=2)
            socket.send(json.dumps({"type": "stream.ready"}))
            for message in socket:
                if isinstance(message, str) and json.loads(message).get("type") == "stream.stop":
                    # Stay connected while omitting the required drain receipt.
                    for _ in socket:
                        pass
                    return

        with serve(never_close_event, "127.0.0.1", 0, origins=[MODULE.ORIGIN]) as fake:
            thread = threading.Thread(target=fake.serve_forever, daemon=True)
            thread.start()
            self.state.ws_port = fake.socket.getsockname()[1]
            result = self.run_replay(duration_seconds=0.1, stop_timeout_seconds=0.05)
            fake.shutdown()
            thread.join(timeout=2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["framesSent"], 1)
        self.assertTrue(any("drain timeout" in error for error in result["errors"]))
        self.assertIn("finalizeSkipped", result)
        self.assertGreater(self.state.sessions.get_recording(result["sessionId"])["audioBytes"], 0)


if __name__ == "__main__":
    unittest.main()

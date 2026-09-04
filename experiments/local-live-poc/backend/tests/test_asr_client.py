from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from backend.asr_client import AsrError, MlxAudioWebSocketClient


class MlxAudioWebSocketClientTest(unittest.TestCase):
    def test_transcribe_collects_provider_finals(self) -> None:
        configurations = []
        received_audio = []

        def handler(connection) -> None:
            configuration = json.loads(connection.recv(timeout=2))
            configurations.append(configuration)
            connection.send(json.dumps({"status": "ready"}))
            try:
                audio = [connection.recv(timeout=2) for _ in range(2)]
            except ConnectionClosed:
                return
            received_audio.extend(audio)
            connection.send(json.dumps({"is_partial": True, "text": "Grace"}))
            connection.send(json.dumps({"is_partial": False, "text": "Grace leads us."}))

        server = serve(handler, "127.0.0.1", 0)
        port = server.socket.getsockname()[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                model = Path(temporary) / "qwen"
                model.mkdir()
                (model / "model.safetensors").write_bytes(b"test-weights")
                client = MlxAudioWebSocketClient(
                    str(model),
                    f"ws://127.0.0.1:{port}/v1/audio/transcriptions/realtime",
                    finalize_silence_frames=1,
                    finalize_frame_interval_seconds=0,
                )
                self.assertFalse(client.status()["available"])
                self.assertTrue(client.warmup()["ready"])
                self.assertTrue(client.status()["available"])
                result = client.transcribe(bytes(32000))
                self.assertEqual(result["sourceTextEn"], "Grace leads us.")
                self.assertEqual(result["finalEventCount"], 1)
                self.assertEqual(result["finalizationMode"], "vad_silence_frames")
                self.assertEqual(len(configurations), 2)
                self.assertTrue(all(item["model"] == str(model.resolve()) for item in configurations))
                self.assertEqual(len(received_audio[0]), 32000)
                self.assertEqual(len(received_audio[1]), 960)
        finally:
            server.shutdown()
            thread.join(timeout=2)

    def test_failed_model_handshake_keeps_provider_unavailable(self) -> None:
        def handler(connection) -> None:
            connection.recv(timeout=2)
            connection.send(json.dumps({"status": "error", "message": "model load failed"}))

        server = serve(handler, "127.0.0.1", 0)
        port = server.socket.getsockname()[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                model = Path(temporary) / "qwen"
                model.mkdir()
                (model / "model.safetensors").write_bytes(b"test-weights")
                client = MlxAudioWebSocketClient(
                    str(model),
                    f"ws://127.0.0.1:{port}/v1/audio/transcriptions/realtime",
                )
                with self.assertRaises(AsrError):
                    client.warmup()
                status = client.status()
                self.assertFalse(status["available"])
                self.assertFalse(status["warmup"]["ready"])
        finally:
            server.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

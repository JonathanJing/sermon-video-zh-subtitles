from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from websockets.sync.server import serve

from backend.asr_client import MlxAudioWebSocketClient


class MlxAudioWebSocketClientTest(unittest.TestCase):
    def test_transcribe_collects_provider_finals(self) -> None:
        received = []

        def handler(connection) -> None:
            configuration = json.loads(connection.recv(timeout=2))
            received.append(configuration)
            connection.send(json.dumps({"status": "ready"}))
            received.append(connection.recv(timeout=2))
            received.append(connection.recv(timeout=2))
            received.append(connection.recv(timeout=2))
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
                )
                self.assertTrue(client.status()["available"])
                result = client.transcribe(bytes(32000))
                self.assertEqual(result["sourceTextEn"], "Grace leads us.")
                self.assertEqual(result["finalEventCount"], 1)
                self.assertEqual(received[0]["model"], str(model.resolve()))
                self.assertEqual(len(received[1]), 32000)
                self.assertEqual(len(received[2]), 128000)
                self.assertEqual(len(received[3]), 960)
        finally:
            server.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

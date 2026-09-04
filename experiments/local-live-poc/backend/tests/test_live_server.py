from __future__ import annotations

import json
import struct
import tempfile
import unittest

from websockets.sync.client import connect

from backend.gateway import GatewayState
from backend.live_server import LiveSocketService


class FakeAsr:
    def status(self):
        return {"available": True, "provider": "fake-asr"}

    def transcribe(self, pcm, sample_rate_hz=16000):
        return {"sourceTextEn": "Grace leads us.", "latencyMs": 1}


class LiveServerTest(unittest.TestCase):
    def test_websocket_pcm_reaches_caption_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = GatewayState(session_root=temporary)
            state.asr = FakeAsr()
            state.translate = lambda source, cursor, policy: {
                "targetTextZh": "恩典引领我们。",
                "model": "fake-model",
                "alignment": {"confidence": "none"},
            }
            def translate_stream(source, cursor, policy, on_partial):
                on_partial("恩典", "恩典")
                on_partial("引领我们。", "恩典引领我们。")
                return state.translate(source, cursor, policy)
            state.translate_stream = translate_stream
            session = state.sessions.create({"audioMimeType": "audio/webm"})
            service = LiveSocketService(state, "127.0.0.1", 0)
            port = service.server.socket.getsockname()[1]
            service.start()
            try:
                events = []
                with connect(
                    f"ws://127.0.0.1:{port}/api/live",
                    origin="http://127.0.0.1:4173",
                ) as socket:
                    socket.send(json.dumps({
                        "type": "stream.start",
                        "sessionId": session["sessionId"],
                        "contextPolicy": "none",
                        "encoding": "pcm_s16le",
                        "sampleRateHz": 16000,
                        "channels": 1,
                        "frameDurationMs": 100,
                    }))
                    events.append(json.loads(socket.recv(timeout=2)))
                    speech = struct.pack("<1600h", *([1000] * 1600))
                    silence = bytes(3200)
                    for sequence in range(1, 5):
                        socket.send(struct.pack(">I", sequence) + speech)
                    for sequence in range(5, 12):
                        socket.send(struct.pack(">I", sequence) + silence)
                    socket.send(json.dumps({"type": "stream.stop"}))
                    while events[-1]["type"] != "stream.closed":
                        events.append(json.loads(socket.recv(timeout=5)))
                types = [event["type"] for event in events]
                self.assertIn("asr.final", types)
                self.assertIn("translation.partial", types)
                self.assertIn("translation.final", types)
                translated = next(event for event in events if event["type"] == "translation.final")
                self.assertEqual(translated["targetTextZh"], "恩典引领我们。")
            finally:
                service.stop()


if __name__ == "__main__":
    unittest.main()

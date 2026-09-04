"""Model-free fault injection through real PCM/VAD workers and Gateway health."""
from __future__ import annotations

import json
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from backend.gateway import GatewayState, create_server
from backend.live_pipeline import LivePipeline


SPEECH_FRAME = struct.pack("<1600h", *([1000] * 1600))
RECOVERY_BYTES = b"opaque-independent-browser-recovery-recording"


class ControlledAsr:
    def __init__(self, no_final_reason="timeout"):
        self.no_final_reason = no_final_reason
        self.source_text = ""
        self.calls = 0

    def status(self):
        return {"available": True, "provider": "health-test-asr"}

    def transcribe(self, pcm, sample_rate_hz=16000):
        self.calls += 1
        return {
            "sourceTextEn": self.source_text,
            "noFinalReason": None if self.source_text else self.no_final_reason,
            "provider": "health-test-asr", "latencyMs": 1,
        }


class LiveHealthTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = GatewayState(session_root=self.temporary.name)
        self.asr = ControlledAsr()
        self.state.asr = self.asr
        self.state.ollama.status = lambda: {"configuredModelInstalled": True}
        self.session = self.state.create_session({
            "audioMimeType": "audio/webm", "mode": "local_live_asr_translation",
        })
        self.state.sessions.append_audio(self.session["sessionId"], 1, RECOVERY_BYTES)
        self.events = []
        self.pipeline = LivePipeline(
            self.session["sessionId"], self.state.sessions, self.asr,
            lambda *args: {"targetTextZh": "恩典带领我们。", "metrics": {}},
            self.events.append, vad_threshold_rms=450, vad_max_segment_ms=1000,
        )
        self.addCleanup(self.pipeline.stop)
        self.state.live_pipelines[self.session["sessionId"]] = self.pipeline
        self.pipeline.start()
        self.server = create_server("127.0.0.1", 0, self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def health(self):
        with urlopen(f"http://127.0.0.1:{self.server.server_port}/api/health", timeout=2) as response:
            return json.load(response)

    def wait_for_asr(self):
        deadline = time.monotonic() + 2
        while self.pipeline.asr_work.unfinished_tasks:
            if time.monotonic() >= deadline:
                self.fail("fake ASR worker did not finish within 2 seconds")
            time.sleep(0.001)

    def assert_recordings_preserved(self, frame_count):
        session = self.state.sessions.get_recording(self.session["sessionId"])
        self.assertEqual(session["pcmFrameCount"], frame_count)
        self.assertEqual(Path(session["asrPcmPath"]).read_bytes(), SPEECH_FRAME * frame_count)
        self.assertEqual(Path(session["audioPath"]).read_bytes(), RECOVERY_BYTES)
        self.assertFalse(self.pipeline.storage_failed)

    def test_three_timeout_results_degrade_gateway_and_valid_final_recovers(self):
        self.assertEqual(self.health()["status"], "ready")
        for segment in range(3):
            for sequence in range(segment * 10 + 1, segment * 10 + 11):
                self.pipeline.process_frame(sequence, SPEECH_FRAME)
            self.wait_for_asr()
            self.assertEqual(self.state.live_health()["degraded"], segment == 2)
        degraded = self.health()
        self.assertEqual(degraded["status"], "degraded")
        progress = degraded["liveProgress"]["streams"][0]
        self.assertEqual(progress["reason"], "consecutive_no_final")
        self.assertEqual(progress["consecutiveNoFinal"], 3)
        empty = [event for event in self.events if event["type"] == "asr.empty"]
        self.assertEqual(len(empty), 3)
        self.assertTrue(all(event["asrMetrics"]["noFinalReason"] == "timeout" for event in empty))
        self.assert_recordings_preserved(30)

        self.asr.source_text = "Grace leads us through the truth."
        for sequence in range(31, 41):
            self.pipeline.process_frame(sequence, SPEECH_FRAME)
        self.wait_for_asr()
        self.assertEqual(self.health()["status"], "ready")
        self.assertFalse(self.state.live_health()["degraded"])
        self.assertEqual(self.pipeline.consecutive_no_final, 0)
        self.assertEqual(sum(event["type"] == "asr.recovered" for event in self.events), 1)
        finals = [event for event in self.events if event["type"] == "asr.final"]
        self.assertEqual([event["sourceTextEn"] for event in finals], [self.asr.source_text])
        self.assert_recordings_preserved(40)

    def test_continuous_voice_without_finals_trips_watchdog_and_preserves_pcm(self):
        # Empty non-timeout results do not increment the three-timeout counter;
        # ongoing voice must independently trip the 12-second progress watchdog.
        self.asr.no_final_reason = "no_speech"
        with patch("backend.live_pipeline.time.perf_counter", return_value=100.0) as clock:
            for sequence in range(1, 122):
                clock.return_value = 100.0 + (sequence - 1) / 10
                self.pipeline.process_frame(sequence, SPEECH_FRAME)
                if sequence % 10 == 0:
                    self.wait_for_asr()
            self.assertFalse(self.state.live_health()["degraded"])
            clock.return_value = 112.1
            self.pipeline.process_frame(122, SPEECH_FRAME)
            health = self.health()
            self.assertEqual(health["status"], "degraded")
            self.assertEqual(health["liveProgress"]["streams"][0]["reason"], "speech_without_final")
            self.assertEqual(self.pipeline.consecutive_no_final, 0)
            self.assertIn("asr.degraded", [event["type"] for event in self.events])

            self.asr.source_text = "Mercy gives us a new beginning."
            for sequence in range(123, 131):
                clock.return_value = 100.0 + (sequence - 1) / 10
                self.pipeline.process_frame(sequence, SPEECH_FRAME)
            self.wait_for_asr()
            self.assertEqual(self.health()["status"], "ready")
            self.assertIn("asr.recovered", [event["type"] for event in self.events])
            self.assert_recordings_preserved(130)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.live_pipeline import (
    EnergyVad,
    LivePipeline,
    PCM_BYTES_PER_FRAME,
    SpeechSegment,
    is_non_speech_label,
)
from backend.session_store import SessionStore


def frame(amplitude: int) -> bytes:
    return struct.pack("<1600h", *([amplitude] * 1600))


class FakeAsr:
    def __init__(self, text="For God so loved the world."):
        self.text = text

    def status(self):
        return {"available": True, "provider": "fake-asr"}

    def transcribe(self, pcm, sample_rate_hz=16000):
        return {
            "sourceTextEn": self.text,
            "provider": "fake-asr",
            "latencyMs": 12,
            "audioDurationMs": len(pcm) // 32,
        }


class LivePipelineTest(unittest.TestCase):
    def test_non_speech_labels_are_detected_without_matching_normal_speech(self) -> None:
        for text in ("[BLANK_AUDIO]", "(birds chirping)", "(chimes)", "[music]"):
            self.assertTrue(is_non_speech_label(text))
        self.assertFalse(is_non_speech_label("The birds are chirping outside."))

    def test_vad_emits_after_speech_and_silence(self) -> None:
        vad = EnergyVad(threshold_rms=450, silence_frames=3, min_speech_frames=2)
        self.assertIsNone(vad.feed(1, frame(0)))
        self.assertIsNone(vad.feed(2, frame(1000)))
        self.assertIsNone(vad.feed(3, frame(1000)))
        self.assertIsNone(vad.feed(4, frame(0)))
        self.assertIsNone(vad.feed(5, frame(0)))
        segment = vad.feed(6, frame(0))
        self.assertIsNotNone(segment)
        self.assertEqual(segment.start_sequence, 1)
        self.assertEqual(segment.end_sequence, 6)

    def test_pipeline_persists_pcm_asr_and_translation_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sessions = SessionStore(temporary)
            created = sessions.create({"audioMimeType": "audio/webm"})
            sent = []

            def translate(source_text, cursor_sequence, context_policy):
                return {
                    "targetTextZh": "神爱世人。",
                    "model": "fake-milmmt",
                    "promptVersion": "test-v1",
                    "contextPolicy": "none",
                    "contextHitIds": [],
                    "alignment": {"confidence": "none"},
                    "metrics": {},
                }

            pipeline = LivePipeline(
                created["sessionId"],
                sessions,
                FakeAsr(),
                translate,
                sent.append,
                vad_threshold_rms=450,
            )
            pipeline.start()
            for sequence in range(1, 5):
                pipeline.process_frame(sequence, frame(1000))
            for sequence in range(5, 12):
                pipeline.process_frame(sequence, frame(0))
            pipeline.stop()

            types = [event["type"] for event in sent]
            self.assertIn("asr.final", types)
            self.assertIn("translation.final", types)
            self.assertEqual(types[-1], "stream.closed")
            manifest = json.loads((Path(created["directory"]) / "manifest.json").read_text())
            self.assertEqual(manifest["pcmFrameCount"], 11)
            persisted = [json.loads(line)["type"] for line in (Path(created["directory"]) / "events.jsonl").read_text().splitlines()]
            self.assertEqual(persisted, types)

    def test_non_speech_asr_result_is_logged_but_not_translated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sessions = SessionStore(temporary)
            created = sessions.create({"audioMimeType": "audio/webm"})
            sent = []
            translated = []

            def translate(source_text, cursor_sequence, context_policy):
                translated.append(source_text)
                return {"targetTextZh": "不应调用"}

            pipeline = LivePipeline(
                created["sessionId"],
                sessions,
                FakeAsr("[BLANK_AUDIO]"),
                translate,
                sent.append,
                vad_threshold_rms=450,
            )
            for sequence in range(1, 5):
                pipeline.process_frame(sequence, frame(1000))
            for sequence in range(5, 12):
                pipeline.process_frame(sequence, frame(0))
            pipeline.stop()

            types = [event["type"] for event in sent]
            self.assertIn("asr.suppressed", types)
            self.assertNotIn("asr.final", types)
            self.assertNotIn("translation.final", types)
            self.assertEqual(translated, [])

    def test_slow_translation_does_not_block_following_asr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sessions = SessionStore(temporary)
            created = sessions.create({"audioMimeType": "audio/webm"})
            sent = []
            translation_started = threading.Event()
            release_translation = threading.Event()

            def translate(source_text, cursor_sequence, context_policy):
                translation_started.set()
                release_translation.wait(timeout=2)
                return {"targetTextZh": "翻译", "alignment": {"confidence": "none"}}

            pipeline = LivePipeline(created["sessionId"], sessions, FakeAsr(), translate, sent.append)
            segment_one = SpeechSegment("seg-000001", 1, 4, frame(1000) * 4)
            segment_two = SpeechSegment("seg-000002", 5, 8, frame(1000) * 4)
            pipeline._enqueue_asr(segment_one)
            self.assertTrue(translation_started.wait(timeout=1))
            pipeline._enqueue_asr(segment_two)

            deadline = time.time() + 1
            while time.time() < deadline and not any(
                event["type"] == "asr.final" and event["segmentId"] == "seg-000002"
                for event in sent
            ):
                time.sleep(0.01)
            self.assertTrue(any(
                event["type"] == "asr.final" and event["segmentId"] == "seg-000002"
                for event in sent
            ))
            release_translation.set()
            closed = pipeline.stop()
            self.assertTrue(closed["workerDrained"])

    def test_pcm_storage_failure_is_visible_but_does_not_crash_pipeline(self) -> None:
        class FailingPcmStore(SessionStore):
            def append_pcm_frames(self, *args, **kwargs):
                raise OSError("disk full")

        with tempfile.TemporaryDirectory() as temporary:
            sessions = FailingPcmStore(temporary)
            created = sessions.create({"audioMimeType": "audio/webm"})
            sent = []
            pipeline = LivePipeline(
                created["sessionId"],
                sessions,
                FakeAsr(),
                lambda *args: {"targetTextZh": "翻译", "alignment": {"confidence": "none"}},
                sent.append,
            )
            for sequence in range(1, 11):
                pipeline.process_frame(sequence, frame(1000))
            closed = pipeline.stop()
            self.assertIn("storage.failed", [event["type"] for event in sent])
            self.assertFalse(closed["storageHealthy"])

    def test_event_persistence_failure_marks_stream_close_unhealthy(self) -> None:
        class FailingEventStore(SessionStore):
            def append_event(self, *args, **kwargs):
                raise OSError("events unavailable")

        with tempfile.TemporaryDirectory() as temporary:
            sessions = FailingEventStore(temporary)
            created = sessions.create({"audioMimeType": "audio/webm"})
            sent = []
            pipeline = LivePipeline(
                created["sessionId"],
                sessions,
                FakeAsr(),
                lambda *args: {"targetTextZh": "翻译", "alignment": {"confidence": "none"}},
                sent.append,
            )
            pipeline.start()
            closed = pipeline.stop()
            self.assertFalse(closed["storageHealthy"])
            self.assertTrue(closed["persistenceFailed"])


if __name__ == "__main__":
    unittest.main()

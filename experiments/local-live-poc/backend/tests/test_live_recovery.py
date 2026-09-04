from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from websockets.sync.client import connect

from backend.gateway import GatewayState
from backend.live_server import LiveSocketService
from backend.session_store import SessionStore, SessionStoreError


LIVE_METADATA = {"audioMimeType": "audio/webm", "mode": "local_live_asr_translation"}
SPEECH = struct.pack("<1600h", *([1000] * 1600))
SILENCE = bytes(3200)
# Opaque recovery bytes: these tests verify concatenation and hashes, not codec
# validity. Real browser/WebM decode evidence belongs to the separate audio E2E.
RECORDING_CHUNKS = (b"\x1a\x45\xdf\xa3-original-recording", b"-chunk-2", b"-chunk-3")


class FakeAsr:
    def status(self):
        return {"available": True, "provider": "recovery-test-asr"}

    def transcribe(self, pcm, sample_rate_hz=16000):
        return {"sourceTextEn": "Grace leads us through the truth.", "latencyMs": 1}


def read_events(session: dict) -> list[dict]:
    return [json.loads(line) for line in Path(session["eventPath"]).read_text(encoding="utf-8").splitlines()]


def append_ready_and_closed(store: SessionStore, session_id: str, frame_count: int, **closed_fields) -> None:
    store.append_event(session_id, {"type": "stream.ready"}, assign_sequence=True)
    store.append_event(session_id, {
        "type": "stream.closed", "lastFrameSequence": frame_count,
        "workerDrained": True, "asrWorkerDrained": True,
        "translationWorkerDrained": True, "storageHealthy": True,
        **closed_fields,
    }, assign_sequence=True)


class LiveRecoveryStoreTest(unittest.TestCase):
    def test_gateway_restart_resume_preserves_original_recording_and_recovery_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            before_restart = SessionStore(temporary)
            session = before_restart.create(LIVE_METADATA)
            session_id = session["sessionId"]
            before_restart.append_audio(session_id, 1, RECORDING_CHUNKS[0])
            before_restart.append_pcm_frames(session_id, 1, 2, SPEECH + SILENCE)
            before_restart.append_event(session_id, {"type": "stream.ready"}, assign_sequence=True)

            after_restart = SessionStore(temporary)
            recovered = after_restart.recover_incomplete()[0]
            self.assertEqual(recovered["status"], "incomplete")
            self.assertEqual(recovered["recoveryReason"], "gateway_restart_before_finalize")
            resumed = after_restart.resume(session_id, available_audio_chunks=3)
            self.assertEqual(resumed["status"], "recording")
            self.assertEqual(resumed["viewerToken"], session["viewerToken"])
            self.assertEqual(resumed["audioChunkCount"], 1)
            self.assertEqual(resumed["pcmFrameCount"], 2)
            self.assertEqual(Path(session["audioPath"]).read_bytes(), RECORDING_CHUNKS[0])
            snapshot_path = Path(session["directory"]) / "recovery-0001.manifest.json"
            snapshot_bytes = snapshot_path.read_bytes()
            snapshot = json.loads(snapshot_bytes)
            self.assertEqual(snapshot["status"], "incomplete")
            self.assertEqual(snapshot["audioSha256"], hashlib.sha256(RECORDING_CHUNKS[0]).hexdigest())

            for sequence, chunk in enumerate(RECORDING_CHUNKS[1:], 2):
                after_restart.append_audio(session_id, sequence, chunk)
            after_restart.append_pcm_frames(session_id, 3, 1, SPEECH)
            append_ready_and_closed(after_restart, session_id, 3)
            completed = after_restart.finalize(session_id, {"durationMs": 3000})
            expected_recording = b"".join(RECORDING_CHUNKS)
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["liveOutcome"]["captionContinuity"], "interrupted")
            self.assertEqual(Path(session["audioPath"]).read_bytes(), expected_recording)
            self.assertEqual(completed["audioSha256"], hashlib.sha256(expected_recording).hexdigest())
            self.assertEqual(completed["pcmSha256"], hashlib.sha256(SPEECH + SILENCE + SPEECH).hexdigest())
            self.assertEqual(snapshot_path.read_bytes(), snapshot_bytes)

    def test_resume_retries_after_snapshot_saved_but_manifest_write_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SessionStore(temporary)
            session = store.create(LIVE_METADATA)
            session_id = session["sessionId"]
            store.append_audio(session_id, 1, RECORDING_CHUNKS[0])
            store.append_pcm_frames(session_id, 1, 1, SPEECH)
            store.recover_incomplete()
            manifest_before = Path(session["manifestPath"]).read_bytes()
            with patch.object(store, "_write_manifest", side_effect=OSError("temporary manifest write failure")):
                with self.assertRaisesRegex(OSError, "temporary manifest write failure"):
                    store.resume(session_id, 1)
            snapshot_path = Path(session["directory"]) / "recovery-0001.manifest.json"
            snapshot_before = snapshot_path.read_bytes()
            self.assertEqual(Path(session["manifestPath"]).read_bytes(), manifest_before)

            # A fresh store models retry after Gateway/process recovery, with
            # no in-memory state available to repair the interrupted attempt.
            resumed = SessionStore(temporary).resume(session_id, 1)
            self.assertEqual(resumed["status"], "recording")
            self.assertEqual(resumed["resumeCount"], 1)
            self.assertEqual(resumed["viewerToken"], session["viewerToken"])
            self.assertEqual(resumed["recoverySnapshotFile"], snapshot_path.name)
            self.assertEqual(snapshot_path.read_bytes(), snapshot_before)
            self.assertEqual(len(list(Path(session["directory"]).glob("recovery-*.manifest.json"))), 1)
            self.assertEqual(Path(session["audioPath"]).read_bytes(), RECORDING_CHUNKS[0])
            self.assertEqual(Path(session["asrPcmPath"]).read_bytes(), SPEECH)

    def test_resume_preserves_torn_or_conflicting_snapshot_and_records_new_snapshot(self) -> None:
        for previous_bytes in (b'{"status":', b'{"status":"different-prior-evidence"}'):
            with self.subTest(previous_bytes=previous_bytes), tempfile.TemporaryDirectory() as temporary:
                store = SessionStore(temporary)
                session = store.create(LIVE_METADATA)
                session_id = session["sessionId"]
                store.append_audio(session_id, 1, RECORDING_CHUNKS[0])
                store.append_pcm_frames(session_id, 1, 1, SPEECH)
                store.recover_incomplete()
                manifest_before = json.loads(Path(session["manifestPath"]).read_text())
                directory = Path(session["directory"])
                previous_snapshot = directory / "recovery-0001.manifest.json"
                previous_snapshot.write_bytes(previous_bytes)

                resumed = store.resume(session_id, 1)
                new_snapshot = directory / resumed["recoverySnapshotFile"]
                self.assertNotEqual(new_snapshot, previous_snapshot)
                self.assertEqual(previous_snapshot.read_bytes(), previous_bytes)
                self.assertEqual(json.loads(new_snapshot.read_text()), manifest_before)
                self.assertEqual(len(list(directory.glob("recovery-*.manifest.json"))), 2)
                self.assertEqual(resumed["resumeCount"], 1)
                self.assertEqual(resumed["viewerToken"], session["viewerToken"])
                self.assertEqual(Path(session["audioPath"]).read_bytes(), RECORDING_CHUNKS[0])
                self.assertEqual(Path(session["asrPcmPath"]).read_bytes(), SPEECH)

    def test_completed_or_unrecoverable_session_cannot_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SessionStore(temporary)
            completed = store.create({"audioMimeType": "audio/webm"})
            store.finalize(completed["sessionId"], {"durationMs": 0})
            with self.assertRaises(SessionStoreError):
                store.resume(completed["sessionId"], 0)
            incomplete = store.create(LIVE_METADATA)
            store.finalize(incomplete["sessionId"], {"status": "incomplete"})
            with self.assertRaises(SessionStoreError):
                store.resume(incomplete["sessionId"], 0)
            self.assertEqual(list(Path(temporary).glob("*/recovery-*.manifest.json")), [])

    def test_insufficient_browser_chunks_and_torn_durable_files_fail_without_mutation(self) -> None:
        for corruption in ("browser_missing_chunks", "audio_size", "pcm_size", "event_count", "event_json"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                store = SessionStore(temporary)
                session = store.create(LIVE_METADATA)
                session_id = session["sessionId"]
                store.append_audio(session_id, 1, RECORDING_CHUNKS[0])
                store.append_pcm_frames(session_id, 1, 1, SPEECH)
                store.append_event(session_id, {"type": "stream.ready"}, assign_sequence=True)
                store.recover_incomplete()
                if corruption in {"audio_size", "pcm_size"}:
                    path = Path(session["audioPath"] if corruption == "audio_size" else session["asrPcmPath"])
                    with path.open("ab") as output:
                        output.write(b"torn-append")
                elif corruption in {"event_count", "event_json"}:
                    with Path(session["eventPath"]).open("a", encoding="utf-8") as output:
                        output.write('{"type":"uncommitted_event"}\n' if corruption == "event_count" else '{"type":')
                manifest_before = Path(session["manifestPath"]).read_bytes()
                audio_before = Path(session["audioPath"]).read_bytes()
                pcm_before = Path(session["asrPcmPath"]).read_bytes()
                with self.assertRaises(SessionStoreError):
                    store.resume(session_id, available_audio_chunks=0 if corruption == "browser_missing_chunks" else 1)
                self.assertEqual(Path(session["manifestPath"]).read_bytes(), manifest_before)
                self.assertEqual(Path(session["audioPath"]).read_bytes(), audio_before)
                self.assertEqual(Path(session["asrPcmPath"]).read_bytes(), pcm_before)
                self.assertEqual(list(Path(session["directory"]).glob("recovery-*.manifest.json")), [])

    def test_live_finalize_needs_pcm_and_current_healthy_drain(self) -> None:
        for case in ("no_socket", "no_pcm", "no_drain", "storage_unhealthy", "worker_not_drained", "wrong_frame_count"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                store = SessionStore(temporary)
                session = store.create(LIVE_METADATA)
                session_id = session["sessionId"]
                store.append_audio(session_id, 1, RECORDING_CHUNKS[0])
                if case != "no_pcm":
                    store.append_pcm_frames(session_id, 1, 1, SPEECH)
                if case not in {"no_socket", "no_drain"}:
                    append_ready_and_closed(
                        store, session_id, 2 if case == "wrong_frame_count" else 1,
                        storageHealthy=case != "storage_unhealthy", workerDrained=case != "worker_not_drained",
                    )
                elif case == "no_drain":
                    store.append_event(session_id, {"type": "stream.ready"}, assign_sequence=True)
                finalized = store.finalize(session_id, {"status": "completed", "durationMs": 1000})
                self.assertEqual(finalized["status"], "incomplete")
                self.assertFalse(finalized["liveOutcome"]["drainConfirmed"])
                self.assertEqual(Path(session["audioPath"]).read_bytes(), RECORDING_CHUNKS[0])

    def test_resume_cannot_reuse_a_previous_socket_drain_for_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SessionStore(temporary)
            session = store.create(LIVE_METADATA)
            session_id = session["sessionId"]
            store.append_audio(session_id, 1, RECORDING_CHUNKS[0])
            store.append_pcm_frames(session_id, 1, 1, SPEECH)
            append_ready_and_closed(store, session_id, 1)
            store.resume(session_id, available_audio_chunks=1)
            # Restoring browser state does not prove its new socket connected or drained.
            finalized = store.finalize(session_id, {"status": "completed", "durationMs": 1000})
            self.assertEqual(finalized["status"], "incomplete")
            self.assertFalse(finalized["liveOutcome"]["drainConfirmed"])


class LiveRecoverySocketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.services: list[LiveSocketService] = []
        self.state = self.make_state()
        self.service, self.url = self.make_service(self.state)

    def tearDown(self) -> None:
        for service in reversed(self.services):
            service.stop()
        self.temporary.cleanup()

    def make_state(self) -> GatewayState:
        # Do not create a cloud publisher from the operator's configured environment.
        with patch("backend.gateway.FirebasePublisherConfig.from_environment", return_value=None):
            state = GatewayState(session_root=self.temporary.name)
        state.asr = FakeAsr()
        state.ollama.status = lambda: {"available": True, "version": "fake", "configuredModel": "recovery-test"}
        state.translate = lambda source, cursor, policy: {
            "sourceTextEn": source, "targetTextZh": "恩典引领我们认识真理。",
            "model": "recovery-test-model", "alignment": {"confidence": "none"},
        }
        state.translate_stream = lambda source, cursor, policy, on_partial: state.translate(source, cursor, policy)
        return state

    def make_service(self, state: GatewayState) -> tuple[LiveSocketService, str]:
        service = LiveSocketService(state, "127.0.0.1", 0)
        self.services.append(service)
        service.start()
        return service, f"ws://127.0.0.1:{service.server.socket.getsockname()[1]}/api/live"

    def start_stream(self, socket, session_id: str) -> dict:
        socket.send(json.dumps({
            "type": "stream.start", "sessionId": session_id, "contextPolicy": "none",
            "encoding": "pcm_s16le", "sampleRateHz": 16000, "channels": 1, "frameDurationMs": 100,
        }))
        return json.loads(socket.recv(timeout=3))

    def receive_until(self, socket, event_type: str) -> list[dict]:
        result = []
        for _ in range(50):
            event = json.loads(socket.recv(timeout=3))
            result.append(event)
            if event["type"] == event_type:
                return result
        self.fail(f"did not receive {event_type}")

    def wait_released(self, state: GatewayState, session_id: str) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with state.live_lock:
                if session_id not in state.live_pipelines:
                    return
            time.sleep(0.01)
        self.fail("socket pipeline remained registered after disconnect/drain")

    def test_restart_reconnect_uses_durable_pcm_position_unique_ids_and_same_viewer_token(self) -> None:
        session = self.state.create_session(LIVE_METADATA)
        session_id = session["sessionId"]
        self.state.sessions.append_audio(session_id, 1, RECORDING_CHUNKS[0])
        with connect(self.url, origin="http://127.0.0.1:4173") as first_socket:
            first_ready = self.start_stream(first_socket, session_id)
            self.assertEqual(first_ready["type"], "stream.ready")
            for sequence in range(1, 12):
                first_socket.send(struct.pack(">I", sequence) + (SPEECH if sequence < 5 else SILENCE))
            first_events = self.receive_until(first_socket, "translation.final")
            first_segment = next(event["segmentId"] for event in first_events if event["type"] == "asr.final")
            # Close the real transport without a stream.stop control message.
        self.wait_released(self.state, session_id)
        durable = self.state.sessions.get_recording(session_id)
        self.assertEqual(durable["pcmFrameCount"], 11)
        pcm_before = Path(session["asrPcmPath"]).read_bytes()
        self.service.stop()
        self.services.remove(self.service)

        restarted = self.make_state()
        restarted.sessions.recover_incomplete()
        resumed = restarted.resume_session(session_id, {"availableAudioChunks": 2, "pcmFrameSequence": 13})
        self.assertEqual(resumed["pcmFrameCount"], 11)
        self.assertEqual(resumed["viewerToken"], durable["viewerToken"])
        restarted.sessions.append_audio(session_id, 2, RECORDING_CHUNKS[1])
        _, resumed_url = self.make_service(restarted)
        with connect(resumed_url, origin="http://127.0.0.1:4173") as second_socket:
            second_ready = self.start_stream(second_socket, session_id)
            self.assertEqual(second_ready["type"], "stream.ready")
            self.assertEqual(second_ready["viewer"]["token"], first_ready["viewer"]["token"])
            # Two disconnected PCM frames are logged as a gap and padded with
            # silence; the independent MediaRecorder recovery bytes stay intact.
            for sequence in range(14, 25):
                second_socket.send(struct.pack(">I", sequence) + (SPEECH if sequence < 18 else SILENCE))
            second_socket.send(json.dumps({"type": "stream.stop"}))
            second_events = self.receive_until(second_socket, "stream.closed")
        self.wait_released(restarted, session_id)
        second_segment = next(event["segmentId"] for event in second_events if event["type"] == "asr.final")
        self.assertNotEqual(first_segment, second_segment)
        self.assertGreater(int(second_segment.split("-")[-1]), int(first_segment.split("-")[-1]))
        gap = next(event for event in second_events if event["type"] == "audio.stream_gap")
        self.assertEqual((gap["expectedSequence"], gap["receivedSequence"], gap["missingFrameCount"]), (12, 14, 2))
        closed = second_events[-1]
        self.assertTrue(closed["workerDrained"])
        self.assertTrue(closed["storageHealthy"])
        self.assertEqual(closed["lastFrameSequence"], 24)
        final = restarted.sessions.finalize(session_id, {"durationMs": 2400})
        self.assertEqual(final["status"], "completed")
        expected_pcm = pcm_before + SILENCE * 2 + SPEECH * 4 + SILENCE * 7
        self.assertEqual(Path(session["asrPcmPath"]).read_bytes(), expected_pcm)
        self.assertEqual(final["pcmSha256"], hashlib.sha256(expected_pcm).hexdigest())
        self.assertEqual(final["audioSha256"], hashlib.sha256(b"".join(RECORDING_CHUNKS[:2])).hexdigest())
        all_events = read_events(final)
        self.assertEqual([event["sequence"] for event in all_events], list(range(1, len(all_events) + 1)))
        segment_ids = [event["segmentId"] for event in all_events if event["type"] == "asr.final"]
        self.assertEqual(len(segment_ids), len(set(segment_ids)))
        self.assertEqual(final["eventCount"], len(all_events))
        self.assertEqual(final["liveOutcome"]["captionContinuity"], "interrupted")

    def test_second_active_socket_cannot_register_or_release_the_first(self) -> None:
        session = self.state.create_session(LIVE_METADATA)
        session_id = session["sessionId"]
        with connect(self.url, origin="http://127.0.0.1:4173") as first_socket:
            self.assertEqual(self.start_stream(first_socket, session_id)["type"], "stream.ready")
            with self.state.live_lock:
                original_pipeline = self.state.live_pipelines[session_id]
            with connect(self.url, origin="http://127.0.0.1:4173") as second_socket:
                duplicate = self.start_stream(second_socket, session_id)
                self.assertEqual(duplicate["type"], "stream.error")
                self.assertIn("active live stream", duplicate["message"])
            with self.state.live_lock:
                self.assertIs(self.state.live_pipelines[session_id], original_pipeline)
            with self.assertRaisesRegex(SessionStoreError, "draining"):
                self.state.resume_session(session_id, {"availableAudioChunks": 0})
            first_socket.send(json.dumps({"type": "stream.stop"}))
            self.receive_until(first_socket, "stream.closed")
        self.wait_released(self.state, session_id)

    def test_resume_rejects_invalid_browser_chunk_counter(self) -> None:
        session = self.state.create_session(LIVE_METADATA)
        for count in (None, True, -1, "1", 1.5):
            with self.subTest(count=count), self.assertRaises(SessionStoreError):
                self.state.resume_session(session["sessionId"], {"availableAudioChunks": count})

    def test_resume_pcm_counter_rejects_invalid_or_excessive_gap_without_mutation(self) -> None:
        for counter in (True, -1, "2", 1.5, 0, 3002):
            with self.subTest(counter=counter):
                session = self.state.create_session(LIVE_METADATA)
                self.state.sessions.append_pcm_frames(session["sessionId"], 1, 1, SPEECH)
                manifest_before = Path(session["manifestPath"]).read_bytes()
                with self.assertRaises(SessionStoreError):
                    self.state.resume_session(session["sessionId"], {
                        "availableAudioChunks": 0, "pcmFrameSequence": counter,
                    })
                self.assertEqual(Path(session["manifestPath"]).read_bytes(), manifest_before)

    def test_resume_pcm_counter_accepts_exact_five_minute_gap(self) -> None:
        session = self.state.create_session(LIVE_METADATA)
        self.state.sessions.append_pcm_frames(session["sessionId"], 1, 1, SPEECH)
        resumed = self.state.resume_session(session["sessionId"], {
            "availableAudioChunks": 0, "pcmFrameSequence": 3001,
        })
        self.assertEqual(resumed["status"], "recording")
        # Validation does not fabricate captured PCM. Missing frames are padded
        # and logged by the resumed live stream only when its next frame arrives.
        self.assertEqual(resumed["pcmFrameCount"], 1)


if __name__ == "__main__":
    unittest.main()

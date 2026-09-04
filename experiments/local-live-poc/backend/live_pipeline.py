from __future__ import annotations

import math
import queue
import re
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from .asr_client import AsrError, WhisperCliClient
from .ollama_client import OllamaError
from .session_store import SessionStore, SessionStoreError


SAMPLE_RATE_HZ = 16000
FRAME_DURATION_MS = 100
PCM_BYTES_PER_FRAME = 3200
SILENCE_FRAME = bytes(PCM_BYTES_PER_FRAME)
NON_SPEECH_LABEL_RE = re.compile(
    r"^(?:"
    r"\[(?:blank[_ ]audio|music|silence|chimes|applause|laughter|inaudible)\]"
    r"|\((?:blank[_ ]audio|music|silence|chimes|applause|laughter|inaudible|birds? chirping|crickets? chirping)\)"
    r")$",
    re.IGNORECASE,
)


def is_non_speech_label(text: str) -> bool:
    return bool(NON_SPEECH_LABEL_RE.fullmatch(" ".join(text.split())))


@dataclass(frozen=True)
class SpeechSegment:
    segment_id: str
    start_sequence: int
    end_sequence: int
    pcm: bytes

    @property
    def audio_start_ms(self) -> int:
        return (self.start_sequence - 1) * FRAME_DURATION_MS

    @property
    def audio_end_ms(self) -> int:
        return self.end_sequence * FRAME_DURATION_MS


@dataclass(frozen=True)
class TranslationTask:
    segment_id: str
    audio_start_ms: int
    audio_end_ms: int
    source_text: str


class EnergyVad:
    def __init__(
        self,
        threshold_rms: int = 150,
        silence_frames: int = 7,
        min_speech_frames: int = 3,
        max_segment_frames: int = 120,
        pre_roll_frames: int = 3,
    ) -> None:
        self.threshold_rms = threshold_rms
        self.silence_frames = silence_frames
        self.min_speech_frames = min_speech_frames
        self.max_segment_frames = max_segment_frames
        self.pre_roll: deque[tuple[int, bytes]] = deque(maxlen=pre_roll_frames)
        self.active: list[tuple[int, bytes]] = []
        self.speech_frame_count = 0
        self.trailing_silence_count = 0
        self.segment_counter = 0

    @staticmethod
    def rms(pcm: bytes) -> int:
        if len(pcm) != PCM_BYTES_PER_FRAME:
            raise ValueError(f"PCM frame must contain {PCM_BYTES_PER_FRAME} bytes")
        sample_count = len(pcm) // 2
        samples = struct.unpack(f"<{sample_count}h", pcm)
        energy = sum(sample * sample for sample in samples) / sample_count
        return round(math.sqrt(energy))

    def feed(self, sequence: int, pcm: bytes) -> SpeechSegment | None:
        is_speech = self.rms(pcm) >= self.threshold_rms
        if not self.active:
            self.pre_roll.append((sequence, pcm))
            if not is_speech:
                return None
            self.active = list(self.pre_roll)
            self.pre_roll.clear()
            self.speech_frame_count = 1
            self.trailing_silence_count = 0
            return None

        self.active.append((sequence, pcm))
        if is_speech:
            self.speech_frame_count += 1
            self.trailing_silence_count = 0
        else:
            self.trailing_silence_count += 1

        if (
            self.trailing_silence_count >= self.silence_frames
            or len(self.active) >= self.max_segment_frames
        ):
            return self._finish()
        return None

    def flush(self) -> SpeechSegment | None:
        return self._finish() if self.active else None

    def _finish(self) -> SpeechSegment | None:
        frames = self.active
        speech_frames = self.speech_frame_count
        self.active = []
        self.speech_frame_count = 0
        self.trailing_silence_count = 0
        if speech_frames < self.min_speech_frames:
            return None
        self.segment_counter += 1
        return SpeechSegment(
            segment_id=f"seg-{self.segment_counter:06d}",
            start_sequence=frames[0][0],
            end_sequence=frames[-1][0],
            pcm=b"".join(frame for _, frame in frames),
        )


class LivePipeline:
    def __init__(
        self,
        session_id: str,
        sessions: SessionStore,
        asr: WhisperCliClient,
        translate: Callable[[str, int | None, str], dict[str, Any]],
        send: Callable[[dict[str, Any]], None],
        context_policy: str = "none",
        vad_threshold_rms: int = 150,
    ) -> None:
        self.session_id = session_id
        self.sessions = sessions
        self.asr = asr
        self.translate = translate
        self.send = send
        self.context_policy = context_policy
        self.cursor_sequence: int | None = None
        self.vad = EnergyVad(threshold_rms=vad_threshold_rms)
        self.last_frame_sequence = 0
        self.pcm_batch: list[bytes] = []
        self.pcm_batch_start = 1
        self.asr_work: queue.Queue[SpeechSegment | None] = queue.Queue(maxsize=2)
        self.translation_work: queue.Queue[TranslationTask | None] = queue.Queue(maxsize=1)
        self.asr_worker = threading.Thread(target=self._run_asr_worker, daemon=True)
        self.translation_worker = threading.Thread(target=self._run_translation_worker, daemon=True)
        self.stopped = False
        self.aborting = False
        self.storage_failed = False
        self.asr_worker.start()
        self.translation_worker.start()

    def start(self) -> None:
        self._emit({
            "type": "stream.ready",
            "encoding": "pcm_s16le",
            "sampleRateHz": SAMPLE_RATE_HZ,
            "channels": 1,
            "frameDurationMs": FRAME_DURATION_MS,
            "asr": self.asr.status(),
        })

    def process_frame(self, sequence: int, pcm: bytes) -> None:
        if self.stopped:
            return
        if len(pcm) != PCM_BYTES_PER_FRAME:
            self._emit({"type": "audio.frame_rejected", "frameSequence": sequence, "reason": "invalid_size"})
            return
        if sequence <= self.last_frame_sequence:
            self._emit({"type": "audio.frame_rejected", "frameSequence": sequence, "reason": "out_of_order"})
            return
        missing = sequence - self.last_frame_sequence - 1
        if missing:
            self._emit({
                "type": "audio.stream_gap",
                "expectedSequence": self.last_frame_sequence + 1,
                "receivedSequence": sequence,
                "missingFrameCount": missing,
            })
            for gap_sequence in range(self.last_frame_sequence + 1, sequence):
                self._accept_frame(gap_sequence, SILENCE_FRAME)
        self._accept_frame(sequence, pcm)

    def stop(self) -> dict[str, Any]:
        if self.stopped:
            return {
                "type": "stream.closed",
                "lastFrameSequence": self.last_frame_sequence,
                "workerDrained": not self.asr_worker.is_alive() and not self.translation_worker.is_alive(),
            }
        self.stopped = True
        segment = self.vad.flush()
        if segment:
            self._enqueue_asr(segment)
        self._flush_pcm()
        try:
            self.asr_work.put(None, timeout=5)
        except queue.Full:
            self._emit({"type": "pipeline.failed", "reason": "asr_queue_did_not_drain"})
        self.asr_worker.join(timeout=35)
        asr_drained = not self.asr_worker.is_alive()
        if not asr_drained:
            self.aborting = True
            self._emit({"type": "pipeline.failed", "reason": "asr_worker_stop_timeout"})
        try:
            self.translation_work.put(None, timeout=20)
        except queue.Full:
            self._emit({"type": "pipeline.failed", "reason": "translation_queue_did_not_drain"})
        self.translation_worker.join(timeout=35)
        translation_drained = not self.translation_worker.is_alive()
        if not translation_drained:
            self._emit({"type": "pipeline.failed", "reason": "translation_worker_stop_timeout"})
        closed = {
            "type": "stream.closed",
            "lastFrameSequence": self.last_frame_sequence,
            "workerDrained": asr_drained and translation_drained,
            "asrWorkerDrained": asr_drained,
            "translationWorkerDrained": translation_drained,
            "storageHealthy": not self.storage_failed,
        }
        return self._emit(closed)

    def _accept_frame(self, sequence: int, pcm: bytes) -> None:
        if not self.storage_failed:
            if not self.pcm_batch:
                self.pcm_batch_start = sequence
            self.pcm_batch.append(pcm)
        self.last_frame_sequence = sequence
        if len(self.pcm_batch) >= 10:
            self._flush_pcm()
        segment = self.vad.feed(sequence, pcm)
        if segment:
            self._enqueue_asr(segment)

    def _flush_pcm(self) -> None:
        if not self.pcm_batch:
            return
        frames = self.pcm_batch
        self.pcm_batch = []
        try:
            self.sessions.append_pcm_frames(
                self.session_id,
                self.pcm_batch_start,
                len(frames),
                b"".join(frames),
            )
        except (OSError, SessionStoreError) as error:
            self.storage_failed = True
            self._emit({
                "type": "storage.failed",
                "stage": "pcm_append",
                "message": str(error),
                "recordingShouldContinue": True,
            })

    def _enqueue_asr(self, segment: SpeechSegment) -> None:
        event = {
            "type": "asr.processing",
            "segmentId": segment.segment_id,
            "audioStartMs": segment.audio_start_ms,
            "audioEndMs": segment.audio_end_ms,
        }
        try:
            self.asr_work.put_nowait(segment)
            self._emit(event)
        except queue.Full:
            self._emit({**event, "type": "asr.failed", "reason": "queue_full"})

    def _run_asr_worker(self) -> None:
        while True:
            segment = self.asr_work.get()
            if segment is None:
                self.asr_work.task_done()
                return
            try:
                self._process_asr(segment)
            except Exception as error:
                self._emit({
                    "type": "pipeline.failed",
                    "stage": "asr_worker",
                    "message": str(error),
                })
            finally:
                self.asr_work.task_done()

    def _process_asr(self, segment: SpeechSegment) -> None:
        common = {
            "segmentId": segment.segment_id,
            "audioStartMs": segment.audio_start_ms,
            "audioEndMs": segment.audio_end_ms,
        }
        try:
            result = self.asr.transcribe(segment.pcm, SAMPLE_RATE_HZ)
        except AsrError as error:
            self._emit({**common, "type": "asr.failed", "message": str(error)})
            return
        source_text = str(result.get("sourceTextEn") or "").strip()
        if not source_text:
            self._emit({**common, "type": "asr.empty", "asrMetrics": result})
            return
        if is_non_speech_label(source_text):
            self._emit({
                **common,
                "type": "asr.suppressed",
                "reason": "non_speech_label",
                "sourceTextEn": source_text,
                "asrMetrics": result,
            })
            return
        self._emit({
            **common,
            "type": "asr.final",
            "sourceTextEn": source_text,
            "asrMetrics": result,
        })
        task = TranslationTask(
            segment_id=segment.segment_id,
            audio_start_ms=segment.audio_start_ms,
            audio_end_ms=segment.audio_end_ms,
            source_text=source_text,
        )
        if self.aborting:
            self._emit({
                **common,
                "type": "translation.skipped",
                "sourceTextEn": source_text,
                "reason": "pipeline_stopping_after_timeout",
            })
            return
        try:
            self.translation_work.put_nowait(task)
        except queue.Full:
            self._emit({
                **common,
                "type": "translation.skipped",
                "sourceTextEn": source_text,
                "reason": "queue_full",
                "recordingShouldContinue": True,
            })

    def _run_translation_worker(self) -> None:
        while True:
            task = self.translation_work.get()
            if task is None:
                self.translation_work.task_done()
                return
            try:
                self._process_translation(task)
            except Exception as error:
                self._emit({
                    "type": "pipeline.failed",
                    "stage": "translation_worker",
                    "segmentId": task.segment_id,
                    "message": str(error),
                })
            finally:
                self.translation_work.task_done()

    def _process_translation(self, task: TranslationTask) -> None:
        common = {
            "segmentId": task.segment_id,
            "audioStartMs": task.audio_start_ms,
            "audioEndMs": task.audio_end_ms,
        }
        source_text = task.source_text
        translation_started = time.perf_counter()
        self._emit({**common, "type": "translation.started", "sourceTextEn": source_text})
        try:
            translated = self.translate(source_text, self.cursor_sequence, self.context_policy)
        except OllamaError as error:
            self._emit({
                **common,
                "type": "translation.failed",
                "sourceTextEn": source_text,
                "message": str(error),
                "recordingShouldContinue": True,
            })
            return
        alignment = translated.get("alignment") or {}
        if alignment.get("confidence") in {"high", "exact"}:
            self.cursor_sequence = alignment.get("suggestedCursor")
        self._emit({
            **common,
            "type": "translation.final",
            "sourceTextEn": source_text,
            "targetTextZh": translated.get("targetTextZh"),
            "latencyMs": round((time.perf_counter() - translation_started) * 1000),
            **{key: value for key, value in translated.items() if key != "targetTextZh"},
        })

    def _emit(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = {"schemaVersion": 1, "sessionId": self.session_id, **event}
        try:
            stored = self.sessions.append_event(self.session_id, payload, assign_sequence=True)
            payload = stored["event"]
        except (OSError, SessionStoreError):
            self.storage_failed = True
            payload["persistenceFailed"] = True
            if payload.get("type") == "stream.closed":
                payload["storageHealthy"] = False
        try:
            self.send(payload)
        except Exception:
            pass
        return payload

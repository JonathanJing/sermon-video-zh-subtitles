from __future__ import annotations

import math
import queue
import re
import struct
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from .asr_client import AsrError, WhisperCliClient
from .caption_presenter import CaptionPresenter
from .ollama_client import OllamaError
from .session_store import SessionStore, SessionStoreError
from .translation_units import TranslationUnitAssembler, is_contentless_fragment


SAMPLE_RATE_HZ = 16000
FRAME_DURATION_MS = 100
TRANSLATION_PARTIAL_INTERVAL_MS = 200
REPEATED_SHORT_RESULT_LIMIT = 3
PCM_BYTES_PER_FRAME = 3200
SILENCE_FRAME = bytes(PCM_BYTES_PER_FRAME)
NON_SPEECH_LABEL_RE = re.compile(
    r"^(?:"
    r"\[(?:blank[_ ]audio|music|silence|chimes|applause|laughter|inaudible)\]"
    r"|\((?:blank[_ ]audio|music|silence|chimes|applause|laughter|inaudible|birds? chirping|crickets? chirping)\)"
    r"|(?:blank[_ ]audio|music|silence|chimes|applause|laughter|inaudible)\.?)$",
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
    asr_final_at: float
    enqueued_at: float
    source_event: dict[str, Any] = field(default_factory=dict)
    unit_metadata: dict[str, Any] = field(default_factory=dict)


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
        translate_stream: Callable[[str, int | None, str, Callable[[str, str], None]], dict[str, Any]] | None = None,
        context_policy: str = "none",
        vad_threshold_rms: int = 150,
        vad_silence_ms: int = 500,
        vad_max_segment_ms: int = 3000,
        caption_presentation_policy: str = "readable_chunks",
        initial_frame_sequence: int = 0,
        initial_segment_count: int = 0,
        translation_unit_policy: str = "legacy",
        source_fragment_policy: str = "content_words",
    ) -> None:
        self.session_id = session_id
        self.sessions = sessions
        self.asr = asr
        self.translate = translate
        self.translate_stream = translate_stream
        self.send = send
        self.context_policy = context_policy
        self.translation_units = TranslationUnitAssembler(policy=translation_unit_policy)
        self.source_fragment_policy = source_fragment_policy
        self.caption_presenter = CaptionPresenter(caption_presentation_policy)
        self.cursor_sequence: int | None = None
        if vad_silence_ms % FRAME_DURATION_MS or vad_max_segment_ms % FRAME_DURATION_MS:
            raise ValueError("VAD timing must be a multiple of 100 ms")
        self.vad = EnergyVad(
            threshold_rms=vad_threshold_rms,
            silence_frames=max(1, vad_silence_ms // FRAME_DURATION_MS),
            max_segment_frames=max(1, vad_max_segment_ms // FRAME_DURATION_MS),
        )
        self.vad.segment_counter = initial_segment_count
        self.last_frame_sequence = initial_frame_sequence
        self.last_voice_at: float | None = None
        self.last_final_at = time.perf_counter()
        self.consecutive_no_final = 0
        self.asr_degraded = False
        self.drain_failed = False
        self.audio_clock_started_at: float | None = None
        self.asr_enqueued_at: dict[str, float] = {}
        self.ux_samples: list[dict[str, int | None]] = []
        self.last_short_asr_result = ""
        self.short_asr_repeat_count = 0
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
            "captionPresentation": {
                "policy": self.caption_presenter.policy,
                "rawEventsVisible": self.caption_presenter.raw_events_are_visible,
            },
            "asr": self.asr.status(),
        })

    def health(self) -> dict[str, Any]:
        now = time.perf_counter()
        stalled = bool(self.last_voice_at and now - self.last_voice_at < 5 and now - self.last_final_at > 12)
        return {
            "sessionId": self.session_id,
            "degraded": self.asr_degraded or stalled or self.drain_failed,
            "reason": "worker_drain_failed" if self.drain_failed else "speech_without_final" if stalled else "consecutive_no_final" if self.asr_degraded else None,
            "consecutiveNoFinal": self.consecutive_no_final,
            "asrQueueDepth": self.asr_work.qsize(),
            "translationQueueDepth": self.translation_work.qsize(),
        }

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
        if missing > 3000:
            self._emit({"type": "pipeline.failed", "reason": "resume_gap_exceeds_five_minutes", "message": "字幕中断超过五分钟，请保存录音并开始新会话。"})
            return
        if self.audio_clock_started_at is None:
            self.audio_clock_started_at = time.perf_counter() - sequence * FRAME_DURATION_MS / 1000
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
        self.drain_failed = not (asr_drained and translation_drained)
        if not translation_drained:
            self._emit({"type": "pipeline.failed", "reason": "translation_worker_stop_timeout"})
        closed = {
            "type": "stream.closed",
            "lastFrameSequence": self.last_frame_sequence,
            "workerDrained": asr_drained and translation_drained,
            "asrWorkerDrained": asr_drained,
            "translationWorkerDrained": translation_drained,
            "storageHealthy": not self.storage_failed,
            "uxMetrics": self._ux_summary(),
        }
        return self._emit(closed)

    def _accept_frame(self, sequence: int, pcm: bytes) -> None:
        if self.audio_clock_started_at is None:
            self.audio_clock_started_at = time.perf_counter() - sequence * FRAME_DURATION_MS / 1000
        if not self.storage_failed:
            if not self.pcm_batch:
                self.pcm_batch_start = sequence
            self.pcm_batch.append(pcm)
        self.last_frame_sequence = sequence
        if self.vad.rms(pcm) >= self.vad.threshold_rms:
            if self.last_voice_at is None or time.perf_counter() - self.last_voice_at > 5:
                self.last_final_at = time.perf_counter()
            self.last_voice_at = time.perf_counter()
        if self.health()["degraded"] and not self.asr_degraded:
            self.asr_degraded = True
            self._emit({"type": "asr.degraded", "reason": "speech_without_final", "message": "持续检测到声音，但识别未产生新字幕；录音继续，请检查音源或恢复字幕。"})
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
            self.asr_enqueued_at[segment.segment_id] = time.perf_counter()
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
        asr_started = time.perf_counter()
        asr_queue_wait_ms = round(
            (asr_started - self.asr_enqueued_at.pop(segment.segment_id, asr_started)) * 1000
        )
        try:
            result = self.asr.transcribe(segment.pcm, SAMPLE_RATE_HZ)
        except AsrError as error:
            self._note_no_final()
            self._emit({**common, "type": "asr.failed", "message": str(error)})
            return
        source_text = str(result.get("sourceTextEn") or "").strip()
        if not source_text:
            if result.get("noFinalReason") == "timeout":
                self._note_no_final()
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
        short_repeat_count = self._note_short_asr_result(source_text)
        if short_repeat_count >= REPEATED_SHORT_RESULT_LIMIT:
            self._emit({
                **common,
                "type": "asr.suppressed",
                "reason": "repeated_short_result",
                "sourceTextEn": source_text,
                "repeatCount": short_repeat_count,
                "asrMetrics": result,
            })
            return
        asr_final_at = time.perf_counter()
        self.last_final_at = asr_final_at
        self.consecutive_no_final = 0
        if self.asr_degraded:
            self.asr_degraded = False
            self._emit({"type": "asr.recovered"})
        audio_end_to_asr_final_ms = self._audio_end_latency_ms(segment.audio_end_ms, asr_final_at)
        final_event = self._emit({
            **common,
            "type": "asr.final",
            "displayEligible": self.caption_presenter.raw_events_are_visible and self.translation_units.policy == "legacy" and not (self.source_fragment_policy == "content_words" and is_contentless_fragment(source_text)),
            "sourceTextEn": source_text,
            "asrMetrics": result,
            "uxMetrics": {
                "segmentDurationMs": segment.audio_end_ms - segment.audio_start_ms,
                "asrQueueWaitMs": asr_queue_wait_ms,
                "asrProcessingMs": round((asr_final_at - asr_started) * 1000),
                "audioEndToAsrFinalMs": audio_end_to_asr_final_ms,
            },
        })
        if self.source_fragment_policy == "content_words" and is_contentless_fragment(source_text):
            self._emit({**common, "type": "translation.skipped", "reason": "insufficient_lexical_content", "displayEligible": False, "sourceTextEn": source_text, "sourceSegmentIds": [segment.segment_id]})
            return
        task = TranslationTask(
            segment_id=segment.segment_id,
            audio_start_ms=segment.audio_start_ms,
            audio_end_ms=segment.audio_end_ms,
            source_text=source_text,
            asr_final_at=asr_final_at,
            enqueued_at=time.perf_counter(),
            source_event=final_event,
        )
        if self.aborting:
            skipped_event = self._emit({
                **common,
                "type": "translation.skipped",
                "displayEligible": self.caption_presenter.raw_events_are_visible,
                "sourceTextEn": source_text,
                "reason": "pipeline_stopping_after_timeout",
            })
            self._emit_terminal_display(skipped_event, "翻译积压，暂时显示英文原文。")
            return
        try:
            self.translation_work.put_nowait(task)
        except queue.Full:
            skipped_event = self._emit({
                **common,
                "type": "translation.skipped",
                "displayEligible": self.caption_presenter.raw_events_are_visible,
                "sourceTextEn": source_text,
                "reason": "queue_full",
                "recordingShouldContinue": True,
            })
            self._emit_terminal_display(skipped_event, "翻译积压，暂时显示英文原文。")

    def _note_short_asr_result(self, source_text: str) -> int:
        normalized = " ".join(source_text.casefold().split())
        word_count = len(re.findall(r"[\w']+", normalized))
        if not normalized or word_count > 3 or len(normalized) > 24:
            self.last_short_asr_result = ""
            self.short_asr_repeat_count = 0
            return 0
        if normalized == self.last_short_asr_result:
            self.short_asr_repeat_count += 1
        else:
            self.last_short_asr_result = normalized
            self.short_asr_repeat_count = 1
        return self.short_asr_repeat_count

    def _note_no_final(self) -> None:
        self.consecutive_no_final += 1
        if self.consecutive_no_final >= 3 and not self.asr_degraded:
            self.asr_degraded = True
            self._emit({"type": "asr.degraded", "reason": "consecutive_no_final", "message": "连续识别无结果；录音继续，请检查音源或恢复字幕。"})

    def _run_translation_worker(self) -> None:
        while True:
            deadline = self.translation_units.deadline_at
            timeout = max(0, deadline - time.perf_counter()) if deadline is not None else None
            try:
                task = self.translation_work.get(timeout=timeout)
            except queue.Empty:
                for unit in self.translation_units.flush_due(time.perf_counter()):
                    self._translate_unit(unit)
                continue
            if task is None:
                for unit in self.translation_units.flush(time.perf_counter(), reason="stop"):
                    self._translate_unit(unit)
                self.translation_work.task_done()
                return
            try:
                final = task.source_event or {"type": "asr.final", "segmentId": task.segment_id, "sourceTextEn": task.source_text, "audioStartMs": task.audio_start_ms, "audioEndMs": task.audio_end_ms}
                for unit in self.translation_units.add(final, time.perf_counter(), final_at=task.asr_final_at):
                    self._translate_unit(unit)
            except Exception as error:
                self._emit({
                    "type": "pipeline.failed",
                    "stage": "translation_worker",
                    "segmentId": task.segment_id,
                    "message": str(error),
                })
            finally:
                self.translation_work.task_done()

    def _translate_unit(self, unit) -> None:
        task = TranslationTask(
            segment_id=unit.segment_id, audio_start_ms=unit.audio_start_ms,
            audio_end_ms=unit.audio_end_ms, source_text=unit.source_text_en,
            asr_final_at=unit.last_final_at, enqueued_at=unit.ready_at,
            unit_metadata=unit.event_metadata(),
        )
        try:
            self._process_translation(task)
        except Exception as error:
            self._emit({"type": "pipeline.failed", "stage": "translation_worker", "segmentId": unit.segment_id, "message": str(error)})

    def _process_translation(self, task: TranslationTask) -> None:
        common = {
            "segmentId": task.segment_id,
            "audioStartMs": task.audio_start_ms,
            "audioEndMs": task.audio_end_ms,
            **task.unit_metadata,
        }
        source_text = task.source_text
        translation_started = time.perf_counter()
        # Waiting behind earlier translations happens before the assembler can
        # accept this unit. Keep it in queue latency, outside semantic hold.
        translation_queue_wait_ms = (
            task.unit_metadata.get("translationUnitQueueWaitMs", 0)
            + round((translation_started - task.enqueued_at) * 1000)
        )
        first_token_at: float | None = None
        last_partial_emit = 0.0
        partial_sequence = 0
        self._emit({**common, "type": "translation.started", "sourceTextEn": source_text, "displayEligible": self.caption_presenter.raw_events_are_visible})

        def on_partial(delta: str, target_text: str) -> None:
            nonlocal first_token_at, last_partial_emit, partial_sequence
            now = time.perf_counter()
            if first_token_at is None:
                first_token_at = now
            should_emit = (
                last_partial_emit == 0
                or (now - last_partial_emit) * 1000 >= TRANSLATION_PARTIAL_INTERVAL_MS
                or target_text.endswith(("。", "！", "？", "；", "，", "\n"))
            )
            if not should_emit:
                return
            partial_sequence += 1
            last_partial_emit = now
            partial_event = self._emit({
                **common,
                "type": "translation.partial",
                "displayEligible": self.caption_presenter.raw_events_are_visible,
                "sourceTextEn": source_text,
                "targetTextZh": target_text,
                "partialSequence": partial_sequence,
                "appendOnly": True,
                "firstTokenLatencyMs": round((first_token_at - translation_started) * 1000),
                "uxMetrics": {
                    "translationQueueWaitMs": translation_queue_wait_ms,
                    "translationTtftMs": round((first_token_at - translation_started) * 1000),
                    "asrFinalToChineseFirstTokenMs": round((first_token_at - task.asr_final_at) * 1000),
                    "audioEndToChineseFirstTokenMs": self._audio_end_latency_ms(task.audio_end_ms, first_token_at),
                },
            })
            display_event = self.caption_presenter.partial(partial_event)
            if display_event:
                self._emit(display_event)
        try:
            if self.translate_stream:
                translated = self.translate_stream(
                    source_text, self.cursor_sequence, self.context_policy, on_partial
                )
            else:
                translated = self.translate(source_text, self.cursor_sequence, self.context_policy)
        except OllamaError as error:
            failed_event = self._emit({
                **common,
                "type": "translation.failed",
                "displayEligible": self.caption_presenter.raw_events_are_visible,
                "sourceTextEn": source_text,
                "message": str(error),
                "recordingShouldContinue": True,
            })
            self._emit_terminal_display(failed_event, "翻译暂时不可用，请查看英文原文。")
            return
        alignment = translated.get("alignment") or {}
        if alignment.get("confidence") in {"high", "exact"}:
            self.cursor_sequence = alignment.get("suggestedCursor")
        translation_final_at = time.perf_counter()
        sample = {
            "audioEndToAsrFinalMs": self._audio_end_latency_ms(task.audio_end_ms, task.asr_final_at),
            "translationQueueWaitMs": translation_queue_wait_ms,
            "translationTtftMs": (
                round((first_token_at - translation_started) * 1000)
                if first_token_at is not None else None
            ),
            "asrFinalToChineseFirstTokenMs": (
                round((first_token_at - task.asr_final_at) * 1000)
                if first_token_at is not None else None
            ),
            "asrFinalToChineseFinalMs": round((translation_final_at - task.asr_final_at) * 1000),
            "audioEndToChineseFirstTokenMs": (
                self._audio_end_latency_ms(task.audio_end_ms, first_token_at)
                if first_token_at is not None else None
            ),
            "audioEndToChineseFinalMs": self._audio_end_latency_ms(task.audio_end_ms, translation_final_at),
        }
        self.ux_samples.append(sample)
        final_event = self._emit({
            **common,
            "type": "translation.final",
            "displayEligible": self.caption_presenter.raw_events_are_visible,
            "sourceTextEn": source_text,
            "targetTextZh": translated.get("targetTextZh"),
            "latencyMs": round((translation_final_at - translation_started) * 1000),
            "firstTokenLatencyMs": (
                round((first_token_at - translation_started) * 1000)
                if first_token_at is not None else None
            ),
            "partialEventCount": partial_sequence,
            "uxMetrics": sample,
            **{key: value for key, value in translated.items() if key != "targetTextZh"},
        })
        display_event = self.caption_presenter.final(final_event)
        if display_event:
            self._emit(display_event)

    def _emit_terminal_display(self, event: dict[str, Any], target_text: str) -> None:
        display_event = self.caption_presenter.terminal(event, target_text)
        if display_event:
            self._emit(display_event)

    def _audio_end_latency_ms(self, audio_end_ms: int, now: float) -> int | None:
        if self.audio_clock_started_at is None:
            return None
        return round((now - self.audio_clock_started_at) * 1000 - audio_end_ms)

    def _ux_summary(self) -> dict[str, Any]:
        keys = (
            "audioEndToAsrFinalMs",
            "translationQueueWaitMs",
            "translationTtftMs",
            "asrFinalToChineseFirstTokenMs",
            "asrFinalToChineseFinalMs",
            "audioEndToChineseFirstTokenMs",
            "audioEndToChineseFinalMs",
        )
        summary: dict[str, Any] = {"completedSegmentCount": len(self.ux_samples)}
        for key in keys:
            values = sorted(
                int(sample[key]) for sample in self.ux_samples if sample.get(key) is not None
            )
            if not values:
                continue
            summary[key] = {
                "p50": round(statistics.median(values)),
                "p95": self._percentile(values, 0.95),
                "max": values[-1],
            }
        return summary

    @staticmethod
    def _percentile(values: list[int], quantile: float) -> int:
        index = (len(values) - 1) * quantile
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        return round(values[lower] + (values[upper] - values[lower]) * (index - lower))

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

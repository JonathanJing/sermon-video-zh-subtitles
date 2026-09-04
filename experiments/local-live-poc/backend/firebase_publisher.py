from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen


PUBLIC_EVENT_TYPES = {
    "asr.final",
    "translation.partial",
    "translation.final",
    "translation.failed",
    "translation.skipped",
}


@dataclass(frozen=True)
class FirebasePublisherConfig:
    database_url: str
    viewer_base_url: str
    partial_interval_ms: int = 500
    session_ttl_seconds: int = 4 * 60 * 60

    def __post_init__(self) -> None:
        if self.partial_interval_ms < 200:
            raise ValueError("Firebase partial interval must be at least 200 ms")
        if not 60 <= self.session_ttl_seconds <= 24 * 60 * 60:
            raise ValueError("Firebase session TTL must be between 60 and 86400 seconds")

    @classmethod
    def from_environment(cls) -> FirebasePublisherConfig | None:
        database_url = os.environ.get("LOCAL_LIVE_FIREBASE_DATABASE_URL", "").rstrip("/")
        viewer_base_url = os.environ.get("LOCAL_LIVE_FIREBASE_VIEWER_URL", "").rstrip("/")
        if not database_url or not viewer_base_url:
            return None
        if not database_url.startswith("https://") and not database_url.startswith("http://127.0.0.1:"):
            raise ValueError("Firebase database URL must use HTTPS")
        return cls(
            database_url=database_url,
            viewer_base_url=viewer_base_url,
            partial_interval_ms=int(os.environ.get("LOCAL_LIVE_FIREBASE_PARTIAL_INTERVAL_MS", "500")),
            session_ttl_seconds=int(os.environ.get("LOCAL_LIVE_FIREBASE_SESSION_TTL_SECONDS", "14400")),
        )


class AccessTokenProvider:
    """Returns a short-lived Google OAuth token without ever logging it."""

    def __init__(self, command: tuple[str, ...] = ("gcloud", "auth", "application-default", "print-access-token")) -> None:
        self.command = command
        self.cached = ""
        self.refresh_at = 0.0
        self.lock = threading.Lock()

    def __call__(self) -> str:
        static_token = os.environ.get("LOCAL_LIVE_FIREBASE_ACCESS_TOKEN", "").strip()
        if static_token:
            return static_token
        with self.lock:
            if self.cached and time.monotonic() < self.refresh_at:
                return self.cached
            result = subprocess.run(
                self.command,
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            token = result.stdout.strip()
            if not token:
                raise RuntimeError("gcloud returned an empty Firebase access token")
            self.cached = token
            self.refresh_at = time.monotonic() + 45 * 60
            return token


class CaptionProjector:
    def __init__(self, expires_at_ms: int) -> None:
        self.sequence = 0
        self.previous_final: dict[str, str] | None = None
        self.active = {
            "segmentId": "",
            "sourceTextEn": "",
            "targetTextZh": "等待现场字幕…",
            "phase": "listening",
        }
        self.status = "live"
        self.expires_at_ms = expires_at_ms

    def apply(self, event: dict[str, Any], published_at_ms: int) -> dict[str, Any] | None:
        event_type = event.get("type")
        if event_type not in PUBLIC_EVENT_TYPES:
            return None
        if event_type == "asr.final":
            if (
                self.active.get("phase") == "final"
                and self.active.get("sourceTextEn")
                and self.active.get("targetTextZh")
            ):
                self.previous_final = {
                    "segmentId": str(self.active.get("segmentId") or ""),
                    "sourceTextEn": str(self.active["sourceTextEn"]),
                    "targetTextZh": str(self.active["targetTextZh"]),
                }
            self.active = {
                "segmentId": str(event.get("segmentId") or ""),
                "sourceTextEn": str(event.get("sourceTextEn") or "")[:1200],
                "targetTextZh": "",
                "phase": "requesting",
            }
        else:
            segment_id = str(event.get("segmentId") or "")
            if segment_id and self.active.get("segmentId") and segment_id != self.active["segmentId"]:
                return None
            fallback = {
                "translation.failed": "翻译暂时不可用，请查看英文原文。",
                "translation.skipped": "翻译积压，暂时显示英文原文。",
                "translation.final": "翻译结果为空。",
            }.get(str(event_type), str(self.active.get("targetTextZh") or ""))
            self.active = {
                "segmentId": segment_id or str(self.active.get("segmentId") or ""),
                "sourceTextEn": str(event.get("sourceTextEn", self.active.get("sourceTextEn", "")))[:1200],
                "targetTextZh": str(event.get("targetTextZh") or fallback)[:1200],
                "phase": "streaming" if event_type == "translation.partial"
                else "final" if event_type == "translation.final" else "error",
            }
        self.sequence += 1
        return self.snapshot(published_at_ms)

    def end(self, published_at_ms: int) -> dict[str, Any]:
        self.status = "ended"
        self.sequence += 1
        return self.snapshot(published_at_ms)

    def snapshot(self, published_at_ms: int) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "status": self.status,
            "sequence": self.sequence,
            "previousFinal": self.previous_final,
            "active": dict(self.active),
            "publishedAt": published_at_ms,
            "expiresAt": self.expires_at_ms,
        }


Transport = Callable[[str, dict[str, Any]], None]


class FirebaseCaptionPublisher:
    """Best-effort outbound publisher. It never blocks the local caption path."""

    def __init__(
        self,
        config: FirebasePublisherConfig,
        token_provider: Callable[[], str] | None = None,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.token_provider = token_provider or AccessTokenProvider()
        self.transport = transport or self._rest_put
        self.clock = clock
        self.projectors: dict[str, CaptionProjector] = {}
        self.tokens: dict[str, str] = {}
        self.last_partial_at: dict[str, float] = {}
        self.work: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue(maxsize=32)
        self.lock = threading.Lock()
        self.last_error = ""
        self.published_count = 0
        self.dropped_partial_count = 0
        self.dropped_final_count = 0
        self.last_write_latency_ms: int | None = None
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def start_session(self, session_id: str, token: str) -> str:
        now_ms = round(self.clock() * 1000)
        projector = CaptionProjector(now_ms + self.config.session_ttl_seconds * 1000)
        with self.lock:
            self.projectors[session_id] = projector
            self.tokens[session_id] = token
        self._enqueue(session_id, projector.snapshot(now_ms), "final")
        return f"{self.config.viewer_base_url}/s/{token}"

    def publish(self, session_id: str, event: dict[str, Any]) -> None:
        now = self.clock()
        with self.lock:
            projector = self.projectors.get(session_id)
            if not projector:
                return
            snapshot = projector.apply(event, round(now * 1000))
            if snapshot is None:
                return
            is_partial = event.get("type") == "translation.partial"
            if is_partial:
                last = self.last_partial_at.get(session_id, 0.0)
                if (now - last) * 1000 < self.config.partial_interval_ms:
                    self.dropped_partial_count += 1
                    return
                self.last_partial_at[session_id] = now
        self._enqueue(session_id, snapshot, "partial" if is_partial else "final")

    def end_session(self, session_id: str) -> None:
        with self.lock:
            projector = self.projectors.get(session_id)
            if not projector:
                return
            snapshot = projector.end(round(self.clock() * 1000))
        self._enqueue(session_id, snapshot, "final")

    def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "mode": "firebase-rtdb",
            "queueDepth": self.work.qsize(),
            "publishedCount": self.published_count,
            "droppedPartialCount": self.dropped_partial_count,
            "droppedFinalCount": self.dropped_final_count,
            "lastWriteLatencyMs": self.last_write_latency_ms,
            "lastError": self.last_error or None,
        }

    def stop(self) -> None:
        try:
            self.work.put(None, timeout=1)
        except queue.Full:
            return
        self.worker.join(timeout=5)

    def _enqueue(self, session_id: str, snapshot: dict[str, Any], kind: str) -> None:
        try:
            self.work.put_nowait((session_id, snapshot))
        except queue.Full:
            if kind == "partial":
                self.dropped_partial_count += 1
                return
            try:
                self.work.put((session_id, snapshot), timeout=0.25)
            except queue.Full:
                self.dropped_final_count += 1
                self.last_error = "public caption queue remained full"

    def _run(self) -> None:
        while True:
            item = self.work.get()
            if item is None:
                self.work.task_done()
                return
            session_id, snapshot = item
            try:
                token = self.tokens.get(session_id)
                if token:
                    started = time.perf_counter()
                    last_error: Exception | None = None
                    for attempt, delay in enumerate((0.0, 0.15, 0.5)):
                        if delay:
                            time.sleep(delay)
                        try:
                            self.transport(token, snapshot)
                            last_error = None
                            break
                        except Exception as error:  # Retry only inside the cloud worker.
                            last_error = error
                    if last_error:
                        raise last_error
                    self.published_count += 1
                    self.last_write_latency_ms = round((time.perf_counter() - started) * 1000)
                    self.last_error = ""
            except Exception as error:  # Cloud publishing must fail open.
                self.last_error = str(error)[:240]
            finally:
                self.work.task_done()

    def _rest_put(self, token: str, snapshot: dict[str, Any]) -> None:
        body = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self.config.database_url}/sessions/{token}.json",
            data=body,
            method="PUT",
            headers={
                "Authorization": f"Bearer {self.token_provider()}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        with urlopen(request, timeout=3) as response:
            if response.status not in {200, 204}:
                raise RuntimeError(f"Firebase write failed with HTTP {response.status}")

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import subprocess
import threading
import time
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_REALTIME_MODEL = "gpt-realtime-translate"
DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-transcribe"
DEFAULT_TARGET_LANGUAGE = "zh"
OPENAI_TRANSLATION_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/translations/client_secrets"
OPENAI_TRANSLATION_CALLS_URL = "https://api.openai.com/v1/realtime/translations/calls"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RealtimeSession:
    session_id: str
    event_token: str
    sunday: str
    model: str = DEFAULT_REALTIME_MODEL
    target_language: str = DEFAULT_TARGET_LANGUAGE
    audio_source_kind: str = "unknown"
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL
    created_at: str = field(default_factory=utc_now)
    last_event_id: int = 0
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))


class RealtimeEventArchive:
    def __init__(
        self,
        root: Path | str,
        gcs_prefix: str | None = None,
        uploader: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.gcs_prefix = normalize_gcs_prefix(gcs_prefix)
        self.uploader = uploader or GcloudStorageUploader()
        self._mirror_failures: deque[dict[str, Any]] = deque(maxlen=10)
        self._mirror_futures: deque[Future] = deque(maxlen=100)
        self._mirror_lock = threading.Lock()
        self._mirror_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="realtime-gcs-mirror")

    def append(self, session: RealtimeSession, event: dict[str, Any]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(session.session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        if self.gcs_prefix:
            self.mirror_to_gcs(path, session)
        return path

    def mirror_to_gcs(self, path: Path, session: RealtimeSession) -> None:
        future = self._mirror_executor.submit(self._upload_to_gcs, path, self.gcs_uri_for(session), session.session_id)
        with self._mirror_lock:
            self._mirror_futures.append(future)

    def _upload_to_gcs(self, path: Path, gcs_uri: str, session_id: str) -> None:
        try:
            self.uploader.upload(path, gcs_uri)
        except Exception as exc:
            with self._mirror_lock:
                self._mirror_failures.append(
                    {
                        "sessionId": session_id,
                        "at": utc_now(),
                        "error": str(exc)[:300],
                    }
                )

    def wait_for_pending_mirrors(self, timeout: float | None = None) -> None:
        with self._mirror_lock:
            futures = list(self._mirror_futures)
        if futures:
            wait(futures, timeout=timeout)

    def path_for(self, session_id: str) -> Path:
        safe_session_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in session_id)
        return self.root / f"{safe_session_id}.jsonl"

    def gcs_uri_for(self, session: RealtimeSession) -> str:
        if not self.gcs_prefix:
            raise RuntimeError("Realtime event GCS prefix is not configured")
        safe_sunday = safe_path_component(session.sunday or "unknown-sunday")
        return f"{self.gcs_prefix}/{safe_sunday}/{self.path_for(session.session_id).name}"

    def status(self) -> dict[str, Any]:
        with self._mirror_lock:
            failures = list(self._mirror_failures)
            pending = sum(1 for future in self._mirror_futures if not future.done())
        status = {
            "enabled": True,
            "directory": str(self.root),
            "gcsMirrorEnabled": bool(self.gcs_prefix),
            "gcsMirrorHealthy": not failures,
            "gcsMirrorPending": pending,
        }
        if self.gcs_prefix:
            status["gcsPrefix"] = self.gcs_prefix
        if failures:
            status["gcsMirrorFailureCount"] = len(failures)
            status["gcsMirrorLastError"] = failures[-1]
        return status


class GcloudStorageUploader:
    def upload(self, local_path: Path, gcs_uri: str) -> None:
        subprocess.run(
            ["gcloud", "storage", "cp", str(local_path), gcs_uri],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )


def normalize_gcs_prefix(value: str | None) -> str | None:
    if not value:
        return None
    clean = value.strip().rstrip("/")
    if not clean.startswith("gs://"):
        raise ValueError("REALTIME_EVENT_GCS_PREFIX must start with gs://")
    rest = clean[5:]
    bucket, sep, object_prefix = rest.partition("/")
    if not bucket or not sep or not object_prefix:
        raise ValueError("REALTIME_EVENT_GCS_PREFIX must be gs://bucket/prefix")
    if any(part in {".", ".."} for part in object_prefix.split("/")):
        raise ValueError("REALTIME_EVENT_GCS_PREFIX contains an unsafe path segment")
    return clean


def safe_path_component(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)[:80]


class RealtimeSessionStore:
    def __init__(self, archive: RealtimeEventArchive | None = None) -> None:
        self._condition = threading.Condition()
        self._sessions: dict[str, RealtimeSession] = {}
        self._current_session_id: str | None = None
        self.archive = archive

    def create(
        self,
        *,
        sunday: str,
        model: str = DEFAULT_REALTIME_MODEL,
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        audio_source_kind: str = "unknown",
        transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL,
    ) -> RealtimeSession:
        session = RealtimeSession(
            session_id=f"rt_{secrets.token_urlsafe(12)}",
            event_token=secrets.token_urlsafe(24),
            sunday=sunday,
            model=model,
            target_language=target_language,
            audio_source_kind=audio_source_kind,
            transcription_model=transcription_model,
        )
        with self._condition:
            self._sessions[session.session_id] = session
            self._current_session_id = session.session_id
            self._condition.notify_all()
        self.append_event(
            session.session_id,
            {
                "type": "session_started",
                "sunday": sunday,
                "model": model,
                "targetLanguage": target_language,
                "audioSourceKind": audio_source_kind,
            },
        )
        return session

    def get(self, session_id: str) -> RealtimeSession | None:
        with self._condition:
            if session_id == "current":
                session_id = self._current_session_id or ""
            return self._sessions.get(session_id)

    def current_session_id(self) -> str | None:
        with self._condition:
            return self._current_session_id

    def wait_for_current_session_id(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._current_session_id:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._current_session_id

    def validate_event_token(self, session_id: str, token: str | None) -> bool:
        session = self.get(session_id)
        return bool(session and token and secrets.compare_digest(session.event_token, token))

    def append_event(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            session = self._sessions[session_id]
            session.last_event_id += 1
            event = {
                "id": session.last_event_id,
                "sessionId": session.session_id,
                "createdAt": utc_now(),
                **sanitize_event(payload),
            }
            session.events.append(event)
            if self.archive:
                self.archive.append(session, event)
            self._condition.notify_all()
            return event

    def wait_for_events(self, session_id: str, after_id: int, timeout: float) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                session = self._sessions.get(session_id)
                if not session:
                    return []
                events = [event for event in session.events if int(event["id"]) > after_id]
                if events:
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._condition.wait(remaining)

    def archive_status(self) -> dict[str, Any]:
        if not self.archive:
            return {"enabled": False}
        return self.archive.status()


def sanitize_event(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "type",
        "text",
        "delta",
        "zh",
        "en",
        "final",
        "source",
        "latencyMs",
        "segmentId",
        "sunday",
        "model",
        "targetLanguage",
        "audioSourceKind",
        "openaiEventType",
    }
    clean = {key: value for key, value in payload.items() if key in allowed}
    for key in ["text", "delta", "zh", "en", "source", "segmentId", "audioSourceKind", "openaiEventType"]:
        if key in clean and clean[key] is not None:
            clean[key] = str(clean[key])[:4000]
    if "final" in clean:
        clean["final"] = bool(clean["final"])
    if "latencyMs" in clean:
        try:
            clean["latencyMs"] = max(0, int(clean["latencyMs"]))
        except (TypeError, ValueError):
            clean.pop("latencyMs", None)
    clean.setdefault("type", "caption_delta")
    return clean


def create_openai_translation_session(
    *,
    api_key: str,
    model: str = DEFAULT_REALTIME_MODEL,
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL,
) -> dict[str, Any]:
    policy_error = realtime_translation_policy_error(model, target_language)
    if policy_error:
        raise ValueError(policy_error["message"])
    payload = {
        "session": {
            "model": model,
            "audio": {
                "output": {
                    "language": target_language,
                },
            },
            "input_audio_transcription": {"model": transcription_model},
            "instructions": (
                "Translate spoken English Christian sermon audio into readable Simplified Chinese captions "
                "for live church attendees. Prioritize faithful meaning, short subtitle lines, and stable "
                "Bible/person/theology terms. Do not add commentary."
            ),
        },
    }
    request = Request(
        OPENAI_TRANSLATION_CLIENT_SECRET_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def realtime_translation_policy_error(model: str, target_language: str) -> dict[str, str] | None:
    if model != DEFAULT_REALTIME_MODEL:
        return {
            "error": "unsupported_realtime_model",
            "message": "Realtime live captions must use gpt-realtime-translate.",
            "expectedModel": DEFAULT_REALTIME_MODEL,
        }
    if target_language != DEFAULT_TARGET_LANGUAGE:
        return {
            "error": "unsupported_realtime_target_language",
            "message": "Realtime live captions must target Simplified Chinese.",
            "expectedTargetLanguage": DEFAULT_TARGET_LANGUAGE,
        }
    return None


def resolve_openai_api_key(raw_key: str | None, secret_resource: str | None) -> str:
    if raw_key:
        return raw_key
    if not secret_resource:
        raise RuntimeError("OpenAI API key is not configured")
    return access_secret_with_gcloud(secret_resource)


def access_secret_with_gcloud(resource_name: str) -> str:
    parts = resource_name.strip().split("/")
    if len(parts) not in {4, 6} or parts[0] != "projects" or parts[2] != "secrets":
        raise RuntimeError("OPENAI_API_KEY_SECRET must be a Secret Manager resource name")
    project = parts[1]
    secret = parts[3]
    version = parts[5] if len(parts) == 6 else "latest"
    completed = subprocess.run(
        ["gcloud", "secrets", "versions", "access", version, "--secret", secret, "--project", project],
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if not value:
        raise RuntimeError("OpenAI API key secret returned an empty value")
    return value

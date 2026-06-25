from __future__ import annotations

from collections import deque
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
DEFAULT_TARGET_LANGUAGE = "zh-CN"
OPENAI_TRANSLATION_SESSION_URL = "https://api.openai.com/v1/realtime/translations"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RealtimeSession:
    session_id: str
    event_token: str
    sunday: str
    model: str = DEFAULT_REALTIME_MODEL
    target_language: str = DEFAULT_TARGET_LANGUAGE
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL
    created_at: str = field(default_factory=utc_now)
    last_event_id: int = 0
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))


class RealtimeEventArchive:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def append(self, session: RealtimeSession, event: dict[str, Any]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(session.session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return path

    def path_for(self, session_id: str) -> Path:
        safe_session_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in session_id)
        return self.root / f"{safe_session_id}.jsonl"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "directory": str(self.root),
        }


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
        transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL,
    ) -> RealtimeSession:
        session = RealtimeSession(
            session_id=f"rt_{secrets.token_urlsafe(12)}",
            event_token=secrets.token_urlsafe(24),
            sunday=sunday,
            model=model,
            target_language=target_language,
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
        "openaiEventType",
    }
    clean = {key: value for key, value in payload.items() if key in allowed}
    for key in ["text", "delta", "zh", "en", "source", "segmentId", "openaiEventType"]:
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
    payload = {
        "model": model,
        "target_language": target_language,
        "input_audio_transcription": {"model": transcription_model},
        "instructions": (
            "Translate spoken English Christian sermon audio into readable Simplified Chinese captions "
            "for live church attendees. Prioritize faithful meaning, short subtitle lines, and stable "
            "Bible/person/theology terms. Do not add commentary."
        ),
    }
    request = Request(
        OPENAI_TRANSLATION_SESSION_URL,
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

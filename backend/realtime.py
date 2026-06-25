from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import json
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_REALTIME_MODEL = "gpt-realtime-translate"
DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-transcribe"
DEFAULT_TARGET_LANGUAGE = "zh"
OPENAI_TRANSLATION_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
OPENAI_TRANSLATION_CALLS_URL = "https://api.openai.com/v1/realtime/calls"
METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
GCS_UPLOAD_BASE_URL = "https://storage.googleapis.com/upload/storage/v1/b"
SECRET_MANAGER_ACCESS_BASE_URL = "https://secretmanager.googleapis.com/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RealtimeCaptionStabilizer:
    """Create low-latency stable caption commits from realtime draft events."""

    stable_delay_ms: int = 1200
    stable_window_ms: int = 8000
    max_context_events: int = 12
    recent_events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=12))
    last_stable_text_by_segment: dict[str, str] = field(default_factory=dict)

    def observe(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = str(event.get("type") or "")
        if event_type in {"input_transcript_delta", "input_transcript_final", "caption_delta", "caption_final"}:
            self.recent_events.append(event)
        if event_type not in {"caption_delta", "caption_final"}:
            return []
        source = str(event.get("source") or "")
        if "stable-correction" in source or source == "realtime-caption-stabilizer":
            return []
        segment_id = str(event.get("segmentId") or "").strip()
        text = event_text(event)
        if not segment_id or not text:
            return []
        final = event_type == "caption_final" or bool(event.get("final"))
        if not final and not ready_for_stable_commit(text):
            return []
        if self.last_stable_text_by_segment.get(segment_id) == text:
            return []
        self.last_stable_text_by_segment[segment_id] = text
        window = stabilizer_window(self.recent_events, segment_id, text, self.stable_window_ms)
        return [
            {
                "type": "caption_stable",
                "text": text,
                "zh": text,
                "en": window["inputTextEn"],
                "final": False,
                "segmentId": segment_id,
                "source": "realtime-caption-stabilizer",
                "stability": "stable",
                "stabilizerWindowMs": self.stable_window_ms,
                "latencyMs": int(event.get("latencyMs") or self.stable_delay_ms),
                "draftZh": text,
                "stabilizerWindow": window,
            }
        ]


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
    stabilizer: RealtimeCaptionStabilizer = field(default_factory=RealtimeCaptionStabilizer)


class RealtimeEventArchive:
    def __init__(
        self,
        root: Path | str,
        gcs_prefix: str | None = None,
        uploader: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.gcs_prefix = normalize_gcs_prefix(gcs_prefix)
        self.uploader = uploader or GcsJsonApiUploader()
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


class GcsJsonApiUploader:
    def upload(self, local_path: Path, gcs_uri: str) -> None:
        bucket, object_name = split_gcs_uri(gcs_uri)
        token = metadata_access_token()
        body = local_path.read_bytes()
        upload_url = (
            f"{GCS_UPLOAD_BASE_URL}/{quote(bucket, safe='')}/o"
            f"?uploadType=media&name={quote(object_name, safe='')}"
        )
        request = Request(
            upload_url,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/jsonl; charset=utf-8",
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            response.read()


class GcloudStorageUploader:
    def upload(self, local_path: Path, gcs_uri: str) -> None:
        subprocess.run(
            ["gcloud", "storage", "cp", str(local_path), gcs_uri],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )


def metadata_access_token() -> str:
    request = Request(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    with urlopen(request, timeout=5) as response:
        data = json.loads(response.read().decode("utf-8"))
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError("Metadata server did not return an access token")
    return str(token)


def split_gcs_uri(value: str) -> tuple[str, str]:
    if not value.startswith("gs://"):
        raise ValueError("GCS URI must start with gs://")
    bucket, sep, object_name = value[5:].partition("/")
    if not bucket or not sep or not object_name:
        raise ValueError("GCS URI must be gs://bucket/object")
    if any(part in {".", ".."} for part in object_name.split("/")):
        raise ValueError("GCS URI contains an unsafe path segment")
    return bucket, object_name


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
            event = self._append_sanitized_event_locked(session, payload)
            for stable_event in session.stabilizer.observe(event):
                self._append_sanitized_event_locked(session, stable_event)
            self._condition.notify_all()
            return event

    def _append_sanitized_event_locked(self, session: RealtimeSession, payload: dict[str, Any]) -> dict[str, Any]:
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
        "stability",
        "stabilizerWindowMs",
        "stabilizerWindow",
        "draftZh",
        "sourceTextEn",
    }
    clean = {key: value for key, value in payload.items() if key in allowed}
    for key in [
        "text",
        "delta",
        "zh",
        "en",
        "source",
        "segmentId",
        "audioSourceKind",
        "openaiEventType",
        "stability",
        "draftZh",
        "sourceTextEn",
    ]:
        if key in clean and clean[key] is not None:
            clean[key] = str(clean[key])[:4000]
    if "final" in clean:
        clean["final"] = bool(clean["final"])
    if "latencyMs" in clean:
        try:
            clean["latencyMs"] = max(0, int(clean["latencyMs"]))
        except (TypeError, ValueError):
            clean.pop("latencyMs", None)
    if "stabilizerWindowMs" in clean:
        try:
            clean["stabilizerWindowMs"] = max(0, int(clean["stabilizerWindowMs"]))
        except (TypeError, ValueError):
            clean.pop("stabilizerWindowMs", None)
    if "stabilizerWindow" in clean:
        window = sanitize_stabilizer_window(clean["stabilizerWindow"])
        if window:
            clean["stabilizerWindow"] = window
        else:
            clean.pop("stabilizerWindow", None)
    clean.setdefault("type", "caption_delta")
    return clean


def event_text(event: dict[str, Any]) -> str:
    return str(event.get("text") or event.get("zh") or event.get("delta") or event.get("en") or "").strip()


def ready_for_stable_commit(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    if ends_with_connector(stripped):
        return False
    return bool(re.search(r"(?:[。！？；]|\.\s*|[!?]\s*|……)$", stripped))


def ends_with_connector(text: str) -> bool:
    lowered = text.strip().lower()
    connector_suffixes = (
        "因为",
        "如果",
        "当",
        "但是",
        "可是",
        "所以",
        "然后",
        "以及",
        "并且",
        "which",
        "because",
        "that",
        "when",
        "if",
        "but",
        "and",
    )
    return lowered.endswith(connector_suffixes)


def recent_input_context(events: deque[dict[str, Any]], segment_id: str) -> str:
    matching = [
        event_text(event)
        for event in events
        if str(event.get("segmentId") or "") == segment_id
        and str(event.get("type") or "").startswith("input_transcript")
        and event_text(event)
    ]
    if matching:
        return compact_context(matching[-2:])
    fallback = [
        event_text(event)
        for event in events
        if str(event.get("type") or "").startswith("input_transcript") and event_text(event)
    ]
    return compact_context(fallback[-2:])


def stabilizer_window(events: deque[dict[str, Any]], segment_id: str, draft_zh: str, window_ms: int) -> dict[str, Any]:
    matching_events = [
        event
        for event in events
        if str(event.get("segmentId") or "") == segment_id
        and str(event.get("type") or "") in {"input_transcript_delta", "input_transcript_final", "caption_delta", "caption_final"}
    ]
    if not matching_events:
        matching_events = [
            event
            for event in events
            if str(event.get("type") or "") in {"input_transcript_delta", "input_transcript_final", "caption_delta", "caption_final"}
        ]
    input_text = compact_context(
        [
            event_text(event)
            for event in matching_events
            if str(event.get("type") or "").startswith("input_transcript") and event_text(event)
        ][-3:]
    )
    return {
        "windowMs": window_ms,
        "segmentId": segment_id,
        "sourceEventIds": [int(event["id"]) for event in matching_events if isinstance(event.get("id"), int)][-6:],
        "inputTextEn": input_text,
        "draftZh": draft_zh[:4000],
    }


def sanitize_stabilizer_window(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    try:
        clean["windowMs"] = max(0, int(value.get("windowMs") or 0))
    except (TypeError, ValueError):
        clean["windowMs"] = 0
    for key in ("segmentId", "inputTextEn", "draftZh"):
        if value.get(key) is not None:
            clean[key] = str(value.get(key))[:4000]
    source_ids = value.get("sourceEventIds")
    if isinstance(source_ids, list):
        clean["sourceEventIds"] = []
        for item in source_ids[:12]:
            try:
                clean["sourceEventIds"].append(max(0, int(item)))
            except (TypeError, ValueError):
                continue
    return clean


def compact_context(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(parts)).strip()[:4000]


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
            "type": "realtime",
            "model": model,
            "output_modalities": ["text"],
            "audio": {
                "input": {
                    "transcription": {
                        "language": "en",
                        "model": transcription_model,
                    },
                },
            },
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
    if not isinstance(data, dict):
        return {}
    if "client_secret" not in data and data.get("value"):
        normalized = dict(data)
        normalized["client_secret"] = {
            "value": data.get("value"),
            "expires_at": data.get("expires_at"),
        }
        return normalized
    return data


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
    try:
        return access_secret_with_secret_manager_api(secret_resource)
    except Exception:
        return access_secret_with_gcloud(secret_resource)


def access_secret_with_secret_manager_api(resource_name: str) -> str:
    normalized = normalize_secret_version_resource(resource_name)
    token = metadata_access_token()
    request = Request(
        f"{SECRET_MANAGER_ACCESS_BASE_URL}/{quote(normalized, safe='/:')}:access",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    payload = data.get("payload") if isinstance(data, dict) else None
    encoded_value = payload.get("data") if isinstance(payload, dict) else None
    if not encoded_value:
        raise RuntimeError("OpenAI API key secret returned an empty value")
    value = base64.b64decode(str(encoded_value)).decode("utf-8").strip()
    if not value:
        raise RuntimeError("OpenAI API key secret returned an empty value")
    return value


def normalize_secret_version_resource(resource_name: str) -> str:
    parts = resource_name.strip().split("/")
    if len(parts) == 4 and parts[0] == "projects" and parts[2] == "secrets":
        return f"{resource_name.strip()}/versions/latest"
    if len(parts) == 6 and parts[0] == "projects" and parts[2] == "secrets" and parts[4] == "versions":
        return resource_name.strip()
    raise RuntimeError("OPENAI_API_KEY_SECRET must be a Secret Manager resource name")


def access_secret_with_gcloud(resource_name: str) -> str:
    normalized = normalize_secret_version_resource(resource_name)
    parts = normalized.split("/")
    project = parts[1]
    secret = parts[3]
    version = parts[5]
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

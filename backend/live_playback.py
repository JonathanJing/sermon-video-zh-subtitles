from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cloud import read_gcs_text, write_gcs_text


VALID_MODES = {"idle", "live", "paused", "ended"}
VALID_ACTIONS = {"start", "pause", "resume", "adjustOffset", "jumpToSegment", "end"}
GCS_READ_CACHE_TTL_SECONDS = 2.0


class LivePlaybackStore:
    def __init__(self, root: Path, gcs_prefix: str | None = None) -> None:
        self.root = root
        self.gcs_prefix = normalize_gcs_prefix(gcs_prefix)
        self._gcs_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    def status(self, sunday: str) -> dict[str, Any]:
        state = self.read_state(sunday) or empty_state(sunday)
        state["serverNow"] = utc_now()
        return sanitize_state(state)

    def apply_action(self, sunday: str, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip()
        if action not in VALID_ACTIONS:
            raise ValueError("unsupported_live_playback_action")
        current = self.read_state(sunday) or empty_state(sunday)
        now = utc_now()
        if action == "start":
            next_state = self.start_state(sunday, payload, now)
        elif action == "pause":
            next_state = self.pause_state(current, now)
        elif action == "resume":
            next_state = self.resume_state(current, now)
        elif action == "adjustOffset":
            next_state = self.adjust_offset_state(current, payload, now)
        elif action == "jumpToSegment":
            next_state = self.jump_to_segment_state(current, payload, now)
        else:
            next_state = self.end_state(current, now)
        self.write_state(sunday, next_state)
        next_state["serverNow"] = utc_now()
        return sanitize_state(next_state)

    def start_state(self, sunday: str, payload: dict[str, Any], now: str) -> dict[str, Any]:
        base_caption_ms = safe_int(payload.get("baseCaptionMs"), 0)
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        return {
            "schemaVersion": 1,
            "mode": "live",
            "sunday": sunday,
            "startedAt": now,
            "pausedAt": None,
            "baseCaptionMs": base_caption_ms,
            "offsetMs": safe_int(payload.get("offsetMs"), 0),
            "currentSegmentId": safe_segment_id(payload.get("currentSegmentId")),
            "updatedAt": now,
            "version": 1,
            "source": sanitize_source(source, sunday),
        }

    def pause_state(self, current: dict[str, Any], now: str) -> dict[str, Any]:
        if current.get("mode") != "live":
            return bump(current, now)
        current = dict(current)
        current["mode"] = "paused"
        current["pausedAt"] = now
        return bump(current, now)

    def resume_state(self, current: dict[str, Any], now: str) -> dict[str, Any]:
        if current.get("mode") != "paused":
            return bump(current, now)
        playhead_ms = playhead_at(current, current.get("pausedAt") or now)
        current = dict(current)
        current["mode"] = "live"
        current["startedAt"] = now
        current["pausedAt"] = None
        current["baseCaptionMs"] = playhead_ms - safe_int(current.get("offsetMs"), 0)
        return bump(current, now)

    def adjust_offset_state(self, current: dict[str, Any], payload: dict[str, Any], now: str) -> dict[str, Any]:
        current = dict(current)
        current["offsetMs"] = safe_int(current.get("offsetMs"), 0) + safe_int(payload.get("deltaMs"), 0)
        return bump(current, now)

    def jump_to_segment_state(self, current: dict[str, Any], payload: dict[str, Any], now: str) -> dict[str, Any]:
        target_ms = safe_int(payload.get("baseCaptionMs"), 0)
        current = dict(current)
        current["mode"] = "live"
        current["startedAt"] = now
        current["pausedAt"] = None
        current["baseCaptionMs"] = target_ms - safe_int(current.get("offsetMs"), 0)
        current["currentSegmentId"] = safe_segment_id(payload.get("currentSegmentId"))
        if isinstance(payload.get("source"), dict):
            current["source"] = sanitize_source(payload["source"], str(current.get("sunday") or ""))
        return bump(current, now)

    def end_state(self, current: dict[str, Any], now: str) -> dict[str, Any]:
        current = dict(current)
        current["mode"] = "ended"
        current["pausedAt"] = None
        return bump(current, now)

    def read_state(self, sunday: str) -> dict[str, Any] | None:
        local = self.read_local_state(sunday)
        gcs = self.read_gcs_state(sunday)
        if local and gcs:
            return newest_state(local, gcs)
        return local or gcs

    def read_local_state(self, sunday: str) -> dict[str, Any] | None:
        path = self.path_for(sunday)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return sanitize_state(data) if isinstance(data, dict) else None

    def read_gcs_state(self, sunday: str) -> dict[str, Any] | None:
        if not self.gcs_prefix:
            return None
        cache_key = safe_component(sunday)
        cached = self._gcs_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < GCS_READ_CACHE_TTL_SECONDS:
            return cached[1]
        try:
            data = json.loads(read_gcs_text(self.gcs_uri(sunday)))
        except Exception:
            self._gcs_cache[cache_key] = (now, None)
            return None
        state = sanitize_state(data) if isinstance(data, dict) else None
        self._gcs_cache[cache_key] = (now, state)
        return state

    def write_state(self, sunday: str, state: dict[str, Any]) -> None:
        clean = sanitize_state(state)
        path = self.path_for(sunday)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clean, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        self._gcs_cache[safe_component(sunday)] = (time.monotonic(), clean)
        if self.gcs_prefix:
            try:
                write_gcs_text(self.gcs_uri(sunday), path.read_text(encoding="utf-8"))
            except Exception:
                return

    def path_for(self, sunday: str) -> Path:
        return self.root / f"{safe_component(sunday)}.json"

    def gcs_uri(self, sunday: str) -> str:
        if not self.gcs_prefix:
            raise RuntimeError("live playback GCS prefix is not configured")
        return f"{self.gcs_prefix}/{safe_component(sunday)}.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_state(sunday: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schemaVersion": 1,
        "mode": "idle",
        "sunday": sunday,
        "startedAt": None,
        "pausedAt": None,
        "baseCaptionMs": 0,
        "offsetMs": 0,
        "currentSegmentId": None,
        "updatedAt": now,
        "version": 0,
        "source": {"sunday": sunday, "artifactKey": "playback-js"},
    }


def bump(state: dict[str, Any], now: str) -> dict[str, Any]:
    state = dict(state)
    state["updatedAt"] = now
    state["version"] = safe_int(state.get("version"), 0) + 1
    return state


def playhead_at(state: dict[str, Any], at_iso: str) -> int:
    base = safe_int(state.get("baseCaptionMs"), 0)
    offset = safe_int(state.get("offsetMs"), 0)
    started_at = parse_iso(state.get("startedAt"))
    at = parse_iso(at_iso)
    if not started_at or not at:
        return max(0, base + offset)
    elapsed_ms = int((at - started_at).total_seconds() * 1000)
    return max(0, base + offset + elapsed_ms)


def parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def sanitize_state(state: dict[str, Any]) -> dict[str, Any]:
    sunday = safe_sunday(state.get("sunday"))
    mode = str(state.get("mode") or "idle")
    if mode not in VALID_MODES:
        mode = "idle"
    return {
        "schemaVersion": 1,
        "mode": mode,
        "sunday": sunday,
        "startedAt": safe_iso_or_none(state.get("startedAt")),
        "pausedAt": safe_iso_or_none(state.get("pausedAt")),
        "baseCaptionMs": safe_int(state.get("baseCaptionMs"), 0),
        "offsetMs": safe_int(state.get("offsetMs"), 0),
        "currentSegmentId": safe_segment_id(state.get("currentSegmentId")),
        "updatedAt": safe_iso_or_none(state.get("updatedAt")) or utc_now(),
        "version": safe_int(state.get("version"), 0),
        "source": sanitize_source(state.get("source") if isinstance(state.get("source"), dict) else {}, sunday),
        **({"serverNow": safe_iso_or_none(state.get("serverNow"))} if state.get("serverNow") else {}),
    }


def sanitize_source(source: dict[str, Any], sunday: str) -> dict[str, Any]:
    return {
        "sunday": safe_sunday(source.get("sunday") or sunday),
        "artifactKey": safe_source_value(source.get("artifactKey") or "playback-js"),
        "artifactDate": safe_sunday(source.get("artifactDate") or source.get("sunday") or sunday),
    }


def safe_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def safe_iso_or_none(value: Any) -> str | None:
    parsed = parse_iso(value)
    return parsed.isoformat() if parsed else None


def safe_sunday(value: Any) -> str:
    clean = str(value or "").strip()
    return clean if re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean) else "unknown"


def safe_segment_id(value: Any) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", clean)[:120]


def safe_source_value(value: Any) -> str:
    clean = str(value or "").strip()
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", clean)[:120] or "playback-js"


def safe_component(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return clean.strip("._") or "unknown"


def newest_state(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    first_updated = str(first.get("updatedAt") or "")
    second_updated = str(second.get("updatedAt") or "")
    return second if second_updated > first_updated else first


def normalize_gcs_prefix(value: str | None) -> str | None:
    clean = str(value or "").strip().rstrip("/")
    if not clean:
        return None
    if not clean.startswith("gs://"):
        raise ValueError("live playback GCS prefix must start with gs://")
    return clean


def default_live_playback_gcs_prefix(
    artifact_bucket: str | None,
    artifact_prefix: str,
    explicit_prefix: str | None = None,
) -> str | None:
    if explicit_prefix:
        return normalize_gcs_prefix(explicit_prefix)
    if not artifact_bucket:
        return None
    clean_prefix = str(artifact_prefix or "").strip("/")
    object_prefix = "/".join(part for part in [clean_prefix, "live-playback"] if part)
    return f"gs://{artifact_bucket}/{object_prefix}"

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .cloud import parse_gcs_uri


@dataclass(frozen=True)
class LeaseHandle:
    location: str
    owner: str
    generation: int | None = None


def acquire_lease(
    location: str,
    *,
    ttl_seconds: int = 14_400,
    owner: str | None = None,
    now: datetime | None = None,
) -> LeaseHandle | None:
    now = now or datetime.now(timezone.utc)
    owner = owner or uuid.uuid4().hex
    payload = {
        "schemaVersion": 1,
        "status": "active",
        "owner": owner,
        "acquiredAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    if location.startswith("gs://"):
        return acquire_gcs_lease(location, payload, now)
    return acquire_local_lease(Path(location), payload, now)


def release_lease(handle: LeaseHandle) -> None:
    if handle.location.startswith("gs://"):
        release_gcs_lease(handle)
        return
    path = Path(handle.location)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if payload.get("owner") == handle.owner:
        path.unlink(missing_ok=True)


def acquire_local_lease(
    path: Path,
    payload: dict[str, Any],
    now: datetime,
) -> LeaseHandle | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not lease_expired(read_json(path), now):
                return None
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        return LeaseHandle(str(path), str(payload["owner"]))
    return None


def acquire_gcs_lease(
    location: str,
    payload: dict[str, Any],
    now: datetime,
) -> LeaseHandle | None:
    from google.api_core.exceptions import NotFound, PreconditionFailed  # type: ignore
    from google.cloud import storage  # type: ignore

    parsed = parse_gcs_uri(location)
    blob = storage.Client().bucket(parsed.bucket).blob(parsed.object_name)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        blob.upload_from_string(
            text,
            content_type="application/json; charset=utf-8",
            if_generation_match=0,
        )
    except PreconditionFailed:
        try:
            blob.reload()
            existing = json.loads(blob.download_as_bytes().decode("utf-8"))
        except NotFound:
            return acquire_gcs_lease(location, payload, now)
        except json.JSONDecodeError:
            existing = {}
        if not lease_expired(existing, now):
            return None
        generation = int(blob.generation)
        try:
            blob.upload_from_string(
                text,
                content_type="application/json; charset=utf-8",
                if_generation_match=generation,
            )
        except PreconditionFailed:
            return None
    blob.reload()
    return LeaseHandle(location, str(payload["owner"]), int(blob.generation))


def release_gcs_lease(handle: LeaseHandle) -> None:
    from google.api_core.exceptions import NotFound, PreconditionFailed  # type: ignore
    from google.cloud import storage  # type: ignore

    parsed = parse_gcs_uri(handle.location)
    blob = storage.Client().bucket(parsed.bucket).blob(parsed.object_name)
    try:
        blob.delete(if_generation_match=handle.generation)
    except (NotFound, PreconditionFailed):
        return


def lease_expired(payload: dict[str, Any] | None, now: datetime) -> bool:
    try:
        expires_at = datetime.fromisoformat(str((payload or {}).get("expiresAt") or ""))
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None

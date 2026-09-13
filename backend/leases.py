from __future__ import annotations

import json
import fcntl
import math
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
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
    token: str | None = None
    expires_at: str | None = None


class LeaseLost(RuntimeError):
    """The caller must stop work; this handle can no longer authorize a stage."""


def validate_ttl(ttl_seconds: float) -> None:
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
        raise ValueError("Lease TTL must be positive and finite")


def acquire_lease(
    location: str,
    *,
    ttl_seconds: int = 14_400,
    owner: str | None = None,
    now: datetime | None = None,
) -> LeaseHandle | None:
    validate_ttl(ttl_seconds)
    now = now or datetime.now(timezone.utc)
    owner = owner or uuid.uuid4().hex
    payload = {
        "schemaVersion": 1,
        "status": "active",
        "owner": owner,
        # Owner is a label, not an acquisition identity (it may be reused).
        "token": uuid.uuid4().hex,
        "acquiredAt": now.isoformat(),
        "expiresAt": (now + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    if location.startswith("gs://"):
        return acquire_gcs_lease(location, payload, now)
    return acquire_local_lease(Path(location).resolve(), payload, now)


def release_lease(handle: LeaseHandle) -> None:
    if handle.location.startswith("gs://"):
        release_gcs_lease(handle)
        return
    path = Path(handle.location)
    with local_transaction(path):
        if local_owned(handle, read_json(path)):
            path.unlink(missing_ok=True)


@contextmanager
def local_transaction(path: Path):
    """One stable inode serializes takeover, renewal and release across processes.

    Never unlink this sidecar: it also retains the monotonically increasing
    local acquisition epoch after the JSON lease has been released.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path.with_name(path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield stream
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_local_lease(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def owns(handle: LeaseHandle, payload: dict[str, Any] | None) -> bool:
    return bool(handle.token and payload and payload.get("status") == "active"
                and payload.get("owner") == handle.owner and payload.get("token") == handle.token)


def local_owned(handle: LeaseHandle, payload: dict[str, Any] | None) -> bool:
    return owns(handle, payload) and payload.get("generation") == handle.generation


def acquire_local_lease(
    path: Path,
    payload: dict[str, Any],
    now: datetime,
) -> LeaseHandle | None:
    with local_transaction(path) as counter:
        if path.exists() and not lease_expired(read_json(path), now):
            return None
        generation = int(counter.read() or "0") + 1
        counter.seek(0)
        counter.write(str(generation))
        counter.truncate()
        counter.flush()
        os.fsync(counter.fileno())
        payload = {**payload, "generation": generation}
        write_local_lease(path, payload)
        return LeaseHandle(str(path), str(payload["owner"]), generation, payload["token"], payload["expiresAt"])


def acquire_gcs_lease(
    location: str,
    payload: dict[str, Any],
    now: datetime,
) -> LeaseHandle | None:
    from google.api_core.exceptions import NotFound, PreconditionFailed  # type: ignore
    from google.cloud import storage  # type: ignore

    parsed = parse_gcs_uri(location)
    blob = storage.Client().bucket(parsed.bucket).blob(parsed.object_name)
    for _ in range(3):
        generation = 0
        try:
            upload_lease(blob, payload, generation)
            return gcs_handle(location, payload, blob)
        except PreconditionFailed:
            pass
        try:
            blob.reload(timeout=10, retry=None)
            generation = int(blob.generation)
            existing = decode_payload(blob.download_as_bytes(if_generation_match=generation, timeout=10, retry=None))
        except NotFound:
            continue
        except PreconditionFailed:
            return None
        if not lease_expired(existing, now):
            return None
        try:
            upload_lease(blob, payload, generation)
        except PreconditionFailed:
            return None
        # Use the generation returned by this upload, never reload a newer owner.
        return gcs_handle(location, payload, blob)
    return None


def upload_lease(blob, payload, generation, *, timeout=10):
    blob.upload_from_string(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                            content_type="application/json; charset=utf-8",
                            if_generation_match=generation, timeout=timeout, retry=None)


def gcs_handle(location, payload, blob):
    return LeaseHandle(location, str(payload["owner"]), int(blob.generation), payload["token"], payload["expiresAt"])


def decode_payload(raw):
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def gcs_owned_blob(handle, *, timeout=10):
    from google.api_core.exceptions import NotFound, PreconditionFailed  # type: ignore
    from google.cloud import storage  # type: ignore

    if handle.generation is None or not handle.token:
        raise LeaseLost("Lease handle has no acquisition fencing identity")
    parsed = parse_gcs_uri(handle.location)
    blob = storage.Client().bucket(parsed.bucket).blob(parsed.object_name)
    try:
        payload = decode_payload(blob.download_as_bytes(if_generation_match=handle.generation, timeout=timeout, retry=None))
    except (NotFound, PreconditionFailed) as exc:
        raise LeaseLost("Lease generation changed or disappeared") from exc
    if not owns(handle, payload):
        raise LeaseLost("Lease acquisition identity changed")
    return blob, payload


def assert_lease_owned(handle: LeaseHandle, *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if handle.location.startswith("gs://"):
        _, payload = gcs_owned_blob(handle)
        if lease_expired(payload, now):
            raise LeaseLost("Lease expired")
    else:
        with local_transaction(Path(handle.location)):
            payload = read_json(Path(handle.location))
            if not local_owned(handle, payload) or lease_expired(payload, now):
                raise LeaseLost("Lease expired or acquisition identity changed")


def renew_lease(handle: LeaseHandle, *, ttl_seconds: float = 14_400, now: datetime | None = None) -> LeaseHandle:
    """Conditional renewal cannot revive an expired lease or adopt a successor."""
    validate_ttl(ttl_seconds)
    fixed_now = now
    now = now or datetime.now(timezone.utc)
    if handle.location.startswith("gs://"):
        from google.api_core.exceptions import NotFound, PreconditionFailed  # type: ignore
        timeout = min(10, ttl_seconds / 6)
        blob, payload = gcs_owned_blob(handle, timeout=timeout)
        now = fixed_now or datetime.now(timezone.utc)
        if lease_expired(payload, now):
            raise LeaseLost("Expired lease cannot be renewed")
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        payload = {**payload, "expiresAt": expires_at, "renewedAt": now.isoformat()}
        try:
            upload_lease(blob, payload, handle.generation, timeout=timeout)
        except (NotFound, PreconditionFailed) as exc:
            raise LeaseLost("Lease changed during renewal") from exc
        return gcs_handle(handle.location, payload, blob)
    path = Path(handle.location)
    with local_transaction(path):
        now = fixed_now or datetime.now(timezone.utc)
        payload = read_json(path)
        if not local_owned(handle, payload) or lease_expired(payload, now):
            raise LeaseLost("Expired or replaced lease cannot be renewed")
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        payload = {**payload, "expiresAt": expires_at, "renewedAt": now.isoformat()}
        write_local_lease(path, payload)
    return LeaseHandle(handle.location, handle.owner, handle.generation, handle.token, expires_at)


def release_gcs_lease(handle: LeaseHandle) -> None:
    from google.api_core.exceptions import NotFound, PreconditionFailed  # type: ignore
    try:
        blob, _ = gcs_owned_blob(handle)
        blob.delete(if_generation_match=handle.generation, timeout=10, retry=None)
    except (LeaseLost, NotFound, PreconditionFailed):
        return


class LeaseGuard:
    """Renew in the background; the execution owner must poll check().

    A monotonic deadline still stops the execution owner when renewal I/O hangs.
    checkpoint() additionally performs a current-owner read before stage effects.
    This fences this process, not already submitted remote/cloud operations.
    """
    def __init__(self, handle: LeaseHandle, *, ttl_seconds: float, renewer=renew_lease,
                 checker=assert_lease_owned, releaser=release_lease):
        validate_ttl(ttl_seconds)
        self.handle, self.ttl_seconds = handle, ttl_seconds
        self.renewer, self.checker, self.releaser = renewer, checker, releaser
        self._stop = threading.Event()
        self._mutex, self._io = threading.Lock(), threading.Lock()
        self._lost = False
        self._deadline = 0.0
        self._thread = None

    def _install(self, handle):
        remaining = (datetime.fromisoformat(handle.expires_at) - datetime.now(timezone.utc)).total_seconds()
        margin = min(1.0, self.ttl_seconds / 10)
        with self._mutex:
            self.handle = handle
            self._deadline = time.monotonic() + max(0.0, remaining - margin)

    def __enter__(self):
        try:
            self._install(self.renewer(self.handle, ttl_seconds=self.ttl_seconds))
            self.check()
        except Exception:
            self.releaser(self.handle)
            raise
        self._thread = threading.Thread(target=self._renew_loop, name="sermon-lease-renewal", daemon=True)
        self._thread.start()
        return self

    def _renew_loop(self):
        interval = min(30.0, self.ttl_seconds / 3)
        while not self._stop.wait(interval):
            try:
                with self._io:
                    if self._stop.is_set():
                        return
                    self.check()
                    # An in-flight renewal has its own bounded acknowledgement
                    # budget; a four-hour lease must not permit a hung RPC to
                    # leave the child running for another four hours.
                    with self._mutex:
                        self._deadline = min(self._deadline, time.monotonic() + interval)
                    renewed = self.renewer(self.handle, ttl_seconds=self.ttl_seconds)
                    try:
                        self.check()
                    except LeaseLost:
                        self.releaser(renewed)
                        raise
                    self._install(renewed)
                    if self._stop.is_set():
                        self.releaser(renewed)
                        return
            except Exception:
                with self._mutex:
                    self._lost = True
                return

    def check(self):
        with self._mutex:
            if self._lost or time.monotonic() >= self._deadline:
                self._lost = True
                raise LeaseLost("Lease ownership or renewal deadline lost; execution must stop")

    def checkpoint(self):
        self.check()
        try:
            with self._io:
                self.checker(self.handle)
        except Exception as exc:
            with self._mutex:
                self._lost = True
            raise LeaseLost("Lease ownership could not be verified; execution must stop") from exc
        self.check()

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self.checkpoint()
        finally:
            self._stop.set()
            if self._thread:
                self._thread.join(timeout=1)
            # If renewal is still in flight this old-generation release is safe;
            # the worker releases its own renewed handle when it eventually exits.
            try:
                self.releaser(self.handle)
            except Exception:
                if exc_type is None:
                    raise


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

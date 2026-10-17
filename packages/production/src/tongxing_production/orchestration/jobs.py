"""Durable local jobs for trusted backend commands, never agent-supplied shells.

A successful job means its command exited zero; the workflow adapter must still
validate its artifacts. An identity is single-use even after failure. Recovery
from an uncertain outcome requires reconciliation, never an automatic respawn.
Request files and logs are private local evidence, not tool-return payloads.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
import uuid

from ..storage.files import (  # noqa: F401  the job store's file primitives, under their old names
    _digest, _directory_fd, _open_lock_file, _persist, _read, _reject_link, _sync_directory,
    _sync_directory_ancestry, utc_now)
from ..storage.locks import _LOCK_FDS
from . import jobs_host as _host


def __getattr__(name):
    # Callers that read the former module constant REPO_ROOT (the checkout the host binds).
    if name == "REPO_ROOT":
        return _host.current().repo_root
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _HostModule:
    def __init__(self, get):
        object.__setattr__(self, "_get", get)

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def __setattr__(self, name, value):
        setattr(self._get(), name, value)


# Job liveness stays in the checkout (orchestration batch); looked up at every use.
liveness = _HostModule(lambda: _host.current().liveness())


def bounded_process(*arguments, **options):
    return _host.current().bounded_process(*arguments, **options)

SCHEMA = "sermon-workflow-job-v1"
STATUSES = {"queued", "running", "succeeded", "failed", "uncertain"}
ACTIVE = {"queued", "running"}


def _paths(root, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{64}", job_id):
        raise ValueError("Invalid workflow job identity")
    root = Path(root).resolve()
    folder, locks = root / job_id, root / ".locks"
    _reject_link(locks, directory=True)
    _reject_link(folder, directory=True)
    for name in ("request.json", "state.json", "worker.log"):
        _reject_link(folder / name, directory=False)
    lock_path = locks / (job_id + ".lock")
    _reject_link(lock_path, directory=False)
    return root, folder, lock_path


def _public(job_id, status):
    return {"jobId": job_id, "status": status}


@contextmanager
def _lock(root, job_id):
    root, folder, path = _paths(root, job_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.mkdir(exist_ok=True, mode=0o700)
    directory_fd = _directory_fd(path.parent)
    try:
        fd = _open_lock_file(path, directory_fd)
    finally:
        os.close(directory_fd)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("Workflow lock must be a regular file")
    held = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = True
        except BlockingIOError:
            pass
        yield folder, fd, held
    finally:
        # Never LOCK_UN: a detached worker/child may still own this description.
        os.close(fd)


def _request_valid(request, job_id):
    return (isinstance(request, dict) and request.get("schemaVersion") == SCHEMA
            and request.get("jobId") == job_id and _digest(request.get("identity")) == job_id
            and request.get("commandSha256") == _digest(request.get("command"))
            and ("livenessPolicy" not in request or liveness.valid_policy(request["livenessPolicy"])))


def _state(folder, job_id):
    try:
        value = _read(folder / "state.json")
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("jobId") != job_id or value.get("schemaVersion") != SCHEMA or value.get("status") not in STATUSES:
        return None
    return value


def _write_state(folder, job_id, status, **fields):
    previous = _state(folder, job_id) or {}
    binding = {key: previous[key] for key in ("requestSha256", "accountingContextSha256") if key in previous}
    state = {"schemaVersion": SCHEMA, "jobId": job_id, "status": status, "updatedAt": utc_now(), **binding, **fields}
    _persist(folder / "state.json", state)
    return state


def _inspect_locked(folder, job_id, held, *, reconcile=True):
    state = _state(folder, job_id)
    if not folder.exists():
        raise FileNotFoundError("Unknown workflow job")
    if state is None:
        if not held:
            return _public(job_id, "queued")
        if reconcile:
            _write_state(folder, job_id, "uncertain", reason="missing_or_invalid_state")
        return _public(job_id, "uncertain")
    try:
        request = _read(folder / "request.json")
        bound = _request_valid(request, job_id) and state.get("requestSha256") == _digest(request)
    except (OSError, ValueError, TypeError):
        bound = False
    if not bound:
        if held and reconcile:
            _write_state(folder, job_id, "uncertain", reason="invalid_request_binding")
        return _public(job_id, "uncertain")
    if held and state["status"] in ACTIVE:
        if reconcile:
            _write_state(folder, job_id, "uncertain", reason="owner_disappeared", previousStatus=state["status"])
        return _public(job_id, "uncertain")
    return _public(job_id, state["status"])


def inspect_job(root: Path, job_id: str) -> dict:
    """Return compact status; missing owner is uncertainty, not permission to retry."""
    with _lock(root, job_id) as (folder, _fd, held):
        return _inspect_locked(folder, job_id, held)


def peek_job(root: Path, job_id: str) -> dict:
    """Inspect existing evidence without creating locks or reconciling state.

    An abandoned owner is still reported as uncertain; only execution inspection
    persists that reconciliation. A read-only lock probe never launches work.
    """
    _, folder, path = _paths(root, job_id)
    try:
        directory_fd = _directory_fd(path.parent)
    except FileNotFoundError:
        return _inspect_locked(folder, job_id, True, reconcile=False)
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        except FileNotFoundError:
            return _inspect_locked(folder, job_id, True, reconcile=False)
    finally:
        os.close(directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Workflow lock must be a regular file")
        held = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = True
        except BlockingIOError:
            pass
        return _inspect_locked(folder, job_id, held, reconcile=False)
    finally:
        os.close(fd)


def start_job(root: Path, identity: dict, command: list[str], timeout_seconds: float,
              *, liveness_policy: dict | None = None) -> dict:
    """Launch exactly once per identity; caller supplies a fixed trusted argv.

    This is a backend function, not a model tool accepting arbitrary commands.
    Identities/argv must not contain credential material. Arguments never pass
    through a shell. Existing failed/uncertain jobs are returned, not restarted.
    """
    if not isinstance(identity, dict) or not identity:
        raise ValueError("A non-empty workflow identity is required")
    if not isinstance(command, list) or not command or not command[0] or any(not isinstance(arg, str) or "\0" in arg for arg in command):
        raise ValueError("A trusted non-empty command argument list is required")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("A positive finite job timeout is required")
    job_id = _digest(identity)
    root = Path(root).resolve()
    request = {"schemaVersion": SCHEMA, "jobId": job_id, "identity": identity,
               "command": command, "commandSha256": _digest(command), "timeoutSeconds": float(timeout_seconds)}
    if liveness_policy is not None:
        request["livenessPolicy"] = liveness.validate_policy(liveness_policy)
    with _lock(root, job_id) as (folder, fd, held):
        if folder.exists():
            try:
                existing = _read(folder / "request.json")
            except (OSError, ValueError):
                return _inspect_locked(folder, job_id, held)
            if not _request_valid(existing, job_id) or existing != request:
                raise ValueError("Existing workflow identity has different or invalid execution parameters")
            return _inspect_locked(folder, job_id, held)
        if not held:
            # A creator has the lock but has not yet published the directory.
            return _public(job_id, "queued")
        folder.mkdir(mode=0o700)
        # Publish the uncertainty marker and its entire directory chain before
        # a worker can start. Other admissions may have just created ancestors.
        os.fsync(fd)
        _sync_directory(root / ".locks")
        _sync_directory_ancestry(root)
        _persist(folder / "request.json", request)
        from ..observability import profile as accounting_profile
        accounting_context = accounting_profile.job_context(job_id)
        context_binding = {}
        if accounting_context is not None:
            _persist(folder / "accounting-context.json", accounting_context)
            context_binding['accountingContextSha256'] = _digest(accounting_context)
        _write_state(folder, job_id, "queued", queuedAt=utc_now(), requestSha256=_digest(request), **context_binding)
        # State precedes spawn. Any crash in this interval becomes uncertain;
        # the lock's inherited open-file description closes the post-spawn gap.
        try:
            directory_fd = _directory_fd(folder)
            try:
                log_fd = os.open("worker.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 0o600, dir_fd=directory_fd)
            finally:
                os.close(directory_fd)
            if not stat.S_ISREG(os.fstat(log_fd).st_mode):
                os.close(log_fd)
                raise ValueError("Workflow log must be a regular file")
            with os.fdopen(log_fd, "ab", buffering=0) as log:
                process = subprocess.Popen(
                    _host.current().worker_command(root, job_id, fd),
                    cwd=_host.current().repo_root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True, pass_fds=(fd,),
                )
        except OSError as exc:
            # Popen raised before returning a child handle. Still do not retry
            # this identity automatically; recording failure is recoverable.
            _write_state(folder, job_id, "failed", reason="worker_spawn_failed", errorType=type(exc).__name__)
            return _public(job_id, "failed")
        threading.Thread(target=process.wait, daemon=True, name="workflow-job-reaper").start()
        # Do not write state here: the worker may already have completed.
        state = _state(folder, job_id)
        return _public(job_id, state["status"] if state else "queued")


def _worker(root, job_id, lock_fd):
    root, folder, lock_path = _paths(root, job_id)
    # Only a inherited descriptor for this exact persistent lock is accepted.
    actual, expected = os.fstat(lock_fd), lock_path.stat()
    if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
        raise ValueError("Worker lock does not match job")
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    request = _read(folder / "request.json")
    if not _request_valid(request, job_id):
        raise ValueError("Invalid durable job request")
    state = _state(folder, job_id)
    if state is None or state["status"] != "queued" or state.get("requestSha256") != _digest(request):
        # Never execute a stale/replayed worker entrypoint.
        return 2
    environment = None
    if 'accountingContextSha256' in state:
        from ..observability import profile as accounting_profile
        accounting_context = _read(folder / 'accounting-context.json')
        if _digest(accounting_context) != state['accountingContextSha256']:
            raise ValueError('job_accounting_context_changed')
        environment = accounting_profile.restore_job_environment(accounting_context, job_id)
    token = _LOCK_FDS.set((lock_fd,))
    os.environ["SERMON_HARNESS_GUARDED_CHILDREN"] = "1"
    _write_state(folder, job_id, "running", workerPid=os.getpid(), startedAt=utc_now())
    monitor = liveness.Monitor(folder, request).start() if 'livenessPolicy' in request else None
    try:
        options = {'cancel_event': monitor.cancel} if monitor else {}
        if environment is not None: options['env'] = environment
        result = bounded_process(request["command"], timeout=request["timeoutSeconds"], cwd=_host.current().repo_root,
                                 stdin=subprocess.DEVNULL, check=False, **options)
        if monitor and (monitor.reason or (result.returncode == 0 and not monitor.completed())):
            _write_state(folder, job_id, "uncertain", reason=monitor.reason,
                         completedAt=utc_now(), automaticRetryAllowed=False)
            return 0
        _write_state(folder, job_id, "succeeded" if result.returncode == 0 else "failed",
                     returnCode=result.returncode, reason="command_completed", completedAt=utc_now())
    except (subprocess.TimeoutExpired, _host.current().execution_terminated()) as exc:
        cleanup_uncertain = any("cleanup failed" in note.lower() for note in getattr(exc, "__notes__", []))
        liveness_reason = monitor.reason if monitor else None
        reason = "cleanup_uncertain" if cleanup_uncertain else liveness_reason or "timeout_or_termination"
        _write_state(folder, job_id, "uncertain" if cleanup_uncertain or liveness_reason else "failed",
                     reason=reason,
                     errorType=type(exc).__name__, completedAt=utc_now())
    except OSError as exc:
        _write_state(folder, job_id, "failed", reason="command_launch_failed", errorType=type(exc).__name__)
    except BaseException as exc:
        _write_state(folder, job_id, "uncertain", reason="worker_interrupted", errorType=type(exc).__name__)
    finally:
        if monitor:
            monitor.close()
        _LOCK_FDS.reset(token)
        os.close(lock_fd)
    return 0


# Public names for the orchestration package. Each delegates at call time, so
# a test that patches the private implementation still intercepts the call.
def digest(value):
    return _digest(value)


def paths(root, job_id):
    return _paths(root, job_id)


def lock(root, job_id):
    return _lock(root, job_id)


def persist(path, value):
    return _persist(path, value)


def sync_directory(path):
    return _sync_directory(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("worker",))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--lock-fd", required=True, type=int)
    args = parser.parse_args()
    return _worker(args.root, args.job_id, args.lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())

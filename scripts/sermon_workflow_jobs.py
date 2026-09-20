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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sermon_execution_harness import (  # noqa: E402
    ExecutionTerminated, _LOCK_FDS, bounded_process, utc_now,
)

SCHEMA = "sermon-workflow-job-v1"
STATUSES = {"queued", "running", "succeeded", "failed", "uncertain"}
ACTIVE = {"queued", "running"}


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _reject_link(path, *, directory):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ValueError("Workflow job descendants must be ordinary directories/files, never symlinks")


def _directory_fd(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("Workflow directory is not a regular directory")
    return fd


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


def _sync_directory(path):
    fd = _directory_fd(path)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _persist(path, value):
    # Anchor every operation to an already-open, non-symlink directory. A
    # descendant path cannot redirect the durable state write outside the job.
    directory_fd = _directory_fd(path.parent)
    temporary = "." + path.name + "." + uuid.uuid4().hex
    try:
        try:
            mode = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None and not stat.S_ISREG(mode):
            raise ValueError("Workflow evidence must be a regular file, never a symlink")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _read(path):
    directory_fd = _directory_fd(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    with os.fdopen(fd, encoding="utf-8") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Workflow evidence must be a regular file")
        return json.load(stream)


def _public(job_id, status):
    return {"jobId": job_id, "status": status}


def _open_lock_file(path, directory_fd):
    """Tolerate Darwin's transient ENOENT on concurrent O_CREAT/O_NOFOLLOW.

    This retries only admission-file creation, never command execution. Recheck
    the directory inode and link/type constraints on every retry; a removed or
    replaced directory is not a transient creation race and must fail closed.
    """
    opened = os.fstat(directory_fd)
    for attempt in range(10):
        try:
            return os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                           0o600, dir_fd=directory_fd)
        except FileNotFoundError:
            current = path.parent.lstat()
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
                raise ValueError("Workflow lock directory changed during admission")
            _reject_link(path, directory=False)
            if attempt == 9:
                raise
            time.sleep(.005 * (attempt + 1))


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
            and request.get("commandSha256") == _digest(request.get("command")))


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
    binding = {"requestSha256": previous["requestSha256"]} if "requestSha256" in previous else {}
    state = {"schemaVersion": SCHEMA, "jobId": job_id, "status": status, "updatedAt": utc_now(), **binding, **fields}
    _persist(folder / "state.json", state)
    return state


def _inspect_locked(folder, job_id, held):
    state = _state(folder, job_id)
    if not folder.exists():
        raise FileNotFoundError("Unknown workflow job")
    if state is None:
        if not held:
            return _public(job_id, "queued")
        _write_state(folder, job_id, "uncertain", reason="missing_or_invalid_state")
        return _public(job_id, "uncertain")
    try:
        request = _read(folder / "request.json")
        bound = _request_valid(request, job_id) and state.get("requestSha256") == _digest(request)
    except (OSError, ValueError, TypeError):
        bound = False
    if not bound:
        if held:
            _write_state(folder, job_id, "uncertain", reason="invalid_request_binding")
        return _public(job_id, "uncertain")
    if held and state["status"] in ACTIVE:
        _write_state(folder, job_id, "uncertain", reason="owner_disappeared", previousStatus=state["status"])
        return _public(job_id, "uncertain")
    return _public(job_id, state["status"])


def inspect_job(root: Path, job_id: str) -> dict:
    """Return compact status; missing owner is uncertainty, not permission to retry."""
    with _lock(root, job_id) as (folder, _fd, held):
        return _inspect_locked(folder, job_id, held)


def start_job(root: Path, identity: dict, command: list[str], timeout_seconds: float) -> dict:
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
        _sync_directory(root.parent)
        _sync_directory(root)
        _persist(folder / "request.json", request)
        _write_state(folder, job_id, "queued", queuedAt=utc_now(), requestSha256=_digest(request))
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
                    [sys.executable, str(Path(__file__).resolve()), "worker", "--root", str(root),
                     "--job-id", job_id, "--lock-fd", str(fd)],
                    cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
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
    token = _LOCK_FDS.set((lock_fd,))
    os.environ["SERMON_HARNESS_GUARDED_CHILDREN"] = "1"
    _write_state(folder, job_id, "running", workerPid=os.getpid(), startedAt=utc_now())
    try:
        result = bounded_process(request["command"], timeout=request["timeoutSeconds"], cwd=REPO_ROOT,
                                 stdin=subprocess.DEVNULL, check=False)
        _write_state(folder, job_id, "succeeded" if result.returncode == 0 else "failed",
                     returnCode=result.returncode, reason="command_completed", completedAt=utc_now())
    except (subprocess.TimeoutExpired, ExecutionTerminated) as exc:
        cleanup_uncertain = any("cleanup failed" in note.lower() for note in getattr(exc, "__notes__", []))
        _write_state(folder, job_id, "uncertain" if cleanup_uncertain else "failed",
                     reason="cleanup_uncertain" if cleanup_uncertain else "timeout_or_termination",
                     errorType=type(exc).__name__, completedAt=utc_now())
    except OSError as exc:
        _write_state(folder, job_id, "failed", reason="command_launch_failed", errorType=type(exc).__name__)
    except BaseException as exc:
        _write_state(folder, job_id, "uncertain", reason="worker_interrupted", errorType=type(exc).__name__)
    finally:
        _LOCK_FDS.reset(token)
        os.close(lock_fd)
    return 0


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

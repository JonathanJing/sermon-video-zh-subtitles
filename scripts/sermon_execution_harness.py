"""Local execution primitives; artifact validators remain the completion authority.

Locks follow the canonical work directory, not the caller's output root. Lock
inodes are never unlinked. Children inherit the descriptor so killing a parent
does not admit another local writer while its child is still running.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

_LOCK_FDS = ContextVar("sermon_work_lock_fds", default=())


class WorkAlreadyRunning(RuntimeError):
    pass


class RemoteOutcomeUnknown(RuntimeError):
    """Connection loss is not proof that the remote model stopped."""


class ExecutionTerminated(InterruptedError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def work_lock(work):
    work = Path(work).resolve()
    folder = work.parent / ".harness-locks"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(str(work).encode()).hexdigest()
    fd = os.open(folder / f"{key}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    token = None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkAlreadyRunning("This canonical work directory already has an active writer") from exc
        token = _LOCK_FDS.set((*_LOCK_FDS.get(), fd))
        yield
    finally:
        if token is not None:
            _LOCK_FDS.reset(token)
        # Do not LOCK_UN: inherited child descriptors must keep this lock alive.
        os.close(fd)


def _terminate_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Kill surviving grandchildren even if the direct child has exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        # A daemon that escaped the process group can retain a pipe. Do not
        # wait forever for its EOF. Escaped daemons are outside our group contract.
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        process.wait(timeout=2)


def bounded_process(command, *, timeout, check=False, capture_output=False,
                    stdout=None, stderr=None, text=False, **kwargs):
    """subprocess.run subset with a finite deadline and process-group cleanup."""
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("A positive finite command timeout is required")
    if isinstance(command, (str, bytes)) or kwargs.get("shell"):
        raise ValueError("Use an explicit argument list, never a local shell")
    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("capture_output conflicts with explicit streams")
        stdout = stderr = subprocess.PIPE
    previous_handler = None
    sentinel_read = sentinel_write = None
    if threading.current_thread() is threading.main_thread():
        previous_handler = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            raise ExecutionTerminated("Execution received a termination request")
        signal.signal(signal.SIGTERM, terminate)
    try:
        actual_command = command
        inherited = _LOCK_FDS.get()
        if os.environ.get("SERMON_HARNESS_GUARDED_CHILDREN") == "1":
            # Temporal cancellation can interrupt several nested independent
            # process groups. Every level owns a pipe to the next guardian;
            # even SIGKILL of an intermediate owner closes its pipe and cascades
            # cleanup, without racing equal graceful-shutdown deadlines.
            sentinel_read, sentinel_write = os.pipe()
            actual_command = [sys.executable, str(Path(__file__).with_name("sermon_guarded_command.py")),
                              "--owner-fd", str(sentinel_read)]
            for fd in inherited:
                actual_command += ["--inherit-fd", str(fd)]
            actual_command += ["--", *command]
            inherited = (*inherited, sentinel_read)
            provided_environment = kwargs.pop("env", None)
            environment = dict(os.environ if provided_environment is None else provided_environment)
            environment["SERMON_HARNESS_GUARDED_CHILDREN"] = "1"
            kwargs["env"] = environment
        try:
            process = subprocess.Popen(actual_command, stdout=stdout, stderr=stderr, text=text,
                                       start_new_session=True, pass_fds=inherited, **kwargs)
        finally:
            if sentinel_read is not None:
                os.close(sentinel_read)
                sentinel_read = None
        try:
            output, errors = process.communicate(timeout=timeout)
        except BaseException as original:
            try:
                _terminate_group(process)
            except (OSError, subprocess.SubprocessError) as cleanup_error:
                # Cleanup failure must never hide timeout/cancellation identity.
                original.add_note("Process cleanup failed: " + type(cleanup_error).__name__)
            raise
    finally:
        if sentinel_read is not None:
            os.close(sentinel_read)
        if sentinel_write is not None:
            os.close(sentinel_write)
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)
    result = subprocess.CompletedProcess(command, process.returncode, output, errors)
    if check:
        result.check_returncode()
    return result


class Execution:
    """Per-attempt operational status, separate from audio/review approval."""

    def __init__(self, work, job_sha256, *, timeout=21600):
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("A positive finite execution timeout is required")
        self.folder = Path(work) / "accounting" / "harness"
        self.attempt = uuid.uuid4().hex
        self.deadline = time.monotonic() + timeout
        self.data = {"schemaVersion": "sermon-execution-harness-v1", "attemptId": self.attempt,
                     "jobSha256": job_sha256, "pid": os.getpid(), "startedAt": utc_now(),
                     "timeoutSeconds": timeout, "status": "running", "stages": [],
                     "approvalGranted": False, "published": False}

    def persist(self):
        self.data["updatedAt"] = utc_now()
        atomic_json(self.folder / "attempts" / f"{self.attempt}.json", self.data)
        atomic_json(self.folder / "latest.json", self.data)

    def __enter__(self):
        previous = self.folder / "latest.json"
        if previous.exists():
            try:
                prior = json.loads(previous.read_text())
                self.data["previousAttemptId"] = prior.get("attemptId")
                self.data["previousStatus"] = prior.get("status")
                self.data["previousAttemptInterrupted"] = prior.get("status") == "running"
            except (ValueError, OSError):
                # Preserve the original corrupt bytes before replacing the derived pointer.
                saved = self.folder / f"unreadable-latest-{self.attempt}.json"
                saved.write_bytes(previous.read_bytes())
                saved.chmod(0o600)
                self.data["previousStateUnreadable"] = True
        self.persist()
        return self

    def remaining(self, limit):
        seconds = min(limit, self.deadline - time.monotonic())
        if seconds <= 0:
            raise subprocess.TimeoutExpired("weekly_execution", self.data["timeoutSeconds"])
        return seconds

    @contextmanager
    def stage(self, name, *, cache_hit=False):
        self.remaining(self.data["timeoutSeconds"])
        item = {"name": name, "startedAt": utc_now(), "status": "running", "cacheHit": bool(cache_hit)}
        self.data["stages"].append(item)
        self.persist()
        started = time.monotonic()
        try:
            yield
            self.remaining(self.data["timeoutSeconds"])
        except BaseException as exc:
            item.update(status="failed", errorType=type(exc).__name__)
            raise
        else:
            item["status"] = "completed"
        finally:
            item.update(endedAt=utc_now(), seconds=time.monotonic() - started)
            self.persist()

    def __exit__(self, kind, error, traceback):
        if kind is None:
            self.data["status"] = "candidate_ready_for_review"
        else:
            self.data["status"] = "waiting_remote_reconciliation" if isinstance(error, RemoteOutcomeUnknown) else "failed"
            self.data["errorType"] = kind.__name__
        self.data["endedAt"] = utc_now()
        self.persist()
        return False

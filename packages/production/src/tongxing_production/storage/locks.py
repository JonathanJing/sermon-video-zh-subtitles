"""Canonical work-directory locks (infrastructure I2).

Locks follow the canonical work directory, not the caller's output root. Lock
inodes are never unlinked. ``_LOCK_FDS`` is the one ContextVar the harness's
``bounded_process`` reads, so children inherit the descriptor and killing a
parent does not admit another local writer while its child is still running.
Extracted from scripts/sermon_execution_harness.py, which re-exports these names.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import os
from pathlib import Path

_LOCK_FDS = ContextVar("sermon_work_lock_fds", default=())


class WorkAlreadyRunning(RuntimeError):
    pass


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

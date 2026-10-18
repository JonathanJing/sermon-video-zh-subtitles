"""Atomic JSON writes and the UTC clock string (infrastructure I2).

Extracted from scripts/sermon_execution_harness.py, which re-exports both names.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import uuid


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


# The durable job store's file primitives, split out of scripts/sermon_workflow_jobs.py in
# the closure window G1 (infrastructure design section 8 item 4); orchestration/jobs.py
# imports them back under the same private names.
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


def _sync_directory(path):
    fd = _directory_fd(path)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_directory_ancestry(path):
    """Persist every containing entry on this filesystem before side effects.

    An existing parent may have just been created by a concurrent admission,
    so stopping at the first directory that exists is insufficient. A mount
    boundary is pre-existing infrastructure, not a directory created here.
    """
    current = Path(path).resolve()
    while True:
        _sync_directory(current)
        parent = current.parent
        if parent == current or parent.stat().st_dev != current.stat().st_dev:
            break
        current = parent


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

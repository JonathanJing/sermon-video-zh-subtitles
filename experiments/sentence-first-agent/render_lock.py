#!/usr/bin/env python3
"""One TTS renderer at a time on the laptop (advisory file lock, stdlib only).

2026-11-21: a sentence repair ran while the Korean render was still going. The machine has
one 36 GiB unified-memory pool, so the second MPS consumer pushed the driver peak to 24.8 GB
and slowed the running language by about 15%. This lock makes that mistake fail loudly instead
of quietly sharing the GPU: every renderer (full render or a single repaired window) takes the
same lock and refuses to start while another one holds it. The override exists for deliberate
component tests, not for production.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "artifacts" / ".tts-render.lock"
BUSY_HINT = ("another TTS renderer is running (pid {pid}, out {out}); the laptop allows one model "
             "copy. Wait for it to exit (pgrep -f tts_sentences.py) or pass --allow-concurrent "
             "for a deliberate component test.")


def holder(path: Path | None = None) -> dict | None:
    path = Path(path or DEFAULT_PATH)
    try:
        return json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    except (FileNotFoundError, IndexError, json.JSONDecodeError):
        return None


def acquire(out: Path | str = "", *, path: Path | None = None, label: str = "",
            allow_concurrent: bool = False):
    """Take the lock and describe the holder; returns the open handle or None when skipped."""
    if allow_concurrent:
        return None
    path = Path(path or DEFAULT_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # a read-only checkout (e.g. inside a Spark fallback container) still gets a lock
        import tempfile
        path = Path(tempfile.gettempdir()) / "tts-render.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
            handle.close()
            raise
        current = holder(path) or {}
        handle.close()
        raise SystemExit(BUSY_HINT.format(pid=current.get("pid", "?"), out=current.get("out", "?")))
    handle.seek(0)
    handle.truncate(0)
    handle.write(json.dumps({"pid": os.getpid(), "out": str(out), "label": label}, ensure_ascii=False) + "\n")
    handle.flush()
    return handle


def release(handle) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


@contextmanager
def locked(out: Path | str = "", *, path: Path | None = None, label: str = "",
           allow_concurrent: bool = False):
    handle = acquire(out, path=path, label=label, allow_concurrent=allow_concurrent)
    try:
        yield handle
    finally:
        release(handle)

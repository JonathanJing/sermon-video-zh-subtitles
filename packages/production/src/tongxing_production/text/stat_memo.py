"""Stat-guarded memo for the canonical Layer 2 worker's repeated binding checks.

The worker re-derives its binding (payload-cache and partial-recovery snapshots,
code identity) before and after every guarded operation. Those derivations are
pure functions of bytes on disk, so a result may be reused while every path it
read still has the same filesystem identity: ``(dev, ino, mode, size,
mtime_ns, ctime_ns)`` from ``lstat``, plus the entry names of every listed
directory. A changed identity means a full recomputation, never a partial one.

What a stat identity detects: any write, truncate, append, chmod, rename-over,
replace, delete or creation (``ctime`` is set by the kernel on every content or
inode change and cannot be set back by ``os.utime``), so a same-size rewrite
that restores ``mtime`` is still caught. What it cannot detect: a change that
leaves ``ctime`` untouched, which needs the system clock moved back, raw block
device writes, or a filesystem that does not maintain ``ctime``; and a write
inside the timestamp granularity of the stat that recorded it. The last case is
closed by the racy rule below (as in Git's index): an entry is memoized only if
every path's ``ctime`` is at least ``RACY_NS`` older than the moment its first
stat was taken, and the identities did not change while the value was computed.

Only successful results are memoized; a failure recomputes every time. The memo
lives in one process: each worker starts empty and pays the full cost once.
"""
from __future__ import annotations

import os
import stat
import threading
import time

# Wider than the coarsest timestamp of a filesystem a run may use (FAT 2 s; HFS+ 1 s).
RACY_NS = 3_000_000_000
_DIRECTORY = ('directory',)  # a directory whose entries are listed by name, not by its own timestamps


def identity(path):
    """The lstat identity of ``path``, or None when it does not exist."""
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def files(*paths):
    return tuple((str(path), identity(path)) for path in paths)


def listing(directory):
    """Every direct entry of ``directory`` with its identity.

    Entries are enumerated on every call, so a created, removed or renamed entry
    changes the fingerprint by name; the directory's own timestamps (which also
    move when a sibling is created) are not needed. A path that is absent or not
    a directory is recorded by its own identity.
    """
    own = identity(directory)
    if own is None or not stat.S_ISDIR(own[2]):
        return ((str(directory), own),)
    with os.scandir(directory) as entries:
        return ((str(directory), _DIRECTORY),
                *sorted((entry.path, _entry_identity(entry)) for entry in entries))


def tree(directory, suffixes):
    """Every file below ``directory`` ending in ``suffixes``, and every symlink, by identity.

    The walk does not follow symlinks, like ``Path.rglob``; any symlink is
    recorded so that one appearing where a glob or path check would meet it
    changes the fingerprint.
    """
    own = identity(directory)
    if own is None or not stat.S_ISDIR(own[2]):
        return ((str(directory), own),)
    rows, pending = [(str(directory), _DIRECTORY)], [str(directory)]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry.path)
                elif entry.name.endswith(suffixes) or entry.is_symlink():
                    rows.append((entry.path, _entry_identity(entry)))
    return tuple(sorted(rows))


def _entry_identity(entry):
    try:
        value = entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _settled(fingerprint, started_ns):
    return all(row is None or row is _DIRECTORY or row[5] < started_ns - RACY_NS for _, row in fingerprint)


class StatMemo:
    """Process-local results keyed by caller key, valid while their fingerprint holds."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}
        self.hits = self.misses = 0

    def get(self, key, fingerprint, compute):
        started_ns = time.time_ns()
        before = fingerprint()
        with self._lock:
            entry = self._entries.get(key)
        if entry is not None and entry[0] == before:
            self.hits += 1
            return entry[1]
        self.misses += 1
        value = compute()
        # Store only a value whose inputs held still while it was computed and whose
        # timestamps are old enough that a later write must produce a new identity.
        if fingerprint() == before and _settled(before, started_ns):
            with self._lock:
                self._entries[key] = (before, value)
        else:
            with self._lock:
                self._entries.pop(key, None)
        return value

    def clear(self):
        with self._lock:
            self._entries.clear()

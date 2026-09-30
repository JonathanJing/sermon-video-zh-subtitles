"""Bounded aggregate JSON evidence; private D1 limits remain unchanged.

Public Candidate packages and derived aggregate bindings may exceed a private
per-revision record. Callers still validate the applicable public schema and
business gates. This module grants no admission or human approval.
"""
import json
import os
import stat
import uuid

from scripts import inspect_canonical_packages as packages
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

MAX_BYTES = packages.MAX_JSON_BYTES


def decode_json(data):
    c.require(type(data) is bytes and len(data) <= MAX_BYTES, 'public_snapshot_size_limit')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=c._pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(c.ContractError('nonfinite_json_number')))
        c.require(c._strict_json(value), 'invalid_public_json_value')
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise c.ContractError('invalid_public_json_bytes') from exc


def read_snapshot(path):
    """Read one stable, caller-selected regular file, including exact byte hash input."""
    path = _safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        c.require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES,
                  'invalid_public_snapshot_file')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        after = os.fstat(fd); named = os.stat(path, follow_symlinks=False)
        identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        c.require(identity(before) == identity(after) == identity(named), 'public_snapshot_changed_during_read')
        return decode_json(data), data
    finally:
        os.close(fd)


def save_once(path, value):
    """Publish a complete immutable aggregate atomically; enforce cap before writing.

    A same-value replay reads the exact existing bytes. Exclusive hard-link
    publication cannot overwrite another writer; a lost acknowledgement leaves
    the complete file available for the same bounded readback/replay.
    """
    c.require(c._strict_json(value), 'invalid_public_json_value')
    data = c.canonical_bytes(value) + b'\n'
    decode_json(data)  # Same reader bound, before creating any output file.
    path = _safe_path(path)
    if path.exists():
        saved, raw = read_snapshot(path)
        c.require(c.canonical_bytes(saved) == c.canonical_bytes(value), 'immutable_public_artifact_changed')
        return raw
    directory = jobs._directory_fd(path.parent)
    temporary = '.' + path.name + '.' + uuid.uuid4().hex
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        except FileExistsError:
            pass  # Verify the competing immutable value below; never replace it.
        os.fsync(directory)
    finally:
        try: os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError: pass
        os.close(directory)
    jobs._sync_directory_ancestry(path.parent)
    saved, raw = read_snapshot(path)
    c.require(c.canonical_bytes(saved) == c.canonical_bytes(value), 'immutable_public_artifact_changed')
    return raw

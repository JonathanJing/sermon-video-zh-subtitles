"""Canonical JSON, fixed error codes and stable snapshot reads.

Canonical JSON v1 = UTF-8, sorted object keys, compact separators, no NaN,
no Unicode normalization, array order preserved. Byte hashes are separate.
These helpers carry no review semantics; receipts and gates live in review/.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat

MAX_BYTES = 256 * 1024


class ContractError(ValueError):
    """Fixed error codes only, without private text or provider exception bodies."""


def require(condition, code):
    if not condition: raise ContractError(code)


def canonical_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError('invalid_json_value') from exc


def canonical_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def bytes_sha256(value):
    require(type(value) is bytes, 'expected_file_bytes')
    return hashlib.sha256(value).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def decode_json(data, *, max_bytes=None):
    max_bytes = MAX_BYTES if max_bytes is None else max_bytes
    require(type(data) is bytes and len(data) <= max_bytes, 'private_contract_size_limit')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError('nonfinite_json_number')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError('invalid_json_bytes') from exc


def read_snapshot(path, *, max_bytes=None):
    """Read a caller-selected regular file; no paths are accepted from receipts."""
    max_bytes = MAX_BYTES if max_bytes is None else max_bytes
    require(type(max_bytes) is int and 0 < max_bytes, 'invalid_snapshot_limit')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= max_bytes, 'invalid_snapshot_file')
        with os.fdopen(os.dup(fd), 'rb') as stream: data = stream.read(max_bytes + 1)
        after = os.fstat(fd); named = os.stat(path, follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(identity(before) == identity(after) == identity(named), 'snapshot_changed_during_read')
        value = decode_json(data, max_bytes=max_bytes)
        return value, data
    finally:
        os.close(fd)


def _strict_json(value):
    if type(value) is dict: return all(type(k) is str and _strict_json(v) for k,v in value.items())
    if type(value) is list: return all(_strict_json(v) for v in value)
    return value is None or type(value) in (str, int, bool) or type(value) is float and math.isfinite(value)

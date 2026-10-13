"""Durable outcome admission for legacy remote calls; never controls Spark.

One accounting output directory is one reconciliation scope. Calls are serialized
under its lock so a crashed/unknown predecessor cannot race another dispatch.
Only response reconciliation is supported: this module never authorizes spending.
"""
from __future__ import annotations
import argparse
from contextvars import ContextVar
import fcntl
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile

_active = ContextVar('api_cli_outcome_admitted', default=False)
SCHEMA = 'sermon-api-cli-outcome-v1'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        for parent in (path.parent, path.parent.parent, path.parent.parent.parent):
            directory = os.open(parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)


def _safe(value, key=''):
    if key.lower() in {'api_key', 'authorization', 'secret', 'access_token'}:
        return '<credential-excluded>'
    if isinstance(value, Path):
        result = {'path': str(value.absolute())}
        if key in {'audio_path', 'file_path', 'schema_path'}:
            result['sha256'] = hashlib.sha256(value.read_bytes()).hexdigest()
        return result
    if isinstance(value, dict): return {k: _safe(v, k) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)): return value
    raise ValueError('api_cli_request_identity_unsupported')


def admitted():
    return _active.get()


def receipt_root(explicit=None):
    if explicit is not None: return Path(explicit)
    from scripts import sermon_accounting as accounting
    directory = accounting.subprocess_environment().get('SERMON_ACCOUNTING_DIR')
    if not directory: raise ValueError('api_cli_outcome_directory_required_before_dispatch')
    return Path(directory) / 'api-cli-outcomes'


def call(caller, args, kwargs, *, purpose, directory=None, guarded=False):
    if _active.get(): return caller(*args, **kwargs)
    if guarded:
        token = _active.set(True)
        try: return caller(*args, **kwargs)
        finally: _active.reset(token)
    bound = inspect.signature(caller).bind(*args, **kwargs)
    bound.apply_defaults()
    identity = _digest({'purpose': purpose, 'arguments': _safe(bound.arguments)})
    root = receipt_root(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in root.glob('*/outcome.json'):
            if json.loads(path.read_text())['status'] != 'returned':
                raise ValueError('api_cli_outcome_reconciliation_required')
        path = root / identity / 'outcome.json'
        if path.exists():
            row = json.loads(path.read_text())
            if row.get('responseSha256') != _digest(row['response']):
                raise ValueError('api_cli_response_identity_mismatch')
            return row['response']
        row = {'schemaVersion': SCHEMA, 'requestSha256': identity, 'purpose': purpose,
               'status': 'started'}
        _write(path, row)
        token = _active.set(True)
        try:
            response = caller(*args, **kwargs)
            _write(path, {**row, 'status': 'returned', 'response': response,
                          'responseSha256': _digest(response)})
            return response
        except BaseException:
            # started is already durable even if this second write cannot finish.
            _write(path, {**row, 'status': 'unknown'})
            raise
        finally: _active.reset(token)


def reconcile(directory, request_sha256, response, evidence):
    """Explicit operator reconciliation of an observed terminal response, no dispatch."""
    if not isinstance(evidence, dict) or not evidence.get('terminalResponseEvidence'):
        raise ValueError('api_cli_terminal_evidence_required')
    root = Path(directory)
    with (root / 'lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / request_sha256 / 'outcome.json'
        row = json.loads(path.read_text())
        if row.get('schemaVersion') != SCHEMA or row.get('requestSha256') != request_sha256:
            raise ValueError('api_cli_request_identity_mismatch')
        if row['status'] not in {'started', 'unknown'}:
            raise ValueError('api_cli_outcome_not_unknown')
        _write(path, {**row, 'status': 'returned', 'response': response,
                     'responseSha256': _digest(response), 'reconciliationEvidenceSha256': _digest(evidence)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--response', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    options = parser.parse_args()
    reconcile(options.directory, options.request_sha256,
              json.loads(options.response.read_text()), json.loads(options.evidence.read_text()))

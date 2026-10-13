"""Durable outcome admission for legacy remote calls; never controls Spark.

One accounting output directory is one reconciliation scope. Calls are serialized
under its lock so a crashed/unknown predecessor cannot race another dispatch.
Only response reconciliation is supported: this module never authorizes spending.
"""
from __future__ import annotations
import argparse
import base64
import urllib.error
import re
from contextvars import ContextVar
import fcntl
import hashlib
import inspect
import marshal
import json
import os
from pathlib import Path
import tempfile

_active = ContextVar('api_cli_outcome_admitted', default=False)
SCHEMA = 'sermon-api-cli-outcome-v3'
V2_SCHEMA = 'sermon-api-cli-outcome-v2'
LEGACY_SCHEMA = 'sermon-api-cli-outcome-v1'
_observer = ContextVar('api_cli_outcome_observer', default=None)


class TerminalOutcomeError(RuntimeError):
    pass


def observed_response(body, *, http_status=200):
    observer = _observer.get()
    if observer is not None:
        observer(body, http_status, None)


def observed_no_dispatch(reason):
    observer = _observer.get()
    if observer is not None: observer(b'', None, reason)


def request_identity(caller, args, kwargs, purpose):
    bound = inspect.signature(caller).bind(*args, **kwargs)
    bound.apply_defaults()
    return _digest({'purpose': purpose, 'arguments': _safe(bound.arguments),
                    'executionBinding': execution_binding(caller, bound.arguments)})


def execution_binding(caller, arguments):
    from scripts.sermon_openai_runtime import selected_route
    function = inspect.unwrap(caller)
    if not inspect.isfunction(function) and not inspect.ismethod(function):
        function = type(caller).__call__
    source = inspect.getsourcefile(function)
    code = getattr(function, '__code__', None)
    transport = getattr(caller, 'execution_identity', None)
    credentials = {key: hashlib.sha256(value.encode()).hexdigest()
                   for key, value in arguments.items()
                   if key.lower() in {'api_key', 'authorization', 'access_token'} and isinstance(value,str) and value}
    return {'runtimeRoute':selected_route(), 'credentialFingerprints':credentials,
            'caller':{'module':function.__module__, 'qualname':function.__qualname__,
                      'sourceSha256':hashlib.sha256(Path(source).read_bytes()).hexdigest() if source and Path(source).is_file() else None,
                      'bytecodeSha256':hashlib.sha256(marshal.dumps(code)).hexdigest() if code else None},
            'transport':transport if isinstance(transport,(dict,str)) else None}


def _validate(row, identity, purpose=None, binding=None):
    if (not isinstance(row, dict) or row.get('schemaVersion') not in {SCHEMA, V2_SCHEMA, LEGACY_SCHEMA}
            or row.get('requestSha256') != identity
            or not isinstance(row.get('purpose'), str) or not row['purpose']
            or (purpose is not None and row['purpose'] != purpose)
            or row.get('status') not in {'started', 'unknown', 'received', 'returned', 'terminal_failure'}):
        raise ValueError('api_cli_receipt_binding_mismatch')
    if row['schemaVersion'] == SCHEMA and (
            not isinstance(row.get('executionBinding'), dict) or
            row.get('executionBindingSha256') != _digest(row['executionBinding']) or
            (binding is not None and row['executionBinding'] != binding)):
        raise ValueError('api_cli_execution_binding_mismatch')
    if row['status'] == 'terminal_failure' and not (
            isinstance(row.get('failureType'), str) or
            ('failure' in row and isinstance(row.get('reconciliationEvidenceSha256'), str))):
        raise ValueError('api_cli_receipt_binding_mismatch')
    if row['schemaVersion'] == LEGACY_SCHEMA and row['status'] not in {'started', 'unknown', 'returned'}:
        raise ValueError('api_cli_receipt_binding_mismatch')
    if 'rawBodyBase64' in row:
        raw = base64.b64decode(row['rawBodyBase64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != row.get('rawBodySha256'):
            raise ValueError('api_cli_raw_response_identity_mismatch')
    if row['status'] == 'returned' and (
            'response' not in row or row.get('responseSha256') != _digest(row['response'])):
        raise ValueError('api_cli_response_identity_mismatch')


def recover(directory, identity, purpose):
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('api_cli_request_identity_mismatch')
    root = receipt_root(directory)
    if not root.exists(): raise ValueError('api_cli_no_returned_response')
    with (root/'lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root/identity/'outcome.json'
        if not path.exists(): raise ValueError('api_cli_no_returned_response')
        row = json.loads(path.read_text()); _validate(row, identity, purpose)
        if row['status'] == 'terminal_failure':
            raise TerminalOutcomeError('api_cli_terminal_failure_replayed')
        if row['status'] != 'returned': raise ValueError('api_cli_outcome_reconciliation_required')
        return row['response']


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


def observing():
    return _observer.get() is not None


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
    identity = request_identity(caller, args, kwargs, purpose)
    arguments = inspect.signature(caller).bind(*args, **kwargs); arguments.apply_defaults()
    binding = execution_binding(caller, arguments.arguments)
    root = receipt_root(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path in root.glob('*/outcome.json'):
            saved = json.loads(path.read_text())
            _validate(saved, path.parent.name)
            if saved['status'] not in {'returned', 'terminal_failure'}:
                raise ValueError('api_cli_outcome_reconciliation_required')
            if saved['schemaVersion']==SCHEMA and (
                    saved['executionBinding']['runtimeRoute'] != binding['runtimeRoute'] or
                    (saved['purpose']==purpose and saved['executionBinding'] != binding)):
                raise ValueError('api_cli_frozen_execution_binding_changed')
        path = root / identity / 'outcome.json'
        if any(json.loads(p.read_text()).get('schemaVersion') != SCHEMA for p in root.glob('*/outcome.json')):
            raise ValueError('api_cli_legacy_execution_binding_requires_explicit_reconciliation')
        if path.exists():
            row = json.loads(path.read_text())
            _validate(row, identity, purpose, binding=binding)
            if row['status'] == 'terminal_failure':
                raise TerminalOutcomeError('api_cli_terminal_failure_replayed')
            return row['response']
        row = {'schemaVersion': SCHEMA, 'requestSha256': identity, 'purpose': purpose,
               'executionBinding':binding, 'executionBindingSha256':_digest(binding),
               'status': 'started'}
        _write(path, row)
        received = {}
        def observe(body, http_status, no_dispatch_reason):
            if not isinstance(body, bytes): raise TypeError('api_cli_raw_response_requires_bytes')
            received.update(rawBodyBase64=base64.b64encode(body).decode('ascii'),
                rawBodySha256=hashlib.sha256(body).hexdigest(), httpStatus=http_status)
            if no_dispatch_reason is not None: received['notDispatchedReason'] = no_dispatch_reason
            _write(path, {**row, **received, 'status':'received'})
        observer_token = _observer.set(observe)
        token = _active.set(True)
        try:
            response = caller(*args, **kwargs)
            _write(path, {**row, **received, 'status': 'returned', 'response': response,
                          'responseSha256': _digest(response)})
            return response
        except BaseException as exc:
            # Complete received bytes prove terminal transport outcome, never cost=0.
            terminal = bool(received) or isinstance(exc, urllib.error.HTTPError)
            try:
                _write(path, {**row, **received,
                    'status': 'terminal_failure' if terminal else 'unknown',
                    'failureType':type(exc).__name__,
                    **({'httpStatus':exc.code} if isinstance(exc, urllib.error.HTTPError) else {})})
            except Exception:
                pass  # The durable started/received proof still blocks; preserve original error.
            raise
        finally:
            _active.reset(token); _observer.reset(observer_token)


def reconcile(directory, request_sha256, response, evidence, *, terminal_failure=False):
    """Explicit operator reconciliation of an observed terminal response, no dispatch."""
    if not isinstance(evidence, dict) or not evidence.get('terminalResponseEvidence'):
        raise ValueError('api_cli_terminal_evidence_required')
    if not re.fullmatch(r'[0-9a-f]{64}', request_sha256):
        raise ValueError('api_cli_request_identity_mismatch')
    root = Path(directory)
    with (root / 'lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / request_sha256 / 'outcome.json'
        row = json.loads(path.read_text())
        _validate(row, request_sha256)
        if row['status'] not in {'started', 'unknown', 'received'}:
            raise ValueError('api_cli_outcome_not_unknown')
        _write(path, {**row, 'schemaVersion': SCHEMA if row['schemaVersion']==SCHEMA else V2_SCHEMA,
                     **({'reconciledFromSchemaVersion':LEGACY_SCHEMA} if row['schemaVersion']==LEGACY_SCHEMA else {}),
                     'status': 'terminal_failure' if terminal_failure else 'returned',
                     **({'failure':response} if terminal_failure else
                        {'response':response, 'responseSha256':_digest(response)}),
                     'reconciliationEvidenceSha256':_digest(evidence)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--terminal-failure', action='store_true')
    parser.add_argument('--response', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    options = parser.parse_args()
    reconcile(options.directory, options.request_sha256,
              json.loads(options.response.read_text()), json.loads(options.evidence.read_text()),
              terminal_failure=options.terminal_failure)

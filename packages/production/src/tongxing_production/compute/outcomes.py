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
from contextlib import contextmanager
import fcntl
import hashlib
import inspect
import types
import shutil
import json
import os
from pathlib import Path
import tempfile
import threading
import time

_active = ContextVar('api_cli_outcome_admitted', default=False)
SCHEMA = 'sermon-api-cli-outcome-v3'
V2_SCHEMA = 'sermon-api-cli-outcome-v2'
LEGACY_SCHEMA = 'sermon-api-cli-outcome-v1'
RECONCILIATION_EVIDENCE_SCHEMA = 'sermon-api-cli-reconciliation-evidence-v1'
_observer = ContextVar('api_cli_outcome_observer', default=None)
_before_dispatch = ContextVar('api_cli_before_dispatch', default=None)
_cli_observer = ContextVar('api_cli_terminal_observer', default=None)
CLI_TERMINAL_SCHEMA = 'sermon-cli-terminal-v1'
RAW_FAILURE_SCHEMA = 'sermon-api-cli-raw-failure-v1'


class TerminalOutcomeError(RuntimeError):
    pass


def observed_response(body, *, http_status=200):
    observer = _observer.get()
    if observer is not None:
        observer(body, http_status, None)


def observed_cli_terminal(*, returncode, stdout, stderr, output=None):
    """Observe actual completed subprocess bytes before decoding; never a timeout."""
    observer = _cli_observer.get()
    if observer is None:
        return
    if type(returncode) is not int or not isinstance(stdout, bytes) or not isinstance(stderr, bytes) or (
            output is not None and not isinstance(output, bytes)):
        raise ValueError('api_cli_terminal_observation_invalid')
    def body(value):
        return None if value is None else {'rawBodyBase64': base64.b64encode(value).decode('ascii'),
                                           'rawBodySha256': hashlib.sha256(value).hexdigest()}
    observer({'schemaVersion': CLI_TERMINAL_SCHEMA, 'returncode': returncode,
              'stdout': body(stdout), 'stderr': body(stderr), 'output': body(output)})


def _validate_cli_terminal(envelope):
    if (not isinstance(envelope, dict)
            or set(envelope) != {'schemaVersion', 'returncode', 'stdout', 'stderr', 'output'}
            or envelope.get('schemaVersion') != CLI_TERMINAL_SCHEMA
            or type(envelope.get('returncode')) is not int):
        raise ValueError('api_cli_terminal_observation_invalid')
    for name in ('stdout', 'stderr', 'output'):
        body = envelope[name]
        if name == 'output' and body is None:
            continue
        if (not isinstance(body, dict) or set(body) != {'rawBodyBase64', 'rawBodySha256'}
                or not isinstance(body.get('rawBodyBase64'), str)):
            raise ValueError('api_cli_terminal_observation_invalid')
        raw = base64.b64decode(body['rawBodyBase64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != body['rawBodySha256']:
            raise ValueError('api_cli_terminal_response_identity_mismatch')


def observed_no_dispatch(reason):
    observer = _observer.get()
    if observer is not None: observer(b'', None, reason)


def request_identity(caller, args, kwargs, purpose):
    bound = inspect.signature(caller).bind(*args, **kwargs)
    bound.apply_defaults()
    return _digest({'purpose': purpose, 'arguments': _safe(bound.arguments),
                    'executionBinding': execution_binding(caller, bound.arguments)})


EXECUTABLE_KEYS = {'codex_cli','cli_path','executable','executable_path','binary_path'}

# Per-process memo of executable digests. The Codex CLI bundle is ~250 MB and a
# request identity needs it several times per group; the digests themselves are
# unchanged. An entry is reused only while the resolved path and the stat key of
# both hashed files are unchanged, and never for a file modified within the
# timestamp-granularity window before hashing began (a same-size rewrite in that
# window could keep its stat key).
_EXECUTABLE_IDENTITIES = {}
_EXECUTABLE_LOCKS = {}
_EXECUTABLE_LOCKS_GUARD = threading.Lock()
_RACY_MTIME_SECONDS = 2.0


def _reset_executable_locks():
    # A forked child must not inherit a lock held by a parent thread mid-hash.
    global _EXECUTABLE_LOCKS_GUARD
    _EXECUTABLE_LOCKS_GUARD = threading.Lock()
    _EXECUTABLE_LOCKS.clear()


os.register_at_fork(after_in_child=_reset_executable_locks)


def _file_stat_key(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _file_sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def executable_identity(value):
    path=Path(value).expanduser()
    if not path.is_file() and len(path.parts)==1:
        found=shutil.which(str(path))
        if found: path=Path(found)
    resolved=path.resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved,os.X_OK):
        raise ValueError('api_cli_executable_identity_invalid')
    bundled=resolved.parent.parent/'CodexCLI.app/Contents/MacOS/codex'
    with _EXECUTABLE_LOCKS_GUARD:
        lock=_EXECUTABLE_LOCKS.setdefault(str(resolved),threading.Lock())
    with lock:
        key=(_file_stat_key(resolved),_file_stat_key(bundled) if bundled.is_file() else None)
        cached=_EXECUTABLE_IDENTITIES.get(str(resolved))
        if cached is not None and cached[0]==key:
            return dict(cached[1])
        started=time.time_ns()
        identity={'resolvedPath':str(resolved),'sha256':_file_sha256(resolved)}
        if bundled.is_file():identity['bundleBinarySha256']=_file_sha256(bundled)
        after=(_file_stat_key(resolved),_file_stat_key(bundled) if bundled.is_file() else None)
        racy=any(part is not None and part[3]>=started-int(_RACY_MTIME_SECONDS*1e9) for part in key)
        if after==key and key[0] is not None and not racy:
            _EXECUTABLE_IDENTITIES[str(resolved)]=(key,dict(identity))
        else:
            _EXECUTABLE_IDENTITIES.pop(str(resolved),None)
        return identity


def _code_identity(code):
    """Canonical code structure; marshal's internal string refs change on use."""
    def constant(value):
        if value is None:
            return ['none']
        if value is Ellipsis:
            return ['ellipsis']
        if type(value) is bool:
            return ['bool', value]
        if type(value) is int:
            return ['int', str(value)]
        if type(value) is float:
            return ['float', value.hex()]
        if type(value) is complex:
            return ['complex', value.real.hex(), value.imag.hex()]
        if type(value) is str:
            return ['str', value]
        if type(value) is bytes:
            return ['bytes', value.hex()]
        if type(value) is tuple:
            return ['tuple', [constant(item) for item in value]]
        if type(value) is frozenset:
            items = [constant(item) for item in value]
            return ['frozenset', sorted(items, key=lambda item: json.dumps(item, sort_keys=True))]
        if isinstance(value, types.CodeType):
            return ['code', _code_identity(value)]
        raise ValueError('api_cli_code_constant_identity_unsupported')
    return {'schemaVersion': 'sermon-python-code-identity-v1',
            'code': code.co_code.hex(), 'constants': [constant(value) for value in code.co_consts],
            'names': list(code.co_names), 'varnames': list(code.co_varnames),
            'freevars': list(code.co_freevars), 'cellvars': list(code.co_cellvars),
            'argcount': code.co_argcount, 'posonlyargcount': code.co_posonlyargcount,
            'kwonlyargcount': code.co_kwonlyargcount, 'nlocals': code.co_nlocals,
            'stacksize': code.co_stacksize, 'flags': code.co_flags,
            'exceptiontable': getattr(code, 'co_exceptiontable', b'').hex()}


def execution_binding(caller, arguments):
    from .openai_runtime import selected_route
    function = inspect.unwrap(caller)
    if not inspect.isfunction(function) and not inspect.ismethod(function):
        function = type(caller).__call__
    source = inspect.getsourcefile(function)
    code = getattr(function, '__code__', None)
    transport = getattr(caller, 'execution_identity', None)
    credentials = {key: hashlib.sha256(value.encode()).hexdigest()
                   for key, value in arguments.items()
                   if key.lower() in {'api_key', 'authorization', 'access_token'} and isinstance(value,str) and value}
    executables={key:executable_identity(value) for key,value in arguments.items()
                 if key in EXECUTABLE_KEYS and isinstance(value,(str,Path))}
    cli_path=getattr(caller,'cli_path',None)
    if isinstance(cli_path,(str,Path)):executables['transportCli']=executable_identity(cli_path)
    return {'runtimeRoute':selected_route(), 'credentialFingerprints':credentials,
            'executables':executables,
            'caller':{'module':function.__module__, 'qualname':function.__qualname__,
                      'sourceSha256':hashlib.sha256(Path(source).read_bytes()).hexdigest() if source and Path(source).is_file() else None,
                      'bytecodeSha256':_digest(_code_identity(code)) if code else None},
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
    if 'cliTerminal' in row:
        _validate_cli_terminal(row['cliTerminal'])
        if (row.get('cliTerminalSha256') != _digest(row['cliTerminal']) or 'rawBodyBase64' in row):
            raise ValueError('api_cli_terminal_response_identity_mismatch')
    if 'reconciliationBinding' in row:
        reconciliation = row['reconciliationBinding']
        response = row.get('failure') if row['status'] == 'terminal_failure' else row.get('response')
        if (not isinstance(reconciliation, dict)
                or reconciliation.get('schemaVersion') != RECONCILIATION_EVIDENCE_SCHEMA
                or reconciliation.get('requestSha256') != identity
                or reconciliation.get('responseSha256') != _digest(response)
                or type(reconciliation.get('terminalFailure')) is not bool
                or reconciliation['terminalFailure'] != (row['status'] == 'terminal_failure')):
            raise ValueError('api_cli_reconciliation_binding_mismatch')
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
    if key in EXECUTABLE_KEYS and isinstance(value,(str,Path)):
        return executable_identity(value)
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
    from .backend import current
    directory = current().accounting.subprocess_environment().get('SERMON_ACCOUNTING_DIR')
    if not directory: raise ValueError('api_cli_outcome_directory_required_before_dispatch')
    return Path(directory) / 'api-cli-outcomes'


@contextmanager
def before_dispatch(callback):
    """Write an upstream marker only after durable shared admission succeeds."""
    token = _before_dispatch.set(callback)
    try:
        yield
    finally:
        _before_dispatch.reset(token)


def _assert_scope_admitted(root, *, purpose, binding):
    paths = list(root.glob('*/outcome.json'))
    legacy = False
    for path in paths:
        saved = json.loads(path.read_text())
        _validate(saved, path.parent.name)
        if saved['status'] not in {'returned', 'terminal_failure'}:
            raise ValueError('api_cli_outcome_reconciliation_required')
        if saved['schemaVersion'] == SCHEMA and (
                saved['executionBinding']['runtimeRoute'] != binding['runtimeRoute'] or
                (saved['purpose'] == purpose and saved['executionBinding'] != binding)):
            raise ValueError('api_cli_frozen_execution_binding_changed')
        legacy = legacy or saved['schemaVersion'] != SCHEMA
    if legacy:
        raise ValueError('api_cli_legacy_execution_binding_requires_explicit_reconciliation')


def assert_replay_admitted(directory, *, purpose, binding):
    """Read-only shared outcome gate for cache lookup; creates no files/receipts."""
    root = receipt_root(directory)
    if not root.exists():
        return
    # Dispatchers always create this lock before any outcome. Reuse it without
    # creating metadata so a cache reader does not mutate its evidence root.
    lock_path = root / 'lock'
    if not lock_path.exists():
        _assert_scope_admitted(root, purpose=purpose, binding=binding)
        return
    with lock_path.open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        _assert_scope_admitted(root, purpose=purpose, binding=binding)


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
        _assert_scope_admitted(root, purpose=purpose, binding=binding)
        path = root / identity / 'outcome.json'
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
        def observe_cli(envelope):
            _validate_cli_terminal(envelope)
            if 'rawBodyBase64' in received:
                raise ValueError('api_cli_mixed_response_formats')
            received.update(cliTerminal=envelope, cliTerminalSha256=_digest(envelope))
            _write(path, {**row, **received, 'status': 'received'})
        cli_token = _cli_observer.set(observe_cli)
        observer_token = _observer.set(observe)
        token = _active.set(True)
        try:
            callback = _before_dispatch.get()
            if callback is not None:
                callback()
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
            _active.reset(token); _observer.reset(observer_token); _cli_observer.reset(cli_token)


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
        binding = {}
        if row['schemaVersion'] == SCHEMA or evidence.get('schemaVersion') is not None:
            if (not isinstance(evidence.get('terminalResponseEvidence'), str)
                    or not evidence['terminalResponseEvidence'].strip()):
                raise ValueError('api_cli_terminal_evidence_required')
            if (evidence.get('schemaVersion') != RECONCILIATION_EVIDENCE_SCHEMA
                    or evidence.get('requestSha256') != request_sha256
                    or evidence.get('responseSha256') != _digest(response)
                    or type(evidence.get('terminalFailure')) is not bool
                    or evidence['terminalFailure'] != terminal_failure):
                raise ValueError('api_cli_reconciliation_evidence_binding_mismatch')
            binding = {'reconciliationBinding': {key: evidence[key] for key in
                       ('schemaVersion', 'requestSha256', 'responseSha256', 'terminalFailure')}}
        if 'cliTerminal' in row:
            # This envelope proves process completion, not the caller's parsed
            # response schema. Normal successful calls already persist returned.
            # Without the specific parser contract, a received CLI envelope may
            # only be explicitly closed as the exact recorded terminal failure.
            if not terminal_failure:
                raise ValueError('api_cli_cli_terminal_requires_failure_reconciliation')
            if _digest(response) != row['cliTerminalSha256']:
                raise ValueError('api_cli_reconciliation_recorded_response_mismatch')
        elif 'rawBodyBase64' in row:
            raw = base64.b64decode(row['rawBodyBase64'], validate=True)
            try:
                decoded_hash = _digest(json.loads(raw.decode('utf-8')))
            except (UnicodeError, ValueError) as error:
                if not terminal_failure:
                    raise ValueError('api_cli_recorded_response_not_json_reconciliation_required') from error
                expected_failure = {'schemaVersion': RAW_FAILURE_SCHEMA,
                    'requestSha256': request_sha256, 'rawBodySha256': row['rawBodySha256'],
                    'httpStatus': row.get('httpStatus'), 'notDispatchedReason': row.get('notDispatchedReason')}
                if _digest(response) != _digest(expected_failure):
                    raise ValueError('api_cli_reconciliation_raw_failure_binding_mismatch') from error
            else:
                if decoded_hash != _digest(response):
                    raise ValueError('api_cli_reconciliation_recorded_response_mismatch')
            if not terminal_failure and (type(row.get('httpStatus')) is not int
                    or not 200 <= row['httpStatus'] < 300 or row.get('notDispatchedReason')):
                raise ValueError('api_cli_recorded_failure_cannot_be_success')
        elif row['status'] == 'received':
            raise ValueError('api_cli_received_response_bytes_required')
        _write(path, {**row, 'schemaVersion': SCHEMA if row['schemaVersion']==SCHEMA else V2_SCHEMA,
                     **({'reconciledFromSchemaVersion':LEGACY_SCHEMA} if row['schemaVersion']==LEGACY_SCHEMA else {}),
                     'status': 'terminal_failure' if terminal_failure else 'returned',
                     **({'failure':response} if terminal_failure else
                        {'response':response, 'responseSha256':_digest(response)}),
                     'reconciliationEvidenceSha256':_digest(evidence), **binding})


def main():
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


if __name__ == '__main__':
    main()

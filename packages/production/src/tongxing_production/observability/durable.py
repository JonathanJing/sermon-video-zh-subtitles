"""Opt-in, restart-safe synthetic controller accounting; never dispatches work.

One immutable binding identifies one logical controller stream per ledger. The
next sequence comes only from the validated ledger plus frozen pending facts,
not a mutable counter or projection. Delivery keys retain their original facts
and timestamps after either side of an append/ACK crash. Builders must be pure:
no logging, job locks, provider calls, or other external work under the lock.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from scripts import sermon_log_contract as contract
from scripts import sermon_log_outbox as outbox
from scripts import sermon_log_profile as profile
from scripts import sermon_workflow_jobs as jobs

BINDING_SCHEMA = 'sermon-durable-controller-stream-v1'
DELIVERY_SCHEMA = 'sermon-durable-controller-delivery-v1'
BINDING_NAME = outbox.DURABLE_BINDING_NAME
DELIVERY_DIRECTORY = outbox.DURABLE_DELIVERY_DIRECTORY
MAX_LEDGER_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 16384
_INCOMPLETE = {'missing_attempt_start', 'missing_attempt_finish', 'missing_model_start', 'missing_model_finish'}


def _hash(value):
    return hashlib.sha256(contract.canonical_bytes(value)).hexdigest()


def _label(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value) is None:
        raise ValueError('invalid_durable_stream_label')
    return value


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r'[a-f0-9]{64}', value) is None:
        raise ValueError('invalid_durable_stream_hash')
    return value


def _binding(scope_id, plan_sha256, production_run_id, purpose, workflow_id):
    data = {'schemaVersion': BINDING_SCHEMA, 'scopeId': _label(scope_id),
        'planSha256': _sha(plan_sha256), 'productionRunId': _sha(production_run_id),
        'purpose': _label(purpose), 'workflowId': _label(workflow_id),
        'contractVersion': contract.VERSION, 'evidenceMode': 'synthetic', 'workKind': 'control'}
    digest = _hash(data)
    return {**data, 'runId': _hash(['controller-run-v1', digest])[:32],
        'producerId': _hash(['controller-producer-v1', digest])[:32]}


def _read(path, limit):
    """Bound bytes before JSON decoding, without following leaf symlinks."""
    jobs._reject_link(path, directory=False)
    directory_fd = jobs._directory_fd(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('invalid_durable_stream_file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('durable_stream_size_limit')
    return json.loads(raw)


def _read_binding(root):
    value = _read(root / BINDING_NAME, 4096)
    if not isinstance(value, dict):
        raise ValueError('invalid_durable_stream_binding')
    try:
        expected = _binding(value['scopeId'], value['planSha256'], value['productionRunId'],
            value['purpose'], value['workflowId'])
    except (KeyError, TypeError) as exc:
        raise ValueError('invalid_durable_stream_binding') from exc
    if value != expected:
        raise ValueError('durable_stream_binding_changed')
    return value


def _ledger_rows(fd):
    from scripts import sermon_accounting as accounting
    if os.fstat(fd).st_size > MAX_LEDGER_BYTES:
        raise ValueError('durable_ledger_size_limit')
    os.lseek(fd, 0, os.SEEK_SET)
    rows = []
    with os.fdopen(os.dup(fd), 'rb') as stream, contract.schema_batch():
        while True:
            line = stream.readline(contract.MAX_EVENT_BYTES + 1)
            if not line:
                break
            if len(line) > contract.MAX_EVENT_BYTES or not line.endswith(b'\n'):
                raise ValueError('durable_ledger_damaged')
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise ValueError('durable_ledger_damaged') from exc
            if not accounting._valid_event(row):
                raise ValueError('durable_ledger_invalid_event')
            rows.append(row)
    return rows


def _pending_rows(pending):
    entries = list(pending.iterdir())
    if len(entries) > 4096:
        raise ValueError('pending_event_count_limit')
    rows = []
    total_bytes = 0
    for path in sorted(entries):
        if not re.fullmatch(r'[a-f0-9]{32}\.json', path.name):
            raise ValueError('invalid_pending_event_name')
        total_bytes += path.lstat().st_size
        if total_bytes > MAX_LEDGER_BYTES:
            raise ValueError('pending_events_size_limit')
        event = _read(path, 4 * contract.MAX_EVENT_BYTES)
        contract.validate_event(event)
        if event['eventId'] != path.stem:
            raise ValueError('pending_event_identity_mismatch')
        rows.append(event)
    return rows


def _event_scope(event, binding):
    if any(event.get(key) != binding[key] for key in ('runId', 'producerId', 'workflowId',
            'productionRunId', 'evidenceMode', 'workKind')):
        raise ValueError('durable_event_scope_conflict')


def _record(event, binding, delivery_key, intent):
    key_hash = _hash(_label(delivery_key))
    intent_bytes = contract.canonical_bytes(intent)
    if len(intent_bytes) > contract.MAX_EVENT_BYTES:
        raise ValueError('durable_intent_size_limit')
    return {'schemaVersion': DELIVERY_SCHEMA, 'bindingSha256': _hash(binding),
        'deliveryKeySha256': key_hash, 'intentSha256': hashlib.sha256(intent_bytes).hexdigest(),
        'eventSha256': contract.fact_hash(event), 'event': event}


def _event_id(binding, key_hash):
    return _hash([DELIVERY_SCHEMA, _hash(binding), key_hash])[:32]


def _validate_record(value, path, binding):
    keys = {'schemaVersion', 'bindingSha256', 'deliveryKeySha256', 'intentSha256', 'eventSha256', 'event'}
    if not isinstance(value, dict) or set(value) != keys or value['schemaVersion'] != DELIVERY_SCHEMA:
        raise ValueError('invalid_durable_delivery_record')
    for key in ('bindingSha256', 'deliveryKeySha256', 'intentSha256', 'eventSha256'):
        _sha(value[key])
    event = value['event']
    contract.validate_event(event)
    _event_scope(event, binding)
    if (value['bindingSha256'] != _hash(binding) or value['eventSha256'] != contract.fact_hash(event)
            or event['eventId'] != path.stem
            or event['eventId'] != _event_id(binding, value['deliveryKeySha256'])):
        raise ValueError('durable_delivery_identity_conflict')
    return value


def validate_locked(root, pending, fd, *, expected=None, candidate=None, additional_events=()):
    """Validate opt-in durable storage while the existing ledger lock is held.

    Used also by ordinary outbox delivery/replay so a worker append cannot
    silently add a newline to a torn controller ledger. No recursive locks.
    """
    binding_path, folder = root / BINDING_NAME, root / DELIVERY_DIRECTORY
    if not (binding_path.exists() or binding_path.is_symlink() or folder.exists() or folder.is_symlink()):
        return None
    binding = _read_binding(root)
    if expected is not None and binding != expected:
        raise ValueError('durable_stream_scope_conflict')
    jobs._reject_link(folder, directory=True)
    if not folder.is_dir():
        raise ValueError('durable_delivery_records_missing')
    entries = list(folder.iterdir())
    if len(entries) > MAX_RECORDS:
        raise ValueError('durable_delivery_count_limit')
    records = {}
    total_bytes = 0
    for path in sorted(entries):
        if not re.fullmatch(r'[a-f0-9]{32}\.json', path.name):
            raise ValueError('invalid_durable_delivery_name')
        total_bytes += path.lstat().st_size
        if total_bytes > MAX_LEDGER_BYTES:
            raise ValueError('durable_delivery_size_limit')
        records[path.stem] = _validate_record(_read(path, 4 * contract.MAX_EVENT_BYTES), path, binding)
    rows = _ledger_rows(fd) + _pending_rows(pending) + list(additional_events)
    if candidate is not None:
        records[candidate['event']['eventId']] = candidate
        rows.append(candidate['event'])
    _validate_union(binding, records, rows)
    return binding, records, rows


def _validate_union(binding, records, rows):
    """Pure validation; use an already-read snapshot while holding the lock."""
    own = {}
    for row in rows:
        if row.get('runId') != binding['runId']:
            raise ValueError('durable_run_scope_conflict')
        if row.get('event') == 'step_state_changed' and row.get('producerId') != binding['producerId']:
            raise ValueError('durable_state_producer_required')
        if row.get('producerId') == binding['producerId']:
            _event_scope(row, binding)
            own[row['eventId']] = row
            record = records.get(row['eventId'])
            if record is None or record['event'] != row:
                raise ValueError('durable_delivery_record_missing_or_changed')
        if row.get('runId') == binding['runId'] and (row.get('evidenceMode') != 'synthetic'
                or row.get('productionRunId') != binding['productionRunId']):
            raise ValueError('durable_run_scope_conflict')
    if set(records) != set(own):
        raise ValueError('durable_event_missing_from_ledger_and_pending')
    checked = contract.replay_integrity(rows)
    if any(d['code'] not in _INCOMPLETE for d in checked['diagnostics']):
        raise ValueError('durable_ledger_integrity_failed')


class DurableStream:
    def __init__(self, directory, binding):
        self.directory = Path(directory)
        self.binding = deepcopy(binding)
        self.run_id = binding['runId']
        self.producer_id = binding['producerId']
        self.workflow_id = binding['workflowId']

    def prepare(self, delivery_key, intent, build):
        """Freeze once before returning; repeat keys never rerun the builder."""
        key_hash = _hash(_label(delivery_key))
        intent_bytes = contract.canonical_bytes(intent)
        if len(intent_bytes) > contract.MAX_EVENT_BYTES:
            raise ValueError('durable_intent_size_limit')
        intent_hash = hashlib.sha256(intent_bytes).hexdigest()
        event_id = _event_id(self.binding, key_hash)
        with outbox._ledger(self.directory) as (root, pending, fd):
            checked = validate_locked(root, pending, fd, expected=self.binding)
            if checked is None:
                raise ValueError('durable_stream_binding_missing')
            _, records, rows = checked
            previous = records.get(event_id)
            if previous is not None:
                if previous['deliveryKeySha256'] != key_hash or previous['intentSha256'] != intent_hash:
                    raise ValueError('durable_delivery_intent_conflict')
                return deepcopy(previous['event'])
            if len(records) >= MAX_RECORDS:
                raise ValueError('durable_delivery_count_limit')
            sequence = max((r['sequence'] for r in rows if r.get('producerId') == self.producer_id), default=0) + 1
            event = json.loads(contract.canonical_bytes(build(event_id, self.producer_id, sequence)))
            contract.validate_event(event)
            if event['eventId'] != event_id or event['producerId'] != self.producer_id or event['sequence'] != sequence:
                raise ValueError('durable_builder_identity_conflict')
            _event_scope(event, self.binding)
            record = _record(event, self.binding, delivery_key, intent)
            _validate_union(self.binding, {**records, event_id: record}, [*rows, event])
            outbox._run_profile(root, fd, event)
            # These are immutable original facts, not a mutable high-water mark.
            # An interrupted two-file freeze is blocked, never guessed/rebuilt.
            jobs._persist(root / DELIVERY_DIRECTORY / (event_id + '.json'), record)
            jobs._persist(pending / (event_id + '.json'), event)
            return deepcopy(event)

    def deliver(self, event):
        contract.validate_event(event)
        with outbox._ledger(self.directory) as (root, pending, fd):
            checked = validate_locked(root, pending, fd, expected=self.binding)
            if checked is None:
                raise ValueError('durable_stream_binding_missing')
            _, records, rows = checked
            record = records.get(event['eventId'])
            if record is None or record['event'] != event:
                raise ValueError('durable_delivery_identity_conflict')
            path = pending / (event['eventId'] + '.json')
            if path.exists():
                # A preceding failed delivery can still be pending. Drain all
                # earlier controller facts first so physical append order agrees.
                ready = [r for r in _pending_rows(pending) if r['producerId'] == self.producer_id
                    and r['sequence'] <= event['sequence']]
                for row in sorted(ready, key=lambda item: item['sequence']):
                    outbox._append(fd, row)
                    (pending / (row['eventId'] + '.json')).unlink()
                    jobs._sync_directory(pending)
            return deepcopy(record['event'])

    def emit(self, delivery_key, intent, build):
        return self.deliver(self.prepare(delivery_key, intent, build))

    def write(self, event, base=None, context=None, *, delivery_key, intent=None):
        """Build a canonical profile envelope without inheriting a producer."""
        from scripts import sermon_accounting as accounting
        event, base, context = deepcopy(event), deepcopy(base or {}), deepcopy(context or {})
        if intent is None:
            intent = {'event': event, 'base': base, 'context': context}
        ctx = {'workKind': 'control', 'evidenceMode': 'synthetic',
            'productionRunId': self.binding['productionRunId'], **context}
        profile._validate_context(ctx)
        envelope = {'schemaVersion': accounting.SCHEMA, 'runId': self.run_id,
            'workflowId': self.workflow_id, 'stage': None, 'spanId': None, **base}
        def build(event_id, producer_id, sequence):
            return profile._build(event, {**envelope, 'recordedAt': accounting.now()}, ctx,
                event_id, producer_id, sequence)
        return self.emit(delivery_key, intent, build)

    @contextmanager
    def context(self):
        """Bind identity only; no automatic starts/ends or producer inheritance.

        Job contexts retain run attribution but ordinary process-local worker
        producers. A pre-existing profile/identity is never silently adopted.
        """
        from scripts import sermon_accounting as accounting
        if (accounting._identity.get() is not None or profile.current() is not None
                or accounting._workflow.get() is not None or accounting._span.get() is not None
                or accounting._stage.get() is not None or any(os.environ.get(key)
                    for key in (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV))):
            raise ValueError('durable_context_already_active')
        with outbox._ledger(self.directory) as (root, pending, fd):
            if validate_locked(root, pending, fd, expected=self.binding) is None:
                raise ValueError('durable_stream_binding_missing')
        identity = accounting._identity.set((str(self.directory), self.run_id))
        workflow = accounting._workflow.set(self.workflow_id)
        try:
            with profile.context(workKind='control', evidenceMode='synthetic',
                    productionRunId=self.binding['productionRunId']):
                yield self
        finally:
            accounting._workflow.reset(workflow)
            accounting._identity.reset(identity)


def open_stream(directory, *, scope_id, plan_sha256, production_run_id, purpose,
                workflow_id='synthetic_controller', create=False):
    """Open the exact frozen binding; creation must be explicit at admission."""
    expected = _binding(scope_id, plan_sha256, production_run_id, purpose, workflow_id)
    with outbox._ledger(directory) as (root, pending, fd):
        path, folder = root / BINDING_NAME, root / DELIVERY_DIRECTORY
        jobs._reject_link(path, directory=False)
        jobs._reject_link(folder, directory=True)
        if not path.exists():
            if not create:
                raise ValueError('durable_stream_binding_missing')
            rows = _ledger_rows(fd) + _pending_rows(pending)
            if folder.exists() or any(r.get('runId') == expected['runId']
                    or r.get('producerId') == expected['producerId'] for r in rows):
                raise ValueError('durable_established_binding_missing')
            # Admission does not attach a durable controller to a foreign ledger.
            if rows:
                raise ValueError('durable_stream_requires_empty_ledger')
            jobs._persist(path, expected)
            folder.mkdir(mode=0o700)
            jobs._sync_directory(root)
        validate_locked(root, pending, fd, expected=expected)
    return DurableStream(root, expected)

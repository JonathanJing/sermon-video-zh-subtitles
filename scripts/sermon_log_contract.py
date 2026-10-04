"""Strict opt-in log profile and read-only, order-independent replay inspection.

No dispatch, recovery, approval or network authority lives in this module.
Legacy records are never upgraded by manufacturing missing observations.
"""
from collections import OrderedDict, defaultdict, namedtuple
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import math
import marshal
import os
from pathlib import Path
import threading

from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import SchemaError

VERSION = 'sermon-accounting-log-contract-v1'
MAX_EVENT_BYTES = 64 * 1024
# At most 16 MiB of canonical payload keys, plus explicitly bounded entry and
# schema-key overhead. A count-only 2048-entry LRU thrashed on the measured
# 39-job working set despite its eligible payload occupying less than 6 MiB.
# Larger valid events still validate normally and never occupy cache memory.
MAX_CACHED_EVENT_BYTES = 8 * 1024
MAX_VALIDATION_CACHE_ENTRIES = 8192
MAX_VALIDATION_CACHE_PAYLOAD_BYTES = 16 * 1024 * 1024
# Each interned snapshot retains at most 256 KiB of typed content bytes and
# a validator compiled from at most 256 KiB of canonical JSON. Eviction clears
# successful-event keys first, so those keys cannot retain an unbounded history.
MAX_SCHEMA_SNAPSHOT_BYTES = 256 * 1024
MAX_SCHEMA_SNAPSHOT_ENTRIES = 2
_schema_snapshots = OrderedDict()
_schema_snapshot_lock = threading.RLock()
_event_successes = OrderedDict()
_event_success_payload_bytes = 0
_event_success_hits = _event_success_misses = 0
_CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')
SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'schemas/sermon-accounting-log-contract-v1.schema.json'


def _reset_snapshot_lock_after_fork():
    global _schema_snapshot_lock, _schema_snapshots, _event_successes
    global _event_success_payload_bytes, _event_success_hits, _event_success_misses
    _schema_snapshot_lock = threading.RLock()
    # Another thread can fork between an OrderedDict update and its accounting
    # update. The child owns a fresh empty cache, never an inherited partial
    # cache/counter mutation or a lock held by a vanished thread.
    _schema_snapshots = OrderedDict()
    _event_successes = OrderedDict()
    _event_success_payload_bytes = _event_success_hits = _event_success_misses = 0


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_snapshot_lock_after_fork)


class ContractError(ValueError):
    """Messages are fixed codes: never include rejected payload content."""


def canonical_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ContractError('invalid_json_value') from exc


def _strict_values(value):
    if isinstance(value, dict):
        return all(type(k) is str and _strict_values(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_strict_values(v) for v in value)
    return value is None or type(value) in (str, bool, int) or type(value) is float and math.isfinite(value)


def format_checker():
    checker = FormatChecker()
    @checker.checks('date-time', raises=(ValueError, TypeError))
    def utc_date(value):
        return isinstance(value, str) and value.endswith('Z') and datetime.fromisoformat(value).tzinfo is not None
    return checker


@lru_cache(maxsize=1)
def validator():
    schema = json.loads(SCHEMA_PATH.read_text())
    return _compile_validator(schema)


def _compile_validator(schema):
    Draft202012Validator.check_schema(schema)
    checker = Draft202012Validator.TYPE_CHECKER.redefine('integer', lambda _, v: type(v) is int)
    cls = validators.extend(Draft202012Validator, type_checker=checker)
    return cls(schema, format_checker=format_checker())


def _schema_snapshot():
    """Intern exact typed content while the snapshot/cache lock is held.

    marshal is a cheap, exact typed snapshot. Only bounded bytes generated here
    are decoded, never a file/network/caller-supplied serialized value. Version 2
    does not depend on reference counts or aliasing.
    Unlike Python equality/JSON coercion, it distinguishes bool/int/float and
    list/tuple. Every new key must pass strict JSON and schema validation before
    a privately compiled canonical copy can be used. No mutable public checker
    participates in cached success validation.
    """
    schema = validator().schema
    try:
        key = marshal.dumps(schema, 2)
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ContractError('invalid_schema_snapshot') from exc
    if len(key) > MAX_SCHEMA_SNAPSHOT_BYTES:
        raise ContractError('schema_snapshot_size_limit')
    if key in _schema_snapshots:
        _schema_snapshots.move_to_end(key)
        return _schema_snapshots[key]
    # Compile from the exact captured bytes, not the still-mutable public schema.
    # A concurrent edit cannot bind one schema's success to another schema's key.
    captured = marshal.loads(key)
    if type(captured) is not dict or not _strict_values(captured):
        raise ContractError('invalid_schema_snapshot')
    frozen = canonical_bytes(captured)
    if len(frozen) > MAX_SCHEMA_SNAPSHOT_BYTES:
        raise ContractError('schema_snapshot_size_limit')
    try:
        checker = _compile_validator(json.loads(frozen))
    except SchemaError as exc:
        raise ContractError('invalid_schema_snapshot') from exc
    if len(_schema_snapshots) >= MAX_SCHEMA_SNAPSHOT_ENTRIES:
        _validate_frozen_event.cache_clear()
        _schema_snapshots.popitem(last=False)
    snapshot = (key, checker)
    _schema_snapshots[key] = snapshot
    return snapshot


def _event_bytes(row):
    if not isinstance(row, dict) or row.get('contractVersion') != VERSION:
        raise ContractError('unsupported_contract_version')
    data = canonical_bytes(row)
    if len(data) + 1 > MAX_EVENT_BYTES:
        raise ContractError('event_size_limit')
    if not _strict_values(row):
        raise ContractError('invalid_contract_event')
    return data


def _validate_with_snapshot(row, data, snapshot):
    schema_key, checker = snapshot
    if len(data) <= MAX_CACHED_EVENT_BYTES and row.get('event') != 'rqc_observation':
        # Exact payload/schema bytes and the version bind every success entry.
        # RQC semantics consult another versioned policy; keep those uncached.
        _validate_frozen_event(data, schema_key, VERSION)
    else:
        _validate_event_uncached(row, checker)


def validate_event(row):
    data = _event_bytes(row)
    with _schema_snapshot_lock:
        # Public single-event checks always observe the current schema content.
        _validate_with_snapshot(row, data, _schema_snapshot())
    return row


def _validate_frozen_event(data, schema_key, version):
    """Cache only complete validation success, never storage/sequence authority.

    The caller has reread and serialized the current event and captured the
    exact current schema. Retaining a success avoids repeated schema work only;
    it cannot establish that a file, union, record hash or sequence is valid.
    """
    global _event_success_payload_bytes, _event_success_hits, _event_success_misses
    with _schema_snapshot_lock:
        key = (data, schema_key, version)
        if key in _event_successes:
            _event_success_hits += 1
            _event_successes.move_to_end(key)
            return
        _event_success_misses += 1
        # Exceptions never populate the success cache. Policy-dependent RQC
        # and oversized events use the uncached caller path as before.
        _validate_event_uncached(json.loads(data), _schema_snapshots[schema_key][1])
        size = len(data)
        if (size > MAX_CACHED_EVENT_BYTES or size > MAX_VALIDATION_CACHE_PAYLOAD_BYTES
                or MAX_VALIDATION_CACHE_ENTRIES < 1):
            return
        while _event_successes and (len(_event_successes) >= MAX_VALIDATION_CACHE_ENTRIES
                or _event_success_payload_bytes + size > MAX_VALIDATION_CACHE_PAYLOAD_BYTES):
            oldest, _ = _event_successes.popitem(last=False)
            _event_success_payload_bytes -= len(oldest[0])
        _event_successes[key] = None
        _event_success_payload_bytes += size


def _validation_cache_clear():
    global _event_success_payload_bytes, _event_success_hits, _event_success_misses
    with _schema_snapshot_lock:
        _event_successes.clear()
        _event_success_payload_bytes = _event_success_hits = _event_success_misses = 0


def _validation_cache_info():
    with _schema_snapshot_lock:
        return _CacheInfo(_event_success_hits, _event_success_misses,
            MAX_VALIDATION_CACHE_ENTRIES, len(_event_successes))


def _validation_cache_usage():
    with _schema_snapshot_lock:
        return {'payloadBytes': _event_success_payload_bytes,
            'maxPayloadBytes': MAX_VALIDATION_CACHE_PAYLOAD_BYTES,
            'entries': len(_event_successes), 'maxEntries': MAX_VALIDATION_CACHE_ENTRIES}


# Preserve the private cache-control API used by schema eviction and tests.
_validate_frozen_event.cache_clear = _validation_cache_clear
_validate_frozen_event.cache_info = _validation_cache_info
_validate_frozen_event.cache_usage = _validation_cache_usage


def _validate_event_uncached(row, checker):
    if next(checker.iter_errors(row), None) is not None:
        raise ContractError('invalid_contract_event')
    kind = row['event']
    if kind == 'rqc_observation':
        from scripts.sermon_review_observation import validate_observation
        try: validate_observation(row)
        except ValueError as exc: raise ContractError('invalid_review_observation') from exc
    if kind.startswith('api_attempt'):
        if row['modelCallId'] != row['attemptId']:
            raise ContractError('model_attempt_alias_conflict')
        if kind == 'api_attempt' and row['responseId'] != row['providerResponseId']:
            raise ContractError('provider_response_alias_conflict')
    if kind.startswith('sdk_call_'):
        if (row['coveredResponseIds'] is None) != (row['coverageStatus'] == 'unknown'):
            raise ContractError('sdk_coverage_conflict')
    if row.get('code') == 'decision_observation':
        f = row['fields']
        if ((f['phase'] == 'commit') != f['status'].startswith('commit_') or
                ((f['selectedAction'] is not None) != (f['status'] == 'proposal_requires_locked_admission'))):
            raise ContractError('decision_observation_phase_conflict')
    if kind == 'stage_finished' and ('monotonicStartNs' in row or 'monotonicEndNs' in row):
        if not all(k in row for k in ('monotonicStartNs', 'monotonicEndNs')):
            raise ContractError('incomplete_monotonic_interval')
        elapsed = (int(row['monotonicEndNs']) - int(row['monotonicStartNs'])) / 1e9
        if elapsed < 0 or abs(elapsed - row['elapsedSeconds']) > 0.000001:
            raise ContractError('monotonic_duration_conflict')
    return row


def valid_event(row):
    try:
        validate_event(row)
        return True
    except (ContractError, RecursionError):
        return False


def fact_hash(row):
    return hashlib.sha256(canonical_bytes(row)).hexdigest()


_TRANSITIONS = {
    None: {'pending'}, 'pending': {'ready'}, 'ready': {'queued', 'running'}, 'queued': {'running'},
    'running': {'waiting_human', 'waiting_external', 'outcome_unknown', 'succeeded', 'failed', 'cancelled'},
    'waiting_human': {'ready'}, 'waiting_external': {'ready'},
    # Reconciliation is an independent event, never reopening the old attempt.
    'outcome_unknown': set(), 'succeeded': set(), 'failed': set(), 'cancelled': set(),
}
_STAGE_IDENTITY = ('traceId', 'runId', 'workflowId', 'spanId', 'parentSpanId', 'stage', 'workUnitId',
                   'attemptId', 'executorType', 'workKind', 'evidenceMode', 'dependsOn',
                   'blockedBy', 'dependencyReadyAt', 'queuedAt', 'clockDomainId', 'monotonicStartNs')


def replay_integrity(events):
    """Inspect all profile facts before selecting equivalent representatives.

    ``_excluded`` uses in-memory row IDs only. Hash diagnostics are public-safe.
    Sequence gaps are intervals, never expanded to attacker-sized integer lists.
    """
    rows = [r for r in events if r.get('contractVersion') == VERSION]
    by_event, by_sequence, producers = defaultdict(list), defaultdict(list), defaultdict(set)
    diagnostics, excluded, representatives = [], set(), []

    def problem(code, affected=(), **details):
        affected = list(affected)
        excluded.update(id(r) for r in affected)
        diagnostics.append({'code': code, 'factSha256': sorted({fact_hash(r) for r in affected}), **details})

    with _schema_snapshot_lock:
        # One explicit immutable schema snapshot per replay batch. The lock
        # prevents another batch evicting it while event-cache entries are used.
        snapshot = _schema_snapshot() if rows else None
        for r in rows:
            _validate_with_snapshot(r, _event_bytes(r), snapshot)
            by_event[r['eventId']].append(r)
            by_sequence[(r['producerId'], r['sequence'])].append(r)
            producers[r['producerId']].add(r['sequence'])
    duplicates = 0
    for _, group in sorted(by_event.items()):
        if len({fact_hash(r) for r in group}) > 1:
            problem('event_conflict', group)
        else:
            representatives.append(group[0]); duplicates += len(group) - 1
    for _, group in sorted(by_sequence.items()):
        if len({r['eventId'] for r in group}) > 1:
            problem('producer_sequence_conflict', group)
    for producer, values in sorted(producers.items()):
        previous = 0
        for value in sorted(values):
            if value > previous + 1:
                problem('sequence_gap', producerId=producer, first=previous + 1, last=value - 1)
            previous = value
    spans, steps, reconciliations = defaultdict(list), defaultdict(list), []
    calls = defaultdict(list)
    traces = defaultdict(set)
    for r in representatives:
        if id(r) in excluded: continue
        traces[r['runId']].add(r['traceId'])
        if r['event'] in {'api_attempt_started', 'api_attempt'}:
            calls[(r['runId'], r['modelCallId'])].append(r)
        if r['event'] in {'stage_started', 'stage_finished'}:
            spans[(r['runId'], r['spanId'])].append(r)
        elif r['event'] == 'step_state_changed':
            steps[(r['runId'], r['stepId'], r['attemptId'])].append(r)
        elif r['event'] == 'attempt_reconciled':
            reconciliations.append(r)
    for run, trace_ids in traces.items():
        if len(trace_ids) != 1: problem('run_trace_identity_conflict', [r for r in representatives if r['runId']==run])
    for _, group in sorted(calls.items()):
        starts=[r for r in group if r['event']=='api_attempt_started']
        ends=[r for r in group if r['event']=='api_attempt']
        if len(starts)>1 or len(ends)>1:
            problem('model_call_multiple_start_or_terminal',group)
        elif not starts or not ends:
            # A provider receipt remains a billing fact even if its start is unavailable.
            problem('missing_model_start' if not starts else 'missing_model_finish')
        elif any(starts[0].get(k)!=ends[0].get(k) for k in
                 ('traceId','workflowId','spanId','workUnitId','logicalCallId','stageAttemptId',
                  'provider','providerScopeKey','requestedModel','attemptNumber','role','revisionId')):
            problem('model_call_identity_conflict',group)
        elif starts[0]['producerId']==ends[0]['producerId'] and starts[0]['sequence']>=ends[0]['sequence']:
            problem('model_finish_precedes_start',group)
    for _, group in sorted(spans.items()):
        starts = [r for r in group if r['event'] == 'stage_started']
        ends = [r for r in group if r['event'] == 'stage_finished']
        if len(starts) > 1 or len(ends) > 1:
            problem('attempt_reopened_or_multiple_terminal', group)
        elif not starts or not ends:
            problem('missing_attempt_start' if not starts else 'missing_attempt_finish')
        elif starts[0]['producerId'] == ends[0]['producerId'] and starts[0]['sequence'] >= ends[0]['sequence']:
            problem('finish_precedes_start_sequence', group)
        elif any(starts[0].get(k) != ends[0].get(k) for k in _STAGE_IDENTITY):
            problem('start_finish_identity_conflict', group)
    for _, group in sorted(steps.items(), key=lambda pair: str(pair[0])):
        if len({r['producerId'] for r in group}) > 1:
            problem('cross_producer_state_order_unproven', group); continue
        state = None
        for r in sorted(group, key=lambda e: e['sequence']):
            if r['fromState'] != state or r['toState'] not in _TRANSITIONS.get(state, set()):
                problem('illegal_step_transition', group); break
            state = r['toState']
    for r in reconciliations:
        prior = [e for e in representatives if e['runId'] == r['runId'] and
                 e['event'] == 'stage_finished' and e['attemptId'] == r['reconcilesAttemptId'] and id(e) not in excluded]
        if len(prior) != 1 or prior[0]['status'] != 'outcome_unknown':
            problem('unbound_attempt_reconciliation', [r])
    # Mark every physical duplicate of an excluded identity, not only its representative.
    bad_ids = {r['eventId'] for r in rows if id(r) in excluded}
    excluded.update(id(r) for r in rows if r['eventId'] in bad_ids)
    diagnostics.sort(key=lambda d: canonical_bytes(d))
    return {'status': 'partial' if diagnostics else 'consistent', 'diagnostics': diagnostics,
            'equivalentDuplicatesIgnored': duplicates, 'profileEventCount': len(rows),
            'executionAuthority': 'none', '_excluded': excluded,
            '_selected': {id(r) for r in representatives if id(r) not in excluded}}

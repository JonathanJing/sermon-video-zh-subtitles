"""Typed, evidence-backed execution leaves; no container or timing inference.

Handles refer to an already durable terminal event and one verified artifact.
They do not grant dispatch authority and cannot turn historical receipts into
current provider execution. Equivalent outbox replay is accepted; conflicts fail.
"""
from copy import deepcopy
from functools import wraps

from scripts import sermon_accounting as accounting
from scripts import sermon_log_contract as log
from scripts import sermon_review_contracts as c

SCHEMA = 'sermon-execution-completion-v1'
KEYS = {'schemaVersion', 'runId', 'productionRunId', 'traceId', 'spanId', 'stage',
        'workUnitId', 'attemptId', 'status', 'dependsOn', 'terminalEventId',
        'terminalFactSha256', 'artifactSha256', 'artifactKind', 'executionMode'}
ARTIFACTS = {'frozen_recipe', 'provider_receipt', 'aligned_segments', 'source_package'}
MODES = {'current_execution', 'cache_replay', 'deterministic_validation', 'backend_execution_unobserved'}
SYNTHETIC_SCHEMA = 'sermon-execution-completion-v2'
SYNTHETIC_KEYS = KEYS | {'evidenceMode', 'jobId', 'revisionId'}
SYNTHETIC_ARTIFACTS = {'mock_wav', 'control_receipt'}


def validate_synthetic_shape(handle):
    """Validate transport shape only; it is not an evidence acceptance gate."""
    c.require(type(handle) is dict and set(handle) == SYNTHETIC_KEYS
        and handle['schemaVersion'] == SYNTHETIC_SCHEMA and handle['evidenceMode'] == 'synthetic'
        and handle['executionMode'] == 'synthetic' and handle['status'] == 'completed'
        and type(handle['artifactKind']) is str and handle['artifactKind'] in SYNTHETIC_ARTIFACTS,
        'completion_synthetic_binding_invalid')
    for key in ('terminalFactSha256', 'artifactSha256', 'productionRunId'):
        c.require(type(handle[key]) is str and len(handle[key]) == 64
            and all(ch in '0123456789abcdef' for ch in handle[key]), 'completion_hash_invalid')
    for key in ('runId', 'traceId', 'spanId', 'stage', 'workUnitId', 'attemptId',
                'terminalEventId', 'jobId', 'revisionId'):
        c.require(accounting._label(handle[key], None) is not None, 'completion_identity_required')
    try:
        accounting._labels(handle['dependsOn'])
    except ValueError as exc:
        raise c.ContractError('completion_dependencies_invalid') from exc
    c.require(type(handle['dependsOn']) is list, 'completion_dependencies_invalid')
    return deepcopy(handle)


def _batch_rows(events, run_ids):
    checked = log.replay_integrity(events)
    incomplete = {'missing_attempt_start', 'missing_attempt_finish', 'missing_model_start', 'missing_model_finish'}
    # An interrupted OLD collector remains historical partial evidence, not a
    # veto on a new receipt-only recovery. Global conflicts remain failures.
    c.require(not [d for d in checked['diagnostics'] if d['code'] not in incomplete],
        'completion_log_integrity_failed')
    unique = {row['eventId']: row for row in events if row.get('contractVersion') == log.VERSION}
    all_rows = list(unique.values())
    by_run = {}
    for run_id in run_ids:
        rows = [row for row in all_rows if row['runId'] == run_id]
        scoped = log.replay_integrity(rows)
        # Producer sequences span collector runs. Global integrity was checked;
        # an open containing stage is expected while capturing a completion.
        c.require(not [d for d in scoped['diagnostics'] if d['code'] not in
            {'sequence_gap', 'missing_attempt_finish'}], 'completion_log_integrity_failed')
        by_run[run_id] = rows
    return all_rows, by_run


def _rows(events, run_id=None):
    rows, by_run = _batch_rows(events, [] if run_id is None else [run_id])
    return rows if run_id is None else by_run[run_id]


def _stable_schema(operation):
    @wraps(operation)
    def checked(*args, **kwargs):
        # No snapshot is returned or reusable. Reject mutation during this
        # operation as well as observing a fresh schema on the next call.
        with log._schema_snapshot_lock:
            schema_key = (log.VERSION, log._schema_snapshot()[0])
        # Never hold the schema lock across ledger IO (writers acquire their
        # file lock before validating schema, so doing so would invert locks).
        result = operation(*args, **kwargs)
        with log._schema_snapshot_lock:
            c.require((log.VERSION, log._schema_snapshot()[0]) == schema_key, 'completion_schema_changed')
        return result
    return checked


@_stable_schema
def validate_many(checks, events, *, production_run_id):
    """Validate V1 handles together; no reusable validation authority escapes.

    Each check contains handle and optional stage/artifact_sha256/dependencies.
    Every call copies current inputs and repeats global and per-run integrity.
    """
    return _validate_many(checks, events, production_run_id=production_run_id, synthetic=False)


@_stable_schema
def validate_synthetic_many(checks, events, *, production_run_id):
    """Explicit V2 batch, additionally accepting per-check job_id/revision_id."""
    return _validate_many(checks, events, production_run_id=production_run_id, synthetic=True)


def _validate_many(checks, events, *, production_run_id, synthetic):
    c.require(type(checks) is list, 'completion_batch_invalid')
    checks = deepcopy(checks)
    events = deepcopy(events)
    allowed = {'handle', 'stage', 'artifact_sha256', 'dependencies'}
    if synthetic:
        allowed |= {'job_id', 'revision_id'}
    run_ids = []
    for check in checks:
        c.require(type(check) is dict and 'handle' in check and set(check) <= allowed,
            'completion_batch_invalid')
        handle = check['handle']
        c.require(type(handle) is dict and type(handle.get('runId')) is str, 'completion_binding_invalid')
        if handle['runId'] not in run_ids:
            run_ids.append(handle['runId'])
    _, by_run = _batch_rows(events, run_ids)
    result = []
    for check in checks:
        args = dict(check)
        handle = args.pop('handle')
        job = args.pop('job_id', None)
        revision = args.pop('revision_id', None)
        if synthetic:
            c.require(handle.get('schemaVersion') == SYNTHETIC_SCHEMA, 'completion_synthetic_version_required')
        _validate_shape(handle, production_run_id=production_run_id, synthetic=synthetic)
        checked = _validate_in_rows(handle, by_run[handle['runId']],
            production_run_id=production_run_id, synthetic=synthetic, **args)
        if synthetic:
            c.require(job is None or checked['jobId'] == job, 'completion_job_changed')
            c.require(revision is None or checked['revisionId'] == revision, 'completion_revision_changed')
        result.append(checked)
    return result


def validate(handle, events, *, production_run_id, stage=None, artifact_sha256=None,
             dependencies=None):
    """Validate a v1 production completion; synthetic evidence is opt-in only."""
    return _validate(handle, events, production_run_id=production_run_id, stage=stage,
        artifact_sha256=artifact_sha256, dependencies=dependencies, synthetic=False)


def _validate(handle, events, *, production_run_id, synthetic, stage=None,
              artifact_sha256=None, dependencies=None):
    _validate_shape(handle, production_run_id=production_run_id, synthetic=synthetic)
    return _validate_in_rows(handle, _rows(events, handle['runId']),
        production_run_id=production_run_id, synthetic=synthetic, stage=stage,
        artifact_sha256=artifact_sha256, dependencies=dependencies)


def _validate_shape(handle, *, production_run_id, synthetic):
    # The public entry point selects the evidence domain. Never infer it from
    # caller-supplied handles at an existing production acceptance gate.
    if synthetic:
        validate_synthetic_shape(handle)
    keys, artifacts, modes = ((SYNTHETIC_KEYS, SYNTHETIC_ARTIFACTS, {'synthetic'}) if synthetic
        else (KEYS, ARTIFACTS, MODES))
    c.require(type(handle) is dict and set(handle) == keys
        and handle['schemaVersion'] == (SYNTHETIC_SCHEMA if synthetic else SCHEMA)
        and handle['productionRunId'] == production_run_id and handle['status'] == 'completed'
        and handle['artifactKind'] in artifacts and handle['executionMode'] in modes,
        'completion_binding_invalid')
    for key in ('terminalFactSha256', 'artifactSha256', 'productionRunId'):
        c.require(type(handle[key]) is str and len(handle[key]) == 64
            and all(ch in '0123456789abcdef' for ch in handle[key]), 'completion_hash_invalid')
    c.require(type(handle['dependsOn']) is list and len(set(handle['dependsOn'])) == len(handle['dependsOn'])
        and handle['workUnitId'] is not None and handle['attemptId'] is not None,
        'completion_identity_required')


def _validate_in_rows(handle, rows, *, production_run_id, synthetic, stage=None,
                      artifact_sha256=None, dependencies=None):
    span = [r for r in rows if r.get('runId') == handle['runId'] and r.get('spanId') == handle['spanId']]
    starts = [r for r in span if r['event'] == 'stage_started']
    ends = [r for r in span if r['event'] == 'stage_finished']
    c.require(len(starts) == len(ends) == 1 and ends[0]['status'] == 'completed',
        'completion_terminal_required')
    c.require(not any(r.get('runId') == handle['runId'] and r.get('parentSpanId') == handle['spanId']
        and r['event'] == 'stage_started' for r in rows), 'completion_container_forbidden')
    end = ends[0]
    c.require(all(handle[k] == end.get(k) for k in
        ('runId', 'productionRunId', 'traceId', 'spanId', 'stage', 'workUnitId', 'attemptId', 'dependsOn'))
        and handle['terminalEventId'] == end['eventId']
        and handle['terminalFactSha256'] == log.fact_hash(end), 'completion_terminal_changed')
    if synthetic:
        c.require(handle['evidenceMode'] == end.get('evidenceMode') == 'synthetic'
            and all(accounting._label(handle[k], None) is not None
                and handle[k] == end.get(k) == starts[0].get(k) for k in ('jobId', 'revisionId'))
            and handle['artifactSha256'] == end.get('artifactSha256'),
            'completion_synthetic_binding_invalid')
    c.require(stage is None or handle['stage'] == stage, 'completion_stage_changed')
    c.require(artifact_sha256 is None or handle['artifactSha256'] == artifact_sha256,
        'completion_artifact_changed')
    c.require(dependencies is None or handle['dependsOn'] == dependencies, 'completion_dependencies_changed')
    return deepcopy(handle)


def current_events():
    identity = accounting._identity.get()
    c.require(identity is not None, 'completion_accounting_required')
    events, errors = accounting.read_events(identity[0])
    c.require(not errors, 'completion_log_damaged')
    return identity, events


@_stable_schema
def capture(span_id, *, production_run_id, artifact_sha256, artifact_kind,
            execution_mode='current_execution'):
    identity, events = current_events()
    rows = _rows(events, identity[1])
    ends = [row for row in rows if row.get('runId') == identity[1]
        and row.get('spanId') == span_id and row['event'] == 'stage_finished']
    c.require(len(ends) == 1, 'completion_terminal_required')
    end = ends[0]
    handle = {k: end[k] for k in ('runId', 'traceId', 'spanId', 'stage', 'workUnitId',
                                'attemptId', 'status', 'dependsOn')}
    handle.update(schemaVersion=SCHEMA, productionRunId=production_run_id,
        terminalEventId=end['eventId'], terminalFactSha256=log.fact_hash(end),
        artifactSha256=artifact_sha256, artifactKind=artifact_kind, executionMode=execution_mode)
    _validate_shape(handle, production_run_id=production_run_id, synthetic=False)
    return _validate_in_rows(handle, rows, production_run_id=production_run_id, synthetic=False)


def validate_synthetic(handle, events, *, production_run_id, job_id=None, revision_id=None,
                       **kwargs):
    c.require(type(handle) is dict and handle.get('schemaVersion') == SYNTHETIC_SCHEMA,
        'completion_synthetic_version_required')
    checked = _validate(handle, events, production_run_id=production_run_id, synthetic=True, **kwargs)
    c.require(job_id is None or checked['jobId'] == job_id, 'completion_job_changed')
    c.require(revision_id is None or checked['revisionId'] == revision_id, 'completion_revision_changed')
    return checked


@_stable_schema
def capture_synthetic(span_id, *, production_run_id, artifact_sha256, artifact_kind,
                      job_id, revision_id):
    """Capture a synthetic leaf whose terminal binds the verified artifact.

    The worker supplies job/revision through profile.context, then records
    stage_outcome.finish('completed', artifact_sha256=...). No Source artifact
    type or production qualification is implied by a synthetic completion.
    """
    identity, events = current_events()
    rows = _rows(events, identity[1])
    ends = [row for row in rows if row.get('spanId') == span_id
        and row['event'] == 'stage_finished']
    c.require(len(ends) == 1, 'completion_terminal_required')
    end = ends[0]
    handle = {k: end[k] for k in ('runId', 'traceId', 'spanId', 'stage', 'workUnitId',
                                'attemptId', 'status', 'dependsOn')}
    handle.update(schemaVersion=SYNTHETIC_SCHEMA, productionRunId=production_run_id,
        terminalEventId=end['eventId'], terminalFactSha256=log.fact_hash(end),
        artifactSha256=artifact_sha256, artifactKind=artifact_kind, executionMode='synthetic',
        evidenceMode='synthetic', jobId=job_id, revisionId=revision_id)
    _validate_shape(handle, production_run_id=production_run_id, synthetic=True)
    return _validate_in_rows(handle, rows, production_run_id=production_run_id, synthetic=True)

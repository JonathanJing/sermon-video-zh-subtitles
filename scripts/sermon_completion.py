"""Typed, evidence-backed execution leaves; no container or timing inference.

Handles refer to an already durable terminal event and one verified artifact.
They do not grant dispatch authority and cannot turn historical receipts into
current provider execution. Equivalent outbox replay is accepted; conflicts fail.
"""
from copy import deepcopy

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


def _rows(events, run_id=None):
    checked = log.replay_integrity(events)
    incomplete = {'missing_attempt_start', 'missing_attempt_finish', 'missing_model_start', 'missing_model_finish'}
    # Preserve global event/sequence conflicts, but an interrupted OLD collector
    # run remains historical partial evidence, not a veto on a new receipt-only
    # recovery. No old fact is removed or completed here.
    c.require(not [d for d in checked['diagnostics'] if d['code'] not in incomplete],
        'completion_log_integrity_failed')
    unique = {row['eventId']: row for row in events if row.get('contractVersion') == log.VERSION}
    rows = list(unique.values())
    if run_id is not None:
        rows = [row for row in rows if row['runId'] == run_id]
        scoped = log.replay_integrity(rows)
        # Producer sequence numbers span collector runs; their global integrity
        # was already checked. An open containing stage is expected at capture.
        c.require(not [d for d in scoped['diagnostics'] if d['code'] not in
            {'sequence_gap', 'missing_attempt_finish'}], 'completion_log_integrity_failed')
    return rows


def validate(handle, events, *, production_run_id, stage=None, artifact_sha256=None,
             dependencies=None):
    """Validate a v1 production completion; synthetic evidence is opt-in only."""
    return _validate(handle, events, production_run_id=production_run_id, stage=stage,
        artifact_sha256=artifact_sha256, dependencies=dependencies, synthetic=False)


def _validate(handle, events, *, production_run_id, synthetic, stage=None,
              artifact_sha256=None, dependencies=None):
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
    rows = _rows(events, handle['runId'])
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
    return validate(handle, events, production_run_id=production_run_id)


def validate_synthetic(handle, events, *, production_run_id, job_id=None, revision_id=None,
                       **kwargs):
    c.require(type(handle) is dict and handle.get('schemaVersion') == SYNTHETIC_SCHEMA,
        'completion_synthetic_version_required')
    checked = _validate(handle, events, production_run_id=production_run_id, synthetic=True, **kwargs)
    c.require(job_id is None or checked['jobId'] == job_id, 'completion_job_changed')
    c.require(revision_id is None or checked['revisionId'] == revision_id, 'completion_revision_changed')
    return checked


def capture_synthetic(span_id, *, production_run_id, artifact_sha256, artifact_kind,
                      job_id, revision_id):
    """Capture a synthetic leaf whose terminal binds the verified artifact.

    The worker supplies job/revision through profile.context, then records
    stage_outcome.finish('completed', artifact_sha256=...). No Source artifact
    type or production qualification is implied by a synthetic completion.
    """
    identity, events = current_events()
    ends = [row for row in _rows(events, identity[1]) if row.get('spanId') == span_id
        and row['event'] == 'stage_finished']
    c.require(len(ends) == 1, 'completion_terminal_required')
    end = ends[0]
    handle = {k: end[k] for k in ('runId', 'traceId', 'spanId', 'stage', 'workUnitId',
                                'attemptId', 'status', 'dependsOn')}
    handle.update(schemaVersion=SYNTHETIC_SCHEMA, productionRunId=production_run_id,
        terminalEventId=end['eventId'], terminalFactSha256=log.fact_hash(end),
        artifactSha256=artifact_sha256, artifactKind=artifact_kind, executionMode='synthetic',
        evidenceMode='synthetic', jobId=job_id, revisionId=revision_id)
    return validate_synthetic(handle, events, production_run_id=production_run_id,
        job_id=job_id, revision_id=revision_id)

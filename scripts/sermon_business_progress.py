"""Readonly business evidence → existing progress projection, for offline fixtures.

Equal weights describe frozen callback nodes, not sentences, percent of quality,
wall time, or production readiness. No assumed queue time or human approval.
Observation files preserve unknown attempts across cache/restart projections;
this adapter cannot manufacture a reconciliation proof.
"""
from datetime import datetime, timezone
from pathlib import Path

from scripts import sermon_review_contracts as c
from scripts import sermon_run_progress as progress
from scripts import sermon_strict_layer2 as strict


def freeze(dag):
    units = []
    for node, identity in zip(dag.nodes, dag.binding['nodes']):
        required = ['executionSucceeded']
        if node.operation in {'source_check', 'locale', 'render_speech'}:
            required.append('contentReviewPassed')
        if node.operation in {'admit_locale', 'prepare_speech'}:
            required.append('admitted')
        if node.operation == 'admit_locale':
            required.append('simulatedHumanApproved')
        units.append({'id': node.id, 'identitySha256': c.canonical_sha256(identity),
            'dependsOn': list(node.depends_on), 'weight': 1,
            'stage': node.operation, 'model': 'mixed_or_not_applicable',
            'locale': 'unspecified', 'lengthBucket': 'callback_node',
            'cacheClass': 'unknown', 'resourceClass': 'serialized_offline_callback',
            'resources': ['callback'], 'requiredEvidence': required})
    plan = progress.freeze_plan('offline-business', 1, dag.callbacks.subject.config['runId'],
        units, {'callback': {'capacity': 1, 'resourceClass': 'serialized_offline_callback'}},
        dag_version=dag.plan_sha256, weight_policy_version='equal-frozen-callback-nodes-v1')
    strict.save_once(dag.root / 'business-progress-plan.json', plan)
    return plan


def _receipt(dag, plan, node, native, sequence, at):
    row = dict(native)
    validated = False
    if node.id in dag._envelopes and row.get('executionStatus') == 'completed':
        try:
            refreshed = dag._validate(node, dag._envelopes[node.id])
            c.require(all(row.get(key) == value for key, value in refreshed.items()),
                      'business_progress_evidence_changed')
            validated = True
        except (OSError, ValueError, KeyError, TypeError):
            row.update(executionStatus='outcome_unknown', processed=None,
                       reason='business_progress_evidence_changed')
    unknown = row.get('executionStatus') == 'outcome_unknown' or row.get('processed') is None
    completed = row.get('executionStatus') == 'completed' and validated
    status = 'outcome_unknown' if unknown else 'succeeded' if completed else 'pending'
    artifact = row.get('artifactSha256') if validated else None
    machine_pass = completed and row.get('machineStatus') == 'pass'
    simulated = completed and row.get('humanStatus') in {
        'original_receipt_validated', 'original_receipts_validated_by_callback'}
    admitted = completed and row.get('admissionStatus') in {'prepare_layer3_intent', 'prepared'}
    facts = {'executionSucceeded': completed, 'contentReviewPassed': machine_pass,
             'simulatedHumanApproved': simulated, 'realHumanApproved': False, 'admitted': admitted}
    unit = next(item for item in plan['units'] if item['id'] == node.id)
    gates_complete = all(facts[key] for key in unit['requiredEvidence'])
    fingerprint = c.canonical_sha256(row)
    spans = row.get('completionSpans', [])
    measured = completed and bool(spans) and row.get('elapsedSeconds') is not None
    return progress.status_receipt(plan, node.id,
        event_id='business.' + fingerprint, attempt_id='attempt.' + (spans[0] if spans else fingerprint),
        sequence=sequence, observed_at=at,
        executionStatus=status,
        reviewVerdict='pass' if machine_pass else ('needs_rework' if completed and row.get('machineStatus') in {'needs_review', 'blocked'} else 'not_assessed'),
        humanReviewKind='simulated' if simulated else 'none',
        humanApprovalStatus='approved' if simulated else 'pending',
        admissionStatus='admitted' if admitted else 'waiting_human' if completed and row.get('humanStatus') == 'pending' else 'blocked',
        phase='unknown_outcome' if unknown else 'complete' if gates_complete else 'waiting_review' if completed and row.get('humanStatus') == 'pending' else 'blocked',
        evidenceValidated=validated, artifactSha256=artifact,
        reviewedArtifactSha256=artifact if machine_pass else None,
        humanReviewedArtifactSha256=artifact if simulated else None,
        evidenceRefs=['callback.' + row['resultSha256'], *spans] if validated else [],
        reasonCode=row.get('reason'), heartbeatStatus='not_applicable' if completed else 'unknown',
        measurementValidated=measured, elapsedSeconds=row.get('elapsedSeconds') if measured else None,
        timingSampleId='spans.' + c.canonical_sha256(spans) if measured else None,
        queueRemainingSeconds=None)


def update(dag, *, at=None):
    """Called serially under the flow's work lock, inside its accounting session.

    Revalidates actual original artifacts/spans, stores immutable observations,
    then atomically updates the disposable projection. No native ledger changes.
    """
    dag._check()
    at = at or datetime.now(timezone.utc).isoformat()
    plan = freeze(dag)
    folder = strict._safe_path(dag.root / 'business-progress-observations')
    folder.mkdir(exist_ok=True)
    history = []
    for path in sorted(folder.glob('*.json')):
        value = c.read_snapshot(path)[0]
        c.require(path.stem == c.canonical_sha256(value) and value['planSha256'] == plan['planSha256'],
                  'business_progress_history_changed')
        history.append(value['receipt'])
    known = {row['eventId']: row for row in history}
    sequence = max((row['sequence'] for row in history), default=0)
    for node in dag.nodes:
        native = dag._outcomes.get(node.id)
        if native is None:
            # Unobserved is deliberately missing, never asserted not dispatched.
            continue
        receipt = _receipt(dag, plan, node, native, sequence + 1, at)
        if receipt['eventId'] in known:
            continue
        sequence += 1
        value = {'planSha256': plan['planSha256'], 'receipt': receipt}
        strict.save_once(folder / (c.canonical_sha256(value) + '.json'), value)
        known[receipt['eventId']] = receipt
        history.append(receipt)
    snapshot = progress.project_progress(plan, history, at=at)
    snapshot.update(evidenceMode='synthetic', productionEligible=False, executionAuthority='none',
                    unitScope='equal_weight_callback_nodes_not_segments', nativePlanSha256=dag.plan_sha256)
    progress.write_progress(dag.root / 'business-progress.json', snapshot)
    return snapshot

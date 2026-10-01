"""Read-only integration of frozen MOCK DAG receipts, progress and diagnostics.

No live clients, dispatch, reconciliation mutation or production approval adapter.
The existing work lock must be present and idle. Every positive progress fact is
revalidated from original job/artifact/trace/budget evidence, never snapshot flags.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import stat

from scripts import sermon_prefect_dag as pilot
from scripts import sermon_run_progress as progress
from scripts import sermon_agent_diagnostics as diagnostics
from scripts import sermon_agent_diagnostics_contracts as dc

SCHEMA = 'sermon-pilot-inspection-v1'


def utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def inventory(root):
    """Bounded hashes of authoritative evidence; excludes Prefect DB/cache/UI."""
    result, total = {}, 0
    paths = [root/'plan.json', root/'runtime.json']
    for name in ('nodes', 'jobs', 'mock-budget', 'accounting', 'accounting-sessions'):
        base = root/name
        if base.is_symlink():
            raise ValueError('pilot_evidence_symlink')
        if base.exists():
            for path in base.rglob('*'):
                if path.is_symlink():
                    raise ValueError('pilot_evidence_symlink')
                if path.is_file():
                    paths.append(path)
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            raise ValueError('pilot_evidence_not_regular')
        size = path.stat().st_size
        total += size
        if size > 16*1024*1024 or total > 64*1024*1024 or len(paths) > 4096:
            raise ValueError('pilot_evidence_bound_exceeded')
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


@contextmanager
def frozen_reader(root):
    root = Path(root).absolute()
    pilot.jobs._reject_link(root, directory=True)
    root = root.resolve()
    folder = root.parent/'.harness-locks'
    pilot.jobs._reject_link(folder, directory=True)
    path = folder/(hashlib.sha256(str(root).encode()).hexdigest()+'.lock')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('pilot_lock_not_regular')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('pilot_writer_active') from exc
        before = inventory(root)
        yield root, before
        if inventory(root) != before:
            raise ValueError('pilot_evidence_changed_during_inspection')
    finally:
        os.close(fd)


def frozen_progress_plan(plan):
    units = []
    for node in plan['nodes']:
        required = ['executionSucceeded', 'contentReviewPassed', 'admitted']
        if node['humanGates']:
            required.append('simulatedHumanApproved' if plan['simulatedHuman'] else 'realHumanApproved')
        units.append({'id': node['id'], 'identitySha256': pilot.c.canonical_sha256({
            'planSha256': plan['planSha256'], 'node': node}),
            'stage': 'pilot.mock.'+node['id'], 'model': 'none', 'locale': node['locale'] or 'shared',
            'lengthBucket': 'synthetic_fixed', 'cacheClass': 'mock', 'resourceClass': node['resourcePool'],
            'dependsOn': node['dependsOn'], 'weight': node['weight'], 'resources': [node['resourcePool']],
            'requiredEvidence': required})
    return progress.freeze_plan('mock_'+plan['runId'], 1, plan['runId'], units,
        {key: {'capacity': value, 'resourceClass': key} for key, value in plan['resourceLimits'].items()},
        dag_version=plan['schemaVersion'], weight_policy_version=plan['weightVersion'])


def _failure(root, plan, node, dependencies, job_status):
    """A controlled failure needs matching job and (for L2) durable result proof."""
    value = pilot.read(pilot.node_dir(root, node)/'failure.json')
    core = pilot._core(plan, node, dependencies)
    expected_status = {'known_failure': 'failed', 'outcome_unknown': 'outcome_unknown'}.get(node['mockScenario'])
    pilot.c.require(job_status == 'failed' and expected_status is not None
        and value == {**core, 'executionStatus': expected_status, 'reason': 'controlled_'+node['mockScenario']},
        'pilot_failure_not_verified')
    if node['layer'] == 2:
        store = pilot.mock_store(root, plan)
        ledger = pilot.read(store.root/pilot.budget.STORE_ID/'state.json')
        pilot.c.require(ledger.get('authority') == store.authority and ledger.get('storeSha256') == store.store_sha256
                        and ledger.get('schemaVersion') == pilot.budget.SCHEMA, 'pilot_budget_identity_changed')
        rows = [(key, row) for key, row in ledger['reservations'].items()
                if row['request']['identity'] == pilot.chain(plan, node)]
        pilot.c.require(len(rows) == 1, 'pilot_failure_budget_missing')
        key, row = rows[0]
        store._validate_row(key, row)
        pilot.c.require(row['request']['inputSha256'] == core['identitySha256'] and row['phase'] == 'result'
            and row['result'] == {'executionStatus': expected_status, 'contentStatus': 'not_assessed',
                'receiptSha256': pilot.c.canonical_sha256(value),
                'usage': None if expected_status == 'outcome_unknown' else pilot.amounts()}, 'pilot_failure_budget_mismatch')
    return value


def _manifest(plan, node, status, evidence_hash, at):
    identity = {'runId': plan['runId'], 'sourceId': 'synthetic_source',
        'sourceSha256': plan['inputIdentitySha256'], 'targetLocale': node['locale'] or 'en',
        'stage': 'layer'+str(node['layer']), 'stateRevision': 1, 'packageVersion': 'mock_v1',
        'planVersion': plan['planSha256'], 'policyVersion': 'mock_only_v1', 'revisionId': 'r1', 'evidenceCutoff': at}
    unit = {'unitId': node['id'].replace('.', '_'), 'unitVersion': 'r1'}
    reason = 'outcome_unknown' if status == 'outcome_unknown' else 'not_assessed' if status == 'failed' else 'dependency_blocked'
    row = {'evidenceId': 'observation_'+evidence_hash[:48], 'evidenceType': 'event', 'identity': identity,
        'units': [unit], 'observedAt': at, 'status': 'uncertain' if status == 'outcome_unknown' else status,
        'reasonCode': reason, 'attemptId': 'mock_1', 'callId': None, 'model': None, 'usage': None}
    row['sha256'] = dc.evidence_sha256(row)
    return dc.validate_manifest({'schemaVersion': dc.INPUT_VERSION, 'redacted': True, 'identity': identity,
        'failedUnits': [unit], 'events': [row], 'receipts': [], 'versionDiffs': [],
        'missingEvidenceTypes': ['reproduction', 'receipt']})


def offline_diagnosis(manifest):
    """Exercise real offline lifecycle with an explicitly synthetic non-answer."""
    bundle = diagnostics.build_context_bundle(manifest)
    report = {'schemaVersion': dc.OUTPUT_VERSION, 'identity': bundle['manifest']['identity'],
        'contextSha256': bundle['contextSha256'], 'snapshotId': bundle['snapshotId'],
        'status': 'needs_more_evidence', 'hypotheses': [],
        'missingDataRequests': [{'kind': kind,
            'unitIds': [row['unitId'] for row in bundle['manifest']['failedUnits']],
            'question': 'Independently validate the original failure and any proposed recovery before execution.'}
            for kind in bundle['manifest']['missingEvidenceTypes']],
        'limitations': ['Synthetic offline lifecycle fixture. No model diagnosis or cause was inferred.']}
    frame = {'session': {'id': 'sess_offline', 'status': 'idle', 'required_actions': []},
        'turns': [{'id': 'turn_offline', 'subagent_id': None, 'status': 'completed'}]}
    import json
    item = {'type': 'message', 'role': 'assistant', 'status': 'completed', 'phase': 'final_answer',
        'turn_id': 'turn_offline', 'content': [{'type': 'output_text', 'text': json.dumps(report)}]}
    result = diagnostics.diagnose(manifest, client=diagnostics.OfflineReplayClient([frame], [item]))
    return {'evidenceMode': 'synthetic_offline_fixture', 'result': result}


def inspect(root, *, diagnose_offline=False):
    with frozen_reader(root) as (root, files):
        plan = pilot.load(root)
        frozen = frozen_progress_plan(plan)
        at, issues, events, ledger_hash = utc(), [], [], None
        if (root/'accounting/events.jsonl').exists():
            events, damaged, ledger_hash = pilot.accounting.read_event_snapshot(root/'accounting')
            integrity = pilot.accounting.profile_integrity(events)
            if damaged or integrity['status'] != 'consistent':
                issues.append('accounting_integrity_unknown')
            if any(e['event'].startswith('api_attempt') for e in events):
                issues.append('unexpected_model_transport_in_mock')
        else:
            issues.append('accounting_not_observed')
        global_issues = tuple(issues)
        # Observations of the same frozen ledger have stable IDs/times; repeat
        # inspections cannot fabricate another attempt or conflicting replay.
        observed_at = max((datetime.fromisoformat(e['recordedAt'].replace('Z', '+00:00'))
                           for e in events), default=datetime.fromisoformat(at.replace('Z', '+00:00'))).isoformat().replace('+00:00', 'Z')
        valid, statuses, evidence, manifests, known_jobs = {}, [], {}, {}, set()
        for node in plan['nodes']:
            key = node['id']
            folder = pilot.node_dir(root, node)
            state = {'executionStatus': 'pending', 'phase': 'blocked', 'reasonCode': 'dependency_not_verified',
                     'queueRemainingSeconds': None}
            proof = {'status': 'blocked', 'reason': 'dependency_not_verified', 'jobId': None, 'receiptSha256': None}
            if all(dep in valid for dep in node['dependsOn']):
                dependencies = {dep: valid[dep]['outputSha256'] for dep in node['dependsOn']}
                identity = pilot.contract.node_identity(plan, node, dependencies)
                job_id = pilot.jobs._digest({'pilotPlanSha256': plan['planSha256'], 'nodeIdentitySha256': identity})
                known_jobs.add(job_id)
                proof['jobId'] = job_id
                job_folder = root/'jobs'/job_id
                if not job_folder.exists():
                    if folder.exists():
                        issues.append('node_without_durable_job')
                        state.update(executionStatus='outcome_unknown', phase='unknown_outcome', reasonCode='job_not_observed')
                    elif node['humanGates'] and not plan['simulatedHuman']:
                        state.update(phase='waiting_review', humanReviewKind='real', reasonCode='real_human_review_pending')
                else:
                    try:
                        job_status = pilot.jobs.peek_job(root/'jobs', job_id)['status']
                        if job_status == 'succeeded':
                            receipt = pilot.valid_receipt(root, plan, node, dependencies)
                            if global_issues:
                                raise ValueError('input_integrity_unknown')
                            valid[key] = receipt
                            sha = pilot.c.canonical_sha256(receipt)
                            artifact = receipt['outputSha256']
                            state.update(executionStatus='succeeded', phase='complete', evidenceValidated=True,
                                artifactSha256=artifact, evidenceRefs=['receipt_'+sha], reasonCode=None,
                                reviewVerdict='pass', reviewedArtifactSha256=artifact, admissionStatus='admitted',
                                measurementValidated=True, elapsedSeconds=receipt['elapsedSeconds'],
                                timingSampleId='receipt_'+sha, heartbeatStatus='not_applicable')
                            if receipt['simulatedHumanStatus'] == 'simulated':
                                state.update(humanReviewKind='simulated', humanApprovalStatus='approved',
                                             humanReviewedArtifactSha256=artifact)
                            proof.update(status='succeeded', reason=None, receiptSha256=sha, spanId=receipt['spanId'])
                        elif job_status == 'failed':
                            failure = _failure(root, plan, node, dependencies, job_status)
                            state.update(executionStatus=failure['executionStatus'],
                                phase='unknown_outcome' if failure['executionStatus']=='outcome_unknown' else 'blocked',
                                reasonCode=failure['reason'])
                            proof.update(status=failure['executionStatus'], reason=failure['reason'],
                                         receiptSha256=pilot.c.canonical_sha256(failure))
                        else:
                            state.update(executionStatus='outcome_unknown', phase='unknown_outcome', reasonCode='job_outcome_unknown')
                            proof.update(status='outcome_unknown', reason='job_outcome_unknown')
                    except (ValueError, OSError, KeyError, TypeError):
                        issues.append('original_evidence_not_verified')
                        state.update(executionStatus='outcome_unknown', phase='unknown_outcome', reasonCode='original_evidence_not_verified')
                        proof.update(status='outcome_unknown', reason='original_evidence_not_verified')
            elif folder.exists():
                state.update(executionStatus='outcome_unknown', phase='unknown_outcome', reasonCode='upstream_evidence_changed')
                proof.update(status='outcome_unknown', reason='upstream_evidence_changed')
            proof['status'] = ('blocked' if state['executionStatus']=='pending' else state['executionStatus'])
            proof['reason'] = state['reasonCode']
            evidence[key] = proof
            statuses.append(progress.status_receipt(frozen, key, event_id='inspection_'+pilot.c.canonical_sha256({'unitId': key, 'proof': proof, 'ledgerSha256': ledger_hash}),
                attempt_id='mock-1', sequence=len(events)+1, observed_at=observed_at, **state))
            if state['executionStatus'] != 'succeeded':
                manifests[key] = _manifest(plan, node, proof['status'], pilot.c.canonical_sha256(proof), at)
        job_root = root/'jobs'
        if job_root.exists() and any(p.is_dir() and p.name != '.locks' and p.name not in known_jobs for p in job_root.iterdir()):
            issues.append('unbound_durable_jobs')
        projected = progress.project_progress(frozen, statuses, at=at, input_issues=sorted(set(issues)))
        result = {'schemaVersion': SCHEMA, 'evidenceMode': 'synthetic', 'productionEligible': False,
            'executionAuthority': 'none', 'runId': plan['runId'], 'sourceIdentitySha256': plan['inputIdentitySha256'],
            'executionPlanSha256': plan['planSha256'], 'runtimeCodeSha256': pilot.code_identity(),
            'readerCodeSha256': pilot.c.canonical_sha256({name: hashlib.sha256((pilot.REPO/'scripts'/name).read_bytes()).hexdigest()
                for name in ('sermon_pilot_evidence.py', 'sermon_run_progress.py', 'sermon_agent_diagnostics.py',
                             'sermon_agent_diagnostics_contracts.py')}),
            'evidenceSnapshotSha256': pilot.c.canonical_sha256(files), 'sourceLedgerSha256': ledger_hash,
            'evidenceFiles': files, 'validatedNodeEvidence': evidence, 'progressPlan': frozen,
            'statusReceipts': statuses, 'progress': projected, 'diagnosticManifests': manifests,
            'diagnostics': {key: offline_diagnosis(value) for key, value in manifests.items()} if diagnose_offline else {},
            'limitations': ['Mock business adapters only; production/provider dispatch remains unwired.',
                'Simulated human and synthetic review/admission do not grant real acceptance.',
                'Frozen inspection only; no live heartbeat/resource queue monitor or durable reconciliation adapter.',
                'Offline diagnostic fixture is not model inference; usage and costs are not measured.']}
    return result

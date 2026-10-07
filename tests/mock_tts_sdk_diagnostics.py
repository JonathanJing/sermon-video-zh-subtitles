"""Bounded read-only diagnostics for the existing synthetic SDK acceptance.

No original request, receipt, input, job or log is changed. Optional CI evidence
copies are test artifacts, not a new producer or an acceptance fallback.
"""
import json
import os
from pathlib import Path
import re
import shutil

from scripts import sermon_accounting as accounting
from scripts import sermon_review_contracts as c


def status_diagnostics(value, events, damaged):
    """Separate observed outcomes; this projection never grants recovery authority."""
    nodes = value.get('nodes', {})
    engine = value.get('engineEvidence', {})
    states = [row.get('engineState') for row in engine.values()]
    engine_complete = bool(nodes) and set(engine) == set(nodes) and all(s == 'Completed' for s in states)
    replay = accounting.profile_integrity(events)
    seen, errors, reconciliations = set(), [], []
    for event in events:
        identity = event.get('eventId')
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        diagnostic = accounting.diagnostic_event(event)
        if (diagnostic['level'] in {'ERROR', 'CRITICAL'} or
                diagnostic.get('status') in {'failed', 'cancelled', 'blocked', 'outcome_unknown'} or
                event.get('status') in {'failed', 'cancelled', 'blocked', 'outcome_unknown'}):
            errors.append(event)
        if event.get('event') == 'attempt_reconciled':
            reconciliations.append(event)
    recovery = []
    for event in errors:
        matches = [r for r in reconciliations
            if event.get('event') == 'stage_finished' and event.get('status') == 'outcome_unknown'
            and r.get('runId') == event.get('runId')
            and r.get('reconcilesAttemptId') == event.get('attemptId')
            and all(r.get(k) == event.get(k) for k in ('jobId', 'revisionId'))]
        verified = (not damaged and replay['status'] == 'consistent' and len(matches) == 1
            and id(event) in replay.get('_selected', set())
            and id(matches[0]) in replay.get('_selected', set()))
        recovery.append({'eventId': event.get('eventId'), 'attemptId': event.get('attemptId'),
            'historicalStatus': accounting.diagnostic_event(event).get('status'),
            'reconciliation': 'recorded' if verified else 'unknown',
            'reconciliationResult': matches[0].get('result') if verified else None,
            'reconciliationEventId': matches[0].get('eventId') if verified else None})
    return {'diagnosticOnly': True, 'executionAuthority': 'none',
        'scope': 'saved_invocation_and_entire_current_ledger_not_live_health',
        'engine': {'aggregate': 'all_tasks_completed' if engine_complete else 'not_all_tasks_completed' if states else 'unknown',
            'observedTaskCount': len(states), 'expectedTaskCount': len(nodes),
            'stateCounts': {str(state): states.count(state) for state in sorted(set(states), key=str)}},
        'business': {'status': value.get('status', 'unknown'), 'authority': 'original_result_unchanged'},
        'history': {'errorEventCount': len(errors) if events else None,
            'reconciliationEventCount': len(reconciliations) if events else None,
            'integrity': 'damaged' if damaged else replay['status'] if events else 'unknown', 'errors': recovery,
            'recoveryInterpretation': 'Only explicit canonical attempt reconciliation is reported; successful later work does not resolve every historical error.'}}


def result_summary(value, root):
    root = Path(root)
    result = {key: value.get(key) for key in ('planSha256', 'invocationId', 'status',
        'newMockDispatches', 'syntheticProviderDispatches', 'unknownDispatchAcknowledgements')}
    result['nodes'] = {key: {name: row.get(name) for name in
        ('executionStatus', 'reason', 'errorType', 'jobId')}
        for key, row in value.get('nodes', {}).items()}
    result['jobs'] = []
    for path in sorted((root/'mock-control'/'jobs').glob('*/state.json'))[:6]:
        state = json.loads(path.read_text())
        item = {key: state.get(key) for key in ('jobId', 'status', 'reason', 'errorType', 'returnCode')}
        logfile = path.parent/'worker.log'
        codes, frames = [], []
        if logfile.exists():
            with logfile.open('rb') as stream:
                stream.seek(max(0, logfile.stat().st_size-65536))
                lines = stream.read(65536).decode('utf-8', errors='replace').splitlines()
            for line in lines:
                code = re.fullmatch(r'([A-Za-z][A-Za-z0-9_.]*(?:Error|Exception)):\s*([a-z][a-z0-9_]{0,119})', line)
                if code: codes.append({'errorType': code[1].split('.')[-1], 'reasonCode': code[2]})
                frame = re.search(r'/scripts/([A-Za-z0-9_./]+\.py)\", line ([0-9]+)', line)
                if frame and '..' not in Path(frame[1]).parts:
                    frames.append({'file': 'scripts/'+frame[1], 'line': int(frame[2])})
        item.update(workerErrorCodes=codes[-4:], workerFrames=frames[-4:])
        result['jobs'].append(item)
    try:
        events, damaged = accounting.read_events(root/'accounting')
        result['statusDiagnostics'] = status_diagnostics(value, events, damaged)
        result['damagedLogRows'] = len(damaged)
        failed = [row for row in events if row.get('event') == 'stage_finished'
            and row.get('status') not in {'completed'}]
        result['terminalDiagnostics'] = [accounting.diagnostic_event(row) for row in failed[-4:]]
    except (OSError, ValueError) as exc:
        result['diagnosticReadErrorType'] = type(exc).__name__
        result['statusDiagnostics'] = status_diagnostics(value, [], [True])
    return result


def preserve_evidence(fixture_root, scenario):
    destination = os.environ.get('SERMON_MOCK_TEST_EVIDENCE_DIR')
    if not destination:
        return
    if scenario not in {'happy', 'failure', 'timeout'}:
        raise ValueError('invalid_mock_sdk_scenario')
    fixture_root = Path(fixture_root)
    for plan in sorted((fixture_root/'mock-tts-dag').iterdir()):
        if not plan.is_dir() or re.fullmatch('[a-f0-9]{64}', plan.name) is None:
            continue
        target = Path(destination)/scenario/plan.name
        if target.exists():
            raise ValueError('mock_sdk_evidence_destination_exists')
        target.parent.mkdir(parents=True, exist_ok=True)
        # Only this explicitly synthetic acceptance plan. Prefect's local DB
        # and temporary server config are not needed for business diagnostics.
        if any(path.is_symlink() for path in plan.rglob('*')):
            raise ValueError('mock_sdk_evidence_link_rejected')
        shutil.copytree(plan, target, symlinks=True, ignore=shutil.ignore_patterns('prefect', '.prefect*'))
        for result_path in sorted((target/'runs').glob('*.json')):
            value = json.loads(result_path.read_text())
            summary = result_summary(value, target)
            summary['captureScope'] = 'read_only_synthetic_test_evidence_not_new_completion'
            summary['resultBytesSha256'] = c.bytes_sha256(result_path.read_bytes())
            (target/('summary-'+result_path.stem+'.json')).write_text(json.dumps(summary, sort_keys=True, indent=2)+'\n')

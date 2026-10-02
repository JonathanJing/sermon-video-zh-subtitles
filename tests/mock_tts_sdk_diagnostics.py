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
        result['damagedLogRows'] = len(damaged)
        failed = [row for row in events if row.get('event') == 'stage_finished'
            and row.get('status') not in {'completed'}]
        result['terminalDiagnostics'] = [accounting.diagnostic_event(row) for row in failed[-4:]]
    except (OSError, ValueError) as exc:
        result['diagnosticReadErrorType'] = type(exc).__name__
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

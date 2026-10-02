"""Fixed local synthetic worker/submit launcher; never a model or Hub client."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_log_profile as profile
from scripts import sermon_mock_tts_contract as contract
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

ENV_KEYS = frozenset((*accounting.ENV_KEYS, accounting.WORKFLOW_ENV,
    profile.PROFILE_ENV, profile.CONTEXT_ENV, 'PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'LC_CTYPE',
    'PYTHONDONTWRITEBYTECODE', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE',
    'HF_HUB_DISABLE_TELEMETRY', 'TOKENIZERS_PARALLELISM', 'SERMON_HARNESS_GUARDED_CHILDREN'))


def environment(root):
    """Use before launching this interpreter, not merely after it has inherited secrets."""
    root = _safe_path(root)
    raw = accounting.subprocess_environment()
    env = {key: raw[key] for key in (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV,
        profile.PROFILE_ENV, profile.CONTEXT_ENV) if key in raw}
    active = profile.current()
    c.require(active and active['evidenceMode'] == 'synthetic'
        and env.get('SERMON_ACCOUNTING_DIR') and env.get('SERMON_ACCOUNTING_RUN_ID'),
        'mock_tts_synthetic_accounting_required')
    for name in ('home', 'tmp'):
        folder = root/name; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_path(folder)
    env.update(PATH='/usr/local/bin:/usr/bin:/bin', HOME=str(root/'home'), TMPDIR=str(root/'tmp'),
        LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        HF_DATASETS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
    return env


def require_environment():
    c.require(not (set(os.environ) - ENV_KEYS), 'mock_tts_environment_not_scrubbed')
    active = profile.current()
    c.require(active and active['evidenceMode'] == 'synthetic', 'mock_tts_synthetic_accounting_required')
    c.require(all(os.environ.get(key) == '1' for key in
        ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY')),
        'mock_tts_environment_not_scrubbed')


def command(request_path, request_sha256):
    c.require(contract.sha(request_sha256), 'mock_tts_frozen_request_hash_required')
    return [sys.executable, '-I', str(Path(__file__).resolve()), 'execute', '--request', str(request_path),
        '--request-sha256', request_sha256]


def submit(request_path, request_sha256):
    require_environment()
    request_path = _safe_path(request_path)
    request = contract.read_request(request_path)
    c.require(contract.sha(request_sha256) and c.canonical_sha256(request) == request_sha256,
        'mock_tts_frozen_request_changed')
    root = contract.scope_for_request(request_path, request)
    contract.require_intent(root, request)
    return jobs.start_job(root/'jobs', contract.job_identity(request), command(request_path, request_sha256),
        request['workerTimeoutSeconds'])


def _phase(root, request, name, dependency, *, delay=0):
    with accounting.stage_outcome('mock_tts.'+name, work_unit_id=request['unitId']+'.'+name,
            attempt_id=request['attemptId']+'.'+name, depends_on=[dependency['spanId']],
            executor_type='deterministic_program') as attempt:
        fact = {'schemaVersion': 'sermon-mock-tts-lifecycle-v1', 'requestSha256': c.canonical_sha256(request),
            'jobId': request['jobId'], 'attemptId': request['attemptId'], 'phase': name,
            'observedAt': accounting.now(), 'monotonicNs': str(time.monotonic_ns()),
            'clockDomainId': accounting.clock_domain(), 'evidenceMode': 'synthetic'}
        (root/'lifecycle').mkdir(mode=0o700, exist_ok=True)
        _safe_path(root/'lifecycle')
        public.save_once(root/'lifecycle'/(name+'.json'), fact)
        if delay:
            time.sleep(delay)
        accounting.record_workload('mock_tts.lifecycle', {'lifecycleReceiptSha256': c.canonical_sha256(fact),
            'simulatedWaitSeconds': delay, 'providerQueueObserved': False, 'resourceQueueObserved': False})
        attempt.finish('completed', artifact_sha256=c.canonical_sha256(fact))
    handle = completion.capture_synthetic(attempt.span_id, production_run_id=request['runId'],
        artifact_sha256=c.canonical_sha256(fact), artifact_kind='control_receipt',
        job_id=request['jobId'], revision_id=request['revisionId'])
    return fact, handle


def execute(request_path, request_sha256):
    require_environment()
    request_path = _safe_path(request_path)
    request = contract.read_request(request_path)
    c.require(contract.sha(request_sha256) and c.canonical_sha256(request) == request_sha256,
        'mock_tts_frozen_request_changed')
    scope = contract.scope_for_request(request_path, request)
    contract.require_intent(scope, request)
    root = request_path.parent.parent/'worker'
    root.mkdir(mode=0o700, exist_ok=True); _safe_path(root)
    terminal_path = root/'receipt.json'
    if terminal_path.exists():
        # A physical job identity is single-use, including failed jobs. Direct
        # duplicate entry never recreates artifacts or logs a second attempt.
        previous = contract.validate_receipt(public.read_snapshot(terminal_path)[0], request)
        return 0 if previous['status'] == 'artifact_returned' else 2
    directory = _safe_path(Path(os.environ['SERMON_ACCOUNTING_DIR']))
    c.require(scope.parent in directory.parents or scope.parent == directory,
        'mock_tts_accounting_outside_scope')
    active = profile.current()
    c.require(active.get('jobId') == request['jobId'] and active.get('productionRunId') == request['runId'],
        'mock_tts_job_context_changed')
    # The existing jobs context has detached dispatch causality, not false
    # synchronous parent containment. This session adopts its original runId.
    with accounting.accounting_session(directory, 'mock_tts_worker', evidence_directory=scope), \
            profile.context(jobId=request['jobId'], revisionId=request['revisionId']):
        _, events = completion.current_events()
        completion.validate_synthetic(request['parentCompletion'], events,
            production_run_id=request['runId'], artifact_sha256=request['inputSha256'])
        received, received_handle = _phase(root, request, 'received', request['parentCompletion'])
        queued, queued_handle = _phase(root, request, 'queued', received_handle,
            delay=request['fault']['queueDelaySeconds'])
        with accounting.stage_outcome('mock_tts.worker', work_unit_id=request['unitId'],
                attempt_id=request['attemptId'], depends_on=[queued_handle['spanId']],
                executor_type='deterministic_program') as attempt:
            started_at, started_ns = accounting.now(), time.monotonic_ns()
            time.sleep(request['fault']['runDelaySeconds'])
            fault = request['fault']['mode']
            failed = fault in {'fail_before_render', 'fail_after_render'}
            artifact = None
            if fault != 'fail_before_render':
                raw = contract.fixture_wav(request)
                if fault == 'invalid_wav': raw = b'invalid synthetic WAV'
                artifact = contract.artifact_reference(request, raw)
                output = root/'fixture.wav'
                if fault != 'missing_artifact':
                    # Exclusive creation; never overwrite an interrupted output.
                    with output.open('xb') as stream:
                        stream.write(raw if fault != 'hash_mismatch' else raw[:-2]+b'XX')
                        stream.flush(); os.fsync(stream.fileno())
                    jobs._sync_directory(root)
            completed_at, completed_ns = accounting.now(), time.monotonic_ns()
            receipt = {'schemaVersion': contract.RECEIPT, 'evidenceMode': 'synthetic',
                'controlBatchSemantics': contract.BATCH, 'requestSha256': c.canonical_sha256(request),
                'binding': {key: request[key] for key in contract.BINDING},
                'status': 'worker_failed' if failed else 'artifact_returned',
                'reasonCode': fault if failed else 'fixture_artifact_returned', 'artifact': artifact,
                'timing': {'receivedAt': received['observedAt'], 'queuedAt': queued['observedAt'],
                    'startedAt': started_at, 'completedAt': completed_at,
                    'clockDomainId': accounting.clock_domain(),
                    'receivedMonotonicNs': received['monotonicNs'], 'startedMonotonicNs': str(started_ns),
                    'completedMonotonicNs': str(completed_ns),
                    'simulatedQueueDelaySeconds': request['fault']['queueDelaySeconds'],
                    'simulatedRunDelaySeconds': request['fault']['runDelaySeconds']},
                'environmentPolicy': 'scrubbed_mock_worker_v1', 'productionEligible': False,
                'humanAcceptance': 'pending', 'modelCalls': 0, 'providerTokens': None, 'providerCost': None,
                'missingReasons': {'providerTokens': 'not_applicable', 'providerCost': 'not_applicable'}}
            contract.validate_receipt(receipt, request)
            public.save_once(terminal_path, receipt)
            accounting.record_workload('mock_tts.artifact_return', {'receiptSha256': c.canonical_sha256(receipt),
                'artifactSha256': artifact['sha256'] if artifact else None,
                'syntheticCompute': True, 'modelCalls': 0, 'providerQueueObserved': False})
            attempt.finish('failed' if failed else 'completed',
                **({'artifact_sha256': artifact['sha256']} if not failed else {}))
        if failed:
            return 2
        worker_handle = completion.capture_synthetic(attempt.span_id, production_run_id=request['runId'],
            artifact_sha256=artifact['sha256'], artifact_kind='mock_wav',
            job_id=request['jobId'], revision_id=request['revisionId'])
        public.save_once(root/'completion.json', {'schemaVersion': contract.COMPLETION,
            'requestSha256': c.canonical_sha256(request), 'receiptSha256': c.canonical_sha256(receipt),
            'handles': {'received': received_handle, 'queued': queued_handle, 'worker': worker_handle},
            'evidenceMode': 'synthetic', 'productionEligible': False})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('submit', 'execute'))
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--request-sha256', required=True)
    args = parser.parse_args(argv)
    if args.action == 'submit':
        print(json.dumps(submit(args.request, args.request_sha256), sort_keys=True)); return 0
    return execute(args.request, args.request_sha256)


if __name__ == '__main__':
    raise SystemExit(main())

"""Strict synthetic WAV job contract; grants no model or publication authority.

This is a local, opt-in adapter for the existing durable job primitive. It is
not a Hub/Spark wire contract and does not register a speech task remotely.
"""
from copy import deepcopy
import io
import math
from pathlib import Path
import re
import struct
import wave

from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts.sermon_release_workflow import _safe_path

REQUEST = 'sermon-mock-tts-request-v1'
RECEIPT = 'sermon-mock-tts-worker-receipt-v1'
COMPLETION = 'sermon-mock-tts-completion-v1'
BATCH = 'independent_unit_jobs_v1'
FAULTS = frozenset(('none', 'fail_before_render', 'fail_after_render', 'missing_artifact',
                   'invalid_wav', 'hash_mismatch'))
LOCALES = frozenset(('zh-Hans', 'ko', 'es'))
SHA = re.compile(r'^[a-f0-9]{64}$')
LABEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$')
REQUEST_KEYS = {'schemaVersion', 'evidenceMode', 'controlBatchSemantics', 'runId', 'planSha256',
    'unitId', 'targetLocale', 'inputSha256', 'revisionId', 'attemptId', 'idempotencyKey',
    'jobId', 'implementationSha256', 'parentCompletion', 'waveform', 'fault',
    'workerTimeoutSeconds', 'attemptNumber', 'retryOfRequestSha256', 'productionEligible', 'humanAcceptance'}
BINDING = ('runId', 'planSha256', 'unitId', 'targetLocale', 'inputSha256', 'revisionId',
           'attemptId', 'attemptNumber', 'retryOfRequestSha256', 'idempotencyKey', 'jobId', 'implementationSha256')


def sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def label(value):
    return type(value) is str and LABEL.fullmatch(value) is not None


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def job_identity(request):
    # The key owns one physical execution. Changed request bytes cannot silently
    # select a new job: the client's immutable request and jobs argv guard it.
    return {'schemaVersion': REQUEST, 'runId': request['runId'],
        'idempotencyKey': request['idempotencyKey'], 'mode': 'synthetic_only'}


def job_id(request):
    return c.canonical_sha256(job_identity(request))


def validate_request(request):
    c.require(type(request) is dict and set(request) == REQUEST_KEYS
        and request['schemaVersion'] == REQUEST and request['evidenceMode'] == 'synthetic'
        and request['controlBatchSemantics'] == BATCH
        and request['productionEligible'] is False and request['humanAcceptance'] == 'pending',
        'mock_tts_request_invalid')
    for key in ('runId', 'planSha256', 'inputSha256', 'revisionId', 'idempotencyKey',
                'jobId', 'implementationSha256'):
        c.require(sha(request[key]), 'mock_tts_request_identity_invalid')
    c.require(label(request['unitId']) and len(request['unitId']) <= 80
        and label(request['attemptId']) and len(request['attemptId']) <= 70
        and request['targetLocale'] in LOCALES and request['jobId'] == job_id(request),
        'mock_tts_request_identity_invalid')
    from scripts import sermon_completion as completion
    c.require(type(request['attemptNumber']) is int and 1 <= request['attemptNumber'] <= 3
        and ((request['attemptNumber'] == 1 and request['retryOfRequestSha256'] is None)
             or (request['attemptNumber'] > 1 and sha(request['retryOfRequestSha256']))),
        'mock_tts_attempt_invalid')
    parent = request['parentCompletion']
    completion.validate_synthetic_shape(parent)
    c.require(type(parent) is dict and parent.get('schemaVersion') == 'sermon-execution-completion-v2'
        and parent.get('evidenceMode') == 'synthetic' and parent.get('artifactKind') == 'control_receipt'
        and parent.get('productionRunId') == request['runId']
        and parent.get('artifactSha256') == request['inputSha256']
        and parent.get('stage') == 'mock_tts.input_verified'
        and parent.get('jobId') == request['jobId'] and parent.get('revisionId') == request['revisionId'],
        'mock_tts_parent_required')
    settings = request['waveform']
    c.require(type(settings) is dict and set(settings) == {'sampleRate', 'frames', 'seed'}
        and settings['sampleRate'] == 16000 and type(settings['frames']) is int
        and 160 <= settings['frames'] <= 160000 and type(settings['seed']) is int
        and 1 <= settings['seed'] <= 31, 'mock_tts_waveform_invalid')
    fault = request['fault']
    c.require(type(fault) is dict and set(fault) == {'mode', 'queueDelaySeconds', 'runDelaySeconds'}
        and fault['mode'] in FAULTS
        and number(fault['queueDelaySeconds'], 0, 10) and number(fault['runDelaySeconds'], 0, 10)
        and number(request['workerTimeoutSeconds'], 1, 60)
        and fault['queueDelaySeconds'] + fault['runDelaySeconds'] < request['workerTimeoutSeconds'],
        'mock_tts_fault_invalid')
    c.require(c._strict_json(request) and len(c.canonical_bytes(request)) <= c.MAX_BYTES,
        'mock_tts_request_invalid')
    return deepcopy(request)


def fixture_wav(request):
    """Deterministic inert waveform, not synthesized speech or model inference."""
    validate_request(request)
    settings = request['waveform']
    samples = b''.join(struct.pack('<h', (((index * settings['seed']) % 64) - 32) * 128)
        for index in range(settings['frames']))
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(settings['sampleRate'])
        audio.writeframes(samples)
    return output.getvalue()


def artifact_reference(request, raw):
    settings = request['waveform']
    return {'name': 'fixture.wav', 'sha256': c.bytes_sha256(raw), 'sizeBytes': len(raw),
        'sampleRate': settings['sampleRate'], 'frames': settings['frames'], 'channels': 1,
        'sampleWidthBytes': 2, 'durationSeconds': settings['frames'] / settings['sampleRate']}


def read_request(path):
    path = _safe_path(Path(path))
    c.require(path.name == 'request.json' and path.parent.name == 'mock-tts-request',
        'mock_tts_request_path_invalid')
    return validate_request(public.read_snapshot(path)[0])


def validate_receipt(receipt, request):
    request = validate_request(request)
    keys = {'schemaVersion', 'evidenceMode', 'controlBatchSemantics', 'requestSha256', 'binding',
        'status', 'reasonCode', 'artifact', 'timing', 'environmentPolicy', 'productionEligible',
        'humanAcceptance', 'modelCalls', 'providerTokens', 'providerCost', 'missingReasons'}
    c.require(type(receipt) is dict and set(receipt) == keys and receipt['schemaVersion'] == RECEIPT
        and receipt['evidenceMode'] == 'synthetic' and receipt['controlBatchSemantics'] == BATCH
        and receipt['requestSha256'] == c.canonical_sha256(request)
        and receipt['binding'] == {key: request[key] for key in BINDING}
        and receipt['productionEligible'] is False and receipt['humanAcceptance'] == 'pending'
        and receipt['modelCalls'] == 0 and receipt['providerTokens'] is None and receipt['providerCost'] is None
        and receipt['missingReasons'] == {'providerTokens': 'not_applicable', 'providerCost': 'not_applicable'}
        and receipt['environmentPolicy'] == 'scrubbed_mock_worker_v1'
        and receipt['status'] in {'artifact_returned', 'worker_failed'}, 'mock_tts_receipt_invalid')
    c.require(receipt['reasonCode'] == ('fixture_artifact_returned' if receipt['status'] == 'artifact_returned'
        else request['fault']['mode']) and (receipt['status'] != 'worker_failed'
            or request['fault']['mode'] in {'fail_before_render', 'fail_after_render'}),
        'mock_tts_receipt_status_invalid')
    timing = receipt['timing']
    c.require(type(timing) is dict and set(timing) == {'receivedAt', 'queuedAt', 'startedAt', 'completedAt',
        'clockDomainId', 'receivedMonotonicNs', 'startedMonotonicNs', 'completedMonotonicNs',
        'simulatedQueueDelaySeconds', 'simulatedRunDelaySeconds'}
        and label(timing['clockDomainId'])
        and all(type(timing[k]) is str and 1 <= len(timing[k]) <= 24 and timing[k].isdigit() for k in
            ('receivedMonotonicNs', 'startedMonotonicNs', 'completedMonotonicNs'))
        and int(timing['receivedMonotonicNs']) <= int(timing['startedMonotonicNs']) <= int(timing['completedMonotonicNs'])
        and timing['simulatedQueueDelaySeconds'] == request['fault']['queueDelaySeconds']
        and timing['simulatedRunDelaySeconds'] == request['fault']['runDelaySeconds'],
        'mock_tts_timing_invalid')
    from datetime import datetime
    try:
        times = [datetime.fromisoformat(timing[key]) for key in ('receivedAt', 'queuedAt', 'startedAt', 'completedAt')]
        valid = all(value.tzinfo is not None for value in times) and times == sorted(times)
    except (TypeError, ValueError):
        valid = False
    c.require(valid, 'mock_tts_timing_invalid')
    artifact = receipt['artifact']
    if artifact is None:
        c.require(receipt['status'] == 'worker_failed' and request['fault']['mode'] == 'fail_before_render',
            'mock_tts_artifact_required')
    else:
        expected = artifact_reference(request, fixture_wav(request))
        c.require(type(artifact) is dict and set(artifact) == set(expected)
            and all(artifact[key] == expected[key] for key in expected if key not in {'sha256', 'sizeBytes'})
            and sha(artifact['sha256']) and type(artifact['sizeBytes']) is int
            and 0 < artifact['sizeBytes'] <= 320044, 'mock_tts_artifact_reference_invalid')
    return deepcopy(receipt)


def verify_wav(path, request, artifact):
    path = _safe_path(Path(path))
    c.require(path.name == 'fixture.wav' and path.is_file() and path.stat().st_size <= 320044,
        'mock_tts_artifact_missing')
    raw = path.read_bytes()
    c.require(len(raw) == artifact['sizeBytes'] and c.bytes_sha256(raw) == artifact['sha256'],
        'mock_tts_artifact_hash_mismatch')
    try:
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            valid = (audio.getnchannels() == 1 and audio.getsampwidth() == 2
                and audio.getframerate() == artifact['sampleRate'] and audio.getnframes() == artifact['frames']
                and audio.getcomptype() == 'NONE'
                and len(audio.readframes(audio.getnframes() + 1)) == artifact['frames'] * 2)
    except (wave.Error, EOFError, ValueError):
        valid = False
    c.require(valid, 'mock_tts_wav_invalid')
    c.require(raw == fixture_wav(request), 'mock_tts_fixture_bytes_changed')
    return deepcopy(artifact)


# This isolated acceptance contract has only two-unit end-to-end evidence.
# Larger plans require a separately measured contract revision, not an implied
# throughput guarantee from a broad JSON shape limit.
MAX_TESTED_UNITS = 2


def validate_policy(value):
    c.require(type(value) is dict and set(value) == {'schemaVersion', 'units', 'maxJobs',
        'maxAttemptsPerUnit', 'maxConcurrentJobs', 'workerTimeoutSeconds', 'observationTimeoutSeconds'}
        and value['schemaVersion'] == 'sermon-mock-tts-control-policy-v1' and type(value['units']) is dict and 1 <= len(value['units']) <= MAX_TESTED_UNITS
        and all(label(unit) and len(unit) <= 80 and locale in LOCALES for unit, locale in value['units'].items())
        and type(value['maxAttemptsPerUnit']) is int and 1 <= value['maxAttemptsPerUnit'] <= 3
        and type(value['maxJobs']) is int and len(value['units']) <= value['maxJobs'] <= MAX_TESTED_UNITS * 3
        and type(value['maxConcurrentJobs']) is int and 1 <= value['maxConcurrentJobs'] <= 4
        and number(value['workerTimeoutSeconds'], 1, 60)
        and number(value['observationTimeoutSeconds'], .01, value['workerTimeoutSeconds']),
        'mock_tts_control_policy_invalid')
    return deepcopy(value)



def intent_for_request(request):
    return {'schemaVersion': 'sermon-mock-tts-intent-v1', 'requestSha256': c.canonical_sha256(request),
        'jobId': request['jobId'], 'idempotencyKey': request['idempotencyKey'],
        'unitId': request['unitId'], 'attemptNumber': request['attemptNumber'],
        'revisionId': request['revisionId'], 'inputSha256': request['inputSha256'],
        'evidenceMode': 'synthetic', 'productionEligible': False}


def require_intent(root, request):
    intent = public.read_snapshot(root/'intents'/(request['idempotencyKey']+'.json'))[0]
    c.require(intent == intent_for_request(request), 'mock_tts_frozen_intent_changed')


def implementation_sha256():
    root = Path(__file__).resolve().parents[1]
    names = ('sermon_mock_tts_contract.py', 'sermon_mock_tts_worker.py', 'sermon_accounting.py',
        'sermon_log_profile.py', 'sermon_log_contract.py', 'sermon_log_outbox.py',
        'sermon_completion.py', 'sermon_mock_tts_control.py', 'sermon_durable_accounting.py',
        'sermon_workflow_jobs.py', 'sermon_execution_harness.py',
        'sermon_guarded_command.py', 'sermon_review_contracts.py', 'sermon_public_snapshot.py',
        'sermon_release_workflow.py', 'sermon_job_liveness.py', 'sermon_clock_evidence.py',
        'sermon_workflow_evidence.py', 'sermon_review_observation.py')
    return c.canonical_sha256({name: c.bytes_sha256((root/'scripts'/name).read_bytes()) for name in names})


def validate_input_binding(value, unit):
    keys = {'schemaVersion', 'unitId', 'targetLocale', 'sourceCanonicalSha256',
        'anchorCanonicalSha256', 'policySha256', 'groupPlanSha256', 'rubricSha256',
        'pluginSha256', 'reviewedGroupSha256', 'sourceUnitIds', 'utteranceSha256'}
    c.require(type(value) is dict and set(value) == keys
        and value['schemaVersion'] == 'sermon-mock-tts-unit-input-v1'
        and value['unitId'] == unit['unitId'] and value['targetLocale'] == unit['targetLocale']
        and all(sha(value[key]) for key in ('sourceCanonicalSha256', 'anchorCanonicalSha256',
            'policySha256', 'groupPlanSha256', 'rubricSha256', 'pluginSha256',
            'reviewedGroupSha256', 'utteranceSha256'))
        and type(value['sourceUnitIds']) is list and 1 <= len(value['sourceUnitIds']) <= 64
        and all(label(item) for item in value['sourceUnitIds'])
        and len(set(value['sourceUnitIds'])) == len(value['sourceUnitIds'])
        and c.canonical_sha256(value) == unit['inputSha256'], 'mock_tts_unit_input_changed')
    return deepcopy(value)


def scope_for_request(path, request):
    path = _safe_path(Path(path))
    c.require(path.parent.parent.name == request['idempotencyKey']
        and path.parent.parent.parent.name == 'requests', 'mock_tts_request_path_invalid')
    validate_input_binding(public.read_snapshot(path.parent.parent/'unit-input.json')[0], request)
    root = path.parents[3]
    scope = public.read_snapshot(root/'scope.json')[0]
    policy = validate_policy(public.read_snapshot(root/'policy.json')[0])
    c.require(policy['units'].get(request['unitId']) == request['targetLocale']
        and request['attemptNumber'] <= policy['maxAttemptsPerUnit']
        and request['workerTimeoutSeconds'] == policy['workerTimeoutSeconds'], 'mock_tts_request_not_authorized')
    c.require(type(scope) is dict and set(scope) == {'schemaVersion', 'runId', 'planSha256',
        'implementationSha256', 'policySha256', 'evidenceMode', 'productionEligible'}
        and scope == {'schemaVersion': 'sermon-mock-tts-scope-v1', 'runId': request['runId'],
            'planSha256': request['planSha256'], 'implementationSha256': request['implementationSha256'],
            'policySha256': c.canonical_sha256(policy),
            'evidenceMode': 'synthetic', 'productionEligible': False}, 'mock_tts_scope_changed')
    c.require(request['implementationSha256'] == implementation_sha256(), 'mock_tts_code_changed')
    return root

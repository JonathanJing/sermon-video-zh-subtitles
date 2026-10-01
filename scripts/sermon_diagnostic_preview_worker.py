"""Fixed local preview worker; diagnostic context never grants production approval.

A caller supplies the original DiagnosticProvider. No provider store, clock,
quota or credential is initialized here. Only the explicit ``execute`` spec may
load an existing local model; offline_fixture uses a fixed PCM test synthesizer.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import render_speculative_target_language_speech as preview
from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_execution_harness as harness
from scripts import sermon_log_profile as profile
from scripts import sermon_public_snapshot as public
from scripts import sermon_native_preview_runtime as native_runtime
from scripts import sermon_clock_evidence as clock
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-diagnostic-preview-worker-receipt-v2'
PATH_KEYS = ('source', 'anchor', 'candidate', 'policy', 'adapter', 'registry')
REQUIRED = {'paths', 'checkpoint_map_path', 'operation_policies_path', 'strict_rubric_path', 'out', 'execute'}
OPTIONS = {'group_ids', 'seed', 'device', 'dtype', 'attention', 'instruct'}


def _path(value):
    path = Path(value)
    c.require(path.is_absolute(), 'preview_absolute_path_required')
    return _safe_path(path)


def _inside(root, value):
    path = _path(value)
    c.require(path.is_relative_to(root), 'preview_output_outside_run')
    return path


def _tree(root, value):
    path = _inside(root, value)
    if path.exists():
        for child in path.rglob('*'):
            _inside(root, child)
    return path


def _read(path):
    return public.read_snapshot(_path(path))[0]


def _ref(path):
    path = _path(path)
    c.require(path.is_file(), 'preview_artifact_missing')
    return {'path': str(path), 'fileBytesSha256': preview.identity.sha256(path)}


def _check_refs(refs):
    c.require(type(refs) is list and refs, 'preview_artifact_inventory_missing')
    for row in refs:
        c.require(type(row) is dict and set(row) == {'path', 'fileBytesSha256'}
                  and _ref(row['path']) == row, 'preview_artifact_changed')


def _embedded(value):
    refs = []
    if isinstance(value, list):
        for item in value:
            refs += _embedded(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == 'path' and isinstance(item, str):
                path = _path(item)
                if 'sha256' in value:
                    c.require(_ref(path)['fileBytesSha256'] == value['sha256'],
                              'preview_embedded_artifact_changed')
                if 'jsonSha256' in value:
                    c.require(c.canonical_sha256(_read(path)) == value['jsonSha256'],
                              'preview_embedded_artifact_changed')
                if path.is_file():
                    refs.append(path)
            else:
                refs += _embedded(item)
    return refs


def _spec(root, spec, context, offline, *, require_runtime_process=False, legacy_receipt=False):
    c.require(type(spec) is dict and REQUIRED <= set(spec)
              and set(spec) <= REQUIRED | OPTIONS | {'fixture_behavior', 'runtime_manifest_path'}, 'invalid_preview_spec')
    c.require(type(spec['execute']) is bool and (offline or spec['execute']), 'preview_execute_required')
    c.require(type(spec['paths']) is dict and set(spec['paths']) == set(PATH_KEYS), 'invalid_preview_paths')
    c.require(offline or 'fixture_behavior' not in spec, 'preview_fixture_behavior_forbidden')
    c.require(offline or legacy_receipt or 'runtime_manifest_path' in spec, 'preview_native_runtime_manifest_required')
    c.require(not offline or 'runtime_manifest_path' not in spec, 'preview_fixture_cannot_claim_native_runtime')
    c.require(spec.get('fixture_behavior', 'pcm') in {'pcm', 'hang', 'fail_after_render'}, 'invalid_preview_fixture')
    normalized = dict(spec, paths={key: str(_path(value)) for key, value in spec['paths'].items()})
    for key in ('checkpoint_map_path', 'operation_policies_path', 'strict_rubric_path'):
        normalized[key] = str(_path(spec[key]))
    out = _tree(root, spec['out'])
    c.require(out != root and not root.is_relative_to(out), 'preview_output_overlaps_run')
    normalized['out'] = str(out)
    runtime_binding = None
    if not offline and not legacy_receipt:
        normalized['runtime_manifest_path'] = str(_path(spec['runtime_manifest_path']))
        runtime_binding = native_runtime.validate(normalized['runtime_manifest_path'], require_process=require_runtime_process)
        runtime_root = _path(runtime_binding['runtimeRoot'])
        c.require(not out.is_relative_to(runtime_root) and not runtime_root.is_relative_to(out), 'preview_output_overlaps_runtime')
    inputs = [*map(Path, normalized['paths'].values()),
              *(Path(normalized[key]) for key in ('checkpoint_map_path', 'operation_policies_path', 'strict_rubric_path'))]
    for path in tuple(inputs):
        inputs += _embedded(_read(path))
    c.require(not any(path == out or path.is_relative_to(out) for path in inputs), 'preview_output_overlaps_input')
    paths = {key: Path(value) for key, value in normalized['paths'].items()}
    rubric = _read(normalized['strict_rubric_path'])
    checked = preview.checked_context(paths, Path(normalized['checkpoint_map_path']),
        Path(normalized['operation_policies_path']), strict_rubric=rubric, diagnostic_context=context)
    checkpoint = _path(checked['checkpoint'])
    c.require(not checkpoint.is_relative_to(out) and not out.is_relative_to(checkpoint), 'preview_output_overlaps_checkpoint')
    inputs += [checkpoint / 'model.safetensors', checkpoint / 'config.json']
    if runtime_binding is not None:
        inputs += [Path(runtime_binding[k]['path']) for k in ('runtimeManifest', 'runtimeInventory', 'runtimeCode')]
    checked['native_runtime_binding'] = runtime_binding
    groups = [row['translationGroupId'] for row in checked['candidate']['groups']]
    selected = normalized.get('group_ids')
    c.require(selected is None or (type(selected) is list and selected and len(selected) == len(set(selected))
              and set(selected) <= set(groups)), 'invalid_preview_group_selection')
    return normalized, checked, [_ref(path) for path in sorted(set(inputs))]


def _runtime(root, subject, context):
    c.require(type(subject) is provider.DiagnosticProvider, 'preview_trusted_provider_required')
    diagnostic.validate_runtime(context, run_id=subject.config['runId'], store_sha256=subject.store.store_sha256)
    c.require(context['runConfigSha256'] == c.canonical_sha256(subject.config), 'preview_config_changed')
    c.require(_path(subject.store.root) == root / 'budget', 'preview_store_outside_original_run')
    state_path = root / 'budget' / budget.STORE_ID / 'provider-run/state.json'
    ledger_path = root / 'budget' / budget.STORE_ID / 'state.json'
    c.require(_path(state_path).is_file() and _path(ledger_path).is_file(), 'preview_existing_provider_required')
    with subject._locked() as (_, state):
        subject._remaining(state)
        c.require(all(row['state'] in {'returned', 'rejected'} for row in state['requests'].values()),
                  'preview_provider_outcome_requires_reconciliation')
        state = _read(state_path)
        ledger = _read(ledger_path)
    return state, ledger, state['startedMonotonic'] + subject.config['totalWallSeconds']


def _same_history(original, current):
    c.require(all(original[key] == current[key] for key in
              ('schemaVersion', 'config', 'authoritySha256', 'clockDomain', 'startedMonotonic'))
              and all(current['requests'].get(key) == value for key, value in original['requests'].items()),
              'preview_original_provider_history_changed')


def _environment(root, out, offline):
    context = profile.current()
    c.require(context is not None and context['evidenceMode'] == ('synthetic' if offline else 'current_execution'),
              'preview_accounting_profile_required')
    raw = accounting.subprocess_environment()
    # Never copy ambient credentials, proxies, cloud settings, or arbitrary env.
    env = {key: raw[key] for key in (*accounting.ENV_KEYS, accounting.WORKFLOW_ENV,
             profile.PROFILE_ENV, profile.CONTEXT_ENV) if key in raw}
    c.require(env.get('SERMON_ACCOUNTING_DIR') and env.get('SERMON_ACCOUNTING_RUN_ID'),
              'preview_accounting_session_required')
    _tree(root, env['SERMON_ACCOUNTING_DIR'])
    env.update(PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
        PYTHONDONTWRITEBYTECODE='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
        HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
        HF_HOME=str(out / 'local-model-cache'), TMPDIR=str(out / 'tmp'))
    return env


def _manifest(checked):
    candidate = checked['candidate']
    return dict(schemaVersion=preview.SCOPED_MANIFEST_VERSION, status='preview_only',
        synthesisEligible=False, releaseEligible=False, targetLocale=candidate['targetLocale'],
        candidateJsonSha256=c.canonical_sha256(candidate), sourceJsonSha256=c.canonical_sha256(checked['source']),
        anchorJsonSha256=c.canonical_sha256(checked['anchor']), translationPolicySha256=candidate['translationPolicySha256'],
        previewRendererSha256=preview.identity.sha256(Path(preview.__file__)),
        strictRubricSha256=c.canonical_sha256(checked['strict_rubric']),
        diagnosticContextSha256=c.canonical_sha256(checked['diagnostic_context']),
        humanAcceptance='pending', productionEligible=False)


def _outputs(root, spec, checked):
    out = _tree(root, spec['out'])
    manifest = out / 'manifest.json'
    c.require(_read(manifest) == _manifest(checked), 'preview_manifest_changed')
    snapshots = []
    for name in (*PATH_KEYS, 'strict_rubric', 'diagnostic_context'):
        path = out / (name + '.json')
        c.require(_read(path) == checked[name], 'preview_input_snapshot_changed')
        snapshots.append(_ref(path))
    units, audio = [], []
    selected = spec.get('group_ids')
    for index, group in enumerate(checked['candidate']['groups']):
        if selected is not None and group['translationGroupId'] not in selected:
            continue
        path = out / f'receipts/unit-{index:04d}.json'
        wav = out / f'units/unit-{index:04d}.wav'
        unit = _read(path)
        expected = preview.sound_identity(checked, index, seed=spec.get('seed', 42),
            dtype=spec.get('dtype', 'bfloat16'), attention=spec.get('attention', 'sdpa'), instruct=spec.get('instruct'))
        measured = preview.integrity.probe_full_decode(wav)
        c.require(unit.get('schemaVersion') == preview.UNIT_VERSION and unit.get('status') == 'preview_only'
            and unit.get('candidateJsonSha256') == c.canonical_sha256(checked['candidate'])
            and unit.get('previewContextSha256') == c.canonical_sha256(_manifest(checked))
            and unit.get('soundIdentity') == expected and unit.get('audioSha256') == _ref(wav)['fileBytesSha256']
            and unit.get('durationSeconds') == measured['durationSeconds'] and unit.get('fullDecode') == 'pass',
            'preview_unit_receipt_changed')
        units.append(_ref(path)); audio.append(_ref(wav))
    return _ref(manifest), units, audio, snapshots


def validate_preview_receipt(root, subject, context, receipt):
    """Read-only completed-preview validation; never dispatch, approve or renew time."""
    root = _path(root)
    c.require(type(subject) is provider.DiagnosticProvider
        and _path(subject.store.root) == root / 'budget', 'preview_trusted_provider_required')
    saved_path = _inside(root, receipt['receiptPath'])
    c.require(_ref(saved_path)['fileBytesSha256'] == receipt['receiptFileSha256'], 'preview_worker_receipt_changed')
    saved = {key: value for key, value in receipt.items() if key not in {'receiptPath', 'receiptFileSha256'}}
    version = saved.get('schemaVersion')
    c.require(_read(saved_path) == saved and version in {SCHEMA, 'sermon-diagnostic-preview-worker-receipt-v1'}
        and saved.get('status') == 'preview_only' and saved.get('humanAcceptance') == 'pending'
        and saved.get('productionEligible') is False, 'preview_worker_receipt_changed')
    c.require(saved['runId'] == subject.config['runId'] and saved['storeSha256'] == subject.store.store_sha256
        and saved['runConfigSha256'] == c.canonical_sha256(subject.config)
        and saved['diagnosticContextSha256'] == c.canonical_sha256(diagnostic.validate_context(context)),
        'preview_worker_context_changed')
    legacy = version == 'sermon-diagnostic-preview-worker-receipt-v1'
    spec, checked, inputs = _spec(root, saved['spec'], context, saved['offlineFixture'], legacy_receipt=legacy)
    c.require(inputs == saved['inputs'] and c.canonical_sha256(spec) == saved['specSha256'], 'preview_inputs_changed')
    if not legacy:
        c.require(saved['nativeRuntimeBinding'] == checked['native_runtime_binding'], 'preview_native_runtime_binding_changed')
    out = Path(spec['out'])
    c.require(saved_path == out / 'worker-receipt.json', 'preview_worker_receipt_location_changed')
    for row in saved['artifacts']:
        _inside(root, row['path'])
    _check_refs(saved['artifacts'])
    for field, name in (('providerStateSnapshot', 'provider-state.snapshot.json'),
                        ('budgetStateSnapshot', 'budget-state.snapshot.json')):
        c.require(saved[field] == _ref(_inside(root, out / name)) and saved[field] in saved['artifacts'],
                  'preview_worker_snapshot_changed')
    request = _read(out / 'worker-request.json')
    request_sha = c.canonical_sha256(request)
    c.require(saved['workerAttemptId'] == saved['requestSha256'] == request_sha
        and _read(out / 'worker-attempt.json') == {'workerAttemptId': request_sha,
            'requestSha256': request_sha, 'status': 'reserved'}
        and request['root'] == str(root) and request['spec'] == spec
        and request['context'] == context and request['inputs'] == inputs
        and request['deadlineMonotonic'] == saved['deadlineMonotonic']
        and request['offlineFixture'] == saved['offlineFixture']
        and request.get('schemaVersion') == ('sermon-diagnostic-preview-worker-request-v1' if legacy else 'sermon-diagnostic-preview-worker-request-v2')
        and (legacy or request['nativeRuntimeBinding'] == saved['nativeRuntimeBinding'])
        and request['workerCodeSha256'] == preview.identity.sha256(Path(__file__)),
        'preview_worker_attempt_changed')
    child_result = _read(out / 'worker-result.json')
    c.require(child_result['requestSha256'] == request_sha
        and child_result['result']['status'] == 'preview_only'
        and child_result['result']['out'] == str(out)
        and child_result['result']['targetLocale'] == checked['candidate']['targetLocale'],
        'preview_worker_result_changed')
    if not legacy:
        proof = saved['clockHandshake']
        c.require(proof['launch'] == request['clockLaunch'] and proof['finished'] == child_result['clockFinished']
            and clock.validate_worker_handshake(proof['launch'], proof['finished'], proof['joined']) == proof['joined'],
            'preview_worker_clock_handshake_changed')
    original = _read(saved['providerStateSnapshot']['path'])
    c.require(c.canonical_sha256(original) == request['providerStateCanonicalSha256']
        and c.canonical_sha256(_read(saved['budgetStateSnapshot']['path'])) == request['budgetStateCanonicalSha256']
        and original['config'] == subject.config
        and original['authoritySha256'] == subject.store.authority_sha256
        and original['clockDomain'] == subject.domain(),
        'preview_worker_snapshot_changed')
    c.require(_ref(saved['providerStateSnapshot']['path']) == saved['providerStateSnapshot']
        and _ref(saved['budgetStateSnapshot']['path']) == saved['budgetStateSnapshot']
        and saved['providerStateFileSha256'] == saved['providerStateSnapshot']['fileBytesSha256']
        and saved['budgetStateFileSha256'] == saved['budgetStateSnapshot']['fileBytesSha256']
        and saved['deadlineMonotonic'] == original['startedMonotonic'] + subject.config['totalWallSeconds'],
        'preview_original_deadline_changed')
    current = _read(root / 'budget' / budget.STORE_ID / 'provider-run/state.json')
    _same_history(original, current)
    c.require(all(row['state'] in {'returned', 'rejected'} for row in current['requests'].values()),
              'preview_provider_outcome_requires_reconciliation')
    manifest, units, audio, _ = _outputs(root, spec, checked)
    c.require(manifest == saved['manifest'] and units == saved['unitReceipts'] and audio == saved['audio'],
              'preview_outputs_changed')
    return receipt


def launch_preview(root, subject, context, spec, *, offline_fixture=False, depends_on=None):
    root = _path(root)
    c.require(type(offline_fixture) is bool, 'preview_explicit_fixture_mode_required')
    context = diagnostic.validate_context(context)
    state, ledger, deadline = _runtime(root, subject, context)
    c.require(depends_on is None or (type(depends_on) is list and len(depends_on) <= 256
        and len(set(depends_on)) == len(depends_on)
        and all(type(value) is str and accounting._label(value, None) == value for value in depends_on)),
        'preview_invalid_predecessor_spans')
    spec, checked, inputs = _spec(root, spec, context, offline_fixture, require_runtime_process=not offline_fixture)
    out = Path(spec['out'])
    c.require(offline_fixture or (profile.current() or {}).get('productionRunId') == subject.config['runId'],
              'preview_accounting_run_changed')
    env = _environment(root, out, offline_fixture)
    lock_key = c.canonical_sha256(str(out))
    with jobs._lock(root / 'diagnostic-preview-workers', lock_key) as (_, _, held):
        c.require(held, 'preview_worker_busy')
        receipt_path = out / 'worker-receipt.json'
        if receipt_path.exists():
            saved = _read(receipt_path)
            c.require(saved['spec'] == spec and saved['offlineFixture'] == offline_fixture, 'preview_worker_request_changed')
            return validate_preview_receipt(root, subject, context, dict(saved,
                receiptPath=str(receipt_path), receiptFileSha256=_ref(receipt_path)['fileBytesSha256']))
        _tree(root, out)
        c.require(not out.exists() or not any(out.iterdir()), 'preview_worker_outcome_requires_reconciliation')
        out.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with accounting.stage('diagnostic.preview_worker', executor_type='deterministic_program', depends_on=depends_on) as parent_span:
                launch_clock = clock.worker_launch(parent_span)
                request = {'schemaVersion': 'sermon-diagnostic-preview-worker-request-v2',
                    'root': str(root), 'spec': spec, 'context': context, 'inputs': inputs,
                    'deadlineMonotonic': deadline, 'offlineFixture': offline_fixture,
                    'providerStateCanonicalSha256': c.canonical_sha256(state),
                    'budgetStateCanonicalSha256': c.canonical_sha256(ledger),
                    'workerCodeSha256': preview.identity.sha256(Path(__file__)),
                    'nativeRuntimeBinding': checked['native_runtime_binding'],
                    'predecessorSpans': depends_on, 'clockLaunch': launch_clock}
                request_sha = c.canonical_sha256(request)
                attempt = {'workerAttemptId': request_sha, 'requestSha256': request_sha, 'status': 'reserved'}
                preview._reserve_model_attempt(out / 'worker-attempt.json', attempt)
                jobs._persist(out / 'worker-request.json', request)
                jobs._persist(out / 'provider-state.snapshot.json', state)
                jobs._persist(out / 'budget-state.snapshot.json', ledger)
                (out / 'tmp').mkdir()
                with (out / 'worker.stdout.log').open('x') as stdout, (out / 'worker.stderr.log').open('x') as stderr:
                    # Accounting/file setup consumes the same original clock.
                    remaining = deadline - time.monotonic()
                    c.require(remaining > 0, 'preview_original_deadline_reached')
                    result = harness.bounded_process([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                        '--worker', str(out / 'worker-request.json')], timeout=remaining, check=False,
                        cwd=REPO_ROOT, env=env, stdout=stdout, stderr=stderr, text=True)
                c.require(result.returncode == 0, 'preview_worker_failed_requires_reconciliation')
                child_result = _read(out / 'worker-result.json')
                c.require(child_result['requestSha256'] == request_sha, 'preview_worker_result_changed')
                joined_clock = clock.worker_joined(launch_clock, child_result['clockFinished'])
            current, _, current_deadline = _runtime(root, subject, context)
            _same_history(state, current)
            c.require(current_deadline == deadline, 'preview_original_deadline_changed')
            _check_refs(inputs)
            c.require(offline_fixture or native_runtime.validate(spec['runtime_manifest_path'], require_process=True)
                == checked['native_runtime_binding'], 'preview_native_runtime_changed_during_worker')
            manifest, units, audio, snapshots = _outputs(root, spec, checked)
            child_result = _read(out / 'worker-result.json')
            c.require(child_result['requestSha256'] == request_sha
                and child_result['result']['status'] == 'preview_only', 'preview_worker_result_changed')
            provider_snapshot = _ref(out / 'provider-state.snapshot.json')
            budget_snapshot = _ref(out / 'budget-state.snapshot.json')
            artifacts = [manifest, *units, *audio, *snapshots, provider_snapshot, budget_snapshot,
                *[_ref(out / name) for name in ('worker-attempt.json', 'worker-request.json', 'worker-result.json')],
                *[_ref(path) for path in sorted((out / 'receipts').glob('*.attempt.json'))]]
            receipt = dict(schemaVersion=SCHEMA, status='preview_only', runId=subject.config['runId'],
                storeSha256=subject.store.store_sha256, runConfigSha256=c.canonical_sha256(subject.config),
                diagnosticContextSha256=c.canonical_sha256(context), deadlineMonotonic=deadline,
                providerStateSnapshot=provider_snapshot, budgetStateSnapshot=budget_snapshot,
                providerStateFileSha256=provider_snapshot['fileBytesSha256'],
                budgetStateFileSha256=budget_snapshot['fileBytesSha256'], spec=spec,
                specSha256=c.canonical_sha256(spec), workerAttemptId=request_sha, requestSha256=request_sha,
                inputs=inputs, artifacts=artifacts, manifest=manifest, unitReceipts=units, audio=audio,
                offlineFixture=offline_fixture, humanAcceptance='pending', productionEligible=False,
                nativeRuntimeBinding=checked['native_runtime_binding'],
                clockHandshake={'launch': launch_clock, 'finished': child_result['clockFinished'], 'joined': joined_clock})
            c.require(time.monotonic() < deadline, 'preview_original_deadline_reached')
            jobs._persist(receipt_path, receipt)
            return dict(receipt, receiptPath=str(receipt_path), receiptFileSha256=_ref(receipt_path)['fileBytesSha256'])
        except BaseException:
            # The immutable attempt survives every launch/timeout/logging failure.
            # Never remove evidence or dispatch another worker for this output.
            raise


@contextmanager
def _local_only(offline):
    def denied(*args, **kwargs):
        raise RuntimeError('diagnostic_preview_network_forbidden')
    popen = subprocess.Popen
    def spawn(command, *args, **kwargs):
        c.require(isinstance(command, (list, tuple)) and command and not kwargs.get('shell')
            and Path(command[0]).name in {'ffmpeg', 'ffprobe', 'git', 'sysctl', 'ps', 'nvidia-smi'},
            'diagnostic_preview_subprocess_forbidden')
        return popen(command, *args, **kwargs)
    with patch.object(socket.socket, 'connect', denied), patch.object(socket.socket, 'connect_ex', denied), \
         patch.object(socket.socket, 'sendto', denied), patch.object(socket, 'create_connection', denied), \
         patch.object(socket, 'getaddrinfo', denied), patch.object(subprocess, 'Popen', spawn):
        if offline:
            with patch.object(preview.formal.QwenSynthesizer, '__init__', denied):
                yield
        else:
            yield


def _worker(path):
    request = _read(path)
    c.require(request.get('schemaVersion') == 'sermon-diagnostic-preview-worker-request-v2', 'preview_worker_request_version_changed')
    c.require(request['workerCodeSha256'] == preview.identity.sha256(Path(__file__)), 'preview_worker_code_changed')
    root = _path(request['root']); out = _inside(root, request['spec']['out'])
    c.require(_path(path) == out / 'worker-request.json', 'preview_worker_request_location_changed')
    request_sha = c.canonical_sha256(request)
    c.require(_read(out / 'worker-attempt.json') == {'workerAttemptId': request_sha,
        'requestSha256': request_sha, 'status': 'reserved'}, 'preview_worker_attempt_changed')
    state = _read(out / 'provider-state.snapshot.json')
    ledger = _read(out / 'budget-state.snapshot.json')
    c.require(c.canonical_sha256(state) == request['providerStateCanonicalSha256']
        and c.canonical_sha256(ledger) == request['budgetStateCanonicalSha256']
        and c.canonical_sha256(state['config']) == request['context']['runConfigSha256']
        and state['config']['runId'] == request['context']['runId']
        and request['deadlineMonotonic'] == state['startedMonotonic'] + state['config']['totalWallSeconds'],
        'preview_original_deadline_changed')
    _same_history(state, _read(root / 'budget' / budget.STORE_ID / 'provider-run/state.json'))
    c.require(time.monotonic() < request['deadlineMonotonic'], 'preview_original_deadline_reached')
    with accounting.accounting_session(Path(os.environ['SERMON_ACCOUNTING_DIR']), 'diagnostic_preview_worker'):
        started_clock = clock.worker_started(request['clockLaunch'])
        with _local_only(request['offlineFixture']):
            spec, checked, refs = _spec(root, request['spec'], request['context'], request['offlineFixture'],
                require_runtime_process=not request['offlineFixture'])
            c.require(refs == request['inputs'] and spec == request['spec'], 'preview_inputs_changed')
            c.require(checked['native_runtime_binding'] == request['nativeRuntimeBinding'], 'preview_native_runtime_binding_changed')
            class FixtureSynth:
                def __init__(self, checkpoint, **kwargs):
                    pass
                def __call__(self, text, language, speaker, *, seed):
                    if spec.get('fixture_behavior') == 'hang':
                        time.sleep(3600)
                    with (out / 'fixture-synth-calls.jsonl').open('a') as stream:
                        stream.write(json.dumps({'textSha256': hashlib.sha256(text.encode()).hexdigest()}) + '\n')
                    return [0.03] * 1280, 16000
            kwargs = {key: spec[key] for key in OPTIONS if key in spec}
            if request['offlineFixture']:
                kwargs['synth_factory'] = FixtureSynth
            result = preview.render({key: Path(value) for key, value in spec['paths'].items()},
                    Path(spec['checkpoint_map_path']), Path(spec['operation_policies_path']), out,
                    strict_rubric=checked['strict_rubric'], diagnostic_context=request['context'],
                    deadline_monotonic=request['deadlineMonotonic'], predecessor_spans=request['predecessorSpans'], **kwargs)
            if spec.get('fixture_behavior') == 'fail_after_render':
                raise RuntimeError('synthetic failure after preview render')
            _check_refs(refs)
            c.require(request['offlineFixture'] or native_runtime.validate(spec['runtime_manifest_path'], require_process=True)
                == checked['native_runtime_binding'], 'preview_native_runtime_changed_during_worker')
            c.require(time.monotonic() < request['deadlineMonotonic'], 'preview_original_deadline_reached')
            finished_clock = clock.worker_finished(started_clock)
            jobs._persist(out / 'worker-result.json', {'requestSha256': request_sha, 'result': result,
                'clockFinished': finished_clock})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    args = parser.parse_args(argv)
    _worker(args.worker)


if __name__ == '__main__':
    main()

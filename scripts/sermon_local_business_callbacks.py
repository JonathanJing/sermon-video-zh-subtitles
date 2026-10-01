"""Offline fixture adapters for existing speech and local delivery producers.

The scope marker is a trusted caller's fixture declaration, never human/content
approval. There is deliberately no production CLI or enable flag. Injected synth
factories are trusted test code, not sandboxed arbitrary Python. Socket guards
are process-wide; callers must serialize these callbacks within a process.
Callback paths are fixture-root-relative; embedded filesystem references must
be absolute. Accounting must already be active inside the declared scope.
"""
from contextlib import contextmanager
import builtins
import hashlib
import json
import os
from pathlib import Path
import re
import socket
from unittest.mock import patch

from scripts import render_formal_target_language_speech as renderer
from scripts import sermon_accounting as accounting
from scripts import sermon_delivery_intent_binding as delivery
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as contracts
from scripts import sermon_strict_gate_admission as admission
from scripts import sermon_strict_layer3_preparation as preparation

MARKER = '.offline-business-callback-scope.json'


def initialize_scope(fixture_root, fixture_id):
    """Explicitly declare a caller-owned synthetic fixture directory, once."""
    root = Path(fixture_root).resolve(strict=True)
    if not root.is_dir() or root == root.parent or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', fixture_id):
        raise ValueError('offline_fixture_scope_invalid')
    value = {'mode': 'offline_fixture', 'fixtureId': fixture_id, 'productionEligible': False}
    marker = root / MARKER
    with marker.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, sort_keys=True)
    return marker


def _path(root, value):
    path = Path(value)
    path = path if path.is_absolute() else root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('offline_fixture_path_outside_scope')
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ValueError('offline_fixture_symlink_forbidden')
        current = current.parent
    return resolved


def _embedded(root, value, *, asset_root=None):
    """Bound artifact references before the existing validators read them."""
    if isinstance(value, list):
        for item in value:
            _embedded(root, item, asset_root=asset_root)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == 'path' and isinstance(item, str):
                # Hash-bound JSON must not be rewritten. Filesystem references
                # must be absolute because existing producers use different
                # relative bases; release public URLs have an explicit asset root.
                if asset_root is None and not Path(item).is_absolute():
                    raise ValueError('offline_fixture_embedded_path_must_be_absolute')
                _path(root, asset_root / item.lstrip('/') if asset_root is not None else item)
            else:
                _embedded(root, item, asset_root=asset_root)


def _json_inputs(root, paths):
    for path in paths:
        path = _path(root, path)
        if path.is_file():
            _embedded(root, json.loads(path.read_text()))


def _boundary(root, boundary):
    if type(boundary) is not admission.AdmissionBoundary:
        raise ValueError('offline_requires_admission_boundary')
    config = boundary.config
    _json_inputs(root, [config.source, config.anchor, config.public_candidate,
                       config.human_receipt, config.policy, config.rubric])
    for path in (boundary.store.root, config.job_root, *config.revision_roots):
        _path(root, path)


def _deny(*args, **kwargs):
    raise ValueError('offline_callback_network_or_real_model_forbidden')


@contextmanager
def _scope(*, offline, fixture_id, fixture_root):
    if offline is not True or (profile.current() or {}).get('evidenceMode') != 'synthetic':
        raise ValueError('offline_callback_requires_synthetic_profile')
    root = Path(fixture_root).resolve(strict=True)
    marker = _path(root, root / MARKER)
    expected = {'mode': 'offline_fixture', 'fixtureId': fixture_id, 'productionEligible': False}
    if json.loads(marker.read_text()) != expected:
        raise ValueError('offline_fixture_identity_changed')
    directory, run_id = accounting._identity.get() or tuple(
        os.environ.get(key) for key in accounting.ENV_KEYS[:2])
    if not directory or not run_id:
        raise ValueError('offline_callback_requires_scoped_accounting_session')
    _path(root, Path(directory).absolute())
    original = marker.read_bytes()
    import_module = builtins.__import__
    def fixture_import(name, *args, **kwargs):
        if name.split('.')[0] in {'torch', 'transformers', 'qwen_tts', 'qwen_asr',
                                  'whisper', 'faster_whisper', 'tensorflow'}:
            _deny()
        return import_module(name, *args, **kwargs)
    with patch.object(builtins, '__import__', fixture_import), \
         patch.object(socket.socket, 'connect', _deny), \
         patch.object(socket.socket, 'connect_ex', _deny), \
         patch.object(socket.socket, 'sendto', _deny), \
         patch.object(socket, 'create_connection', _deny), \
         patch.object(socket, 'getaddrinfo', _deny), \
         patch.object(renderer.QwenSynthesizer, '__init__', _deny):
        yield root
    if marker.read_bytes() != original:
        raise ValueError('offline_fixture_scope_changed')


def _artifacts(root, paths):
    result = []
    for raw in sorted(set(map(str, paths))):
        path = _path(root, raw)
        if not path.is_file():
            raise ValueError('offline_callback_artifact_missing')
        result.append({'path': str(path), 'fileBytesSha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def _result(result, root, paths, fixture_id, span):
    refs = _artifacts(root, paths)
    digest = contracts.canonical_sha256(result)
    accounting.record_workload('local.business.result', {'resultSha256': digest, 'artifactCount': len(refs)})
    return {'result': result, 'resultSha256': digest, 'artifacts': refs, 'spanId': span,
            'fixtureId': fixture_id, 'evidenceMode': 'synthetic',
            'productionEligible': False, 'executionAuthority': 'none'}


def prepare_speech(boundary, intent_id, *, adapter_path, registry_path, out,
                   offline, fixture_id, fixture_root, **voice_paths):
    with _scope(offline=offline, fixture_id=fixture_id, fixture_root=fixture_root) as root:
        _boundary(root, boundary)
        adapter_path, registry_path = _path(root, adapter_path), _path(root, registry_path)
        voice_paths = {key: _path(root, path) for key, path in voice_paths.items()}
        inputs = [adapter_path, registry_path, *voice_paths.values()]
        _json_inputs(root, inputs)
        out = _path(root, out)
        with accounting.stage('local.business.prepare_speech', executor_type='deterministic_program') as span:
            result = preparation.prepare(boundary, intent_id, adapter_path=adapter_path,
                registry_path=registry_path, out=out, **voice_paths)
            return _result(result, root, [*inputs, out / 'job.json', boundary.config.public_candidate,
                boundary.config.human_receipt], fixture_id, span)


def render_speech(paths, checkpoint_map_path, operation_policies_path, *, synth_factory=None,
                  offline, fixture_id, fixture_root, **kwargs):
    # Reject before parsing a job or opening a checkpoint, including on replay.
    if not callable(synth_factory) or synth_factory is renderer.QwenSynthesizer:
        raise ValueError('offline_trusted_synth_fixture_required')
    with _scope(offline=offline, fixture_id=fixture_id, fixture_root=fixture_root) as root:
        paths = {key: _path(root, path) for key, path in paths.items()}
        checkpoint_map_path = _path(root, checkpoint_map_path)
        operation_policies_path = _path(root, operation_policies_path)
        inputs = [*paths.values(), checkpoint_map_path, operation_policies_path]
        _json_inputs(root, inputs)
        if kwargs.get('progress_ledger') is None and os.environ.get('SERMON_FOUR_LAYER_LEDGER'):
            kwargs['progress_ledger'] = Path(os.environ['SERMON_FOUR_LAYER_LEDGER']).absolute()
        for key in ('path_map_path', 'reuse_from', 'speculative_from', 'unit_instructions_path', 'progress_ledger'):
            if kwargs.get(key) is not None:
                kwargs[key] = _path(root, kwargs[key])
        for key in ('unit_instructions_path', 'progress_ledger'):
            if kwargs.get(key) is not None:
                inputs.append(kwargs[key])
                _json_inputs(root, [kwargs[key]])
        # Materialization can write original absolute paths; use already local inputs.
        if kwargs.get('path_map_path') is not None:
            raise ValueError('offline_render_requires_materialized_fixture_inputs')
        job_root = Path(paths['job']).parent
        with accounting.stage('local.business.render_speech', executor_type='deterministic_program') as span:
            result = renderer.render_accounted(paths, checkpoint_map_path, operation_policies_path,
                synth_factory=synth_factory, **kwargs)
            outputs = [job_root / 'render-manifest.json']
            outputs += [job_root / row['path'] for row in renderer._evidence_paths(result)]
            outputs += list((job_root / 'receipts').glob('*.json'))
            return _result(result, root, [*inputs, *outputs], fixture_id, span)


def _delivery_inputs(scope, root, configuration, strict_admissions):
    root = _path(scope, root)
    paths = [root / configuration[key] for key in ('source', 'anchor')]
    paths += [root / path for lane in configuration['locales'].values() for path in lane.values()]
    _json_inputs(scope, paths)
    for row in (strict_admissions or {}).values():
        _boundary(scope, row['boundary'])
    return paths


def delivery_preflight(manifest, release_plan, *, root, configuration, offline,
                       fixture_id, fixture_root, binding=None, weekly_plan=None, strict_admissions=None):
    with _scope(offline=offline, fixture_id=fixture_id, fixture_root=fixture_root) as scope:
        root = _path(scope, root)
        inputs = _delivery_inputs(scope, root, configuration, strict_admissions)
        with accounting.stage('local.business.delivery_preflight', executor_type='deterministic_program') as span:
            arguments = dict(root=root, configuration=configuration, weekly_plan=weekly_plan,
                             strict_admissions=strict_admissions)
            bound = binding if binding is not None else delivery.freeze_binding(manifest, release_plan, **arguments)
            result = delivery.validate_preflight_binding(bound, manifest, release_plan, **arguments)
            envelope = _result(result, scope, inputs, fixture_id, span)
            envelope['binding'] = bound
            return envelope


def prepare_delivery(manifest, *, root, configuration, stage_args, preparation_receipt_path,
                     offline, fixture_id, fixture_root, weekly_plan=None, strict_admissions=None):
    with _scope(offline=offline, fixture_id=fixture_id, fixture_root=fixture_root) as scope:
        inputs = _delivery_inputs(scope, root, configuration, strict_admissions)
        root = _path(scope, root)
        out = _path(scope, root / stage_args.out)
        if out.exists():
            raise ValueError('formal_delivery_local_output_requires_reconciliation')
        for name in ('source', 'asset_root'):
            _path(scope, root / getattr(stage_args, name))
        public_documents = []
        for name in (*delivery.FORMAL_ASSIGNMENTS, 'release', 'content_review_receipt', 'fingerprint_index'):
            values = getattr(stage_args, name, [])
            if values:
                selected = [_path(scope, root / value) for value in delivery.stage.assignment_map(values, name).values()]
                if name == 'release':
                    public_documents += selected
                else:
                    inputs += selected
        preparation_receipt_path = _path(scope, preparation_receipt_path)
        inputs.append(preparation_receipt_path)
        _json_inputs(scope, inputs)
        for document in public_documents:
            _embedded(scope, json.loads(document.read_text()), asset_root=root / stage_args.asset_root)
        inputs += public_documents
        with accounting.stage('local.business.prepare_delivery', executor_type='deterministic_program') as span:
            result = delivery.prepare_formal_delivery(manifest, root=root, configuration=configuration,
                stage_args=stage_args, preparation_receipt_path=preparation_receipt_path,
                weekly_plan=weekly_plan, strict_admissions=strict_admissions)
            return _result(result, scope, [*inputs, *(out / p for p in result['outputFileBytesSha256'])],
                           fixture_id, span)

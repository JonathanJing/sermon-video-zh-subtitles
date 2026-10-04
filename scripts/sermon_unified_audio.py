"""Closed formal Layer 3 adapter. Configuration selects data, never executable code."""
from __future__ import annotations
import json
from pathlib import Path
from scripts import render_formal_target_language_speech as renderer
from scripts import validate_target_language_audio_unit as integrity
from scripts import sermon_sentence_interpretation as identity
from scripts import review_target_language_audio as audio_review

SCHEMA = 'sermon-unified-audio-job-v1'
PATH_KEYS = {'source', 'anchor', 'candidate', 'job', 'adapter', 'policy', 'human_receipt',
             'registry', 'clip_timeline_map', 'clip_voice_authorization',
             'source_voice_authorization', 'clip_voice_capability'}
SETTING_DEFAULTS = {'assemblyOnly': True, 'seed': 42, 'batchSize': 1, 'replicas': 1,
                    'device': 'cuda:0', 'dtype': 'bfloat16', 'attention': 'sdpa',
                    'trackFormat': 'wav', 'maxSynthesisUnits': 0}


def _load(job_path):
    job_path = Path(job_path).resolve()
    config = json.loads(job_path.read_text())
    if set(config) - {'schemaVersion', 'paths', 'checkpointMap', 'audioOperationPolicies',
                      'settings', 'unitInstructions', 'strictRubric', 'reuseFrom', 'inputSnapshotSha256'}:
        raise ValueError('Unknown audio adapter configuration field')
    if config.get('schemaVersion') != SCHEMA or not isinstance(config.get('paths'), dict):
        raise ValueError('Invalid fixed audio adapter configuration')
    if set(config['paths']) - PATH_KEYS:
        raise ValueError('Unknown formal audio input')
    def resolve(value):
        if not isinstance(value, str) or not value: raise ValueError('Expected nonempty input path')
        return (job_path.parent / value).resolve()
    paths = {key: resolve(value) for key, value in config['paths'].items()}
    settings = dict(SETTING_DEFAULTS)
    requested = config.get('settings', {})
    if not isinstance(requested, dict) or set(requested) - set(settings):
        raise ValueError('Unknown audio synthesis setting')
    settings.update(requested)
    if (type(settings['assemblyOnly']) is not bool or type(settings['seed']) is not int
            or type(settings['maxSynthesisUnits']) is not int or settings['maxSynthesisUnits'] < 0
            or type(settings['batchSize']) is not int or settings['batchSize'] not in renderer.BATCH_SIZES
            or type(settings['replicas']) is not int or settings['replicas'] not in (1, 8)
            or settings['device'] not in ('cuda:0', 'mps', 'cpu')
            or settings['dtype'] not in ('bfloat16', 'float32') or settings['attention'] != 'sdpa'
            or settings['trackFormat'] not in ('wav', 'mp3')):
        raise ValueError('Invalid audio settings')
    if settings['device'] == 'cpu' and not settings['assemblyOnly']:
        raise ValueError('CPU adapter is assembly-only')
    if settings['replicas'] == 8 and (settings['batchSize'], settings['device'], settings['dtype']) != (8, 'cuda:0', 'bfloat16'):
        raise ValueError('Spark replica identity requires batch8 CUDA BF16')
    extra = {name: resolve(config[name]) for name in ('checkpointMap', 'audioOperationPolicies',
             'unitInstructions', 'strictRubric', 'reuseFrom') if name in config}
    if not {'checkpointMap', 'audioOperationPolicies'} <= extra.keys():
        raise ValueError('Checkpoint map and operation policies required')
    return job_path, config, paths, settings, extra


def inspect(job_path, output_path=None):
    config_path, config, paths, settings, extra = _load(job_path)
    strict = json.loads(extra['strictRubric'].read_text()) if 'strictRubric' in extra else None
    model_directories = renderer.checkpoint_directories(paths['job'], extra['checkpointMap'],
                                                         assembly_only=settings['assemblyOnly'])
    frozen = integrity.ValidatedJobContext(paths['job'], strict_rubric=strict,
        extra_directories=model_directories,
        extra_paths=[config_path, *paths.values(), *[p for key, p in extra.items() if key != 'reuseFrom']])
    context = renderer.checked_context(paths, extra['checkpointMap'], extra['audioOperationPolicies'],
                                       strict_rubric=strict, assembly_only=settings['assemblyOnly'])
    if not settings['assemblyOnly'] and context['checkpoint'].resolve() not in {p.resolve() for p in model_directories}:
        raise ValueError('Validated checkpoint differs from frozen model directory')
    renderer.unit_instructions(context['job'], extra.get('unitInstructions'))
    root = paths['job'].parent
    committed, missing = [], []
    for index, unit in enumerate(context['job']['units']):
        commit_path = root / f'receipts/unit-{index:04d}.render.json'
        wav = root / unit['outputRelativePath']
        if commit_path.is_file():
            commit = json.loads(commit_path.read_text())
            if not wav.is_file() or identity.sha256(wav) != commit.get('audioSha256'):
                raise ValueError('Audio cache bytes differ from commit')
            receipt = root / f'receipts/unit-{index:04d}.json'
            if receipt.is_file():
                integrity.validate_receipt(paths['job'], index, wav, json.loads(receipt.read_text()), validated_context=frozen)
            committed.append(index)
        else: missing.append(index)
    frozen.check(full=True)
    dependencies = {str(path): digest for path, (_, digest) in frozen.files.items()}
    batch = settings['batchSize']
    starts = {index // batch * batch for index in missing}
    generated_units = sum(min(batch, len(context['job']['units']) - start) for start in starts)
    inputs_sha = identity.json_sha256({path: digest for path, digest in dependencies.items() if path != str(config_path)})
    if config.get('inputSnapshotSha256') not in (None, inputs_sha):
        raise ValueError('Audio input snapshot changed; create a new bound configuration')
    cache = {'committedUnits': committed, 'missingUnits': missing, 'plannedGeneratedUnits': generated_units,
             'soundIdentityAdmission': 'renderer_required'}
    plan = {'schemaVersion': 'sermon-unified-audio-plan-v1', 'adapter': 'canonical.audio',
            'targetLocale': context['job']['targetLocale'],
            'sourceMediaSha256': context['source']['source']['media']['sha256'],
            'policySha256': identity.sha256(paths['policy']), 'speechJobSha256': identity.sha256(paths['job']),
            'settings': settings, 'dependencies': dependencies, 'inputsSha256': inputs_sha,
            'snapshotBound': config.get('inputSnapshotSha256') == inputs_sha,
            'adapterCodeSha256': identity.json_sha256({p.name: identity.sha256(p) for p in
                [Path(__file__), Path(renderer.__file__), Path(integrity.__file__)]}),
            'cache': cache, 'maxEndLagSeconds': 8.0, 'humanListeningReview': 'pending',
            'productionEligible': False}
    # Cache growth during a resumed attempt does not change the admitted plan.
    plan['planHash'] = identity.json_sha256({k:v for k,v in plan.items() if k != 'cache'})
    if output_path is not None: _write_once(Path(output_path), plan)
    return plan


def _write_once(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if json.loads(path.read_text()) != result: raise ValueError('Immutable audio adapter output differs')
        return
    with path.open('x') as handle: json.dump(result, handle, ensure_ascii=False, indent=2); handle.write('\n')


def freeze(job_path, output_path):
    """Write a new fixed-data configuration before the owner freezes its run."""
    config_path, config, paths, _, extra = _load(job_path)
    if Path(output_path).resolve() == config_path:
        raise ValueError('Freeze requires a new configuration path')
    plan = inspect(config_path)
    config['paths'] = {key: str(path) for key, path in paths.items()}
    config.update({key: str(path) for key, path in extra.items()})
    config['inputSnapshotSha256'] = plan['inputsSha256']
    _write_once(Path(output_path), config)
    return inspect(output_path)


def _validated_output(paths, extra):
    root = paths['job'].parent.resolve()
    manifest_path = root / 'render-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    package = renderer.package.build_package(paths, manifest_path, root,
        strict_rubric=json.loads(extra['strictRubric'].read_text()) if 'strictRubric' in extra else None)
    if package['machineScreening']['status'] in {'pass', 'requires_review'}:
        screening_ref = renderer.package.checked_artifact(root, manifest.get('machineScreeningReceipt'), json_artifact=True)
        screening = json.loads(Path(screening_ref['path']).read_text())
        audio_review.queue(package, screening)
    closure = {}
    def collect(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                ref = renderer.package.checked_artifact(root, value, json_artifact='jsonSha256' in value)
                closure[ref['path']] = ref['sha256']
            for child in value.values(): collect(child)
        elif isinstance(value,list):
            for child in value: collect(child)
    collect(manifest)
    job = json.loads(paths['job'].read_text())
    for index in range(len(job['units'])):
        for suffix in ('.intent', '.render'):
            path = root / f'receipts/unit-{index:04d}{suffix}.json'
            if not path.is_file(): raise ValueError('Audio result lacks immutable render identity')
            closure[str(path)] = identity.sha256(path)
    track = Path(package['track']['path'])
    integrity.probe_full_decode(track)
    if track.suffix == '.mp3':
        pcm = track.with_suffix('.wav')
        integrity.probe_full_decode(pcm)
        closure[str(pcm)] = identity.sha256(pcm)
    closure[str(manifest_path)] = identity.sha256(manifest_path)
    return package, closure


def verify_result(config_path, result):
    """Read-only reconciliation: validate current input and complete output bytes.

    No synthesizer, ASR, paid request or human-approval writer is invoked.
    """
    plan = inspect(config_path)
    if (not plan['snapshotBound'] or result.get('schemaVersion') != 'sermon-unified-audio-result-v1'
            or result.get('planHash') != plan['planHash'] or result.get('status') != 'succeeded'
            or result.get('targetLocale') != plan['targetLocale']):
        raise ValueError('Audio result input/plan identity differs')
    _, _, paths, _, extra = _load(config_path)
    manifest = paths['job'].parent.resolve() / 'render-manifest.json'
    ref = result.get('renderManifest', {})
    if Path(ref.get('path', '')).resolve() != manifest or ref.get('sha256') != identity.sha256(manifest):
        raise ValueError('Audio render manifest changed')
    package, closure = _validated_output(paths, extra)
    if result.get('artifactClosure') != closure:
        raise ValueError('Audio result artifact closure changed')
    package_ref = result.get('audioPackage', {})
    package_path = Path(package_ref.get('path', ''))
    if (not package_path.is_file() or identity.sha256(package_path) != package_ref.get('sha256')
            or json.loads(package_path.read_text()) != package
            or identity.json_sha256(package) != package_ref.get('jsonSha256')):
        raise ValueError('Audio package result changed')
    if (result.get('machineScreening') != package['machineScreening']['status']
            or result.get('review') != 'human_pending' or result.get('productionEligible') is not False):
        raise ValueError('Audio result screening/review claim differs')
    for path, expected in plan['dependencies'].items():
        if identity.sha256(Path(path)) != expected: raise ValueError('Audio result dependency changed during verification')
    return {'status':'verified', 'planHash':plan['planHash'], 'fullDecode':'pass',
            'artifactCount':len(closure), 'machineScreening':package['machineScreening']['status'],
            'humanListeningReview':'pending', 'productionEligible':False}


def execute(job_path, output_path, *, expected_plan_hash, allow_synthesis=False):
    plan = inspect(job_path)
    if plan['planHash'] != expected_plan_hash: raise ValueError('Audio adapter plan identity changed')
    if not plan['snapshotBound']: raise ValueError('Audio input snapshot must be frozen before execution')
    _, _, paths, settings, extra = _load(job_path)
    missing = plan['cache']['missingUnits']
    if settings['assemblyOnly'] and missing: raise ValueError('Assembly-only requires complete committed cache')
    if not settings['assemblyOnly'] and not allow_synthesis:
        raise ValueError('Audio synthesis dispatch is not authorized by caller')
    if plan['cache']['plannedGeneratedUnits'] > settings['maxSynthesisUnits']:
        raise ValueError('Audio synthesis unit budget exceeded')
    for path, digest in plan['dependencies'].items():
        if identity.sha256(Path(path)) != digest: raise ValueError('Frozen audio adapter input changed')
    result = renderer.render_accounted(paths, extra['checkpointMap'], extra['audioOperationPolicies'],
        expected_dependency_hashes=plan['dependencies'],
        assembly_only=settings['assemblyOnly'], max_synthesis_units=settings['maxSynthesisUnits'], seed=settings['seed'], batch_size=settings['batchSize'],
        replicas=settings['replicas'], device=settings['device'], dtype=settings['dtype'], attention=settings['attention'],
        track_format=settings['trackFormat'], policy=renderer.DEFAULT_POLICY.copy(),
        unit_instructions_path=extra.get('unitInstructions'), reuse_from=extra.get('reuseFrom'),
        strict_rubric=json.loads(extra['strictRubric'].read_text()) if 'strictRubric' in extra else None)
    manifest_path = paths['job'].parent / 'render-manifest.json'
    package, closure = _validated_output(paths, extra)
    package_path = Path(output_path).with_suffix('.audio-package.json').resolve()
    _write_once(package_path, package)
    receipt = {'schemaVersion': 'sermon-unified-audio-result-v1', 'status': 'succeeded',
               'planHash': plan['planHash'], 'artifact': 'verified', 'targetLocale': result['targetLocale'],
               'renderManifest': {'path': str(manifest_path), 'sha256': identity.sha256(manifest_path)},
               'audioPackage': {'path':str(package_path), 'sha256':identity.sha256(package_path),
                                'jsonSha256':identity.json_sha256(package)},
               'artifactClosure':closure, 'review': 'human_pending',
               'machineScreening': package['machineScreening']['status'], 'productionEligible': False,
               'freshApiAttempts': 0}
    _write_once(Path(output_path), receipt)
    return receipt

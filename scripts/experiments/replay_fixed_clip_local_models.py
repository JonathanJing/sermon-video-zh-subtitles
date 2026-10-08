#!/usr/bin/env python3
"""Offline diagnostic TTS/back-ASR for frozen, source-bound CLI translations.

No content approval, formal package or publication is produced. Started batches
without a verified completion require reconciliation, never automatic replay.
The legacy 180-second fixture retains its original 39/13 identity and defaults.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from types import SimpleNamespace
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MEDIA_SHA = '79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b'
SOURCE_UNITS_SHA = 'c9ed80d95e8bdc287c9fded61c8505bf5e932f2b2d1868c11349393f8eded24e'
SOURCE_PACKAGE_SHA = '5db807669ed56c3f0e8f2dfc9550177e6f91930148ed574a17946d3136686035'
ANCHOR_SHA = 'd77f889cb8160469a979664d39f953b528cb73f54cc3a41724ce850aeaaadd62'
FLAGS = {'diagnosticOnly': True, 'humanApproval': False, 'formalEligible': False}
UNKNOWN_USAGE = {'inputTokens': None, 'outputTokens': None, 'totalTokens': None,
                 'usageStatus': 'unavailable', 'generationTokensPerSecond': None}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    require(isinstance(value, dict), 'expected_json_object')
    return value


def save(path, value):
    """Atomic JSON plus fsync before dispatch or acknowledgment."""
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def output_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.worker.lock').open('a') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('diagnostic_worker_already_running') from exc
        yield


def offline():
    # Must happen before third-party model imports and from_pretrained.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_DATASETS_OFFLINE'] = '1'


def model_tree(path):
    path = Path(path).expanduser().resolve()
    require(path.is_dir() and (path / 'config.json').is_file(), 'local_model_missing')
    require(any(path.glob('*.safetensors')), 'local_model_weights_missing')
    rows = [{'path': str(item.relative_to(path)), 'sha256': sha(item)}
            for item in sorted(path.rglob('*')) if item.is_file()]
    return {'files': rows, 'sha256': digest(rows)}


def fixed_groups(evidence, media):
    require(sha(media) == MEDIA_SHA, 'fixed_media_sha_changed')
    require(evidence.get('targetLocale') == 'zh-Hans' and evidence.get('sourceLocale') == 'en',
            'fixed_locale_changed')
    units = evidence.get('sourceUnits', [])
    require(len(units) == 39 and digest(units) == SOURCE_UNITS_SHA, 'fixed_source_units_changed')
    require(evidence.get('englishSourcePackageJsonSha256') == SOURCE_PACKAGE_SHA and
            evidence.get('anchorManifestSha256') == ANCHOR_SHA, 'fixed_source_binding_changed')
    source_ids = [f'fresh-diagnostic-u{i:03d}' for i in range(1, 40)]
    require([row.get('sourceUnitId') for row in units] == source_ids, 'fixed_unit_order_changed')
    groups = evidence.get('groups', [])
    require(len(groups) == 13, 'fixed_group_count_changed')
    result = []
    for index, group in enumerate(groups):
        gid = f'fresh-g{index + 1:03d}'
        ids = source_ids[index * 3:index * 3 + 3]
        require(group.get('translationGroupId') == gid and group.get('sourceUnitIds') == ids,
                'fixed_group_coverage_changed')
        coverage = group.get('coverage', [])
        require(len(coverage) == 3 and [row.get('sourceUnitId') for row in coverage] == ids,
                'fixed_target_coverage_changed')
        texts = [row.get('targetText') for row in coverage]
        require(all(isinstance(text, str) and text.strip() for text in texts), 'target_text_missing')
        utterances = group.get('targetUtterances', [])
        require(isinstance(utterances, list) and utterances and
                all(isinstance(text, str) and text.strip() for text in utterances), 'target_utterances_missing')
        text = ''.join(utterances)
        require(all(covered in text for covered in texts), 'target_utterances_coverage_mismatch')
        result.append({'groupId': gid, 'sourceUnitIds': ids, 'text': text,
                       'textSha256': hashlib.sha256(text.encode()).hexdigest()})
    return result


def speaker_context(registry_path, checkpoint_map_path, target_locale='zh-Hans'):
    from scripts import render_multilingual_voice_demos as demos
    registry, mapping = read(registry_path), read(checkpoint_map_path)
    require(registry.get('schemaVersion') == 'sermon-speaker-voice-registry-v1' and
            mapping.get('schemaVersion') == 'sermon-speaker-checkpoint-map-v1', 'unsupported_voice_registry')
    speakers = [r for r in registry.get('speakers', []) if r.get('speakerId') == 'eric_geiger']
    choices = [r for r in mapping.get('checkpoints', []) if r.get('speakerId') == 'eric_geiger']
    require(len(speakers) == len(choices) == 1, 'eric_checkpoint_mapping_not_unique')
    speaker, locator = speakers[0], choices[0]
    authorization = speaker.get('authorization', {})
    require(authorization.get('status') == 'authorized' and
            ('chinese_dubbing' if target_locale == 'zh-Hans' else 'multilingual_voice_demo') in
            authorization.get('purposes', []) and authorization.get('evidence'),
            'eric_chinese_voice_not_authorized')
    languages = {'zh-Hans': 'Chinese', 'ko': 'Korean', 'es': 'Spanish'}
    require(target_locale in languages, 'diagnostic_voice_locale_not_supported')
    capabilities = [r for r in speaker.get('localeCapabilities', []) if r.get('targetLocale') == target_locale]
    require(len(capabilities) == 1 and capabilities[0].get('modelLanguage') == languages[target_locale] and
            capabilities[0].get('status') in {'human_reviewed', 'unverified_poc'} and not capabilities[0].get('adapterOverride'),
            'eric_chinese_capability_invalid')
    checkpoint = speaker.get('checkpoint', {})
    require(locator.get('checkpointRef') == checkpoint.get('checkpointRef'), 'checkpoint_ref_changed')
    task = {'speakerId': 'eric_geiger', 'speakerKey': speaker['speakerKey'],
            'checkpointPath': locator.get('path'), 'checkpointSha256': checkpoint['checkpointSha256']}
    path = demos.validate_checkpoint(task)
    return path, {'speakerId': 'eric_geiger', 'speakerKey': speaker['speakerKey'],
                  'modelLanguage': languages[target_locale], 'checkpointSha256': checkpoint['checkpointSha256'],
                  'checkpointTreeSha256': model_tree(path)['sha256'],
                  'registrySha256': sha(registry_path), 'checkpointMapSha256': sha(checkpoint_map_path)}


def bind_run(root, identity):
    path = root / 'run.json'
    if path.exists():
        require(read(path) == identity, 'diagnostic_resume_identity_changed')
    else:
        require(not any(root.glob('batch-*.json')), 'orphan_batch_requires_reconciliation')
        save(path, identity)


def batch_paths(root, index):
    prefix = root / f'batch-{index:03d}'
    return prefix.with_suffix('.started.json'), prefix.with_suffix('.completed.json')


def completed_batch(root, index, identity, expected):
    started, completed = batch_paths(root, index)
    if completed.exists():
        envelope = read(completed)
        receipt = envelope.get('receipt', {})
        require(envelope.get('receiptSha256') == digest(receipt) and
                receipt.get('runIdentitySha256') == digest(identity) and
                receipt.get('batchIndex') == index and receipt.get('inputs') == expected and
                all(receipt.get(k) == v for k, v in FLAGS.items()) and
                receipt.get('status') == 'completed_diagnostic', 'batch_receipt_identity_changed')
        elapsed = receipt.get('inferenceSeconds')
        require(type(elapsed) in (float, int) and math.isfinite(elapsed) and elapsed >= 0,
                'batch_timing_invalid')
        require(len(receipt.get('outputs', [])) == len(expected), 'batch_output_cardinality_changed')
        return receipt
    require(not started.exists(), 'unknown_batch_requires_reconciliation')
    return None


def begin_batch(root, index, identity, inputs):
    started, _ = batch_paths(root, index)
    attempt = {'runIdentitySha256': digest(identity), 'batchIndex': index,
               'callId': uuid.uuid4().hex, 'backend': 'local', 'model': identity['model'],
               'startedAt': datetime.now(timezone.utc).isoformat(),
               'inputs': inputs, 'status': 'started_unknown_until_receipt', **FLAGS}
    save(started, attempt)
    return attempt


def finish_batch(root, index, receipt):
    _, completed = batch_paths(root, index)
    save(completed, {'receiptSha256': digest(receipt), 'receipt': receipt})


def safe_audio(root, row):
    path = (root / row['audioPath']).resolve()
    require(path.is_relative_to(root.resolve()) and path.is_file() and sha(path) == row['audioSha256'],
            'completed_audio_missing_or_changed')
    return path


def audio_output(root, group, wave, sample_rate):
    from scripts.render_formal_target_language_speech import _cpu_audio_input, write_pcm16
    wave = _cpu_audio_input(wave)
    require(wave and all(math.isfinite(float(value)) for value in wave) and
            any(value != 0 for value in wave), 'tts_wave_nonfinite_or_silent')
    require(type(sample_rate) is int and sample_rate > 0 and len(wave) > 0, 'tts_audio_invalid')
    name = group['groupId'] + '.wav'
    path = root / name
    require(not path.exists() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
            'orphan_audio_requires_reconciliation')
    tmp = root / (name + '.tmp.wav')
    require(not tmp.exists() and not tmp.is_symlink() and tmp.resolve().is_relative_to(root.resolve()),
            'orphan_partial_audio_requires_reconciliation')
    write_pcm16(tmp, wave, sample_rate)
    with tmp.open('rb') as stream:
        os.fsync(stream.fileno())
    from scripts.validate_target_language_audio_unit import probe_full_decode
    decoded = probe_full_decode(tmp)
    return {**group, 'audioPath': name, 'audioSha256': sha(tmp), 'sampleRate': sample_rate,
            'audioSeconds': decoded['durationSeconds'], '_preparedAudioPath': tmp.name}


def commit_audio_output(root, output):
    """Only the parent promotes prepared WAVs, in bound group order."""
    output = dict(output)
    prepared = output.pop('_preparedAudioPath', None)
    if prepared is not None:
        path, temporary = root / output['audioPath'], root / prepared
        require(temporary.resolve().is_relative_to(root.resolve()) and
                path.resolve().is_relative_to(root.resolve()) and not path.exists()
                and sha(temporary) == output['audioSha256'], 'prepared_audio_changed')
        os.replace(temporary, path)
        fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return output


def synchronize(model):
    torch = getattr(model, 'torch', None)
    if torch is not None and torch.cuda.is_available():
        torch.cuda.synchronize()


def render_tts(args, *, factory=None, writer=audio_output, model_session=None, runtime_identity_sha256=None):
    process_started = time.perf_counter()
    from scripts import local_audio_resource_admission as gpu
    resource_policy=gpu.policy_from_path(getattr(args, 'resource_policy', None))
    evidence = read(args.evidence)
    general = getattr(args, 'diagnostic_fixture', None) is not None
    require(general == (getattr(args, 'diagnostic_candidate', None) is not None), 'diagnostic_fixture_candidate_required_together')
    binding = None
    if general:
        from scripts.experiments.diagnostic_audio_inputs import checked_inputs, check_frozen
        groups, binding = checked_inputs(args)
    else:
        groups = fixed_groups(evidence, args.media)
    batch_size = getattr(args, 'batch_size', None) or 2
    replicas = getattr(args, 'replicas', 1)
    cpu_workers = getattr(args, 'cpu_workers', 0)
    if general and binding.get('concurrencyProfile') is not None:
        require(cpu_workers == binding['concurrencyProfile']['cpuWorkers'], 'diagnostic_cpu_profile_not_consumed')
    require(type(batch_size) is int and batch_size in (1, 2, 4, 8), 'tts_batch_size_invalid')
    require(type(replicas) is int and replicas in (1, 8), 'tts_replicas_invalid')
    require(general or (batch_size == 2 and replicas == 1), 'fixed_diagnostic_settings_changed')
    require(replicas == 1 or (batch_size == 8 and args.device == 'cuda:0' and args.attention == 'sdpa'
                            and model_session is None), 'diagnostic_replica_profile_invalid')
    require(replicas == 1 or resource_policy is not None, 'diagnostic_replicas_require_shared_gpu_policy')
    target_locale = binding['targetLocale'] if general else 'zh-Hans'
    checkpoint, voice = speaker_context(args.registry, args.checkpoint_map, target_locale)
    offline()
    identity = {'schemaVersion': 'fixed-clip-local-tts-run-v1', **FLAGS,
                'mediaSha256': binding['sourceMediaSha256'] if general else MEDIA_SHA,
                'sourceUnitCount': binding['sourceUnitCount'] if general else 39, 'groupCount': len(groups),
                'evidenceSha256': sha(args.evidence), 'voice': voice, 'batchSize': batch_size,
                'backend': 'local', 'model': 'Qwen/Qwen3-TTS-12Hz-1.7B-speaker-checkpoint',
                'synthesizerImplementationSha256': sha(Path(__file__).resolve().parents[1] / 'render_formal_target_language_speech.py'),
                'checkpointValidatorImplementationSha256': sha(Path(__file__).resolve().parents[1] / 'render_multilingual_voice_demos.py'),
                'settings': {'seed': args.seed, 'device': args.device, 'dtype': 'bfloat16',
                             'attention': args.attention}, 'workerSha256': sha(__file__)}
    if general:
        identity.update(schemaVersion='source-bound-local-tts-run-v1', diagnosticBinding=binding,
                        targetLocale=target_locale,
                        replicas=replicas, cpuWorkers=cpu_workers,
                        cpuQueueUnits=getattr(args, 'cpu_queue_units', 16),
                        seedPolicy='base_plus_fixed_window_start',
                        simulationOnly=True, productionEligible=False, releaseEligible=False)
    if resource_policy is not None:
        identity['resourcePolicySha256']=digest(resource_policy)
        identity['resourceAdmissionImplementationSha256']=sha(gpu.__file__)
        identity['gpuCleanupRequired']=True
    session_key=None
    if model_session is not None:
        require(resource_policy is None, 'resident_session_requires_whole_session_gpu_admission')
        from scripts.experiments import local_model_session as resident
        session_key=resident.ModelKey(
            stage='tts' if 'voice' in identity else 'asr',
            model_tree_sha256=identity['voice']['checkpointTreeSha256'] if 'voice' in identity else identity['modelTreeSha256'],
            checkpoint_sha256=identity['voice']['checkpointSha256'] if 'voice' in identity else None,
            device=args.device,dtype='bfloat16',attention=getattr(args,'attention',None),
            runtime_identity_sha256=runtime_identity_sha256,
            implementation_sha256=identity.get('synthesizerImplementationSha256',identity['workerSha256']))
        from dataclasses import asdict
        identity['modelSessionKey']=asdict(session_key)
        identity['modelSessionImplementationSha256']=sha(resident.__file__)
    root = args.out.resolve()
    with output_lock(root), ExitStack() as borrowed:
        from scripts.bounded_audio_cpu import BoundedAudioCPU
        cpu = BoundedAudioCPU(cpu_workers, getattr(args, 'cpu_queue_units', 16))
        borrowed.callback(cpu.close)
        bind_run(root, identity)
        receipts, model, load_seconds = [], None, None
        # Check every existing batch before even loading a model.
        for index, start in enumerate(range(0, len(groups), batch_size)):
            selected = groups[start:start + batch_size]
            receipt = completed_batch(root, index, identity, selected)
            if receipt is not None:
                for row, expected in zip(receipt['outputs'], selected):
                    require(all(row.get(k) == v for k, v in expected.items()), 'cached_tts_text_changed')
                    safe_audio(root, row)
            receipts.append(receipt)
        final_path = root / 'manifest.json'
        if final_path.exists() and all(receipts):
            final = read(final_path)
            require(all(final.get(k) == v for k, v in identity.items()) and
                    final.get('groups') == [row for r in receipts for row in r['outputs']],
                    'completed_manifest_changed')
            gpu.finish(root, identity, resource_policy, final)
            return final
        if not all(receipts):
            gpu.admit(root, identity, resource_policy)
        attempts, pool = {}, None
        if replicas == 8 and not all(receipts):
            from scripts import spark_tts_replica_pool as pool_module
            from scripts.render_formal_target_language_speech import SparkQwenSynthesizer
            from scripts.spark_tts_window_scheduler import ParallelBatchEngine
            windows = {}
            for index, start in enumerate(range(0, len(groups), batch_size)):
                if receipts[index] is None:
                    selected = groups[start:start + batch_size]
                    attempts[index] = begin_batch(root, index, identity, selected)
                    windows[start] = [{'identity': row, 'text': row['text'], 'language': voice['modelLanguage'],
                                       'speaker': voice['speakerKey'], 'instruct': None} for row in selected]
            runtime = {'schemaVersion': 'diagnostic-tts-replica-runtime-v1', 'replicas': 8,
                       'batchSize': 8, 'status': 'running', 'events': [], **FLAGS}
            def event(row):
                runtime['events'].append(row); save(root / 'replica-runtime.json', runtime)
            pool = pool_module.ReplicaPool(checkpoint, factory=SparkQwenSynthesizer if factory is None else factory,
                engine_kwargs={'device': args.device, 'dtype': 'bfloat16', 'attention': args.attention},
                replicas=replicas, telemetry=event)
            borrowed.callback(pool.close)
            def frozen_check():
                require(sha(args.evidence) == identity['evidenceSha256'], 'diagnostic_evidence_changed_before_dispatch')
                check_frozen(binding)
            began = time.perf_counter()
            model = ParallelBatchEngine(pool, windows, seed=args.seed, frozen_check=frozen_check)
            load_seconds = time.perf_counter() - began
        for index, start in enumerate(range(0, len(groups), batch_size)):
            if receipts[index] is not None:
                continue
            if general:
                check_frozen(binding)
            if model is None:
                if factory is None:
                    from scripts.render_formal_target_language_speech import QwenSynthesizer
                    factory = QwenSynthesizer
                began = time.perf_counter()
                load=lambda: factory(checkpoint, device=args.device, dtype='bfloat16', attention=args.attention)
                model=load() if model_session is None else borrowed.enter_context(model_session.borrow(session_key,load))
                synchronize(model)
                load_seconds = time.perf_counter() - began
            selected = groups[start:start + batch_size]
            attempt = attempts.get(index) or begin_batch(root, index, identity, selected)
            synchronize(model); began = time.perf_counter()
            values = model.batch([{'identity': row, 'text': row['text'], 'language': voice['modelLanguage'],
                                  'speaker': voice['speakerKey'], 'instruct': None} for row in selected],
                                 seed=args.seed + (start if general else index))
            synchronize(model); waited = time.perf_counter() - began
            if replicas == 8:
                # Replica windows run in workers; the parent only waits for the one it collects.
                elapsed, timing_scope = model.last_window_seconds, 'replica_worker_generation'
                require(type(elapsed) in (float, int) and math.isfinite(elapsed) and elapsed >= 0,
                        'replica_window_timing_missing')
            else:
                elapsed, timing_scope = waited, 'batch_including_gpu_synchronization'
            require(len(values) == len(selected), 'tts_output_cardinality_changed')
            pending_outputs = []
            for expected, value in zip(selected, values):
                require(value.get('identity') == expected, 'tts_output_identity_changed')
                require(getattr(value.get('wave'), 'ndim', 1) == 1,
                        'tts_requires_mono_model_output')
            # Validate the whole model window before any CPU write. GPU transfer
            # happens here on the caller; workers only encode/decode/hash bytes.
            from scripts.render_formal_target_language_speech import _cpu_audio_input
            for expected, value in zip(selected, values):
                pending_outputs.append(cpu.submit(writer, root, expected,
                    _cpu_audio_input(value['wave']) if cpu_workers else value['wave'], value['sampleRate']))
            prepared_outputs = [future.result() for future in pending_outputs]
            outputs = [commit_audio_output(root, output) for output in prepared_outputs]
            receipt = {'schemaVersion': 'fixed-clip-local-tts-batch-v1', **FLAGS,
                       'runIdentitySha256': digest(identity), 'batchIndex': index,
                       'callId': attempt['callId'], 'backend': 'local', 'model': identity['model'],
                       'startedAt': attempt['startedAt'], 'completedAt': datetime.now(timezone.utc).isoformat(),
                       'status': 'completed_diagnostic', 'inputs': selected, 'outputs': outputs,
                       'inferenceSeconds': elapsed, 'timingScope': timing_scope,
                       'parentWaitSeconds': waited, 'usage': dict(UNKNOWN_USAGE)}
            finish_batch(root, index, receipt); receipts[index] = receipt
            print(json.dumps({'stage': 'tts', 'batchIndex': index, 'completedGroups': sum(len(r['outputs']) for r in receipts if r)}), flush=True)
        # Revalidate live input/voice identities before publishing a final manifest.
        require(sha(args.evidence) == identity['evidenceSha256'] and sha(args.media) == identity['mediaSha256'],
                'input_changed_during_tts')
        if general:
            current_groups, current_binding = checked_inputs(args)
            require(current_groups == groups and current_binding == binding, 'diagnostic_audio_inputs_changed_during_run')
        _, current_voice = speaker_context(args.registry, args.checkpoint_map, target_locale)
        require(current_voice == voice, 'voice_changed_during_tts')
        manifest = {**identity, 'status': 'completed_diagnostic', 'modelLoadSeconds': load_seconds,
                    'processWallSeconds': time.perf_counter() - process_started,
                    'processWallScope': 'this_invocation_including_validation_load_and_io',
                    'inferenceSeconds': sum(r['inferenceSeconds'] for r in receipts),
                    'usage': dict(UNKNOWN_USAGE), 'groups': [row for r in receipts for row in r['outputs']],
                    'batchReceipts': [{'path': batch_paths(root, i)[1].name,
                                       'sha256': sha(batch_paths(root, i)[1])} for i in range(len(receipts))]}
        if cpu_workers:
            cpu.close()
            manifest['cpuRuntime'] = cpu.report()
            save(root / 'cpu-runtime.json', manifest['cpuRuntime'])
        if pool is not None:
            pool.close(); model = None
            runtime['status'] = 'closed'; save(root / 'replica-runtime.json', runtime)
        if resource_policy is not None:
            if model is not None or pool is not None:
                from scripts.experiments.local_model_session import dispose_model, cleanup_loaded_gpu
                import gc
                if model is not None:
                    dispose_model(model); model=None
                gc.collect(); cleanup_loaded_gpu()
                gpu.record_cleanup(root, identity)
            else:
                gpu.require_cleanup(root, identity)
        save(root / 'manifest.json', manifest)
        gpu.finish(root, identity, resource_policy, manifest)
        return manifest


class LocalASR:
    def __init__(self, path, *, device, batch_size=4, language='Chinese', session_verifier=None):
        from scripts.production_spark_admission import require_bound_model_session
        require_bound_model_session(verifier=session_verifier)
        import torch
        from qwen_asr import Qwen3ASRModel
        self.torch = torch
        self.language = language
        self.model = Qwen3ASRModel.from_pretrained(str(path), dtype=torch.bfloat16,
            device_map=device, max_inference_batch_size=batch_size, max_new_tokens=2048)

    def batch(self, paths):
        import soundfile as sf
        began = time.perf_counter()
        audio = [sf.read(str(path), dtype='float32') for path in paths]
        self.decode_seconds = time.perf_counter() - began
        require(all(w.ndim == 1 for w, _ in audio), 'asr_requires_mono_audio')
        synchronize(self); began = time.perf_counter()
        result = self.model.transcribe(audio=audio, language=[self.language] * len(paths))
        synchronize(self); self.inference_seconds = time.perf_counter() - began
        return result


def back_asr(args, *, factory=LocalASR, model_session=None, runtime_identity_sha256=None):
    process_started = time.perf_counter()
    from scripts import local_audio_resource_admission as gpu
    resource_policy=gpu.policy_from_path(getattr(args, 'resource_policy', None))
    source = read(args.tts_manifest)
    general = source.get('schemaVersion') == 'source-bound-local-tts-run-v1'
    batch_size = getattr(args, 'batch_size', None) or 4
    require(type(batch_size) is int and batch_size in (1, 4, 8), 'asr_batch_size_invalid')
    require(general or batch_size == 4, 'fixed_diagnostic_asr_settings_changed')
    require(source.get('schemaVersion') in ('fixed-clip-local-tts-run-v1', 'source-bound-local-tts-run-v1') and
            source.get('status') == 'completed_diagnostic' and
            all(source.get(k) == v for k, v in FLAGS.items()) and
            (general or (source.get('mediaSha256') == MEDIA_SHA and source.get('sourceUnitCount') == 39 and
            source.get('groupCount') == 13 and source.get('batchSize') == 2)), 'tts_manifest_not_fixed_diagnostic')
    groups = source.get('groups', [])
    tts_root = args.tts_manifest.parent.resolve()
    tts_identity = read(tts_root / 'run.json')
    require(all(source.get(key) == value for key, value in tts_identity.items()), 'tts_manifest_identity_changed')
    if general:
        from scripts.experiments.diagnostic_audio_inputs import checked_inputs, check_frozen
        binding = source['diagnosticBinding']
        bound_args = SimpleNamespace(diagnostic_fixture=Path(binding['fixtureDirectory']),
            diagnostic_candidate=Path(binding['candidatePath']), evidence=Path(binding['evidencePath']),
            media=Path(binding['mediaPath']))
        expected_groups, current_binding = checked_inputs(bound_args)
        if binding.get('concurrencyProfile') is not None:
            require(batch_size == binding['concurrencyProfile']['backASRBatchSize'], 'diagnostic_asr_profile_not_consumed')
        require(current_binding == binding and len(groups) == source['groupCount'] == len(expected_groups)
                and all(all(row.get(key) == value for key, value in expected.items())
                        for row, expected in zip(groups, expected_groups))
                and all(source.get(key) is value for key, value in
                        {'simulationOnly': True, 'productionEligible': False, 'releaseEligible': False}.items()),
                'asr_diagnostic_source_binding_changed')
    else:
        require(len(groups) == 13 and [r.get('groupId') for r in groups] ==
                [f'fresh-g{i:03d}' for i in range(1, 14)], 'asr_fixed_group_coverage_changed')
    for index, row in enumerate(groups):
        require((general or row.get('sourceUnitIds') == [f'fresh-diagnostic-u{i:03d}' for i in range(index * 3 + 1, index * 3 + 4)]) and
                isinstance(row.get('text'), str) and row['text'].strip() and
                row.get('textSha256') == hashlib.sha256(row['text'].encode()).hexdigest(), 'asr_text_identity_changed')
        safe_audio(args.tts_manifest.parent, row)
    for row in source.get('batchReceipts', []):
        path = (args.tts_manifest.parent / row['path']).resolve()
        require(path.is_relative_to(args.tts_manifest.parent.resolve()) and sha(path) == row['sha256'],
                'tts_batch_receipt_changed')
    require(len(source.get('batchReceipts', [])) == math.ceil(len(groups) / source['batchSize']), 'tts_batch_receipts_missing')
    require(source['batchReceipts'] == [{'path': batch_paths(tts_root, index)[1].name,
                'sha256': sha(batch_paths(tts_root, index)[1])}
                for index in range(math.ceil(len(groups) / source['batchSize']))], 'tts_batch_receipt_inventory_changed')
    for index, start in enumerate(range(0, len(groups), source['batchSize'])):
        expected = [{k: row[k] for k in ('groupId', 'sourceUnitIds', 'text', 'textSha256')}
                    for row in groups[start:start + source['batchSize']]]
        receipt = completed_batch(tts_root, index, tts_identity, expected)
        require(receipt is not None and receipt['outputs'] == groups[start:start + source['batchSize']],
                'tts_batch_outputs_changed')
    tree = model_tree(args.model_path)
    offline()
    identity = {'schemaVersion': 'fixed-clip-local-asr-run-v1', **FLAGS,
                'mediaSha256': source['mediaSha256'], 'sourceUnitCount': source['sourceUnitCount'], 'groupCount': len(groups),
                'ttsManifestSha256': sha(args.tts_manifest), 'modelTreeSha256': tree['sha256'],
                'batchSize': batch_size, 'backend': 'local', 'model': 'Qwen/Qwen3-ASR-0.6B', 'device': args.device, 'workerSha256': sha(__file__)}
    if general:
        identity.update(schemaVersion='source-bound-local-asr-run-v1', diagnosticBinding=binding,
                        modelReplicas=1, targetLocale=binding['targetLocale'], modelLanguage=source['voice']['modelLanguage'],
                        simulationOnly=True, productionEligible=False, releaseEligible=False)
    if resource_policy is not None:
        identity['resourcePolicySha256']=digest(resource_policy)
        identity['resourceAdmissionImplementationSha256']=sha(gpu.__file__)
        identity['gpuCleanupRequired']=True
    session_key=None
    if model_session is not None:
        require(resource_policy is None, 'resident_session_requires_whole_session_gpu_admission')
        from scripts.experiments import local_model_session as resident
        session_key=resident.ModelKey(
            stage='tts' if 'voice' in identity else 'asr',
            model_tree_sha256=identity['voice']['checkpointTreeSha256'] if 'voice' in identity else identity['modelTreeSha256'],
            checkpoint_sha256=identity['voice']['checkpointSha256'] if 'voice' in identity else None,
            device=args.device,dtype='bfloat16',attention=getattr(args,'attention',None),
            runtime_identity_sha256=runtime_identity_sha256,
            implementation_sha256=digest({'workerSha256': identity['workerSha256'], 'maxInferenceBatchSize': batch_size,
                                         'modelLanguage': identity['modelLanguage']})
                if general else identity['workerSha256'])
        from dataclasses import asdict
        identity['modelSessionKey']=asdict(session_key)
        identity['modelSessionImplementationSha256']=sha(resident.__file__)
    root = args.out.resolve()
    with output_lock(root), ExitStack() as borrowed:
        bind_run(root, identity)
        receipts, model, load_seconds = [], None, None
        for index, start in enumerate(range(0, len(groups), batch_size)):
            selected = groups[start:start + batch_size]
            receipt = completed_batch(root, index, identity, selected)
            if receipt is not None:
                for row, expected in zip(receipt['outputs'], selected):
                    require(row.get('groupId') == expected['groupId'] and
                            row.get('expectedText') == expected['text'] and
                            row.get('audioSha256') == expected['audioSha256'] and
                            isinstance(row.get('recognizedText'), str), 'cached_asr_output_changed')
            receipts.append(receipt)
        final_path = root / 'manifest.json'
        if final_path.exists() and all(receipts):
            final = read(final_path)
            require(all(final.get(k) == v for k, v in identity.items()) and
                    final.get('groups') == [row for r in receipts for row in r['outputs']],
                    'completed_manifest_changed')
            gpu.finish(root, identity, resource_policy, final)
            return final
        if not all(receipts):
            gpu.admit(root, identity, resource_policy)
        for index, start in enumerate(range(0, len(groups), batch_size)):
            if receipts[index] is not None:
                continue
            if general:
                check_frozen(binding)
            if model is None:
                began = time.perf_counter()
                load=lambda: factory(args.model_path.resolve(), device=args.device, **(
                    {'batch_size': batch_size, 'language': identity['modelLanguage']} if general else
                    {'batch_size': batch_size} if factory is LocalASR else {}))
                model=load() if model_session is None else borrowed.enter_context(model_session.borrow(session_key,load))
                synchronize(model); load_seconds = time.perf_counter() - began
            selected = groups[start:start + batch_size]
            paths = [safe_audio(args.tts_manifest.parent, row) for row in selected]
            attempt = begin_batch(root, index, identity, selected)
            synchronize(model); began = time.perf_counter()
            results = model.batch(paths)
            synchronize(model); batch_wall = time.perf_counter() - began
            elapsed = getattr(model, 'inference_seconds', batch_wall)
            require(len(results) == len(selected), 'asr_output_cardinality_changed')
            outputs = []
            for row, result in zip(selected, results):
                require(isinstance(result.text, str) and result.text.strip(), 'asr_text_missing')
                outputs.append({'groupId': row['groupId'], 'expectedText': row['text'],
                                'recognizedText': result.text, 'audioSha256': row['audioSha256'],
                                'status': 'machine_output_requires_review'})
            receipt = {'schemaVersion': 'fixed-clip-local-asr-batch-v1', **FLAGS,
                       'runIdentitySha256': digest(identity), 'batchIndex': index,
                       'callId': attempt['callId'], 'backend': 'local', 'model': identity['model'],
                       'startedAt': attempt['startedAt'], 'completedAt': datetime.now(timezone.utc).isoformat(),
                       'status': 'completed_diagnostic', 'inputs': selected, 'outputs': outputs,
                       'inferenceSeconds': elapsed, 'batchWallSeconds': batch_wall,
                       'audioDecodeSeconds': getattr(model, 'decode_seconds', None),
                       'timingScope': 'model_inference_including_gpu_synchronization',
                       'usage': dict(UNKNOWN_USAGE)}
            finish_batch(root, index, receipt); receipts[index] = receipt
            print(json.dumps({'stage': 'asr', 'batchIndex': index, 'completedGroups': sum(len(r['outputs']) for r in receipts if r)}), flush=True)
        require(sha(args.tts_manifest) == identity['ttsManifestSha256'] and
                model_tree(args.model_path)['sha256'] == identity['modelTreeSha256'], 'asr_inputs_changed_during_run')
        for row in groups:
            safe_audio(args.tts_manifest.parent, row)
        if general:
            current_groups, current_binding = checked_inputs(bound_args)
            require(current_binding == binding and current_groups == expected_groups,
                    'asr_diagnostic_inputs_changed_during_run')
        report = {**identity, 'status': 'completed_diagnostic', 'modelLoadSeconds': load_seconds,
                  'processWallSeconds': time.perf_counter() - process_started,
                  'processWallScope': 'this_invocation_including_validation_load_and_io',
                  'inferenceSeconds': sum(r['inferenceSeconds'] for r in receipts),
                  'usage': dict(UNKNOWN_USAGE), 'groups': [row for r in receipts for row in r['outputs']],
                  'batchReceipts': [{'path': batch_paths(root, i)[1].name,
                                     'sha256': sha(batch_paths(root, i)[1])} for i in range(len(receipts))]}
        if resource_policy is not None:
            if model is not None:
                from scripts.experiments.local_model_session import dispose_model, cleanup_loaded_gpu
                import gc
                dispose_model(model); model=None
                gc.collect(); cleanup_loaded_gpu()
                gpu.record_cleanup(root, identity)
            else:
                gpu.require_cleanup(root, identity)
        save(root / 'manifest.json', report)
        gpu.finish(root, identity, resource_policy, report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='stage', required=True)
    tts = commands.add_parser('tts')
    for name in ('evidence', 'media', 'registry', 'checkpoint-map'):
        tts.add_argument('--' + name, type=Path, required=True)
    tts.add_argument('--seed', type=int, default=42)
    tts.add_argument('--attention', default='sdpa')
    tts.add_argument('--diagnostic-fixture', type=Path)
    tts.add_argument('--diagnostic-candidate', type=Path)
    tts.add_argument('--replicas', type=int, choices=(1, 8), default=1)
    tts.add_argument('--cpu-workers', type=int, choices=(0, 1, 2, 4), default=0)
    tts.add_argument('--cpu-queue-units', type=int, choices=range(1, 17), default=16)
    asr = commands.add_parser('asr')
    asr.add_argument('--tts-manifest', type=Path, required=True)
    asr.add_argument('--model-path', type=Path, required=True)
    for command in (tts, asr):
        command.add_argument('--batch-size', type=int, choices=(1, 2, 4, 8), default=None)
        command.add_argument('--out', type=Path, required=True)
        command.add_argument('--device', default='cuda:0')
        command.add_argument('--resource-policy', type=Path, help='Explicit shared host-local GPU admission policy')
    args = parser.parse_args()
    result = render_tts(args) if args.stage == 'tts' else back_asr(args)
    print(json.dumps({'status': result['status'], 'groups': len(result['groups']), **FLAGS}))


if __name__ == '__main__':
    main()

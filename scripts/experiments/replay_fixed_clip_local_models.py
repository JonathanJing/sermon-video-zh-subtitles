#!/usr/bin/env python3
"""Offline diagnostic TTS/back-ASR for the frozen 180-second CLI translation.

No content approval, formal package or publication is produced. Started batches
without a verified completion require reconciliation, never automatic replay.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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


def speaker_context(registry_path, checkpoint_map_path):
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
            'chinese_dubbing' in authorization.get('purposes', []) and authorization.get('evidence'),
            'eric_chinese_voice_not_authorized')
    capabilities = [r for r in speaker.get('localeCapabilities', []) if r.get('targetLocale') == 'zh-Hans']
    require(len(capabilities) == 1 and capabilities[0].get('modelLanguage') == 'Chinese' and
            capabilities[0].get('status') in {'human_reviewed', 'unverified_poc'} and not capabilities[0].get('adapterOverride'),
            'eric_chinese_capability_invalid')
    checkpoint = speaker.get('checkpoint', {})
    require(locator.get('checkpointRef') == checkpoint.get('checkpointRef'), 'checkpoint_ref_changed')
    task = {'speakerId': 'eric_geiger', 'speakerKey': speaker['speakerKey'],
            'checkpointPath': locator.get('path'), 'checkpointSha256': checkpoint['checkpointSha256']}
    path = demos.validate_checkpoint(task)
    return path, {'speakerId': 'eric_geiger', 'speakerKey': speaker['speakerKey'],
                  'modelLanguage': 'Chinese', 'checkpointSha256': checkpoint['checkpointSha256'],
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
    import soundfile as sf
    import numpy as np
    wave = np.asarray(wave)
    require(wave.ndim == 1 and wave.size > 0 and np.isfinite(wave).all() and
            np.any(wave != 0), 'tts_wave_nonfinite_or_silent')
    require(type(sample_rate) is int and sample_rate > 0 and len(wave) > 0, 'tts_audio_invalid')
    name = group['groupId'] + '.wav'
    path = root / name
    require(not path.exists(), 'orphan_audio_requires_reconciliation')
    tmp = root / (name + '.tmp.wav')
    sf.write(str(tmp), wave, sample_rate, subtype='PCM_16')
    with tmp.open('rb') as stream:
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    return {**group, 'audioPath': name, 'audioSha256': sha(path), 'sampleRate': sample_rate,
            'audioSeconds': len(wave) / sample_rate}


def synchronize(model):
    torch = getattr(model, 'torch', None)
    if torch is not None and torch.cuda.is_available():
        torch.cuda.synchronize()


def render_tts(args, *, factory=None, writer=audio_output):
    process_started = time.perf_counter()
    evidence = read(args.evidence)
    groups = fixed_groups(evidence, args.media)
    checkpoint, voice = speaker_context(args.registry, args.checkpoint_map)
    offline()
    identity = {'schemaVersion': 'fixed-clip-local-tts-run-v1', **FLAGS,
                'mediaSha256': MEDIA_SHA, 'sourceUnitCount': 39, 'groupCount': 13,
                'evidenceSha256': sha(args.evidence), 'voice': voice, 'batchSize': 2,
                'backend': 'local', 'model': 'Qwen/Qwen3-TTS-12Hz-1.7B-speaker-checkpoint',
                'synthesizerImplementationSha256': sha(Path(__file__).resolve().parents[1] / 'render_formal_target_language_speech.py'),
                'checkpointValidatorImplementationSha256': sha(Path(__file__).resolve().parents[1] / 'render_multilingual_voice_demos.py'),
                'settings': {'seed': args.seed, 'device': args.device, 'dtype': 'bfloat16',
                             'attention': args.attention}, 'workerSha256': sha(__file__)}
    root = args.out.resolve()
    with output_lock(root):
        bind_run(root, identity)
        receipts, model, load_seconds = [], None, None
        # Check every existing batch before even loading a model.
        for index, start in enumerate(range(0, len(groups), 2)):
            selected = groups[start:start + 2]
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
            return final
        for index, start in enumerate(range(0, len(groups), 2)):
            if receipts[index] is not None:
                continue
            if model is None:
                if factory is None:
                    from scripts.render_formal_target_language_speech import QwenSynthesizer
                    factory = QwenSynthesizer
                began = time.perf_counter()
                model = factory(checkpoint, device=args.device, dtype='bfloat16', attention=args.attention)
                synchronize(model)
                load_seconds = time.perf_counter() - began
            selected = groups[start:start + 2]
            attempt = begin_batch(root, index, identity, selected)
            synchronize(model); began = time.perf_counter()
            values = model.batch([{'identity': row, 'text': row['text'], 'language': 'Chinese',
                                  'speaker': voice['speakerKey'], 'instruct': None} for row in selected],
                                 seed=args.seed + index)
            synchronize(model); elapsed = time.perf_counter() - began
            require(len(values) == len(selected), 'tts_output_cardinality_changed')
            outputs = []
            for expected, value in zip(selected, values):
                require(value.get('identity') == expected, 'tts_output_identity_changed')
                outputs.append(writer(root, expected, value['wave'], value['sampleRate']))
            receipt = {'schemaVersion': 'fixed-clip-local-tts-batch-v1', **FLAGS,
                       'runIdentitySha256': digest(identity), 'batchIndex': index,
                       'callId': attempt['callId'], 'backend': 'local', 'model': identity['model'],
                       'startedAt': attempt['startedAt'], 'completedAt': datetime.now(timezone.utc).isoformat(),
                       'status': 'completed_diagnostic', 'inputs': selected, 'outputs': outputs,
                       'inferenceSeconds': elapsed, 'timingScope': 'batch_including_gpu_synchronization',
                       'usage': dict(UNKNOWN_USAGE)}
            finish_batch(root, index, receipt); receipts[index] = receipt
            print(json.dumps({'stage': 'tts', 'batchIndex': index, 'completedGroups': sum(len(r['outputs']) for r in receipts if r)}), flush=True)
        # Revalidate live input/voice identities before publishing a final manifest.
        require(sha(args.evidence) == identity['evidenceSha256'] and sha(args.media) == MEDIA_SHA,
                'input_changed_during_tts')
        _, current_voice = speaker_context(args.registry, args.checkpoint_map)
        require(current_voice == voice, 'voice_changed_during_tts')
        manifest = {**identity, 'status': 'completed_diagnostic', 'modelLoadSeconds': load_seconds,
                    'processWallSeconds': time.perf_counter() - process_started,
                    'processWallScope': 'this_invocation_including_validation_load_and_io',
                    'inferenceSeconds': sum(r['inferenceSeconds'] for r in receipts),
                    'usage': dict(UNKNOWN_USAGE), 'groups': [row for r in receipts for row in r['outputs']],
                    'batchReceipts': [{'path': batch_paths(root, i)[1].name,
                                       'sha256': sha(batch_paths(root, i)[1])} for i in range(len(receipts))]}
        save(root / 'manifest.json', manifest)
        return manifest


class LocalASR:
    def __init__(self, path, *, device):
        import torch
        from qwen_asr import Qwen3ASRModel
        self.torch = torch
        self.model = Qwen3ASRModel.from_pretrained(str(path), dtype=torch.bfloat16,
            device_map=device, max_inference_batch_size=4, max_new_tokens=2048)

    def batch(self, paths):
        import soundfile as sf
        began = time.perf_counter()
        audio = [sf.read(str(path), dtype='float32') for path in paths]
        self.decode_seconds = time.perf_counter() - began
        require(all(w.ndim == 1 for w, _ in audio), 'asr_requires_mono_audio')
        synchronize(self); began = time.perf_counter()
        result = self.model.transcribe(audio=audio, language=['Chinese'] * len(paths))
        synchronize(self); self.inference_seconds = time.perf_counter() - began
        return result


def back_asr(args, *, factory=LocalASR):
    process_started = time.perf_counter()
    source = read(args.tts_manifest)
    require(source.get('schemaVersion') == 'fixed-clip-local-tts-run-v1' and
            source.get('status') == 'completed_diagnostic' and
            all(source.get(k) == v for k, v in FLAGS.items()) and
            source.get('mediaSha256') == MEDIA_SHA and source.get('sourceUnitCount') == 39 and
            source.get('groupCount') == 13 and source.get('batchSize') == 2, 'tts_manifest_not_fixed_diagnostic')
    groups = source.get('groups', [])
    require(len(groups) == 13 and [r.get('groupId') for r in groups] ==
            [f'fresh-g{i:03d}' for i in range(1, 14)], 'asr_fixed_group_coverage_changed')
    for index, row in enumerate(groups):
        require(row.get('sourceUnitIds') == [f'fresh-diagnostic-u{i:03d}' for i in range(index * 3 + 1, index * 3 + 4)] and
                isinstance(row.get('text'), str) and row['text'].strip() and
                row.get('textSha256') == hashlib.sha256(row['text'].encode()).hexdigest(), 'asr_text_identity_changed')
        safe_audio(args.tts_manifest.parent, row)
    for row in source.get('batchReceipts', []):
        path = (args.tts_manifest.parent / row['path']).resolve()
        require(path.is_relative_to(args.tts_manifest.parent.resolve()) and sha(path) == row['sha256'],
                'tts_batch_receipt_changed')
    require(len(source.get('batchReceipts', [])) == 7, 'tts_batch_receipts_missing')
    tree = model_tree(args.model_path)
    offline()
    identity = {'schemaVersion': 'fixed-clip-local-asr-run-v1', **FLAGS,
                'mediaSha256': MEDIA_SHA, 'sourceUnitCount': 39, 'groupCount': 13,
                'ttsManifestSha256': sha(args.tts_manifest), 'modelTreeSha256': tree['sha256'],
                'batchSize': 4, 'backend': 'local', 'model': 'Qwen/Qwen3-ASR-0.6B', 'device': args.device, 'workerSha256': sha(__file__)}
    root = args.out.resolve()
    with output_lock(root):
        bind_run(root, identity)
        receipts, model, load_seconds = [], None, None
        for index, start in enumerate(range(0, len(groups), 4)):
            selected = groups[start:start + 4]
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
            return final
        for index, start in enumerate(range(0, len(groups), 4)):
            if receipts[index] is not None:
                continue
            if model is None:
                began = time.perf_counter()
                model = factory(args.model_path.resolve(), device=args.device)
                synchronize(model); load_seconds = time.perf_counter() - began
            selected = groups[start:start + 4]
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
        report = {**identity, 'status': 'completed_diagnostic', 'modelLoadSeconds': load_seconds,
                  'processWallSeconds': time.perf_counter() - process_started,
                  'processWallScope': 'this_invocation_including_validation_load_and_io',
                  'inferenceSeconds': sum(r['inferenceSeconds'] for r in receipts),
                  'usage': dict(UNKNOWN_USAGE), 'groups': [row for r in receipts for row in r['outputs']],
                  'batchReceipts': [{'path': batch_paths(root, i)[1].name,
                                     'sha256': sha(batch_paths(root, i)[1])} for i in range(len(receipts))]}
        save(root / 'manifest.json', report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='stage', required=True)
    tts = commands.add_parser('tts')
    for name in ('evidence', 'media', 'registry', 'checkpoint-map'):
        tts.add_argument('--' + name, type=Path, required=True)
    tts.add_argument('--seed', type=int, default=42)
    tts.add_argument('--attention', default='sdpa')
    asr = commands.add_parser('asr')
    asr.add_argument('--tts-manifest', type=Path, required=True)
    asr.add_argument('--model-path', type=Path, required=True)
    for command in (tts, asr):
        command.add_argument('--out', type=Path, required=True)
        command.add_argument('--device', default='cuda:0')
    args = parser.parse_args()
    result = render_tts(args) if args.stage == 'tts' else back_asr(args)
    print(json.dumps({'status': result['status'], 'groups': len(result['groups']), **FLAGS}))


if __name__ == '__main__':
    main()

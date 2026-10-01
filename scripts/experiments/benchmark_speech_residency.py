#!/usr/bin/env python3
"""Compare four fresh Spark speech workers with one resident batch (offline cache).

Default prepares frozen inputs only. --run explicitly permits GPU execution.
No retries or automatic fallback; a started/unknown attempt requires reconciliation.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / 'experiments/sermon-dubbing-poc'
sys.path.insert(0, str(LEGACY))
import spark_speech as speech

DEFAULT_OUT = ROOT / 'artifacts/local-production-acceptance-20261001/speech-residency'
IMAGE = 'nvcr.io/nvidia/pytorch:26.06-py3'
RUNTIME = '/home/achillesjing/sermon-speech-runtime'

# Instrument a benchmark-only wrapper around the unchanged production execute().
# The original worker source remains the code/provenance identity of its results.
REMOTE_WRAPPER = r'''
import sys, time, json, hashlib, contextlib
started = time.perf_counter()
source = sys.argv[1]
namespace = {'__name__': 'benchmark_worker', '__file__': '/benchmark/spark_speech_worker.py'}
exec(compile(source, namespace['__file__'], 'exec'), namespace)
request = json.load(sys.stdin)
stats = {'importSeconds': 0., 'inputDecodeSeconds': 0., 'snapshotResolutionSeconds': 0.,
         'modelHashSeconds': 0., 'modelLoadSeconds': 0., 'inferenceSeconds': [],
         'modelLoadCount': 0, 'snapshotResolutionCount': 0}
phase = time.perf_counter()
with contextlib.redirect_stdout(sys.stderr):
    import torch, soundfile, huggingface_hub, qwen_asr, numpy
stats['importSeconds'] = time.perf_counter() - phase
original_read = soundfile.read
original_snapshot = huggingface_hub.snapshot_download
original_load = qwen_asr.Qwen3ASRModel.from_pretrained
hash_start = None

def read(*args, **kwargs):
    phase = time.perf_counter()
    try: return original_read(*args, **kwargs)
    finally: stats['inputDecodeSeconds'] += time.perf_counter() - phase

def snapshot(*args, **kwargs):
    global hash_start
    phase = time.perf_counter()
    try: return original_snapshot(*args, **kwargs)
    finally:
        stats['snapshotResolutionSeconds'] += time.perf_counter() - phase
        stats['snapshotResolutionCount'] += 1
        hash_start = time.perf_counter()

def load(*args, **kwargs):
    stats['modelHashSeconds'] += time.perf_counter() - hash_start
    phase = time.perf_counter()
    model = original_load(*args, **kwargs)
    stats['modelLoadSeconds'] += time.perf_counter() - phase
    stats['modelLoadCount'] += 1
    original_transcribe = model.transcribe
    def transcribe(*args, **kwargs):
        phase = time.perf_counter()
        try:
            value = original_transcribe(*args, **kwargs)
            if torch.cuda.is_available(): torch.cuda.synchronize()
            return value
        finally: stats['inferenceSeconds'].append(time.perf_counter() - phase)
    model.transcribe = transcribe
    return model
soundfile.read = read
huggingface_hub.snapshot_download = snapshot
qwen_asr.Qwen3ASRModel.from_pretrained = load

def emit(result):
    result['benchmarkTiming'] = dict(stats, processElapsedSeconds=time.perf_counter() - started)
    print(json.dumps(result, ensure_ascii=False), flush=True)
namespace['execute'](request, emit)
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())
        handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def prepare(source, out):
    manifest_path = out / 'inputs.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['sourceSha256'] != sha(source):
            raise ValueError('Frozen benchmark source changed')
        verify_manifest(manifest)
        return manifest
    out.mkdir(parents=True, exist_ok=True)
    inputs = []
    with wave.open(str(source), 'rb') as handle:
        frames, rate = handle.getnframes(), handle.getframerate()
        channels, width = handle.getnchannels(), handle.getsampwidth()
        if handle.getcomptype() != 'NONE' or frames <= 0 or channels != 1 or width != 2:
            raise ValueError('Expected an uncompressed mono PCM16 benchmark source')
        for index in range(4):
            begin, end = frames * index // 4, frames * (index + 1) // 4
            handle.setpos(begin)
            raw = handle.readframes(end - begin)
            path = out / 'inputs' / f'unit-{index:04d}.wav'
            path.parent.mkdir(exist_ok=True)
            if path.exists():
                raise ValueError('Preserve partial preparation inputs; choose a fresh output directory')
            with wave.open(str(path), 'wb') as clipped:
                clipped.setnchannels(channels); clipped.setsampwidth(width); clipped.setframerate(rate)
                clipped.writeframes(raw)
            inputs.append({'unitId': index, 'path': str(path), 'sha256': sha(path),
                'startFrame': begin, 'endFrame': end, 'durationSeconds': (end - begin) / rate,
                'sampleRate': rate, 'channels': channels, 'sampleWidthBytes': width})
    manifest = {'schemaVersion': 'speech-residency-inputs-v1', 'sourcePath': str(source),
        'sourceSha256': sha(source), 'sourceDurationSeconds': frames / rate, 'inputs': inputs,
        'model': speech.ASR[0], 'revision': speech.ASR[1], 'language': 'English',
        'maxTokens': 2048, 'workerSha256': sha(LEGACY / 'spark_speech_worker.py'),
        'clientSha256': sha(LEGACY / 'spark_speech.py'),
        'wrapperSha256': hashlib.sha256(REMOTE_WRAPPER.encode()).hexdigest(),
        'policy': 'same four frozen slices, scalar inference, fresh process per dispatch, no model-result reuse'}
    write(manifest_path, manifest)
    (out / 'benchmark-wrapper.py').write_text(REMOTE_WRAPPER)
    return manifest


def verify_manifest(manifest):
    if len(manifest['inputs']) != 4 or any(sha(row['path']) != row['sha256'] for row in manifest['inputs']):
        raise ValueError('Frozen speech inputs changed')
    if manifest['workerSha256'] != sha(LEGACY / 'spark_speech_worker.py') or manifest['clientSha256'] != sha(LEGACY / 'spark_speech.py'):
        raise ValueError('Production code changed after preparation')
    if manifest['wrapperSha256'] != hashlib.sha256(REMOTE_WRAPPER.encode()).hexdigest():
        raise ValueError('Benchmark wrapper changed after preparation')


def command(host, name, source):
    docker = ['docker', 'run', '--rm', '--name', name, '-i', '--gpus', 'all', '--memory', '12g',
        '--memory-swap', '12g', '--cpus', '4', '--network', 'none', '--entrypoint', '/runtime/venv/bin/python',
        '-v', RUNTIME + ':/runtime:ro', '-e', 'HF_HOME=/runtime/model-cache',
        '-e', 'HF_HUB_OFFLINE=1', '-e', 'TRANSFORMERS_OFFLINE=1', IMAGE, '-c', REMOTE_WRAPPER, source]
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=20',
            '-o', 'ServerAliveCountMax=2', host, shlex.join(docker)]


def dispatch(out, host, label, request, source, expected):
    name = 'speech-residency-' + hashlib.sha256((sha(out / 'inputs.json') + label).encode()).hexdigest()[:20]
    folder = out / label; folder.mkdir(exist_ok=True)
    marker = folder / 'dispatch.json'
    if marker.exists():
        raise RuntimeError(f'Preserve prior benchmark attempt; never replay automatically: {marker}')
    argv = command(host, name, source)
    state = {'status': 'started', 'label': label, 'containerName': name,
             'unitIds': [row['unitId'] for row in expected], 'startedAtUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    write(marker, state)
    phase = time.perf_counter()
    payload = json.dumps(request)
    request_prepare = time.perf_counter() - phase
    phase = time.perf_counter()
    try:
        result = subprocess.run(argv, input=payload, capture_output=True, text=True, timeout=240, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        for stream in ('stdout', 'stderr'):
            value = getattr(exc, stream, None) or ''
            if isinstance(value, bytes): value = value.decode(errors='replace')
            (folder / f'{stream}.log').write_text(value)
        write(marker, {**state, 'status': 'unknown', 'errorType': type(exc).__name__, 'dispatchSeconds': time.perf_counter() - phase})
        raise
    elapsed = time.perf_counter() - phase
    (folder / 'stdout.log').write_text(result.stdout); (folder / 'stderr.log').write_text(result.stderr)
    if result.returncode:
        write(marker, {**state, 'status': 'unknown' if result.returncode == 255 else 'confirmed_terminal_failure',
                       'returncode': result.returncode, 'dispatchSeconds': elapsed})
        raise subprocess.CalledProcessError(result.returncode, argv, result.stdout, result.stderr)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    unit_rows = rows[:-1] if 'schemaVersion' in request else rows
    model = speech.SparkModel(speech.ASR)
    if len(unit_rows) != len(expected):
        raise ValueError('Benchmark result cardinality differs')
    transcripts, receipts = [], []
    for output, bound in zip(unit_rows, expected):
        if 'schemaVersion' in request and output.get('unitId') != bound['unitId']:
            raise ValueError('Benchmark unit result order differs')
        output_result, receipt = model._response(output, bound['identity'])
        if not output_result.text.strip():
            raise ValueError('Benchmark ASR returned empty speech')
        transcripts.append(output_result.text); receipts.append(receipt)
    if 'schemaVersion' in request and rows[-1] != {
            'event': 'batch_complete', 'batchSha256': request['batchSha256'], 'count': len(expected),
            'benchmarkTiming': rows[-1].get('benchmarkTiming')}:
        raise ValueError('Benchmark batch completion differs')
    timing = unit_rows[-1]['benchmarkTiming']
    if timing['modelLoadCount'] != 1 or timing['snapshotResolutionCount'] != 1:
        raise ValueError('Worker was not resident exactly once per dispatch')
    report = {'label': label, 'containerName': name, 'unitIds': state['unitIds'],
              'requestPrepareSeconds': request_prepare, 'dispatchSeconds': elapsed,
              'wallSecondsIncludingRequestPrepare': request_prepare + elapsed,
              'requestBytes': len(payload.encode()), 'responseBytes': len(result.stdout.encode()),
              'returncode': result.returncode, 'timing': timing, 'transcripts': transcripts,
              'receipts': receipts, 'resultValidated': True}
    write(folder / 'report.json', report)
    write(marker, {**state, 'status': 'complete', 'dispatchSeconds': elapsed})
    return report


def run(manifest, out, host, order, condition):
    verify_manifest(manifest)
    requests = [{'unitId': row['unitId'], 'path': row['path'], 'language': 'English', 'max_tokens': 2048, 'locale': 'en'}
                for row in manifest['inputs']]
    source = (LEGACY / 'spark_speech_worker.py').read_text()
    frozen = speech.freeze_requests(requests, speech.ASR)
    batch_request = {'schemaVersion': speech.BATCH_SCHEMA, 'batchSha256': speech.batch_sha256(frozen), 'requests': frozen}
    singles = []
    if order == 'batch-first':
        batch = dispatch(out, host, 'batch-4', batch_request, source, frozen)
    for index, row in enumerate(frozen):
        singles.append(dispatch(out, host, f'single-{index}', {key: row[key] for key in ('identity', 'audio')}, source, [row]))
    if order == 'single-first':
        batch = dispatch(out, host, 'batch-4', batch_request, source, frozen)
    single_wall = sum(row['wallSecondsIncludingRequestPrepare'] for row in singles)
    batch_wall = batch['wallSecondsIncludingRequestPrepare']
    single_transcripts = [row['transcripts'][0] for row in singles]
    summary = {'schemaVersion': 'speech-residency-acceptance-v1', 'status': 'completed',
        'condition': condition, 'checkpointTransferConcurrent': condition == 'pilot_under_checkpoint_transfer',
        'inputManifestSha256': sha(out / 'inputs.json'), 'model': list(speech.ASR),
        'scope': 'four frozen English audio units, production worker execute with benchmark-only timing wrapper',
        'order': (['single-0', 'single-1', 'single-2', 'single-3', 'batch-4'] if order == 'single-first'
                  else ['batch-4', 'single-0', 'single-1', 'single-2', 'single-3']),
        'single4WallSeconds': single_wall, 'batch4WallSeconds': batch_wall,
        'speedup': single_wall / batch_wall, 'wallReductionPercent': (1 - batch_wall / single_wall) * 100,
        'single4ModelLoadCount': sum(row['timing']['modelLoadCount'] for row in singles),
        'batch4ModelLoadCount': batch['timing']['modelLoadCount'],
        'single4ModelHashSeconds': sum(row['timing']['modelHashSeconds'] for row in singles),
        'batch4ModelHashSeconds': batch['timing']['modelHashSeconds'],
        'single4ModelLoadSeconds': sum(row['timing']['modelLoadSeconds'] for row in singles),
        'batch4ModelLoadSeconds': batch['timing']['modelLoadSeconds'],
        'single4InferenceSeconds': sum(sum(row['timing']['inferenceSeconds']) for row in singles),
        'batch4InferenceSeconds': sum(batch['timing']['inferenceSeconds']),
        'identitiesValidated': True, 'orderedCoverage': 4, 'sameTranscripts': single_transcripts == batch['transcripts'],
        'singleTranscripts': single_transcripts, 'batchTranscripts': batch['transcripts'],
        'perDispatch': [{'label': row['label'], 'wallSeconds': row['wallSecondsIncludingRequestPrepare'],
                         'timing': row['timing']} for row in singles + [batch]],
        'limits': {'dockerMemoryGiB': 12, 'dockerCpus': 4, 'offline': True, 'noRetries': True},
        'limitations': (['pilot under concurrent 3.6GiB Spark-to-Mac checkpoint SCP; not a quiet acceptance result']
                        if condition == 'pilot_under_checkpoint_transfer' else []) +
                      ['one paired measurement; fresh processes but filesystem cache not cleared',
                       'fixed order can favor later file-cache reads; no formal checkpoint, Korean/Spanish or weekly SLA claim',
                       'worker retains scalar per-unit inference; measures residency and fewer dispatches, not tensor batching',
                       'wall includes JSON/stdin upload, SSH, Docker, imports, hashes, load, inference and result return; no separate SCP',
                       'wrapper adds CUDA synchronize and instrumentation; unchanged production worker source is executed']}
    write(out / 'summary.json', summary)
    print(json.dumps({key: summary[key] for key in ('status', 'single4WallSeconds', 'batch4WallSeconds', 'speedup', 'sameTranscripts')}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--host', default='achillesjing@192.168.1.152')
    parser.add_argument('--condition', choices=('quiet', 'pilot_under_checkpoint_transfer'), default='quiet')
    parser.add_argument('--order', choices=('single-first', 'batch-first'), default='single-first')
    parser.add_argument('--run', action='store_true', help='Explicitly start the five GPU worker processes; no retries')
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(DEFAULT_OUT.resolve()):
        raise ValueError('Benchmark writes must stay under the isolated speech-residency artifacts')
    manifest = prepare(args.source.resolve(), out)
    if args.run:
        run(manifest, out, args.host, args.order, args.condition)
    else:
        print(json.dumps({'status': 'prepared_only_no_gpu', 'inputs': len(manifest['inputs']),
                          'audioSeconds': sum(row['durationSeconds'] for row in manifest['inputs']), 'manifest': str(out / 'inputs.json')}))


if __name__ == '__main__':
    main()

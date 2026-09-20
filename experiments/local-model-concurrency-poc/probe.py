#!/usr/bin/env python3
"""Bounded, offline TTS/MPS + ASR/MLX residency and inference experiment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.sermon_model_resources import local_model_slot, memory_snapshot

ASR_MODEL = 'mlx-community/Qwen3-ASR-0.6B-8bit'
ASR_REVISION = '89e96d92ba34aca20b3e29fb10cc284097d1219f'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def worker(args):
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    started = time.time()
    with local_model_slot(timeout=600) as slot:
        loading = time.time()
        if args.worker == 'tts':
            import torch
            import soundfile as sf
            import numpy as np
            from qwen_tts import Qwen3TTSModel
            job = json.loads(args.job.read_text())
            if len(job['units']) != 1 or not job.get('smokeOnly'):
                raise ValueError('Only frozen one-unit smoke jobs are accepted')
            if digest(args.checkpoint / 'model.safetensors') != job['voice']['checkpointSha256']:
                raise ValueError('Checkpoint differs from frozen job')
            if not torch.backends.mps.is_available():
                raise RuntimeError('MPS is unavailable; no fallback is permitted')
            model = Qwen3TTSModel.from_pretrained(str(args.checkpoint), device_map='mps', dtype=torch.float32, attn_implementation='sdpa')
            torch.mps.synchronize()
            def gpu_memory():
                return {'allocatedBytes': torch.mps.current_allocated_memory(), 'driverBytes': torch.mps.driver_allocated_memory()}
            identity = {'model': job['voice']['model'], 'checkpointSha256': job['voice']['checkpointSha256'], 'device': 'mps', 'dtype': 'float32'}
        else:
            from huggingface_hub import snapshot_download
            from mlx_audio.stt.utils import load_model
            import mlx.core as mx
            snapshot = snapshot_download(repo_id=ASR_MODEL, revision=ASR_REVISION, local_files_only=True)
            model = load_model(snapshot)
            mx.synchronize()
            def gpu_memory():
                return {'allocatedBytes': mx.get_active_memory(), 'peakBytes': mx.get_peak_memory(), 'cacheBytes': mx.get_cache_memory()}
            identity = {'model': ASR_MODEL, 'revision': ASR_REVISION, 'device': 'mlx', 'quantization': '8bit'}
        loaded = time.time()
        ready = {'pid': os.getpid(), 'startedAtEpoch': started, 'loadStartedAtEpoch': loading, 'readyAtEpoch': loaded,
                 'loadSeconds': loaded - loading, 'modelIdentity': identity, 'loadedDeviceMemory': gpu_memory(), 'slot': slot}
        write(out / 'ready.json', ready)
        deadline = time.monotonic() + 180
        while not (out.parent / 'release').exists():
            if time.monotonic() > deadline:
                raise TimeoutError('Inference barrier was not released')
            time.sleep(.05)
        inference = time.time()
        if args.worker == 'tts':
            torch.manual_seed(42)
            unit = job['units'][0]
            waves, rate = model.generate_custom_voice(text=[unit.get('spokenText', unit['text'])], language=['Chinese'],
                speaker=[job['voice']['speakerKey']], temperature=.7, repetition_penalty=1.05, max_new_tokens=768)
            torch.mps.synchronize()
            wave = np.asarray(waves[0], dtype=np.float32).reshape(-1)
            if not np.isfinite(wave).all() or not .3 < len(wave) / rate < 20:
                raise ValueError('Invalid TTS smoke waveform')
            sf.write(out / 'sample.wav', wave, rate)
            output = {'audioSha256': digest(out / 'sample.wav'), 'durationSeconds': len(wave) / rate, 'sampleRate': rate, 'humanReview': 'pending'}
        else:
            result = model.generate(str(args.audio), language='English', max_tokens=2048)
            mx.synchronize()
            if not result.text.strip():
                raise ValueError('ASR returned empty text')
            (out / 'transcript.txt').write_text(result.text)
            output = {'transcriptSha256': digest(out / 'transcript.txt'), 'characters': len(result.text), 'humanReview': 'pending'}
        ended = time.time()
        write(out / 'result.json', {**ready, 'inferenceStartedAtEpoch': inference, 'inferenceEndedAtEpoch': ended,
            'inferenceSeconds': ended - inference, 'processSeconds': ended - started,
            'peakRssBytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'finalDeviceMemory': gpu_memory(), 'output': output})


def run_group(args, folder, names):
    folder.mkdir(parents=True)
    children = []
    started = time.time()
    samples = []
    deadline = time.monotonic() + 900
    try:
        for name in names:
            python = args.tts_python if name == 'tts' else args.asr_python
            command = [str(python), str(Path(__file__).resolve()), '--worker', name, '--out', str(folder / name),
                       '--job', str(args.job), '--checkpoint', str(args.checkpoint), '--audio', str(args.audio)]
            stream = (folder / (name + '.log')).open('w')
            environment = {**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false', 'PYTHONUNBUFFERED': '1'}
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            children.append((name, process, stream))
        released = False
        while True:
            samples.append({'atEpoch': time.time(), 'memory': memory_snapshot()})
            for name, process, _ in children:
                if process.poll() is not None and process.returncode != 0:
                    raise RuntimeError(name + ' worker failed; inspect its preserved log')
            if not released and all((folder / name / 'ready.json').exists() for name in names):
                (folder / 'release').write_text(str(time.time()))
                released = True
            if all(process.poll() is not None for _, process, _ in children):
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Probe deadline exceeded')
            time.sleep(.5)
        results = {name: json.loads((folder / name / 'result.json').read_text()) for name in names}
        overlap = max(0, min(r['inferenceEndedAtEpoch'] for r in results.values()) - max(r['inferenceStartedAtEpoch'] for r in results.values())) if len(names) > 1 else 0
        report = {'wallSeconds': time.time() - started, 'inferenceOverlapSeconds': overlap, 'models': results,
                  'systemSamples': samples, 'approvalGranted': False, 'publicationPerformed': False}
        write(folder / 'report.json', report)
        return report
    finally:
        for _, process, stream in children:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            stream.close()
        write(folder / 'system-samples.json', samples)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--worker', choices=['tts', 'asr'])
    for name in ('out', 'job', 'checkpoint', 'audio'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--tts-python', type=Path)
    p.add_argument('--asr-python', type=Path)
    args = p.parse_args()
    if args.worker:
        return worker(args)
    args.out.mkdir(parents=True, exist_ok=False)
    identity = {'jobSha256': digest(args.job), 'audioSha256': digest(args.audio), 'scriptSha256': digest(__file__), 'scope': 'runtime_probe_not_production', 'order': 'sequential_then_parallel', 'warmFilesystemCacheCaveat': True}
    write(args.out / 'identity.json', identity)
    first = run_group(args, args.out / 'sequential-tts', ['tts'])
    second = run_group(args, args.out / 'sequential-asr', ['asr'])
    parallel = run_group(args, args.out / 'parallel', ['tts', 'asr'])
    if parallel['inferenceOverlapSeconds'] <= 0:
        raise ValueError('No simultaneous model inference was observed')
    sequential_seconds = first['wallSeconds'] + second['wallSeconds']
    write(args.out / 'comparison.json', {**identity, 'sequentialWallSeconds': sequential_seconds,
          'parallelWallSeconds': parallel['wallSeconds'], 'wallSpeedup': sequential_seconds / parallel['wallSeconds'],
          'inferenceOverlapSeconds': parallel['inferenceOverlapSeconds'], 'models': parallel['models'],
          'limitations': ['Single short sample; no whole-sermon throughput claim', 'No quality or human approval claim', 'Order/cache effects are not controlled']})
    print(json.dumps({'out': str(args.out), 'sequentialSeconds': sequential_seconds, 'parallelSeconds': parallel['wallSeconds'], 'overlapSeconds': parallel['inferenceOverlapSeconds']}))


if __name__ == '__main__':
    main()

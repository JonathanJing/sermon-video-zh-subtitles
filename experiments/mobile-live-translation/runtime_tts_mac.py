#!/usr/bin/env python3
"""Bounded local CustomVoice batch/stream diagnostic; never plays audio.

The controller enforces a 90-second wall deadline per child call. The child
imports, loads, generates and synchronizes MLX on its main thread. Raw yields
are preserved: a streaming run that falls through to full-audio output is not
silently repaired and does not receive a qualified RTF.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import selectors
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / 'experiments/mobile-live-translation/artifacts/tts-20260906/mac'
EXPERIMENT = ROOT / 'artifacts/sermon-dubbing/2026-09-05-fluency-poc-v2/experiment.json'
EXPERIMENT_SHA = '2087816e0ba31564d586d8fb82aadc7a6c2ebe124c4bbcbc4d8176b425949268'
MODEL_ID = 'mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit'
REVISION = '41d3337e8b7f2843a75841595fc14e4b9a7a4b96'
SNAPSHOT = Path.home() / '.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit/snapshots' / REVISION
CALL_TIMEOUT_SECONDS = 90
MODES = [('batch', False, 2.0), ('stream-048', True, 0.48), ('stream-100', True, 1.0)]


def sha(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def save_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def event(name: str, **fields) -> None:
    print(json.dumps({'event': name, **fields}, ensure_ascii=False), flush=True)


def fixtures(plan: dict) -> list[dict]:
    sentences = plan['variants']['sentence']
    expected = [(1, 18), (4, 28), (0, 40)]
    result = []
    for index, count in expected:
        text = sentences[index]
        if len(text) != count:
            raise ValueError('frozen sentence length changed')
        result.append({'id': f'sentence-{index:02d}-chars{count}', 'sentenceIndexZeroBased': index,
                       'text': text, 'textSha256': text_sha(text), 'charactersIncludingPunctuation': count,
                       'cjkCharacters': sum('\u3400' <= c <= '\u9fff' for c in text)})
    return result


def worker(output: Path) -> int:
    if sha(EXPERIMENT) != EXPERIMENT_SHA:
        raise ValueError('frozen fluency experiment changed')
    plan = json.loads(EXPERIMENT.read_text())
    if (plan['model'], plan['revision'], plan['temperature'], plan['seed']) != (MODEL_ID, REVISION, 0.7, 42):
        raise ValueError('unexpected frozen generation settings')
    if plan['voice'] != {'type': 'preset', 'name': 'Uncle_Fu', 'speakerClone': False}:
        raise ValueError('this diagnostic only allows the existing preset voice')
    if importlib.metadata.version('mlx-audio') != '0.3.1':
        raise ValueError('this diagnostic requires installed mlx-audio 0.3.1')
    if not SNAPSHOT.is_dir():
        raise FileNotFoundError('pinned local TTS snapshot is not present; no download is allowed')
    chosen = fixtures(plan)
    event('preflight_started')
    package_versions = {name: importlib.metadata.version(name) for name in
                        ['mlx-audio', 'mlx', 'numpy', 'soundfile', 'transformers', 'huggingface-hub']}
    model_files = [{'path': str(path.relative_to(SNAPSHOT)), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                   for path in sorted(SNAPSHOT.rglob('*')) if path.is_file()]
    manifest_sha = text_sha(json.dumps(model_files, sort_keys=True, separators=(',', ':')))
    # All model imports, loading and generation run on this same main thread.
    import mlx.core as mx
    import numpy as np
    import soundfile as sf
    import mlx_audio.tts.models.qwen3_tts.qwen3_tts as qwen_module
    from mlx_audio.tts.utils import load_model
    model_source = Path(qwen_module.__file__)
    load_started = time.perf_counter()
    model = load_model(SNAPSHOT, lazy=False)
    mx.synchronize()
    load_ms = (time.perf_counter() - load_started) * 1000
    if model.config.tts_model_type != 'custom_voice':
        raise ValueError('loaded model is not CustomVoice')
    event('model_ready', modelLoadMs=load_ms)
    identity = {
        'schemaVersion': 'mobile-tts-runtime-diagnostic-v1', 'createdAt': datetime.now(timezone.utc).isoformat(),
        'platform': platform.platform(), 'python': sys.version, 'packages': package_versions,
        'scriptSha256': sha(Path(__file__)), 'modelId': MODEL_ID, 'revision': REVISION,
        'modelSnapshot': str(SNAPSHOT), 'modelFiles': model_files, 'modelManifestSha256': manifest_sha,
        'installedGenerationSource': str(model_source), 'installedGenerationSourceSha256': sha(model_source),
        'modelLoadMs': load_ms, 'modelLoadScope': 'load_model(lazy=False) through mx.synchronize; manifest hashing/imports excluded',
        'experimentPath': str(EXPERIMENT), 'experimentSha256': EXPERIMENT_SHA, 'fixtures': chosen,
        'sourceTranslationStatus': plan['translationStatus'], 'sourceHumanListeningStatus': plan['humanListeningStatus'],
        'voice': plan['voice'], 'language': 'Chinese', 'instruct': plan['instruct'],
        'instructSha256': text_sha(plan['instruct']), 'temperature': 0.7, 'seed': 42,
        'maxTokensArgument': 4096, 'effectiveLimitPolicy': 'min(4096,max(75,target_text_token_count*6)), installed implementation',
        'topK': 50, 'topP': 1.0, 'repetitionPenalty': 1.05,
        'warmups': 1, 'formalCalls': 9, 'callTimeoutSeconds': CALL_TIMEOUT_SECONDS,
        'timingScope': 'same-thread generate_custom_voice through generator exhaustion/close and final sync; first PCM after mx.eval/sync plus CPU float32 copy; audio/hash/file serialization after timed generation',
        'rtfDefinition': 'elapsed seconds / returned audio seconds; inverse of mlx-audio field real_time_factor',
        'modelEosObservable': False, 'releaseEligible': False, 'playbackPerformed': False,
        'hardwareOnlyComparison': False, 'dgxComparisonLimit': 'DGX Base batch entry is a different model/voice path and does not establish equivalent streaming capability',
    }
    save_json(output / 'identity.json', identity)
    records, audio_by_call = [], {}

    def run_one(fixture, mode_name, stream, interval, warmup=False):
        key = ('warmup-' if warmup else '') + mode_name + '-' + fixture['id']
        call_dir = output / key
        call_dir.mkdir()
        mx.random.seed(42)
        mx.synchronize()
        call_started = time.monotonic()
        save_json(output / 'active-call.json', {'callKey': key, 'startedMonotonic': call_started, 'timeoutSeconds': CALL_TIMEOUT_SECONDS})
        event('call_started', callKey=key, startedMonotonic=call_started, warmup=warmup)
        arrays, chunks, error = [], [], None
        first_pcm_ms = None
        exhausted = False
        t0 = time.perf_counter()
        generator = model.generate_custom_voice(
            text=fixture['text'], speaker='Uncle_Fu', language='Chinese', instruct=plan['instruct'],
            temperature=0.7, max_tokens=4096, top_k=50, top_p=1.0, repetition_penalty=1.05,
            verbose=False, stream=stream, streaming_interval=interval,
        )
        try:
            for result in generator:
                yield_ms = (time.perf_counter() - t0) * 1000
                mx.eval(result.audio)
                mx.synchronize()
                array = np.asarray(result.audio, dtype=np.float32).reshape(-1).copy()
                pcm_ready_ms = (time.perf_counter() - t0) * 1000
                if array.size and first_pcm_ms is None:
                    first_pcm_ms = pcm_ready_ms
                arrays.append(array)
                chunks.append({
                    'index': len(chunks), 'yieldArrivalMs': yield_ms, 'pcmReadyMs': pcm_ready_ms,
                    'sampleCount': int(array.size), 'reportedSampleCount': int(result.samples),
                    'sampleRate': int(result.sample_rate), 'tokenCount': int(result.token_count),
                    'is_streaming': bool(result.is_streaming_chunk), 'is_final': bool(result.is_final_chunk),
                    'libraryProcessingTimeSeconds': float(result.processing_time_seconds),
                    'libraryRealTimeFactor': float(result.real_time_factor),
                })
            exhausted = True
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)[:500]}
        finally:
            generator.close()
            mx.synchronize()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        event('call_generation_finished', callKey=key, elapsedMs=elapsed_ms, chunks=len(chunks), error=error)
        rates = {c['sampleRate'] for c in chunks}
        if len(rates) != 1:
            raise ValueError('empty or mixed-rate TTS output')
        rate = next(iter(rates))
        concatenated = np.concatenate(arrays)
        if concatenated.size > rate * 120:
            raise ValueError('diagnostic output exceeded bounded 120-second retention size')
        finite = bool(np.isfinite(concatenated).all())
        saw_stream = False
        fallback_indices = []
        for c, array in zip(chunks, arrays):
            if saw_stream and not c['is_streaming']:
                fallback_indices.append(c['index'])
            saw_stream = saw_stream or c['is_streaming']
            pcm = array.astype('<f4', copy=False).tobytes()
            chunk_path = call_dir / f"chunk-{c['index']:03d}.f32le"
            chunk_path.write_bytes(pcm)
            c['pcmFloat32LeSha256'] = hashlib.sha256(pcm).hexdigest()
            c['pcmPath'] = str(chunk_path.relative_to(output))
            c['finite'] = bool(np.isfinite(array).all())
            c['durationSeconds'] = c['sampleCount'] / rate
        raw_pcm = concatenated.astype('<f4', copy=False).tobytes()
        pcm_path = call_dir / 'returned-concatenation.f32le'
        pcm_path.write_bytes(raw_pcm)
        wav_path = call_dir / 'returned-concatenation.wav'
        if finite:
            sf.write(wav_path, concatenated, rate, subtype='FLOAT')
            decoded, decoded_rate = sf.read(wav_path, dtype='float32')
            if decoded_rate != rate or not np.array_equal(decoded, concatenated):
                raise ValueError('saved WAV differs from retained raw PCM')
        duration = concatenated.size / rate
        code_tokens = chunks[-1]['tokenCount'] if fallback_indices else sum(c['tokenCount'] for c in chunks)
        text_tokens = len(model.tokenizer.encode(fixture['text']))
        effective_limit = min(4096, max(75, text_tokens * 6))
        final_markers = sum(c['is_final'] for c in chunks)
        qualified = (error is None and exhausted and finite and duration > 0 and not fallback_indices
                     and code_tokens < effective_limit and (not stream or final_markers == 1))
        record = {
            'callKey': key, 'fixture': fixture, 'warmup': warmup, 'mode': mode_name,
            'streamRequested': stream, 'streamingIntervalSeconds': interval if stream else None,
            'effectiveChunkCodecTokens': max(1, int(interval * 12.5)) if stream else None,
            'effectiveChunkSeconds': max(1, int(interval * 12.5)) / 12.5 if stream else None,
            'generatorExhausted': exhausted, 'error': error, 'finitePcm': finite,
            'terminationEvidence': 'generator exhausted; API does not expose codec EOS',
            'textTokens': text_tokens, 'effectiveMaxCodecTokens': effective_limit,
            'observedCodecTokens': code_tokens, 'atEffectiveTokenLimit': code_tokens >= effective_limit,
            'firstCpuPcmMs': first_pcm_ms, 'fullCompletionMs': elapsed_ms,
            'sampleRate': rate, 'returnedSampleCount': int(concatenated.size),
            'returnedConcatenationDurationSeconds': duration,
            'rtfRawReturnedConcatenation': elapsed_ms / 1000 / duration if duration else None,
            'qualifiedRtf': elapsed_ms / 1000 / duration if qualified else None,
            'qualifiedIncrementalAudio': qualified,
            'streamingChunkCount': sum(c['is_streaming'] for c in chunks), 'finalMarkerCount': final_markers,
            'nonStreamingFallbackAfterStreaming': bool(fallback_indices), 'fallbackChunkIndices': fallback_indices,
            'chunks': chunks, 'rawPcmSha256': hashlib.sha256(raw_pcm).hexdigest(),
            'rawPcmPath': str(pcm_path.relative_to(output)),
            'wavPath': str(wav_path.relative_to(output)) if finite else None,
            'wavSha256': sha(wav_path) if finite else None,
            'audioWasDeduplicated': False, 'audioWasNormalized': False, 'playbackPerformed': False,
            'consumerScope': 'Only PCM materialization/copy and in-memory metadata during generation; disk/hash/WAV serialization after timed completion',
        }
        save_json(call_dir / 'result.json', record)
        with (output / ('warmups.jsonl' if warmup else 'results.jsonl')).open('a') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        records.append(record)
        audio_by_call[key] = arrays
        event('call_saved', callKey=key, firstCpuPcmMs=first_pcm_ms, fullCompletionMs=elapsed_ms,
              returnedSeconds=duration, finalMarkers=final_markers, fullFallback=bool(fallback_indices),
              qualifiedIncrementalAudio=qualified)

    run_one(chosen[0], *MODES[0], warmup=True)
    for mode_name, stream, interval in MODES:
        for fixture in chosen:
            run_one(fixture, mode_name, stream, interval)
    comparisons = []
    for record in records:
        if record['warmup'] or not record['streamRequested']:
            continue
        fixture_id = record['fixture']['id']
        batch_key = 'batch-' + fixture_id
        batch = np.concatenate(audio_by_call[batch_key])
        returned = np.concatenate(audio_by_call[record['callKey']])
        fallbacks = [audio_by_call[record['callKey']][i] for i in record['fallbackChunkIndices']]
        comparisons.append({
            'callKey': record['callKey'], 'batchCallKey': batch_key,
            'batchSampleCount': int(batch.size), 'returnedSampleCount': int(returned.size),
            'returnedToBatchSampleRatio': float(returned.size / batch.size),
            'exactBatchPcm': bool(np.array_equal(returned, batch)),
            'fallbackChunksEqualEntireBatch': [bool(np.array_equal(a, batch)) for a in fallbacks],
            'fallbackChunkSampleCounts': [int(a.size) for a in fallbacks],
            'comparisonLimit': 'Same seed does not guarantee equivalent codec sampling across decoding schedules; chunk decoder context can change PCM. No acoustic quality review.'
        })
    formal = [r for r in records if not r['warmup']]
    summary = {
        'schemaVersion': 'mobile-tts-runtime-summary-v1', 'callsCompleted': len(formal), 'warmupsCompleted': 1,
        'allFormalGeneratorsExhausted': all(r['generatorExhausted'] and r['error'] is None for r in formal),
        'allFormalPcmFinite': all(r['finitePcm'] for r in formal),
        'qualifiedFormalCalls': sum(r['qualifiedIncrementalAudio'] for r in formal),
        'fallbackAffectedCalls': [r['callKey'] for r in formal if r['nonStreamingFallbackAfterStreaming']],
        'perCall': [{k: r[k] for k in ['callKey', 'mode', 'firstCpuPcmMs', 'fullCompletionMs',
                   'returnedConcatenationDurationSeconds', 'qualifiedRtf', 'qualifiedIncrementalAudio',
                   'streamingChunkCount', 'finalMarkerCount', 'nonStreamingFallbackAfterStreaming']} for r in formal],
        'batchComparisons': comparisons,
        'staticRisk': 'Installed _generate_with_instruct returns after streaming only when remaining tokens exist. Exact chunk exhaustion falls through to non-streaming full decode/yield.',
        'sampleLimit': 'Three existing machine-translated sentences; one call per text/mode; warmup excluded; no p95/SLA or listening-quality conclusion.',
        'rtfLimit': 'RTF is null for unqualified incremental output; the raw ratio can be misleading when duplicate full audio is concatenated.',
        'modelComparisonLimit': 'Mac CustomVoice preset and DGX Base batch are different model/voice paths; no pure-hardware or equivalent-streaming claim.',
        'releaseEligible': False, 'playbackPerformed': False,
        'identitySha256': sha(output / 'identity.json'), 'resultsSha256': sha(output / 'results.jsonl'),
        'warmupsSha256': sha(output / 'warmups.jsonl'),
    }
    save_json(output / 'summary.json', summary)
    event('experiment_completed', formalCalls=len(formal), qualifiedCalls=summary['qualifiedFormalCalls'],
          fallbackAffectedCalls=summary['fallbackAffectedCalls'])
    return 0 if summary['allFormalGeneratorsExhausted'] and summary['allFormalPcmFinite'] else 1


def controller(output: Path) -> int:
    if output.exists():
        # A documented pending preflight is preparation, not earlier execution.
        allowed = {'preflight.json', 'PENDING.zh.md'}
        if not {p.name for p in output.iterdir()}.issubset(allowed) or not (output / 'preflight.json').is_file():
            raise FileExistsError('output contains execution evidence; earlier results are never overwritten')
        preflight = json.loads((output / 'preflight.json').read_text())
        if preflight.get('status') != 'pending_active_live_capture' or preflight.get('experimentSha256') != EXPERIMENT_SHA:
            raise ValueError('unrecognized pending preflight')
    # One read at explicit invocation time; never poll, stop or change the service.
    try:
        with urllib.request.urlopen('http://127.0.0.1:8766/api/health', timeout=3) as response:
            health = json.load(response)
        active_count = health['liveProgress']['activeStreamCount']
    except Exception as exc:
        raise RuntimeError('live capture state unavailable; diagnostic model was not loaded') from exc
    if not isinstance(active_count, int) or isinstance(active_count, bool) or active_count < 0:
        raise RuntimeError('live capture count is invalid; diagnostic model was not loaded')
    if active_count:
        event('pending_active_live_capture', activeStreamCount=active_count, modelLoaded=False)
        return 75
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', '--output', str(output)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment)
    assert child.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    buffer = b''
    active = None
    deadline = time.monotonic() + 180  # Initialization and non-generation stages.
    log_path = output / 'execution.log'
    with log_path.open('wb') as log:
        while child.poll() is None or selector.get_map():
            now = time.monotonic()
            if child.poll() is None and now >= deadline:
                child.kill()
                child.wait()
                save_json(output / 'watchdog-timeout.json', {'activeCall': active,
                          'timeoutSeconds': CALL_TIMEOUT_SECONDS if active else 180,
                          'evidence': 'External parent killed only this diagnostic child after its wall deadline; incomplete call is not accepted.'})
                event('watchdog_timeout', activeCall=active)
                return 124
            events = selector.select(timeout=max(0, min(0.2, deadline - now)))
            for key, _ in events:
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                log.write(data)
                log.flush()
                buffer += data
                while b'\n' in buffer:
                    raw_line, buffer = buffer.split(b'\n', 1)
                    line = raw_line.decode('utf-8', errors='replace')
                    print(line, flush=True)
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    if message.get('event') == 'call_started':
                        active = message['callKey']
                        deadline = message['startedMonotonic'] + CALL_TIMEOUT_SECONDS
                    elif message.get('event') in {'call_generation_finished', 'call_saved', 'model_ready', 'experiment_completed'}:
                        active = None
                        deadline = time.monotonic() + 180
    return child.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.output.resolve() != DEFAULT_OUTPUT.resolve():
        parser.error('this bounded diagnostic writes only its declared output directory')
    return worker(args.output) if args.worker else controller(args.output)


if __name__ == '__main__':
    raise SystemExit(main())

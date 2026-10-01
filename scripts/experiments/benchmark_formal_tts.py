#!/usr/bin/env python3
"""Diagnostic-only component timing using the production QwenSynthesizer.

Warm: one resident engine, one recorded warm-up plus three measured repetitions
per condition. Cold: invoke a fresh Python process per condition and measure its
first batch; OS caches are never cleared. Mixed-locale conditions are synthetic
engine exercises, not formal locale jobs or release acceptance.
"""
from __future__ import annotations

import time
PROCESS_STARTED = time.perf_counter()
import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import sys
import threading
import traceback


LANGUAGES = {"zh-Hans": "Chinese", "ko": "Korean", "es": "Spanish"}
CONDITIONS = {f"{locale}-b{size}": (locale, size)
              for locale in LANGUAGES for size in (1, 2)}
CONDITIONS.update({"mixed-b4": (None, 4), "mixed-b8": (None, 8)})


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, path)


class Memory:
    def __init__(self, torch, device):
        self.torch, self.device = torch, device
        self.samples = []
        self.stop = threading.Event()
        self.thread = None

    def sample(self):
        try:
            if self.device.startswith('cuda'):
                row = {'allocatedBytes': self.torch.cuda.memory_allocated(),
                       'reservedBytes': self.torch.cuda.memory_reserved()}
            else:
                row = {'allocatedBytes': self.torch.mps.current_allocated_memory(),
                       'driverAllocatedBytes': self.torch.mps.driver_allocated_memory()}
            self.samples.append(row)
        except Exception as exc:
            self.samples.append({'unavailable': type(exc).__name__})

    def __enter__(self):
        if self.device.startswith('cuda'):
            self.torch.cuda.reset_peak_memory_stats()
        self.samples = []
        def poll():
            while not self.stop.wait(.2):
                self.sample()
        self.sample()
        self.thread = threading.Thread(target=poll, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        self.sample()

    def receipt(self):
        keys = {key for row in self.samples for key in row if key != 'unavailable'}
        value = {'sampledPeakBytes': {key: max(row.get(key, 0) for row in self.samples) for key in keys},
                 'sampleIntervalSeconds': .2, 'sampledPeakIsAnExactGPUHighWaterMark': False,
                 'processPeakRssBytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    * (1 if platform.system() == 'Darwin' else 1024)}
        if self.device.startswith('cuda'):
            value['cudaPeakAllocatedBytes'] = self.torch.cuda.max_memory_allocated()
            value['cudaPeakReservedBytes'] = self.torch.cuda.max_memory_reserved()
        else:
            value['mpsExactPeakAvailable'] = False
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--renderer-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--device', choices=('mps', 'cuda:0'), default='mps')
    parser.add_argument('--dtype', choices=('float32', 'bfloat16'), default='float32')
    parser.add_argument('--phase', choices=('warm', 'cold'), default='warm')
    parser.add_argument('--condition', choices=('all', *CONDITIONS), default='all')
    parser.add_argument('--repeats', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text())
    require(inputs.get('schemaVersion') == 'formal-tts-component-benchmark-inputs-v1'
            and inputs.get('releaseEligible') is False, 'Diagnostic input manifest required')
    cases = inputs['cases']
    require(len(cases) == 8 and len({row['caseId'] for row in cases}) == 8,
            'Eight unique approved diagnostic source cases required')
    for row in cases:
        require(row['targetLocale'] in LANGUAGES and 0 < len(row['text']) <= 120
                and hashlib.sha256(row['text'].encode()).hexdigest() == row['textSha256']
                and row['sourceAdapter']['conditioningSha256'] == inputs['checkpointSha256']
                and row['sourceAdapter']['speakerKey'] == inputs['speakerKey'],
                'Frozen source case text/checkpoint identity differs')
    require(all(sorted(row['lengthClass'] for row in cases
                       if row['targetLocale'] == locale and row['lengthClass'] in ('short', 'long'))
                == ['long', 'short'] for locale in LANGUAGES),
            'Each locale needs exactly the original short and long cases')
    names = list(CONDITIONS) if args.condition == 'all' else [args.condition]
    require(args.phase != 'cold' or len(names) == 1,
            'Cold conditions require separate fresh Python processes')
    if args.plan:
        print(json.dumps({'conditions': CONDITIONS, 'cases': [(row['caseId'], len(row['text'])) for row in cases]},
                         ensure_ascii=False))
        return
    require(args.checkpoint and args.out and not args.out.exists(), 'Use a checkpoint and a new output directory')
    args.out.mkdir(parents=True)
    result = {'schemaVersion': 'formal-tts-component-benchmark-v1', 'status': 'running',
              'scope': 'diagnostic_only', 'releaseEligible': False, 'humanListeningStatus': 'pending',
              'device': args.device, 'dtype': args.dtype, 'phase': args.phase,
              'host': platform.node(), 'platform': platform.platform(),
              'inputManifestSha256': sha(args.inputs), 'benchmarkSha256': sha(__file__),
              'sourceCases': cases, 'osCacheCleared': False,
              'settings': {'seed': 42, 'seedPolicy': 'base_plus_fixed_window_start_ordered_missing_units_v1',
                           'temperature': .7, 'repetitionPenalty': 1.05, 'maxNewTokens': 768,
                           'attention': 'sdpa', 'ratePolicy': 'natural_no_time_stretch'},
              'termination': 'high_level_api_has_no_eos_or_finish_reason; no EOS claim', 'trials': []}
    try:
        started = time.perf_counter()
        checkpoint = args.checkpoint.resolve()
        weights_sha = sha(checkpoint / 'model.safetensors')
        config = json.loads((checkpoint / 'config.json').read_text())
        config_sha = sha(checkpoint / 'config.json')
        require(weights_sha == inputs['checkpointSha256']
                and config_sha == inputs['checkpointConfigSha256']
                and inputs['speakerKey'] in config['talker_config']['spk_id'],
                'Live formal checkpoint weights/speaker key differ')
        result['checkpoint'] = {'weightsSha256': weights_sha, 'configSha256': config_sha,
                                'speakerId': inputs['speakerId'], 'speakerKey': inputs['speakerKey'],
                                'path': str(checkpoint)}
        result['checkpointHashSeconds'] = time.perf_counter() - started
        started = time.perf_counter()
        sys.path.insert(0, str(args.renderer_root.resolve()))
        from scripts import render_formal_target_language_speech as formal
        import torch
        result['runtimeImportSeconds'] = time.perf_counter() - started
        result['rendererSha256'] = sha(formal.__file__)
        result['runtime'] = {'torchVersion': torch.__version__, 'qwenTtsVersion': importlib.metadata.version('qwen-tts')}
        require(torch.backends.mps.is_available() if args.device == 'mps' else torch.cuda.is_available(),
                'Requested GPU backend unavailable; no CPU fallback')
        def sync():
            torch.mps.synchronize() if args.device == 'mps' else torch.cuda.synchronize()
        started = time.perf_counter()
        with Memory(torch, args.device) as memory:
            engine = formal.QwenSynthesizer(checkpoint, device=args.device, dtype=args.dtype, attention='sdpa')
            sync()
        result['modelLoadSeconds'] = time.perf_counter() - started
        result['modelLoadMemory'] = memory.receipt()
        save(args.out / 'result.partial.json', result)
        for name in names:
            locale, batch_size = CONDITIONS[name]
            selected = [row for row in cases if locale is None or
                        (row['targetLocale'] == locale and row['lengthClass'] in ('short', 'long'))]
            if args.phase == 'cold':
                selected = selected[:batch_size]
            repetitions = ['cold-first-batch'] if args.phase == 'cold' else ['warmup', *[f'warm-{i + 1}' for i in range(args.repeats)]]
            for repetition in repetitions:
                trial = {'condition': name, 'repetition': repetition, 'batchSize': batch_size,
                         'scope': 'synthetic_mixed_locale_engine_only' if locale is None else 'same_locale_component',
                         'batches': [], 'units': []}
                trial_started = time.perf_counter()
                with Memory(torch, args.device) as memory:
                    for start in range(0, len(selected), batch_size):
                        rows = selected[start:start + batch_size]
                        requests = [{'identity': {'caseId': row['caseId'], 'unitIndex': start + j,
                                     'sourceJobSha256': row['sourceJobSha256'], 'sourceUnitIndex': row['unitIndex'],
                                     'textSha256': row['textSha256'], 'targetLocale': row['targetLocale']},
                                     'text': row['text'], 'language': LANGUAGES[row['targetLocale']],
                                     'speaker': inputs['speakerKey'], 'instruct': None} for j, row in enumerate(rows)]
                        sync(); begin = time.perf_counter()
                        if batch_size == 1:
                            wave, rate = engine(requests[0]['text'], requests[0]['language'],
                                                requests[0]['speaker'], seed=42 + start)
                            values = [{'identity': requests[0]['identity'], 'wave': wave, 'sampleRate': rate}]
                        else:
                            values = engine.batch(copy.deepcopy(requests), seed=42 + start)
                        sync(); synthesis = time.perf_counter() - begin
                        require(len(values) == len(requests) and all(value['identity'] == row['identity']
                                for value, row in zip(values, requests)), 'TTS output coverage/order differs')
                        batch = {'windowStart': start, 'requestedBatchSize': batch_size,
                                 'actualBatchSize': len(rows),
                                 'unitIds': [row['identity']['caseId'] for row in requests],
                                 'seed': 42 + start, 'synthesisSeconds': synthesis,
                                 'synthesisIncludesCodecDecodeAndReturnTransfer': True,
                                 'cpuConversionSeconds': 0, 'pcmSaveSeconds': 0, 'decodeHashSeconds': 0}
                        for value in values:
                            begin = time.perf_counter()
                            wave = value['wave']
                            if hasattr(wave, 'detach'):
                                wave = wave.detach().cpu().reshape(-1).tolist()
                            elif hasattr(wave, 'reshape'):
                                wave = wave.reshape(-1).tolist()
                            batch['cpuConversionSeconds'] += time.perf_counter() - begin
                            path = args.out / name / repetition / (value['identity']['caseId'] + '.wav')
                            path.parent.mkdir(parents=True, exist_ok=True)
                            begin = time.perf_counter()
                            formal.write_pcm16(path, wave, int(value['sampleRate']))
                            batch['pcmSaveSeconds'] += time.perf_counter() - begin
                            begin = time.perf_counter()
                            decoded = formal.integrity.probe_full_decode(path)
                            audio_hash = sha(path)
                            batch['decodeHashSeconds'] += time.perf_counter() - begin
                            trial['units'].append({'identity': value['identity'], 'audioPath': str(path.relative_to(args.out)),
                                                   'audioSha256': audio_hash, **decoded, 'fullDecode': 'pass',
                                                   'decodeMethod': 'ffprobe_ffmpeg' if shutil.which('ffprobe') and shutil.which('ffmpeg')
                                                       else 'native_pcm_full_frame_decode'})
                        batch['audioSeconds'] = sum(row['durationSeconds'] for row in trial['units'][-len(values):])
                        batch['rtf'] = synthesis / batch['audioSeconds']
                        batch['unitsPerSynthesisSecond'] = len(values) / synthesis
                        trial['batches'].append(batch)
                trial['wallSeconds'] = time.perf_counter() - trial_started
                trial['memory'] = memory.receipt()
                trial['audioSeconds'] = sum(row['durationSeconds'] for row in trial['units'])
                trial['synthesisSeconds'] = sum(row['synthesisSeconds'] for row in trial['batches'])
                trial['rtf'] = trial['synthesisSeconds'] / trial['audioSeconds']
                require([row['identity']['caseId'] for row in trial['units']] == [row['caseId'] for row in selected],
                        'Diagnostic unit coverage incomplete')
                result['trials'].append(trial)
                result['processEntryToReceiptSeconds'] = time.perf_counter() - PROCESS_STARTED
                save(args.out / 'result.partial.json', result)
                print(json.dumps({'event': 'trial_complete', 'condition': name, 'repetition': repetition,
                                  'wallSeconds': trial['wallSeconds'], 'rtf': trial['rtf']}), flush=True)
        result['summaries'] = {}
        for name in names:
            measured = [trial for trial in result['trials'] if trial['condition'] == name and trial['repetition'] != 'warmup']
            result['summaries'][name] = {'measuredRepetitions': len(measured),
                **{key + 'Median': statistics.median(trial[key] for trial in measured)
                   for key in ('wallSeconds', 'synthesisSeconds', 'audioSeconds', 'rtf')}}
        result['status'] = 'complete_diagnostic'
        result['processEntryToReceiptSeconds'] = time.perf_counter() - PROCESS_STARTED
        save(args.out / 'result.json', result)
    except BaseException as exc:
        result['status'] = 'failed_diagnostic'
        result['errorType'], result['error'] = type(exc).__name__, str(exc)
        result['processEntryToReceiptSeconds'] = time.perf_counter() - PROCESS_STARTED
        save(args.out / 'failure.json', result)
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Run the fixed v4.1 Mac MLX deployment diagnostic without changing services."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats != 3:
        parser.error('the frozen comparison requires exactly three repeats')
    if args.output.exists():
        parser.error('output must be a new directory; existing results are never overwritten')
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location('v41_service', root / 'scripts/serve_milmmt_v41_local.py')
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    rows = [json.loads(line) for line in args.samples.read_text().splitlines() if line.strip()]
    if len(rows) != 12 or len({x['id'] for x in rows}) != 12:
        parser.error('expected twelve unique frozen inputs')
    if [x['stratum'] for x in rows] != ['short'] * 6 + ['natural'] * 6:
        parser.error('expected six short, then six natural inputs')
    for row in rows:
        if row['prompt'] != service.official_prompt(row['source']):
            parser.error('input prompt differs from the frozen source-only contract')
        if hashlib.sha256(row['source'].encode()).hexdigest() != row['sourceTextSha256']:
            parser.error('source hash mismatch')
    args.output.mkdir(parents=True)
    started = time.perf_counter()
    packages = service.verify_package(service.MODEL)
    verification_ms = (time.perf_counter() - started) * 1000
    import mlx.core as mx
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_sampler
    loaded = time.perf_counter()
    model, tokenizer = load(str(service.MODEL), lazy=False, tokenizer_config={'trust_remote_code': False})
    mx.synchronize()
    model_load_ms = (time.perf_counter() - loaded) * 1000
    if set(tokenizer.eos_token_ids) != {1, 106}:
        raise ValueError('unexpected EOS configuration')
    sampler = make_sampler(temp=0)
    identity = {
        'schemaVersion': 'mobile-runtime-diagnostic-v1', 'host': 'macbook-pro',
        'platform': platform.platform(), 'machine': platform.machine(),
        'python': sys.version, 'runtimePackages': packages,
        'model': str(service.MODEL), 'weightsSha256': service.WEIGHTS_SHA,
        'packageSha256': service.MANIFEST_SHA, 'quantization': 'MLX affine Q5 group64',
        'samplesSha256': sha(args.samples), 'scriptSha256': sha(__file__),
        'modelLoadMs': model_load_ms, 'packageVerificationMs': verification_ms,
        'maxNewTokens': 512, 'greedy': True, 'eosTokenIds': [1, 106],
        'addSpecialTokens': False, 'kvCachePolicy': 'new per call',
        'timingBoundary': 't0 before source-to-prompt/tokenization; CPU-visible native MLX stream responses (lookahead included); final after detokenizer finalize, generator close and mx.synchronize',
        'modelLoadScope': 'mlx_lm.load lazy=False through mx.synchronize; package hash verification excluded',
        'releaseEligible': False, 'hardwareOnlyComparison': False,
    }
    write_json(args.output / 'identity.json', identity)

    def run(row, repeat, position, warmup=False):
        mx.random.seed(42)
        mx.synchronize()
        client_started = time.perf_counter()
        t0 = time.perf_counter()
        text = service.official_prompt(row['source'])
        ids = tokenizer.encode(text, add_special_tokens=False)
        tokenized = time.perf_counter()
        prompt = mx.array(ids, dtype=mx.int32)
        mx.eval(prompt)
        mx.synchronize()
        prepared = time.perf_counter()
        token_ids, parts, first_token, first_chinese, last = [], [], None, None, None
        error = None
        generator = stream_generate(model, tokenizer, prompt, max_tokens=512,
                                    sampler=sampler, prompt_cache=None)
        try:
            for item in generator:
                now = time.perf_counter()
                if first_token is None:
                    first_token = (now - t0) * 1000
                token_ids.append(int(item.token))
                parts.append(item.text)
                if first_chinese is None and any('\u3400' <= c <= '\u9fff' for c in item.text):
                    first_chinese = (now - t0) * 1000
                last = item
                if now - t0 > 90:
                    raise TimeoutError('diagnostic generation exceeded 90 seconds')
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)[:300]}
        finally:
            generator.close()
            mx.synchronize()
        ended = time.perf_counter()
        complete = error is None and last is not None and last.finish_reason == 'stop' and bool(''.join(parts).strip())
        result = {
            'id': row['id'], 'stratum': row['stratum'], 'repeat': repeat,
            'position': position, 'warmup': warmup, 'source': row['source'],
            'sourceTextSha256': row['sourceTextSha256'], 'promptSha256': row['promptSha256'],
            'status': 'completed' if complete else 'failed', 'error': error,
            'text': ''.join(parts), 'generatedTokenIds': token_ids,
            'generatedTokenIdsSha256': hashlib.sha256(json.dumps(token_ids, separators=(',', ':')).encode()).hexdigest(),
            'promptTokens': len(ids), 'generatedTokens': len(token_ids),
            'eosTokenId': token_ids[-1] if token_ids and token_ids[-1] in {1, 106} else None,
            'finishReason': last.finish_reason if last else None,
            'tokenizationMs': (tokenized - t0) * 1000,
            'inputPrepareMs': (prepared - tokenized) * 1000,
            'firstTokenMs': first_token, 'firstChineseMs': first_chinese,
            'fullEosMs': (ended - t0) * 1000 if complete else None,
            'attemptElapsedMs': (ended - t0) * 1000,
            'generationMs': (ended - prepared) * 1000,
            'clientWallMs': (time.perf_counter() - client_started) * 1000,
            'peakMemoryBytes': mx.get_peak_memory(),
        }
        with (args.output / ('warmups.jsonl' if warmup else 'results.jsonl')).open('a') as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + '\n')
            handle.flush()
        print(json.dumps({'position': position, 'repeat': repeat, 'warmup': warmup,
                          'status': result['status'], 'firstChineseMs': first_chinese,
                          'fullEosMs': result['fullEosMs']}, ensure_ascii=False), flush=True)
        return complete

    ok = True
    for index in [0, 6]:
        ok = run(rows[index], -1, index, True) and ok
    for repeat in range(3):
        order = list(range(12)) if repeat % 2 == 0 else list(reversed(range(12)))
        for position, index in enumerate(order):
            ok = run(rows[index], repeat, position) and ok
    write_json(args.output / 'completion.json', {
        'completed': ok, 'expectedFormalCalls': 36, 'expectedWarmupCalls': 2,
        'resultsSha256': sha(args.output / 'results.jsonl'),
        'warmupsSha256': sha(args.output / 'warmups.jsonl'),
        'identitySha256': sha(args.output / 'identity.json'),
    })
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

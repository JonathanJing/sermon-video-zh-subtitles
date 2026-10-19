#!/usr/bin/env python3
"""Read-only baseline versus attempt-context receipt validation measurement."""
import argparse
import json
from pathlib import Path
import time
try:
    from scripts import validate_target_language_audio_unit as integrity
    from scripts import sermon_sentence_interpretation as identity
except ImportError:
    import validate_target_language_audio_unit as integrity
    import sermon_sentence_interpretation as identity


def benchmark(job_path, *, progress=None):
    job = json.loads(job_path.read_text())
    digest = identity.sha256(job_path)
    result = {'schemaVersion': 'sermon-audio-receipt-benchmark-v1', 'jobSha256': digest,
              'unitCount': len(job['units']), 'fullDecode': True, 'results': {}}
    for mode in ('baseline', 'snapshot'):
        start = time.monotonic()
        context = integrity.ValidatedJobContext(job_path) if mode == 'snapshot' else None
        for index, unit in enumerate(job['units']):
            receipt = json.loads((job_path.parent / f'receipts/unit-{index:04d}.json').read_text())
            integrity.validate_receipt(job_path, index, job_path.parent / unit['outputRelativePath'],
                                       receipt, validated_context=context)
            if progress and ((index + 1) % 25 == 0 or index + 1 == len(job['units'])):
                progress({'mode': mode, 'validatedUnits': index + 1, 'seconds': time.monotonic() - start})
        if context: context.check(full=True)
        if identity.sha256(job_path) != digest: raise ValueError('Benchmark job changed')
        result['results'][mode] = {'seconds': time.monotonic() - start, 'validatedUnits': len(job['units'])}
    result['savedSeconds'] = result['results']['baseline']['seconds'] - result['results']['snapshot']['seconds']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists(): raise ValueError('Benchmark receipt already exists')
    result = benchmark(args.job.resolve(), progress=lambda row: print(json.dumps(row), flush=True))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as handle: json.dump(result, handle, indent=2); handle.write('\n')


if __name__ == '__main__': main()

"""Bounded scratch-file append/fsync probe, never an execution ledger.

Measures the existing low-level append syscall path only. No durable controller,
job or provider is created, and no existing evidence is opened for writing.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

from scripts import sermon_log_contract as contract
from scripts import sermon_log_outbox as outbox


def measure(directory, *, seed_bytes=641503, record_bytes=1400, samples=30, trials=3):
    if not (0 <= seed_bytes <= 2*1024*1024 and 256 <= record_bytes <= 8192
            and 1 <= samples <= 100 and 1 <= trials <= 5):
        raise ValueError('scratch_probe_bounds_exceeded')
    row = {'scope': 'non_authoritative_scratch_io_probe', 'payload': ''}
    row['payload'] = 'x' * (record_bytes-len(contract.canonical_bytes(row))-1)
    encoded = contract.canonical_bytes(row)+b'\n'
    assert len(encoded) == record_bytes
    seed = b' '*(seed_bytes-1)+b'\n' if seed_bytes else b''
    results = []
    for trial in range(trials):
        with tempfile.TemporaryDirectory(prefix='append-probe-', dir=directory) as temporary:
            path = Path(temporary)/'not-an-execution-ledger.bin'
            with path.open('w+b') as stream:
                stream.write(seed); stream.flush(); os.fsync(stream.fileno())
                values = []
                for index in range(samples):
                    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                    outbox._append(stream.fileno(), row)
                    cpu, wall = time.process_time_ns()-cpu, time.perf_counter_ns()-wall
                    values.append({'wallSeconds': wall/1e9, 'cpuSeconds': cpu/1e9})
            assert path.read_bytes() == seed+encoded*samples
            results.append({'trial': trial, 'samples': values,
                'medianWallSeconds': statistics.median(r['wallSeconds'] for r in values),
                'medianCpuSeconds': statistics.median(r['cpuSeconds'] for r in values)})
    return {'schemaVersion': 'scratch-append-cost-v1',
        'scope': 'existing_low_level_append_and_os_fsync_only_not_end_to_end_durable_write',
        'seedBytes': len(seed), 'recordBytes': len(encoded), 'trials': results,
        'medianOfTrialMedians': statistics.median(r['medianWallSeconds'] for r in results),
        'jobSubmissions': 0, 'providerCalls': 0, 'temporaryFilesRemoved': True,
        'limitations': 'No directory fsync, durable validation, contention or power-loss guarantee measured.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--record-bytes', type=int, default=1400)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('output already exists')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = measure(args.output.parent, record_bytes=args.record_bytes)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps({'medianSeconds': result['medianOfTrialMedians'], 'trials': len(result['trials'])}))


if __name__ == '__main__':
    main()

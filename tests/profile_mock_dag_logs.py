"""Read-only cost attribution on saved two-unit synthetic DAG evidence.

Each operation runs in fresh sequential processes; first call is Python-cache
cold, later calls are warm. OS caches are not cleared. No producer is invoked.
"""
import argparse
import cProfile
import fcntl
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import pstats
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
OPERATIONS = ('file_bytes', 'json_parse', 'read_snapshot', 'schema', 'replay',
              'completion_batch', 'durable_precheck', 'weekly_report',
              'log_inspection', 'status_projection')


def read(path):
    return json.loads(path.read_text())


def fingerprints(root):
    result = {}
    total = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('evidence_symlink_rejected')
        if path.is_file():
            size = path.stat().st_size
            total += size
            if size > 16*1024*1024 or total > 256*1024*1024 or len(result) >= 5000:
                raise ValueError('evidence_size_limit')
            result[str(path.relative_to(root))] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'sizeBytes': size}
    if not result:
        raise ValueError('empty_evidence')
    return result


def prepare(saved, operation):
    from scripts import sermon_accounting as accounting
    from scripts import sermon_completion as completion
    from scripts import sermon_durable_accounting as durable
    from scripts import sermon_log_contract as contract
    from scripts import sermon_logs
    from scripts import sermon_review_contracts as c
    from scripts import weekly_pipeline_report as weekly
    from tests.mock_tts_sdk_diagnostics import status_diagnostics

    if read(saved/'EVIDENCE_ONLY.json').get('auditOnly') is not True:
        raise ValueError('saved_synthetic_evidence_required')
    root = saved/'fresh-full-dag'/saved.name
    directory = root/'accounting'
    ledger = directory/'events.jsonl'
    raw = ledger.read_bytes()
    if len(raw) > 16*1024*1024:
        raise ValueError('ledger_size_limit')
    lines = raw.splitlines()
    events = [json.loads(line) for line in lines if line.strip()]
    if not events or any(e.get('evidenceMode') != 'synthetic' for e in events):
        raise ValueError('synthetic_events_required')
    handles = {}
    def walk(value):
        if isinstance(value, dict):
            if value.get('schemaVersion') in (completion.SCHEMA, completion.SYNTHETIC_SCHEMA):
                handles[c.canonical_sha256(value)] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for path in root.rglob('*.json'):
        walk(read(path))
    walk(read(saved/'fresh-source-causality.json')['handles'])
    value = read(saved/'sdk-result-2.json')

    def file_bytes():
        return len(ledger.read_bytes())
    def json_parse():
        return len([json.loads(line) for line in lines if line.strip()])
    def read_snapshot():
        rows, errors, digest = accounting.read_event_snapshot(directory)
        assert not errors and digest == hashlib.sha256(raw).hexdigest()
        return len(rows)
    def schema():
        for event in events:
            contract.validate_event(event)
        return len(events)
    def replay():
        result = contract.replay_integrity(events)
        assert result['status'] == 'consistent'
        return result['status']
    def completion_batch():
        for handle in handles.values():
            validator = completion.validate_synthetic if handle['schemaVersion'] == completion.SYNTHETIC_SCHEMA else completion.validate
            validator(handle, events, production_run_id=handle['productionRunId'])
        return len(handles)
    def durable_precheck():
        # Read-only counterpart of the existing pre-write validation. Do not use
        # outbox._ledger: it may create directories/files and permits writes.
        with ledger.open('rb') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            result = durable.validate_locked(directory, directory/'.pending-events', stream.fileno())
        assert result is not None
        return len(result[1])
    def weekly_report():
        result = weekly.project(directory)
        assert result['receiptIntegrity']['status'] == 'consistent'
        assert result['observedProviderCalls']['directReceiptCount'] == 6
        return result['receiptIntegrity']['status']
    def log_inspection():
        result = sermon_logs.inspect_logs(directory, tail=1)
        assert result['ledgerIntegrity'] == 'readable' and not result['unfinished']
        return result['errorEvents']
    def status_projection():
        result = status_diagnostics(value, events, [])
        assert result['history']['integrity'] == 'consistent'
        return result['history']['errorEventCount']

    return locals()[operation], contract, {'eventCount': len(events), 'ledgerBytes': len(raw),
        'completionCount': len(handles), 'deliveryRecords': len(list((directory/durable.DELIVERY_DIRECTORY).glob('*.json'))),
        'ledgerSha256': hashlib.sha256(raw).hexdigest()}


def cache_state(contract):
    info = contract._validate_frozen_event.cache_info()
    return {**info._asdict(), **contract._validate_frozen_event.cache_usage()}


def child(saved, operation, profile_output=None):
    action, contract, metadata = prepare(saved, operation)
    # No validation has run in preparation: measure a genuinely fresh Python
    # cache, not an artificial clearing during an active workflow.
    assert contract._validate_frozen_event.cache_info().currsize == 0
    results = []
    for index in range(3):
        before = cache_state(contract)
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        value = action()
        cpu, wall = time.process_time_ns()-cpu, time.perf_counter_ns()-wall
        after = cache_state(contract)
        results.append({'cachePhase': 'cold' if index == 0 else 'warm',
            'wallSeconds': wall/1e9, 'cpuSeconds': cpu/1e9, 'result': value,
            'cacheBefore': before, 'cacheAfter': after,
            'cacheDelta': {key: after[key]-before[key] for key in ('hits', 'misses')}})
    assert len({json.dumps(r['result'], sort_keys=True) for r in results}) == 1
    output = {'operation': operation, 'metadata': metadata, 'measurements': results}
    if profile_output:
        profiler = cProfile.Profile()
        start = time.perf_counter()
        profiler.runcall(action)
        output['profiledWallSeconds'] = time.perf_counter()-start
        profiler.dump_stats(str(profile_output))
        stats = pstats.Stats(profiler)
        functions = []
        for (filename, line, name), (cc, nc, tt, ct, callers) in stats.stats.items():
            path = Path(filename)
            label = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else filename
            functions.append({'file': label, 'line': line, 'function': name,
                'primitiveCalls': cc, 'totalCalls': nc, 'selfSeconds': tt, 'cumulativeSeconds': ct})
        output['profileFunctions'] = functions
        output['profileScope'] = 'one_extra_warm_call_instrumented_not_baseline'
    return output


def aggregate(samples):
    result = {}
    for phase in ('cold', 'warm'):
        rows = [m for sample in samples for m in sample['measurements'] if m['cachePhase'] == phase]
        result[phase] = {key: {'median': statistics.median(r[key] for r in rows),
            'min': min(r[key] for r in rows), 'max': max(r[key] for r in rows)}
            for key in ('wallSeconds', 'cpuSeconds')}
        result[phase]['sampleCount'] = len(rows)
        result[phase]['cacheDeltas'] = [r['cacheDelta'] for r in rows]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--saved', type=Path)
    parser.add_argument('--operation', choices=OPERATIONS)
    parser.add_argument('--profile-output', type=Path)
    parser.add_argument('--samples', type=int, default=3, choices=range(1, 6))
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args(argv)
    if args.child:
        if args.saved is None or args.operation is None:
            parser.error('--child requires --saved and --operation')
        if args.profile_output and args.profile_output.resolve().is_relative_to(args.saved.resolve()):
            parser.error('profile output must be outside saved evidence')
        print(json.dumps(child(args.saved, args.operation, args.profile_output)))
        return
    if args.evidence_root is None or args.output_dir is None:
        parser.error('--evidence-root and --output-dir required')
    evidence = args.evidence_root.resolve(strict=True)
    output = args.output_dir.resolve()
    if output.is_relative_to(evidence):
        parser.error('output must be outside evidence')
    output.mkdir(parents=True, exist_ok=False)
    before = fingerprints(evidence)
    (output/'input-files.json').write_text(json.dumps(before, sort_keys=True, indent=2)+'\n')
    report = {'schemaVersion': 'mock-log-cost-analysis-v1', 'python': sys.version,
        'platform': platform.platform(), 'jsonschemaVersion': version('jsonschema'),
        'startedAtUnix': time.time(), 'status': 'running',
        'analysisCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        'scope': 'read_only_saved_synthetic_evidence_not_live_dag_share',
        'coldMeaning': 'fresh_python_process_not_cold_disk', 'results': {}}
    try:
        for scenario in ('happy', 'failure', 'timeout'):
            saved_roots = list((evidence/scenario).iterdir())
            if len(saved_roots) != 1:
                raise ValueError('single_saved_plan_required')
            saved = saved_roots[0]
            if saved.is_symlink() or not saved.is_dir():
                raise ValueError('invalid_saved_plan')
            report['results'][scenario] = {}
            for operation in OPERATIONS:
                samples = []
                for index in range(args.samples):
                    command = [sys.executable, '-B', '-m', 'tests.profile_mock_dag_logs',
                        '--child', '--saved', str(saved), '--operation', operation]
                    process = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=180)
                    if process.returncode:
                        (output/'failed-child.log').write_text(process.stderr)
                        raise RuntimeError('read_only_measurement_failed')
                    sample = json.loads(process.stdout); samples.append(sample)
                    (output/f'{scenario}-{operation}-{index}.json').write_text(json.dumps(sample, indent=2)+'\n')
                report['results'][scenario][operation] = {'metadata': samples[0]['metadata'],
                    'summary': aggregate(samples)}
                print(json.dumps({'scenario': scenario, 'operation': operation,
                    'warmMedianSeconds': report['results'][scenario][operation]['summary']['warm']['wallSeconds']['median']}), flush=True)
                (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        report['status'] = 'passed'
    except BaseException:
        report['status'] = 'failed_or_interrupted'
        raise
    finally:
        report['inputFilesUnchanged'] = before == fingerprints(evidence)
        report['endedAtUnix'] = time.time()
        (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        if not report['inputFilesUnchanged']:
            raise RuntimeError('evidence_changed')


if __name__ == '__main__':
    main()

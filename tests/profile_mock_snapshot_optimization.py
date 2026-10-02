"""Paired, read-only measurements on saved two-unit synthetic DAG evidence.

Each implementation runs in a fresh process: first call is Python-cache cold,
subsequent calls warm. Filesystem caches are not flushed. No producer is called.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
import tempfile
import types

from tests.profile_mock_dag_logs import fingerprints, cache_state

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
PAIRS = {'completion_v1': ('v1_single', 'v1_batch'),
         'completion_v2': ('v2_single', 'v2_batch'),
         'reports': ('reports_repeated', 'reports_shared')}
OPERATIONS = tuple(op for pair in PAIRS.values() for op in pair)
BASELINE_REF = '7eb153b'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_baseline(filename):
    source = subprocess.check_output(['git', 'show', BASELINE_REF+':scripts/'+filename+'.py'], cwd=REPO)
    module = types.ModuleType('_snapshot_baseline_'+filename)
    module.__file__ = str(REPO/'scripts'/(filename+'.py'))
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()


def prepare(saved, operation):
    from scripts import sermon_accounting as accounting
    from scripts import sermon_completion as completion
    from scripts import sermon_log_contract as contract
    from scripts import sermon_logs

    baseline, baseline_sha = load_baseline('sermon_completion')

    marker = json.loads((saved/'EVIDENCE_ONLY.json').read_text())
    if marker.get('auditOnly') is not True or marker.get('dispatchAuthorized') is not False:
        raise ValueError('read_only_synthetic_evidence_required')
    root = saved/'fresh-full-dag'/saved.name
    directory = root/'accounting'
    raw = (directory/'events.jsonl').read_bytes()
    if len(raw) > 16*1024*1024:
        raise ValueError('ledger_size_limit')
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not events or any(row.get('evidenceMode') != 'synthetic' for row in events):
        raise ValueError('synthetic_events_required')
    handles = {}

    def walk(value):
        if isinstance(value, dict):
            if value.get('schemaVersion') in (completion.SCHEMA, completion.SYNTHETIC_SCHEMA):
                handles[digest(value)] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for path in sorted(root.rglob('*.json')):
        walk(json.loads(path.read_text()))
    walk(json.loads((saved/'fresh-source-causality.json').read_text())['handles'])
    groups = {}
    for key, handle in sorted(handles.items()):
        groups.setdefault((handle['schemaVersion'], handle['productionRunId']), []).append(
            {'handle': handle, 'stage': handle['stage'], 'artifact_sha256': handle['artifactSha256'],
             'dependencies': handle['dependsOn'], **({'job_id': handle['jobId'],
             'revision_id': handle['revisionId']} if handle['schemaVersion'] == completion.SYNTHETIC_SCHEMA else {})})

    def validate(synthetic, batch):
        results = []
        schema = completion.SYNTHETIC_SCHEMA if synthetic else completion.SCHEMA
        for (group_schema, production_id), checks in sorted(groups.items()):
            if group_schema != schema:
                continue
            if batch:
                validator = completion.validate_synthetic_many if synthetic else completion.validate_many
                results.extend(validator(checks, events, production_run_id=production_id))
            else:
                validator = baseline.validate_synthetic if synthetic else baseline.validate
                for check in checks:
                    results.append(validator(events=events, production_run_id=production_id, **check))
        if not results:
            raise ValueError('missing_completion_domain')
        return results

    report_action, report_metadata = (prepare_reports(saved, directory, events, operation)
        if operation.startswith('reports_') else (None, {}))

    action = {'v1_single': lambda: validate(False, False),
              'v1_batch': lambda: validate(False, True),
              'v2_single': lambda: validate(True, False),
              'v2_batch': lambda: validate(True, True),
              'reports_repeated': report_action,
              'reports_shared': report_action}[operation]
    return action, contract, {'eventCount': len(events), 'ledgerBytes': len(raw),
        'ledgerSha256': hashlib.sha256(raw).hexdigest(),
        'baselineCompletionSourceSha256': baseline_sha, **report_metadata,
        'completionV1Count': sum(len(v) for (s, _), v in groups.items() if s == completion.SCHEMA),
        'completionV2Count': sum(len(v) for (s, _), v in groups.items() if s == completion.SYNTHETIC_SCHEMA),
        'completionInputsSha256': digest([handles[key] for key in sorted(handles)])}


def prepare_reports(saved, directory, events, operation):
    from scripts import sermon_fresh_full_dag as current
    old_accounting, accounting_sha = load_baseline('sermon_accounting')
    old_logs, logs_sha = load_baseline('sermon_logs')
    old_dag, dag_sha = load_baseline('sermon_fresh_full_dag')
    old_dag.accounting, old_dag.logs = old_accounting, old_logs
    for name in ('read_events', 'receipt_integrity', 'profile_integrity'):
        setattr(old_logs, name, getattr(old_accounting, name))
    # Both public report paths preserve summary writes. Exercise them only on
    # an isolated byte-identical accounting copy; the saved evidence is read-only.
    temporary = tempfile.TemporaryDirectory(prefix='mock-report-profile-')
    scratch = Path(temporary.name)/'accounting'
    shutil.copytree(directory, scratch)
    binding = json.loads((saved/'fresh-full-dag'/saved.name/'plan.json').read_text())
    final = json.loads((saved/'sdk-result-2.json').read_text())
    module = current if operation == 'reports_shared' else old_dag
    probe = object.__new__(module.FullFreshDAG)
    probe.stream = types.SimpleNamespace(directory=scratch, run_id=events[0]['runId'])
    probe.session = types.SimpleNamespace(subject=types.SimpleNamespace(config={'runId': binding['productionRunId']}))
    probe.binding, probe.units = binding, binding['units']
    probe.plan_sha256, probe.invocation = saved.name, final['invocationId']
    probe.prior_api_events = {row['eventId'] for row in events if row['event'] == 'api_attempt'}
    original_read = module.accounting.read_event_snapshot
    read_calls = [0]

    def counted_read(*args, **kwargs):
        read_calls[0] += 1
        return original_read(*args, **kwargs)

    module.accounting.read_event_snapshot = counted_read

    def action():
        # Capture the TemporaryDirectory owner for the lifetime of this action.
        assert Path(temporary.name).is_dir()
        read_calls[0] = 0
        if operation == 'reports_shared':
            result = probe.report_bundle()
        else:
            result = {'layerEvidence': probe.layer_evidence(), 'accountingProjection': probe.accounting_projection()}
        action.last_read_calls = read_calls[0]
        return result

    return action, {'baselineReportSourceSha256': {'sermon_accounting': accounting_sha,
        'sermon_logs': logs_sha, 'sermon_fresh_full_dag': dag_sha},
        'reportScope': 'original_public_report_composition_vs_current_bundle_on_temporary_accounting_copy',
        'reportWrites': 'summary_outputs_and_lock_in_temporary_copy_only'}


def child(saved, operation, warm_calls):
    action, contract, metadata = prepare(saved, operation)
    assert contract._validate_frozen_event.cache_info().currsize == 0
    measurements = []
    for index in range(warm_calls+1):
        before = cache_state(contract)
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        result = action()
        elapsed_cpu, elapsed_wall = time.process_time_ns()-cpu, time.perf_counter_ns()-wall
        measurements.append({'cachePhase': 'cold' if index == 0 else 'warm',
            'wallSeconds': elapsed_wall/1e9, 'cpuSeconds': elapsed_cpu/1e9,
            'resultSha256': digest(result), 'cacheBefore': before, 'cacheAfter': cache_state(contract),
            **({'snapshotReadCalls': action.last_read_calls} if hasattr(action, 'last_read_calls') else {})})
    assert len({row['resultSha256'] for row in measurements}) == 1
    return {'operation': operation, 'metadata': metadata, 'measurements': measurements}


def phase_summary(samples, phase):
    rows = [row for sample in samples for row in sample['measurements'] if row['cachePhase'] == phase]
    return {'sampleCount': len(rows), **{key: {'median': statistics.median(row[key] for row in rows),
        'min': min(row[key] for row in rows), 'max': max(row[key] for row in rows)}
        for key in ('wallSeconds', 'cpuSeconds')}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--samples', type=int, choices=range(1, 4), default=1)
    parser.add_argument('--warm-calls', type=int, choices=range(1, 6), default=3)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--saved', type=Path)
    parser.add_argument('--operation', choices=OPERATIONS)
    args = parser.parse_args(argv)
    if args.child:
        if args.saved is None or args.operation is None:
            parser.error('--child requires --saved and --operation')
        print(json.dumps(child(args.saved, args.operation, args.warm_calls)))
        return
    if args.evidence_root is None or args.output_dir is None:
        parser.error('--evidence-root and --output-dir required')
    evidence, output = args.evidence_root.resolve(strict=True), args.output_dir.resolve()
    if output.is_relative_to(evidence):
        parser.error('output must be outside evidence')
    before = fingerprints(evidence)
    output.mkdir(parents=True, exist_ok=False)
    (output/'input-files.json').write_text(json.dumps(before, sort_keys=True, indent=2)+'\n')
    code = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((REPO/'scripts').glob('*.py'))}
    code[str(Path(__file__).relative_to(REPO))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    helper = REPO/'tests/profile_mock_dag_logs.py'
    code[str(helper.relative_to(REPO))] = hashlib.sha256(helper.read_bytes()).hexdigest()
    report = {'schemaVersion': 'mock-snapshot-optimization-profile-v1', 'status': 'running',
        'startedAtUnix': time.time(), 'python': sys.version, 'platform': platform.platform(),
        'jsonschemaVersion': version('jsonschema'),
        'analysisCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        'codeSha256': code, 'inputManifestSha256': digest(before),
        'scope': 'saved_synthetic_read_only_operations_not_live_dag_speedup',
        'coldMeaning': 'fresh_python_process_and_validation_cache_not_cold_disk',
        'baselineCommit': subprocess.check_output(['git', 'rev-parse', BASELINE_REF], cwd=REPO, text=True).strip(),
        'baselineMeaning': 'original_completion_accounting_logs_dag_modules_with_unchanged_shared_dependencies',
        'results': {}}
    try:
        for scenario in ('happy', 'failure', 'timeout'):
            roots = list((evidence/scenario).iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError('single_saved_plan_required')
            saved = roots[0]
            report['results'][scenario] = {}
            for pair_name, operations in PAIRS.items():
                samples = {op: [] for op in operations}
                for index in range(args.samples):
                    # Reverse alternate pairs to avoid a fixed implementation order.
                    for operation in operations[::1 if index % 2 == 0 else -1]:
                        command = [sys.executable, '-B', '-m', 'tests.profile_mock_snapshot_optimization',
                            '--child', '--saved', str(saved), '--operation', operation,
                            '--warm-calls', str(args.warm_calls)]
                        process = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=600)
                        if process.returncode:
                            (output/f'{scenario}-{operation}-{index}.stderr').write_text(process.stderr)
                            raise RuntimeError('read_only_measurement_failed')
                        sample = json.loads(process.stdout)
                        samples[operation].append(sample)
                        (output/f'{scenario}-{operation}-{index}.json').write_text(json.dumps(sample, indent=2)+'\n')
                hashes = {row['resultSha256'] for group in samples.values() for sample in group
                    for row in sample['measurements']}
                if len(hashes) != 1:
                    raise RuntimeError('paired_result_mismatch')
                result = {'resultEquality': True, 'resultSha256': hashes.pop(),
                    'metadata': samples[operations[0]][0]['metadata'], 'phases': {}}
                for phase in ('cold', 'warm'):
                    baseline, optimized = [phase_summary(samples[op], phase) for op in operations]
                    result['phases'][phase] = {'baseline': baseline, 'optimized': optimized,
                        'wallRatioBaselineOverOptimized': baseline['wallSeconds']['median']/optimized['wallSeconds']['median']}
                report['results'][scenario][pair_name] = result
                print(json.dumps({'scenario': scenario, 'pair': pair_name, 'equality': True,
                    'warmRatio': result['phases']['warm']['wallRatioBaselineOverOptimized']}), flush=True)
                (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        report['status'] = 'passed'
    except BaseException:
        report['status'] = 'failed_or_interrupted'
        raise
    finally:
        report['inputFilesUnchanged'] = before == fingerprints(evidence)
        report['codeFilesUnchanged'] = all(hashlib.sha256((REPO/path).read_bytes()).hexdigest() == sha
            for path, sha in code.items())
        report['endedAtUnix'] = time.time()
        (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
        if not report['inputFilesUnchanged'] or not report['codeFilesUnchanged']:
            raise RuntimeError('measurement_inputs_changed')


if __name__ == '__main__':
    main()

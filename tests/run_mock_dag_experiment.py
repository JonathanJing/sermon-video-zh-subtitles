"""Run the existing two-unit SDK acceptance with durable progress and timings.

Usage: python -m tests.run_mock_dag_experiment --output-dir artifacts/new-run
This is a local synthetic test runner, never a production/resume dispatcher.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from tests.mock_experiment_progress import EVENTS, STATUSES

METHODS = {
    'happy': 'test_actual_full_graph_then_clean_process_receipt_only_repeat',
    'failure': 'test_actual_confirmed_failure_explicit_retry_keeps_successful_neighbor',
    'timeout': 'test_actual_ordinary_timeout_then_original_receipt_reconciliation',
}
REPO = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')
    temporary.replace(path)


def show_progress(output, scenario, seen):
    path = output/'progress.jsonl'
    if not path.exists() or path.stat().st_size > 1024*1024:
        return seen
    lines = path.read_text().splitlines()
    for line in lines[seen:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get('scenario') != scenario or row.get('event') not in EVENTS:
            continue
        safe = {'event': row['event'], 'scenario': scenario}
        if row.get('invocation') in (1, 2):
            safe['invocation'] = row['invocation']
        if row.get('status') in STATUSES:
            safe['status'] = row['status']
        print(json.dumps(safe), flush=True)
    return len(lines)


def run_scenario(scenario, output, env, *, heartbeat_seconds=30):
    command = [sys.executable, '-u', '-m', 'unittest',
        'tests.test_sermon_fresh_full_dag.ActualFreshFullPrefectTests.'+METHODS[scenario], '-v']
    started = time.monotonic()
    seen = 0
    record = {'scenario': scenario, 'startedAt': utc_now(), 'command': command,
              'status': 'running', 'exitCode': None}
    path = output/(scenario+'-timing.json')
    save(path, record)
    print(json.dumps({'event': 'scenario_started', 'scenario': scenario}), flush=True)
    with (output/(scenario+'.log')).open('x') as log:
        process = None
        try:
            process = subprocess.Popen(command, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
            while True:
                try:
                    code = process.wait(timeout=heartbeat_seconds)
                    seen = show_progress(output, scenario, seen)
                    break
                except subprocess.TimeoutExpired:
                    seen = show_progress(output, scenario, seen)
                    print(json.dumps({'event': 'scenario_running', 'scenario': scenario,
                        'elapsedSeconds': round(time.monotonic()-started, 3)}), flush=True)
        except KeyboardInterrupt:
            # Do not reinterpret interrupted observation as a failed remote job,
            # nor start another scenario. Existing child timeouts remain in force.
            record.update(status='interrupted_observation', wallSeconds=time.monotonic()-started,
                          childPid=process.pid if process is not None else None)
            save(path, record)
            raise
        except Exception as exc:
            record.update(status='runner_error', errorType=type(exc).__name__,
                          wallSeconds=time.monotonic()-started)
            save(path, record)
            raise
    record.update(status='passed' if code == 0 else 'failed', exitCode=code,
                  endedAt=utc_now(), wallSeconds=time.monotonic()-started)
    save(path, record)
    print(json.dumps({'event': 'scenario_finished', **record}), flush=True)
    return record


def require_candidate(commit):
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True)
    if actual != commit or dirty.strip():
        raise ValueError('experiment_candidate_changed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path,
                        help='New directory; existing evidence is never overwritten')
    parser.add_argument('--scenario', choices=tuple(METHODS), action='append',
                        help='Default: all three, fail-fast; each may be selected once')
    args = parser.parse_args(argv)
    scenarios = args.scenario or list(METHODS)
    if len(set(scenarios)) != len(scenarios):
        parser.error('duplicate scenarios are not allowed')
    # Check before creating evidence; the SDK also verifies identity independently.
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO, text=True)
    if dirty.strip():
        parser.error('commit the candidate first; actual SDK requires a clean worktree')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    output = args.output_dir.resolve()
    if output.is_relative_to(REPO):
        ignored = subprocess.run(['git', 'check-ignore', '-q', str(output)], cwd=REPO)
        if ignored.returncode != 0:
            parser.error('output inside the repository must be Git-ignored (for example artifacts/new-run)')
    output.mkdir(parents=True, exist_ok=False)
    progress = output/'progress.jsonl'
    progress.touch(mode=0o600)
    env = {key: value for key, value in os.environ.items() if not key.startswith('PREFECT_')}
    env.update(SERMON_TEST_PREFECT='1', SERMON_MOCK_EXPERIMENT_COMMIT=commit, SERMON_FRESH_FULL_TEST_EVIDENCE_DIR=str(output/'evidence'),
               SERMON_MOCK_EXPERIMENT_PROGRESS_FILE=str(progress))
    summary = {'schemaVersion': 'mock-experiment-run-v1', 'candidateSha': commit,
               'scope': 'local_two_unit_synthetic_candidate_not_production',
               'startedAt': utc_now(), 'status': 'running', 'scenarios': [],
               'timingScope': 'wall_time_including_sdk_processes_and_validation_not_critical_path',
               'requestedScenarios': scenarios}
    save(output/'summary.json', summary)
    try:
        for scenario in scenarios:
            require_candidate(commit)
            record = run_scenario(scenario, output, env)
            summary['scenarios'].append(record)
            require_candidate(commit)
            save(output/'summary.json', summary)
            if record['exitCode'] != 0:
                break
    except KeyboardInterrupt:
        summary.update(status='interrupted_observation', endedAt=utc_now())
        save(output/'summary.json', summary)
        return 130
    except Exception as exc:
        summary.update(status='runner_error', errorType=type(exc).__name__, endedAt=utc_now())
        save(output/'summary.json', summary)
        raise
    summary.update(status='passed' if all(r['exitCode'] == 0 for r in summary['scenarios']) else 'failed',
                   endedAt=utc_now())
    save(output/'summary.json', summary)
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

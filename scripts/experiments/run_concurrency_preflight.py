#!/usr/bin/env python3
"""Opt-in diagnostic command DAG. Preparation/preflight never starts a model.

Independent branches are bounded by the frozen profile. Leaf diagnostic scripts
own shared API/CLI/GPU admission; this runner does not double-reserve their slots.
An abandoned started node remains unknown and is never automatically reissued.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextvars import copy_context
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.production_concurrency_profile import validate_profile
from scripts.sermon_unified import resources
from scripts import sermon_workflow_jobs as jobs
from scripts import english_source_judge_cache as immutable

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'diagnostic-concurrency-command-plan-v1'
KINDS = {'source', 'layer2', 'audio', 'study_outline', 'study_meditation', 'manual'}
STUDY = {'study_outline', 'study_meditation'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def _hash(path):
    path = Path(path)
    require(not path.is_symlink(), 'diagnostic_artifact_symlink_forbidden')
    if path.is_file():
        return {'kind': 'file', 'sha256': _file_hash(path)}
    require(path.is_dir(), 'diagnostic_artifact_missing:' + str(path))
    entries = {}
    for entry in sorted(path.rglob('*')):
        require(not entry.is_symlink(), 'diagnostic_artifact_symlink_forbidden')
        if entry.is_file():
            entries[str(entry.relative_to(path))] = _file_hash(entry)
    require(bool(entries), 'diagnostic_output_directory_empty')
    return {'kind': 'directory', 'sha256': jobs._digest(entries), 'files': entries}


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path, value):
    if path.exists():
        require(jobs._read(path) == value, 'diagnostic_immutable_receipt_changed')
    else:
        immutable._atomic(path, value)


def _command(command):
    require(type(command) is list and len(command) >= 2 and all(type(a) is str and a and '\x00' not in a for a in command),
            'diagnostic_command_requires_argv')
    interpreter = Path(command[0]).absolute().resolve()
    allowed_python = {Path(sys.executable).resolve(), (ROOT / '.venv/bin/python').resolve()}
    require(interpreter in allowed_python and interpreter.is_file(), 'diagnostic_python_interpreter_not_allowed')
    raw_script = Path(command[1])
    script = (raw_script if raw_script.is_absolute() else ROOT / raw_script).resolve()
    require(script.is_relative_to(ROOT / 'scripts') and script.suffix == '.py' and script.is_file()
        and (script.is_relative_to(ROOT / 'scripts/experiments')
             or ('diagnostic' in script.stem and script.parent == ROOT / 'scripts')
             or script == ROOT / 'scripts/run_codex_layer2_test.py')
        and script != Path(__file__).resolve(), 'diagnostic_script_not_allowed')
    return [str(interpreter), str(script), *command[2:]], {
        'interpreterSha256': hashlib.sha256(interpreter.read_bytes()).hexdigest(),
        'scriptSha256': hashlib.sha256(script.read_bytes()).hexdigest()}


def _path(raw):
    path = Path(raw).absolute()
    require(path.is_relative_to(ROOT / 'artifacts') and '..' not in path.parts and not path.is_symlink(),
            'diagnostic_artifact_path_not_allowed')
    require(path.resolve().is_relative_to(ROOT / 'artifacts'), 'diagnostic_artifact_path_not_allowed')
    return path.resolve()


def _input_path(raw):
    path = Path(raw).absolute()
    require(path.is_relative_to(ROOT) and '..' not in path.parts and not path.is_symlink()
        and path.relative_to(ROOT).parts and path.relative_to(ROOT).parts[0] in {'artifacts', 'config', 'scripts', 'docs'},
        'diagnostic_input_path_not_allowed')
    require(path.resolve().is_relative_to(ROOT), 'diagnostic_input_path_not_allowed')
    return path.resolve()


def prepare(plan, out_dir):
    """Freeze an immutable plan. Missing/unimplemented commands are manual nodes."""
    out = _path(out_dir)
    require(out != ROOT / 'artifacts', 'diagnostic_batch_requires_dedicated_output')
    require(type(plan) is dict and set(plan) == {'profile', 'resourcePolicy', 'nodes'}, 'invalid_diagnostic_command_plan')
    profile = validate_profile(plan['profile'])
    policy = resources.validate_policy(plan['resourcePolicy'])
    require(policy['capacities']['codex_cli'] == profile['totalCodexSlots']
        and policy['capacities']['online_api'] == profile['sourceASRWorkers'], 'diagnostic_shared_capacity_mismatch')
    require(type(plan['nodes']) is list and 1 <= len(plan['nodes']) <= 256, 'diagnostic_nodes_required')
    nodes, names = [], set()
    for raw in plan['nodes']:
        require(type(raw) is dict and {'id', 'kind', 'dependsOn', 'command', 'inputs', 'outputs'} <= set(raw)
            and set(raw) <= {'id', 'kind', 'dependsOn', 'command', 'inputs', 'outputs', 'locale', 'timeoutSeconds'},
            'invalid_diagnostic_node')
        name = raw['id']
        require(type(name) is str and 1 <= len(name) <= 128 and all(c.isalnum() or c in '-_.' for c in name)
            and name not in names and raw['kind'] in KINDS, 'invalid_diagnostic_node_identity')
        require(type(raw['dependsOn']) is list and all(type(x) is str for x in raw['dependsOn'])
            and len(set(raw['dependsOn'])) == len(raw['dependsOn']) and name not in raw['dependsOn'], 'invalid_diagnostic_dependencies')
        require(type(raw['inputs']) is list and type(raw['outputs']) is list and all(type(p) is str for p in raw['inputs'] + raw['outputs']),
                'invalid_diagnostic_artifacts')
        timeout = raw.get('timeoutSeconds', 3600)
        require(type(timeout) is int and 1 <= timeout <= 21600, 'invalid_diagnostic_timeout')
        node = {**raw, 'timeoutSeconds': timeout, 'preparedStatus': 'ready', 'preparationIssues': []}
        if raw['command'] is None or raw['kind'] == 'manual':
            node.update(command=None, preparedStatus='prepared_manual')
            node['preparationIssues'].append('command_not_implemented')
        else:
            try:
                node['command'], node['commandIdentity'] = _command(raw['command'])
            except ValueError as exc:
                node['preparedStatus'] = 'prepared_manual'
                node['preparationIssues'].append(str(exc))
        node['inputs'], node['outputs'] = [str(_input_path(p)) for p in raw['inputs']], [str(_path(p)) for p in raw['outputs']]
        require(len(set(node['outputs'])) == len(node['outputs'])
            and all(Path(p) != out and Path(p) not in out.parents for p in node['outputs']), 'diagnostic_outputs_overlap_batch_state')
        nodes.append(node); names.add(name)
    by_id = {n['id']: n for n in nodes}
    require(sum(n['kind'] == 'source' for n in nodes) <= 1, 'diagnostic_source_node_limit')
    locales = [n.get('locale') for n in nodes if n['kind'] == 'layer2']
    require(len(locales) <= profile['maxActiveLocales'] and len(set(locales)) == len(locales)
        and all(type(locale) is str and locale for locale in locales), 'diagnostic_locale_limit')
    def ancestors(name, visiting=()):
        require(name not in visiting, 'diagnostic_dependency_cycle')
        result = set()
        for parent in by_id[name]['dependsOn']:
            require(parent in by_id, 'diagnostic_dependency_missing')
            result.add(parent); result.update(ancestors(parent, (*visiting, name)))
        return result
    output_owner = {}
    for node in nodes:
        for path in node['outputs']:
            require(not any(Path(path) == Path(prior) or Path(path) in Path(prior).parents
                or Path(prior) in Path(path).parents for prior in output_owner), 'diagnostic_output_has_multiple_writers')
            output_owner[path] = node['id']
    for node in nodes:
        upstream = ancestors(node['id'])
        if node['kind'] == 'audio':
            require(any(by_id[name]['kind'] == 'layer2' and by_id[name].get('locale') == node.get('locale')
                        for name in upstream), 'diagnostic_audio_requires_matching_layer2')
        if node['kind'] == 'layer2':
            require(all(n['id'] in upstream for n in nodes if n['kind'] == 'source'),
                    'diagnostic_layer2_requires_source_dependency')
        bindings = {}
        for raw_path in node['inputs']:
            path = Path(raw_path)
            if path.exists():
                bindings[raw_path] = {'mode': 'frozen', 'artifact': _hash(path)}
            elif raw_path in output_owner and output_owner[raw_path] in upstream:
                bindings[raw_path] = {'mode': 'dependency_output', 'producer': output_owner[raw_path]}
            else:
                bindings[raw_path] = {'mode': 'missing'}
                node['preparedStatus'] = 'prepared_manual'
                node['preparationIssues'].append('missing_input:' + raw_path)
        node['inputBindings'] = bindings
    frozen = {'schemaVersion': SCHEMA, 'diagnosticOnly': True, 'productionEligible': False,
        'humanApproval': False, 'profile': profile, 'resourcePolicy': policy,
        'sharedPolicySha256': resources._identity(policy), 'nodes': nodes,
        'implementationSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'outputDirectory': str(out)}
    _write(out / 'plan.json', frozen)
    return preflight(out)


def _load(out):
    out = _path(out)
    plan = jobs._read(out / 'plan.json')
    require(plan.get('schemaVersion') == SCHEMA and plan.get('diagnosticOnly') is True
        and plan.get('productionEligible') is False and plan.get('humanApproval') is False
        and plan.get('outputDirectory') == str(out)
        and plan.get('implementationSha256') == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'diagnostic_plan_identity_changed')
    validate_profile(plan['profile']); resources.validate_policy(plan['resourcePolicy'])
    require(resources._identity(plan['resourcePolicy']) == plan['sharedPolicySha256'], 'diagnostic_shared_policy_changed')
    return out, plan


def _paths(out, name):
    folder = out / 'nodes' / name
    return folder, folder / 'started.json', folder / 'terminal.json'


def preflight(out_dir):
    """Pure local checks, no owner claim, subprocess, model or broker reservation."""
    out, plan = _load(out_dir)
    statuses = {}
    for node in plan['nodes']:
        folder, started_path, terminal_path = _paths(out, node['id'])
        status = node['preparedStatus']
        if node['command'] is not None and status == 'ready':
            command, identity = _command(node['command'])
            require(command == node['command'] and identity == node['commandIdentity'], 'diagnostic_command_identity_changed')
        for path, binding in node['inputBindings'].items():
            if binding['mode'] == 'frozen':
                require(_hash(path) == binding['artifact'], 'diagnostic_input_identity_changed')
        if terminal_path.exists():
            terminal = jobs._read(terminal_path)
            require(started_path.exists() and terminal.get('planSha256') == jobs._digest(plan)
                and terminal.get('startedSha256') == jobs._digest(jobs._read(started_path)), 'diagnostic_terminal_identity_changed')
            status = terminal['status']
            require(status in {'completed', 'failed'}, 'diagnostic_terminal_status_invalid')
            if status == 'completed':
                require(all(_hash(p) == value for p, value in terminal['outputs'].items())
                    and set(terminal['outputs']) == set(node['outputs']), 'diagnostic_completed_output_changed')
                require(all(_hash(p) == value for p, value in jobs._read(started_path)['inputs'].items()),
                        'diagnostic_completed_input_changed')
        elif started_path.exists():
            started = jobs._read(started_path)
            require(started.get('planSha256') == jobs._digest(plan), 'diagnostic_started_identity_changed')
            status = 'unknown_outcome'
        statuses[node['id']] = {'status': status, 'issues': node['preparationIssues']}
    blocked = any(row['status'] in {'prepared_manual', 'failed', 'unknown_outcome'} for row in statuses.values())
    return {'schemaVersion': 'diagnostic-command-preflight-v1', 'status': 'blocked' if blocked else 'ready',
        'diagnosticOnly': True, 'productionEligible': False, 'humanApproval': False, 'modelCalls': 0,
        'sparkSessionRequiredForExecution': True,
        'planSha256': jobs._digest(plan), 'maxBranches': plan['profile']['maxBranches'],
        'studyBranches': plan['profile']['studyBranches'], 'nodes': statuses}


def _spark_session(session_id=None, owner=None):
    from scripts.spark_exclusive_session import Client
    return Client.from_environment(session_id=session_id, owner=owner)


def _executor(command, *, cwd, timeout, env=None):
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False, env=env)
    return {'returncode': process.returncode, 'stdout': process.stdout, 'stderr': process.stderr}


def run(out_dir, *, execute=False, executor=None, spark_session_id=None, spark_session_owner=None):
    if execute is not True:
        return preflight(out_dir)
    out, plan = _load(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'owner.lock').open('a') as owner_lock:
        try:
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('diagnostic_batch_already_running') from None
        snapshot = preflight(out)
        statuses = [row['status'] for row in snapshot['nodes'].values()]
        if not any(status == 'ready' for status in statuses) or any(status in {'unknown_outcome', 'failed'} for status in statuses):
            return _run_owned(out, plan, executor or _executor, None)
        session = _spark_session(spark_session_id, spark_session_owner)
        session.require_ready()
        hold = session.start_job('diagnostic-command-dag.' + jobs._digest(plan)[:32], pid=os.getpid())
        # An exception or a child with uncertain outcome keeps the host-level
        # hold. Closing the whole development session is an explicit action.
        result = _run_owned(out, plan, executor or _executor, session)
        if not any(row['status'] == 'unknown_outcome' for row in result['nodes'].values()):
            session.end_job(hold, process_exited=True, outcome='known_terminal')
        return result


def _run_owned(out, plan, executor, session):
    snapshot = preflight(out)
    statuses = {name: row['status'] for name, row in snapshot['nodes'].items()}
    # An unknown owner blocks ALL further dispatch before any sibling call.
    if any(s in {'unknown_outcome', 'failed'} for s in statuses.values()):
        return {**snapshot, 'executed': False, 'reason': 'reconciliation_required'}
    owner = {'token': uuid.uuid4().hex, 'pid': os.getpid()}
    plan_sha = jobs._digest(plan)
    def leaf(node):
        folder, started_path, terminal_path = _paths(out, node['id'])
        command, command_identity = _command(node['command'])
        require(command == node['command'] and command_identity == node['commandIdentity'],
                'diagnostic_command_identity_changed')
        input_hashes = {}
        for path, binding in node['inputBindings'].items():
            current = _hash(path)
            if binding['mode'] == 'frozen':
                require(current == binding['artifact'], 'diagnostic_input_identity_changed')
            elif binding['mode'] == 'dependency_output':
                _, _, parent_terminal = _paths(out, binding['producer'])
                parent = jobs._read(parent_terminal)
                require(parent['status'] == 'completed' and parent['outputs'][path] == current,
                        'diagnostic_dependency_output_changed')
            input_hashes[path] = current
        session.require_ready()
        started = {'schemaVersion': 'diagnostic-node-started-v1', 'planSha256': plan_sha,
            'nodeId': node['id'], 'owner': owner, 'commandIdentity': node['commandIdentity'],
            'inputs': input_hashes, 'status': 'started_response_unconfirmed', 'startedAtUnix': time.time()}
        require(not started_path.exists() and not terminal_path.exists(), 'diagnostic_node_never_reissued')
        _write(started_path, started)
        begin = time.monotonic()
        try:
            response = executor(node['command'], cwd=str(ROOT), timeout=node['timeoutSeconds'],
                env={**os.environ, **session.environment})
            require(type(response) is dict and type(response.get('returncode')) is int
                and isinstance(response.get('stdout', ''), str) and isinstance(response.get('stderr', ''), str),
                'diagnostic_executor_response_invalid')
            # Child logs are private artifacts, never copied into the git report.
            folder.mkdir(parents=True, exist_ok=True)
            for name in ('stdout', 'stderr'):
                path = folder / (name + '.txt')
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as handle:
                    handle.write(response.get(name, '')); handle.flush(); os.fsync(handle.fileno())
            outputs = {path: _hash(path) for path in node['outputs']} if response['returncode'] == 0 else {}
            terminal = {'schemaVersion': 'diagnostic-node-terminal-v1', 'planSha256': plan_sha,
                'nodeId': node['id'], 'startedSha256': jobs._digest(started),
                'status': 'completed' if response['returncode'] == 0 else 'failed',
                'exitCode': response['returncode'], 'outputs': outputs,
                'elapsedSeconds': time.monotonic() - begin, 'completedAtUnix': time.time(),
                'diagnosticOnly': True, 'productionEligible': False, 'humanApproval': False}
            _write(terminal_path, terminal)
            return terminal['status']
        except BaseException as exc:
            _write(folder / 'unknown.json', {'status': 'unknown_outcome', 'errorType': type(exc).__name__,
                'planSha256': plan_sha, 'startedSha256': jobs._digest(started)})
            return 'unknown_outcome'
    by_id = {node['id']: node for node in plan['nodes']}
    pending, peak, study_peak, halted = {}, 0, 0, False
    with ThreadPoolExecutor(max_workers=plan['profile']['maxBranches']) as pool:
        while True:
            if not halted:
                for node in plan['nodes']:
                    if len(pending) >= plan['profile']['maxBranches']:
                        break
                    if statuses[node['id']] != 'ready' or not all(statuses[p] == 'completed' for p in node['dependsOn']):
                        continue
                    live_study = sum(by_id[name]['kind'] in STUDY for name in pending.values())
                    if node['kind'] in STUDY and live_study >= plan['profile']['studyBranches']:
                        continue
                    statuses[node['id']] = 'running'
                    pending[pool.submit(copy_context().run, leaf, node)] = node['id']
                    peak = max(peak, len(pending))
                    study_peak = max(study_peak, live_study + (node['kind'] in STUDY))
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                name = pending.pop(future)
                try:
                    statuses[name] = future.result()
                except BaseException:
                    # Pre-dispatch artifact/admission error is not a model call.
                    _, started, _ = _paths(out, name)
                    statuses[name] = 'unknown_outcome' if started.exists() else 'blocked_before_dispatch'
                if statuses[name] != 'completed':
                    halted = True
    success = all(status == 'completed' for status in statuses.values())
    result = {'schemaVersion': 'diagnostic-command-run-v1', 'status': 'completed' if success else 'blocked',
        'executed': True, 'diagnosticOnly': True, 'productionEligible': False, 'humanApproval': False,
        'planSha256': plan_sha, 'peakBranches': peak, 'peakStudyBranches': study_peak,
        'nodes': {name: {'status': status} for name, status in statuses.items()}}
    # Snapshot may evolve when independent ready nodes are added only in a NEW
    # plan. Resume under this plan keeps immutable completed node receipts.
    immutable._atomic(out / 'latest-run.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'preflight', 'run'))
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--spark-session-id')
    parser.add_argument('--spark-session-owner')
    parser.add_argument('--execute', action='store_true', help='Explicitly execute approved diagnostic commands')
    args = parser.parse_args()
    if args.command == 'prepare':
        require(args.plan is not None, 'diagnostic_input_plan_required')
        result = prepare(jobs._read(args.plan), args.out_dir)
    elif args.command == 'preflight':
        result = preflight(args.out_dir)
    else:
        result = run(args.out_dir, execute=args.execute, spark_session_id=args.spark_session_id,
            spark_session_owner=args.spark_session_owner)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in ('ready', 'completed') else 2


if __name__ == '__main__':
    raise SystemExit(main())

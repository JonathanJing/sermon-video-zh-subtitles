"""Compose the existing PDF supervisor with opt-in, durable release jobs.

Only local code sees configuration paths and evidence. The Agents API adapter
exports a separate minimal allowlist; no model chooses subprocess arguments.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

from scripts import sermon_production_supervisor as production

ACTIONS = ('generate_audio_candidate', 'sync_audio', 'build_page', 'prepare_release',
           'deploy_release', 'verify_release', 'record_published')
WAIT_ACTIONS = ('wait_for_workflow_job', 'inspect_workflow_job_failure',
                'inspect_workflow_evidence', 'waiting_audio_review',
                'waiting_release_authorization', 'waiting_release_configuration',
                'waiting_source_or_voice', 'waiting_evidence_repair',
                'waiting_outcome_reconciliation', 'waiting_timing_review')


def configuration(config):
    path = getattr(config, 'release_workflow_config', None)
    if path is None:
        return None
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError('Release workflow config must be a regular local file')
    return path.resolve()


def config_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def job_root(config, path):
    root = Path(config.work_root).resolve() / 'release-jobs' / config.sunday / config_hash(path)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Release job paths must not contain symlinks')
    return root


def _recommend(action, human=False):
    return {'action': action, 'reason': action, 'humanActionRequired': human}


def _inspect_job(root, job_id):
    from scripts.sermon_workflow_jobs import inspect_job
    try:
        return inspect_job(root, job_id)
    except FileNotFoundError:
        # A persisted launch intent without a job needs reconciliation, not retry.
        return {'jobId': job_id, 'status': 'uncertain'}


def _outstanding_jobs(root):
    """Discover durable jobs even if an older launcher lost its active pointer."""
    if not root.parent.exists():
        return
    for config_root in sorted(root.parent.iterdir()):
        if not re.fullmatch(r'[a-f0-9]{64}', config_root.name):
            continue
        if config_root.is_symlink() or not config_root.is_dir():
            raise ValueError('Invalid release job directory')
        ids = {p.name for p in config_root.iterdir()
               if re.fullmatch(r'[a-f0-9]{64}', p.name)}
        pointer = config_root / 'active.json'
        if pointer.is_symlink():
            raise ValueError('Invalid release job pointer')
        if pointer.exists():
            ids.add(json.loads(pointer.read_text())['jobId'])
        for job_id in sorted(ids):
            job = _inspect_job(config_root, job_id)
            if job['status'] in ('queued', 'running', 'uncertain'):
                yield config_root, job


def snapshot(config):
    upstream = production.production_snapshot(config)
    path = configuration(config)
    if path is None:
        return upstream
    from scripts import sermon_release_workflow as release
    # Validate opt-in configuration even while upstream is waiting.
    release.load_config(path)
    result = dict(upstream)
    result['workflowScope'] = 'page_release'
    result['workflowComplete'] = False
    if (upstream.get('recommendedAction') or {}).get('action') != 'complete':
        # Do not start new upstream mutations over an outstanding downstream job.
        root = job_root(config, path)
        for _, job in _outstanding_jobs(root):
            result['workflowJob'] = job
            result['recommendedAction'] = _recommend(
                'inspect_workflow_job_failure' if job['status'] == 'uncertain' else 'wait_for_workflow_job',
                job['status'] == 'uncertain')
            break
        return result
    downstream = release.snapshot(path, config.sunday)
    source_root = (downstream.get('evidence') or {}).get('sourceRunRoot')
    upstream_root = (upstream.get('locations') or {}).get('runRoot')
    if source_root and (not upstream_root or Path(source_root).resolve() != Path(upstream_root).resolve()):
        raise ValueError('Release source does not match the current upstream production run')
    result['releaseWorkflow'] = downstream
    recommended = downstream.get('recommendedAction')
    if not isinstance(recommended, dict):
        recommended = _recommend(recommended or 'inspect_workflow_evidence', downstream.get('humanActionRequired', True))
    result['recommendedAction'] = recommended
    root = job_root(config, path)
    # A configuration change cannot abandon a still-running or uncertain job.
    for previous, prior in _outstanding_jobs(root):
        result['workflowJob'] = prior
        human = previous != root or prior['status'] == 'uncertain'
        result['recommendedAction'] = _recommend(
            'inspect_workflow_job_failure' if human else 'wait_for_workflow_job', human)
        return result
    active = root / 'active.json'
    if active.exists():
        if active.is_symlink():
            raise ValueError('Invalid active release job pointer')
        pointer = json.loads(active.read_text())
        state = _inspect_job(root, pointer['jobId'])
        result['workflowJob'] = state
        if state['status'] in ('queued', 'running'):
            result['recommendedAction'] = _recommend('wait_for_workflow_job')
        elif state['status'] != 'succeeded':
            result['recommendedAction'] = _recommend('inspect_workflow_job_failure', True)
        elif recommended.get('action') == pointer['action']:
            # Exit zero is not completion evidence. Never repeat an operation
            # simply because its expected artifact was not observed.
            result['recommendedAction'] = _recommend('inspect_workflow_evidence', True)
    result['workflowComplete'] = result['recommendedAction'].get('action') == 'complete'
    return result


def start_action(config, action):
    path = configuration(config)
    if path is None:
        return {'status': 'blocked'}
    from scripts.sermon_workflow_jobs import _lock, _digest
    # Serialize admission across configurations, and recheck evidence under lock.
    week_root = job_root(config, path).parent
    with _lock(week_root, _digest({'purpose': 'release-admission'})) as (_, _, held):
        if not held:
            return {'status': 'blocked'}
        return _start_action_locked(config, action)


def _start_action_locked(config, action):
    if action not in ACTIONS:
        raise ValueError('Unknown release operation')
    current = snapshot(config)
    rec = current.get('recommendedAction') or {}
    if rec.get('action') != action or rec.get('humanActionRequired'):
        return {'status': 'blocked'}
    path = configuration(config)
    if path is None:
        return {'status': 'blocked'}
    digest = config_hash(path)
    root = job_root(config, path)
    # The downstream config fixes the work/source/release; each stage is allowed
    # one durable attempt for this configuration, across all agent sessions.
    identity = {'schemaVersion': 1, 'sunday': config.sunday, 'configSha256': digest, 'action': action}
    command = [config.python_executable, str(Path(__file__).with_name('sermon_release_workflow.py')),
               '--config', str(path), '--sunday', config.sunday, '--action', action,
               '--expected-config-sha', digest]
    source_root = (current.get('locations') or {}).get('runRoot')
    if not source_root:
        raise ValueError('Current production source run is required for release execution')
    command.extend(['--expected-source-run-root', str(Path(source_root).resolve())])
    from scripts.sermon_workflow_jobs import start_job, _digest, _persist
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _persist(root / 'active.json', {'jobId': _digest(identity), 'action': action})
    return start_job(root, identity, command, timeout_seconds=21600)

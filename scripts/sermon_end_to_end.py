"""Compose the existing PDF supervisor with opt-in, durable release jobs.

Only local code sees configuration paths and evidence. The Agents API adapter
exports a separate minimal allowlist; no model chooses subprocess arguments.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

from scripts import sermon_production_supervisor as production
from scripts.sermon_agents_api import _write_json

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
        if root.parent.exists():
            from scripts.sermon_workflow_jobs import inspect_job
            for pointer_path in root.parent.glob('*/active.json'):
                if pointer_path.is_symlink() or pointer_path.parent.is_symlink():
                    raise ValueError('Invalid release job pointer')
                saved = json.loads(pointer_path.read_text())
                job = inspect_job(pointer_path.parent, saved['jobId'])
                if job['status'] in ('queued', 'running', 'uncertain'):
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
    from scripts.sermon_workflow_jobs import inspect_job
    if root.parent.exists():
        for previous in root.parent.glob('*/active.json'):
            if previous.parent == root:
                continue
            if previous.is_symlink() or previous.parent.is_symlink():
                raise ValueError('Invalid previous release job pointer')
            saved = json.loads(previous.read_text())
            prior = inspect_job(previous.parent, saved['jobId'])
            if prior['status'] in ('queued', 'running', 'uncertain'):
                result['workflowJob'] = prior
                result['recommendedAction'] = _recommend('inspect_workflow_job_failure', True)
                return result
    active = root / 'active.json'
    if active.exists():
        if active.is_symlink():
            raise ValueError('Invalid active release job pointer')
        pointer = json.loads(active.read_text())
        from scripts.sermon_workflow_jobs import inspect_job
        state = inspect_job(root, pointer['jobId'])
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
    from scripts.sermon_workflow_jobs import start_job
    state = start_job(root, identity, command, timeout_seconds=21600)
    _write_json(root / 'active.json', {'jobId': state['jobId'], 'action': action})
    return state

"""Read-only bridge between canonical package evidence and existing durable jobs.

This module has no worker, queue, command builder or dispatch authority. It reads
sermon_workflow_jobs receipts, preserving unknown outcomes even when artifacts
look complete. Future execution must revalidate this view under its admission
lock and keep one stable job root for the production run across revisions.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import canonical_pipeline_definition as pipeline
from scripts import inspect_canonical_packages as packages
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

IDENTITY_SCHEMA = 'sermon-canonical-workflow-job-identity-v1'
VIEW_SCHEMA = 'sermon-canonical-durable-job-inspection-v1'
RECONCILIATION_SCHEMA = 'sermon-canonical-artifact-reconciliation-v1'
RECONCILIATION_FILE = 'canonical-reconciliation.json'
MAX_JOBS = 4096
MAX_REQUEST_BYTES = 1024 * 1024
IDENTITY_FIELDS = {'schemaVersion', 'productionRunId', 'workflowDefinitionVersion',
                   'workUnitId', 'nodeIdentity', 'inputIdentitySha256'}


def _input_identity(view, unit):
    """Bind a node's actual upstream evidence, excluding its own future outputs.

    Unrelated locale outputs cannot change this identity. The nodeIdentity also
    binds definition, Source and dependency outputs through the canonical DAG.
    This is an observation identity, not permission to execute a command.
    """
    phase, _, locale = unit.partition('.')
    hashes = view['packageIdentities']
    selected = {k: v for k, v in hashes.items() if k in
                {'source', 'anchor', 'sourceSummary', 'sourceWindowReview'}}
    if locale:
        for name in ('policy', 'candidate', 'review')[:{'text': 1, 'audio': 3, 'page': 3}[phase]]:
            key = name + '.' + locale
            if key in hashes:
                selected[key] = hashes[key]
        if phase in {'audio', 'page'}:
            audio_prefix = 'audio.' + locale + '.'
            input_names = {'job', 'adapter', 'registry', 'clipTimelineMap',
                           'clipVoiceAuthorization', 'sourceVoiceAuthorization', 'clipVoiceCapability'}
            selected.update({k: v for k, v in hashes.items()
                             if k.startswith(audio_prefix) and
                             (phase == 'page' or k[len(audio_prefix):] in input_names)})
        if phase == 'page':
            key = 'release.' + locale + '.contentReview'
            if key in hashes:
                selected[key] = hashes[key]
    return jobs._digest(selected)


def identity(view, production_run_id, unit):
    """Identity for a trusted backend's canonical job; contains no local paths."""
    if (not pipeline._sha(production_run_id) or unit not in view['nodes']
            or not pipeline._sha(view['nodes'][unit].get('identity'))):
        raise ValueError('canonical_job_requires_bound_node')
    return {'schemaVersion': IDENTITY_SCHEMA, 'productionRunId': production_run_id,
            'workflowDefinitionVersion': pipeline.VERSION, 'workUnitId': unit,
            'nodeIdentity': view['nodes'][unit]['identity'],
            'inputIdentitySha256': _input_identity(view, unit)}


def _valid_identity(value, production_run_id, known):
    return (isinstance(value, dict) and set(value) == IDENTITY_FIELDS
            and value['schemaVersion'] == IDENTITY_SCHEMA
            and value['productionRunId'] == production_run_id
            and value['workflowDefinitionVersion'] == pipeline.VERSION
            and isinstance(value['workUnitId'], str) and value['workUnitId'] in known
            and pipeline._sha(value['nodeIdentity']) and pipeline._sha(value['inputIdentitySha256']))


def _receipts(root, production_run_id, known):
    if not root.exists():
        return [], []
    if not root.is_dir():
        raise ValueError('invalid_canonical_job_root')
    # A bounded scan never treats a truncated directory listing as complete.
    names = []
    for entry in root.iterdir():
        if entry.name == '.locks':
            if entry.is_symlink() or not entry.is_dir():
                raise ValueError('invalid_canonical_lock_root')
            continue
        if len(names) >= MAX_JOBS or not re.fullmatch(r'[a-f0-9]{64}', entry.name):
            return [], ['unrecognized_or_excess_canonical_job_evidence']
        names.append(entry.name)
    receipts, errors = [], []
    for job_id in sorted(names):
        try:
            folder = _safe_path(root / job_id)
            request_path = _safe_path(folder / 'request.json')
            if request_path.stat().st_size > MAX_REQUEST_BYTES:
                raise ValueError('oversized_job_request')
            request = jobs._read(request_path)
            ident = request.get('identity') if isinstance(request, dict) else None
            if not jobs._request_valid(request, job_id) or not _valid_identity(ident, production_run_id, known):
                raise ValueError('unbound_canonical_job_request')
            before_state = jobs._state(folder, job_id)
            status = jobs.peek_job(root, job_id)['status']
            # Detect a request replacement during inspection, rather than join
            # one request's identity to another request's state.
            if jobs._read(request_path) != request or jobs._state(folder, job_id) != before_state:
                raise ValueError('canonical_job_request_changed')
            row = {'jobId': job_id, 'status': status, 'identity': ident,
                   'requestSha256': jobs._digest(request), 'stateSha256': jobs._digest(before_state)}
            reconciliation_path = _safe_path(folder / RECONCILIATION_FILE)
            if reconciliation_path.exists():
                if reconciliation_path.stat().st_size > MAX_REQUEST_BYTES:
                    raise ValueError('oversized_reconciliation')
                receipt = jobs._read(reconciliation_path)
                state = before_state
                required = {'schemaVersion', 'jobId', 'requestSha256', 'stateSha256', 'identity',
                            'validatedOutputSha256', 'configurationSha256', 'codeIdentitySha256', 'resolution'}
                if (not isinstance(receipt, dict) or set(receipt) != required
                        or receipt['schemaVersion'] != RECONCILIATION_SCHEMA
                        or receipt['jobId'] != job_id or receipt['identity'] != ident
                        or not ident['workUnitId'].startswith('text.')
                        or receipt['requestSha256'] != jobs._digest(request)
                        or state is None or receipt['stateSha256'] != jobs._digest(state)
                        or state.get('requestSha256') != jobs._digest(request)
                        or status not in {'failed', 'uncertain'}
                        or receipt['resolution'] != 'validated_artifact_command_outcome_unchanged'
                        or any(not pipeline._sha(receipt[k]) for k in
                               ('validatedOutputSha256', 'configurationSha256', 'codeIdentitySha256'))):
                    raise ValueError('invalid_artifact_reconciliation')
                row['reconciliation'] = receipt
            receipts.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            errors.append('unreadable_or_unbound_canonical_job')
    return receipts, sorted(set(errors))


def inspect(config_path, job_root, production_run_id):
    if not pipeline._sha(production_run_id):
        raise ValueError('invalid_production_run_id')
    return project(packages.inspect(config_path), job_root, production_run_id)


def project(observed, job_root, production_run_id):
    """Join a trusted backend's already-validated package view with job facts."""
    if not pipeline._sha(production_run_id):
        raise ValueError('invalid_production_run_id')
    root = _safe_path(Path(job_root).absolute())
    result = copy.deepcopy(observed)
    known = set(observed['nodes'])
    receipts, errors = _receipts(root, production_run_id, known)
    by_unit = {unit: [] for unit in known}
    for row in receipts:
        unit = row['identity']['workUnitId']
        if 'reconciliation' in row:
            state = observed['nodes'][unit]
            expected = identity(observed, production_run_id, unit) if state.get('identity') else None
            receipt = row['reconciliation']
            if (row['identity'] == expected and state['status'] == 'validated'
                    and observed['packageIdentities'].get('candidate.' + unit[5:]) == receipt['validatedOutputSha256']):
                row['observedStatus'] = row['status']
                row['status'] = 'artifact_reconciled'
            # Stale/missing output does not erase uncertainty or permit retry.
        by_unit[unit].append(row)
    blocked = set()
    for unit, state in result['nodes'].items():
        rows = by_unit[unit]
        if not rows:
            continue
        expected = identity(observed, production_run_id, unit) if state.get('identity') else None
        relevant = [row for row in rows if row['status'] != 'succeeded' or row['identity'] == expected]
        if not relevant:
            continue  # A completed prior revision never validates the new one.
        status, reason = None, None
        if any(row['status'] == 'uncertain' or row['identity'] != expected for row in relevant):
            status, reason = 'reconciliation_required', 'unknown_or_changed_identity_job'
        elif any(row['status'] == 'failed' for row in relevant):
            status, reason = 'blocked', 'failed_durable_job'
        elif any(row['status'] in jobs.ACTIVE for row in relevant):
            status, reason = 'waiting_job', 'durable_job_active'
        elif state['status'] != 'validated':
            status, reason = 'reconciliation_required', 'job_success_without_validated_package'
        if status:
            state.update(status=status, reasonCode=reason)
            blocked.add(unit)
    # Never let a pre-existing downstream artifact conceal an outstanding
    # upstream mutation. Other locale branches retain their own readiness.
    locales = tuple(unit[5:] for unit in known if unit.startswith('text.'))
    spec = pipeline.definition(locales)
    for node in spec['nodes']:
        unit = node['id']
        if errors:
            result['nodes'][unit].update(status='reconciliation_required', reasonCode='unbound_job_evidence')
        elif unit not in blocked and any(dep in blocked for dep in node['depends_on']):
            result['nodes'][unit].update(status='waiting_dependency', reasonCode='upstream_durable_job_unsettled')
            blocked.add(unit)
    result['status'] = ('terminal_evidence_observed' if all(result['nodes'][n]['status'] == 'validated'
                         for n in spec['terminalDependencies']) else 'in_progress')
    result['durableJobInspection'] = {
        'schemaVersion': VIEW_SCHEMA, 'productionRunId': production_run_id,
        'jobs': [{'jobId': row['jobId'], 'status': row['status'],
                  'workUnitId': row['identity']['workUnitId'],
                  'identitySha256': jobs._digest(row['identity']),
                  'requestSha256': row['requestSha256'], 'stateSha256': row['stateSha256'],
                  **({'originalJobStatus': row['observedStatus'],
                      'reconciliationSha256': jobs._digest(row['reconciliation'])}
                     if 'observedStatus' in row else {})} for row in receipts],
        'diagnostics': errors, 'readOnly': True,
    }
    result['stateRevision'] = jobs._digest({'packageRevision': observed['stateRevision'],
                                           'durableJobs': result['durableJobInspection']})
    result['dispatchEnabled'] = False
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--job-root', required=True, type=Path)
    parser.add_argument('--production-run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.config, args.job_root, args.production_run_id), sort_keys=True))


if __name__ == '__main__':
    main()

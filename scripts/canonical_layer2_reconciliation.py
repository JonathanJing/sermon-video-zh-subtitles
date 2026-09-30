"""Explicit artifact reconciliation; never retry a worker or rewrite job history.

A validated candidate can settle the canonical work unit after its owner exited
without a final success receipt. The original command outcome stays unchanged.
This cannot settle a missing/invalid candidate or authorize another paid call.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import canonical_layer2_controller as layer2
from scripts import canonical_durable_jobs as durable
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path


def reconcile(config_path, locale, expected_revision):
    layer2.require(durable.pipeline._sha(expected_revision), 'expected_revision_required')
    config = layer2.load_configuration(config_path)
    code = layer2.code_identity()
    layer2.require(locale in config.lanes, 'locale_not_registered')
    unit = 'text.' + locale
    # Read the same concrete state the operator saw before creating any locks.
    initial = layer2.snapshot(config)
    layer2.require(initial['stateRevision'] == expected_revision, 'stale_reconciliation_revision')
    candidate_view = layer2.package_view(config)
    layer2.require(candidate_view['nodes'][unit]['status'] == 'validated', 'validated_candidate_required')
    ident = durable.identity(candidate_view, config.run_id, unit)
    key = jobs._digest(ident)
    folder = _safe_path(config.job_root / key)
    layer2.require(folder.is_dir(), 'existing_durable_job_required')
    with jobs._lock(config.job_root, layer2.ADMISSION_LOCK) as (_, _, admitted):
        layer2.require(admitted, 'admission_busy')
        # Verify the revision before taking the job lock: holding it ourselves
        # would make a separate read-only probe look like a live worker owner.
        admitted_config = layer2.load_configuration(config.path)
        layer2.require(admitted_config.sha256 == config.sha256 and layer2.code_identity() == code,
                       'configuration_or_code_changed')
        admitted_view = layer2.snapshot(admitted_config)
        layer2.require(admitted_view['stateRevision'] == expected_revision, 'stale_reconciliation_revision')
        admitted_row = next((row for row in admitted_view['durableJobInspection']['jobs']
                             if row['jobId'] == key), None)
        layer2.require(admitted_row is not None, 'existing_bound_job_required')
        with jobs._lock(config.job_root, key) as (folder, _, held):
            layer2.require(held, 'job_owner_still_active')
            with work_lock(config.lanes[locale]['output']):
                fresh_config = layer2.load_configuration(config.path)
                layer2.require(fresh_config.sha256 == config.sha256 and layer2.code_identity() == code,
                               'configuration_or_code_changed')
                view = layer2.package_view(fresh_config)
                layer2.require(view['stateRevision'] == candidate_view['stateRevision']
                               and view['nodes'][unit]['status'] == 'validated'
                               and durable.identity(view, config.run_id, unit) == ident,
                               'candidate_or_upstream_changed')
                layer2._inputs(fresh_config, locale, view)
                request = jobs._read(folder / 'request.json')
                state = jobs._state(folder, key)
                layer2.require(jobs._request_valid(request, key) and request['identity'] == ident
                               and request['command'] == layer2._worker_command(config, locale, key, code)
                               and request['timeoutSeconds'] == 21600.0
                               and state is not None and state.get('requestSha256') == jobs._digest(request)
                               and admitted_row['requestSha256'] == jobs._digest(request)
                               and admitted_row['stateSha256'] == jobs._digest(state),
                               'original_execution_binding_changed')
                layer2.require(state['status'] in {'queued', 'running', 'uncertain', 'failed'},
                               'job_does_not_require_artifact_reconciliation')
                receipt = {
                    'schemaVersion': durable.RECONCILIATION_SCHEMA,
                    'jobId': key, 'requestSha256': jobs._digest(request),
                    'stateSha256': jobs._digest(state), 'identity': ident,
                    'validatedOutputSha256': view['packageIdentities']['candidate.' + locale],
                    'configurationSha256': config.sha256, 'codeIdentitySha256': code,
                    'resolution': 'validated_artifact_command_outcome_unchanged',
                }
                path = _safe_path(folder / durable.RECONCILIATION_FILE)
                if path.exists():
                    layer2.require(jobs._read(path) == receipt, 'immutable_reconciliation_conflict')
                else:
                    # Atomic durable publication under the job lock. Never
                    # update state.json, request.json, logs or a prior receipt.
                    jobs._persist(path, receipt)
                # A prior interruption after rename but before directory fsync
                # can be resumed without overwriting the matching receipt.
                with path.open('rb') as stream:
                    jobs.os.fsync(stream.fileno())
                jobs._sync_directory_ancestry(folder)
                return {'schemaVersion': 'sermon-canonical-layer2-reconciliation-result-v1',
                        'status': 'artifact_reconciled', 'jobId': key, 'workUnitId': unit,
                        'receiptSha256': jobs._digest(receipt), 'originalJobStatus': state['status'],
                        'candidateJsonSha256': receipt['validatedOutputSha256'],
                        'modelCalls': 0, 'runtimeCodexTurns': 0, 'humanApprovalCreated': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--locale', required=True, choices=layer2.pipeline.LOCALES)
    parser.add_argument('--expected-state-revision', required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.config, args.locale, args.expected_state_revision), sort_keys=True))


if __name__ == '__main__':
    main()

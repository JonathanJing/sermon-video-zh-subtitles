#!/usr/bin/env python3
"""Opt-in durable producer of an approved local App delivery bundle.

Consumes existing products and supplied human receipts. It neither generates
sermon content nor publishes/sends notifications. Legacy PDF scopes are separate.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sermon_app_delivery as app
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock, WorkAlreadyRunning
from scripts.sermon_release_workflow import _safe_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / 'schemas/sermon-app-delivery-workflow-v1.schema.json'
SCOPE = 'app_delivery_readiness'
ACTION = 'prepare_app_delivery'
TIMEOUT_SECONDS = 21600


@dataclass(frozen=True)
class Configuration:
    path: Path
    plan: Path
    jobs: Path
    output: Path
    sunday: str
    sha256: str


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def _route_root(config):
    # Stable across config byte/path-field revisions, before a jobRoot exists.
    return _safe_path(config.path.parent / '.app-delivery-routes'
                      / app.digest({'configurationPath': str(config.path)}))


def _route_binding(config):
    return {'schemaVersion': 'sermon-app-delivery-route-v1',
            'configurationPath': str(config.path), 'sunday': config.sunday,
            'jobRoot': str(config.jobs), 'outputDirectory': str(config.output)}


def _check_route(config):
    receipt = _safe_path(_route_root(config) / 'route.json')
    if receipt.exists():
        app.require(app.read(receipt) == _route_binding(config), 'app_workflow_route_changed')


def load_configuration(path, *, sunday=None):
    path = _safe_path(path)
    value = app.read(path)
    schema = app.read(SCHEMA_PATH)
    app.require(app.Draft202012Validator(schema).is_valid(value), 'app_workflow_configuration_invalid')
    parsed = date.fromisoformat(value['sunday'])
    app.require(parsed.isoformat() == value['sunday'] and parsed.weekday() == 6
                and (sunday is None or sunday == value['sunday']), 'app_workflow_sunday_mismatch')
    paths = {key: _safe_path(path.parent / value[key]) for key in ('plan', 'jobRoot', 'outputDirectory')}
    app.require(paths['plan'].is_file(), 'app_workflow_plan_missing')
    inputs = paths['plan'].parent
    app.require(not _overlap(paths['jobRoot'], inputs)
                and not _overlap(paths['outputDirectory'], inputs)
                and not _overlap(paths['jobRoot'], paths['outputDirectory'])
                and not paths['outputDirectory'].is_relative_to(paths['jobRoot'])
                and not any(_overlap(p, path) for p in (paths['jobRoot'], paths['outputDirectory'])),
                'app_workflow_paths_overlap')
    config = Configuration(path, paths['plan'], paths['jobRoot'], paths['outputDirectory'],
                           value['sunday'], app.digest(value))
    route = _route_root(config)
    app.require(not any(_overlap(route, p) for p in (config.jobs, config.output)),
                'app_workflow_route_paths_overlap')
    _check_route(config)
    return config


def implementation_identity():
    names = ('scripts/sermon_app_delivery_workflow.py', 'scripts/sermon_app_delivery.py',
             'schemas/sermon-app-delivery-workflow-v1.schema.json',
             'schemas/sermon-app-delivery-v1.schema.json')
    return app.digest({name: app.stage.file_sha(ROOT / name) for name in names})


def frozen_app_plan(plan):
    # An on-demand PDF failure/repair or later publication observation cannot
    # invalidate the independently frozen App bundle. Retain them only in views.
    return {**plan, 'pdfAdHoc': {'status': 'not_requested'}, 'productionRuns': {}}


def _asset_closure(config, plan):
    """Inventory only referenced assets, never the surrounding input directory."""
    root = config.plan.parent.resolve()
    found = {}
    traversed = set()
    def visit(value, base):
        if isinstance(value, dict):
            if {'path', 'sha256'} <= set(value):
                path, _ = app.package_artifact(root, base, value, object_required=False)
                relative = str(path.relative_to(root))
                row = {'path': relative, 'sha256': value['sha256']}
                if relative in found:
                    app.require(found[relative] == row, 'app_bundle_asset_identity_conflict')
                found[relative] = row
                if relative not in traversed:
                    traversed.add(relative)
                    # Schema-declared JSON evidence may also contain artifacts.
                    # Other binary formats are copied as bytes, never executed.
                    if path.suffix.lower() == '.json':
                        visit(app.json_value(path.read_bytes()), path.parent)
                return
            for child in value.values():
                visit(child, base)
        elif isinstance(value, list):
            for child in value:
                visit(child, base)
    for key in ('source', 'products', 'clientCapabilities', 'approvalReceipts'):
        visit(plan[key], root)
    app.require('frozen-app-plan.json' not in found, 'reserved_app_bundle_plan_path')
    return [found[name] for name in sorted(found)]


def observe(config):
    inspection = app.inspect(config.plan)
    plan = app.read(config.plan)
    core = frozen_app_plan(plan)
    inventory = _asset_closure(config, core)
    identity = {'schemaVersion': 'sermon-app-delivery-job-identity-v1',
                'workflowScope': SCOPE, 'sunday': config.sunday,
                'configurationSha256': config.sha256,
                'implementationSha256': implementation_identity(),
                'candidateJsonSha256': inspection['candidateJsonSha256'],
                'frozenAppPlanJsonSha256': app.digest(core),
                'assetInventorySha256': app.digest(inventory)}
    return inspection, core, inventory, identity


def _bundle(config, job_id):
    return _safe_path(config.output / job_id)


def _verify_bundle(config, identity, core, inventory, *, input_root=None):
    root = _bundle(config, jobs._digest(identity))
    result = inspect_bundle(root)
    manifest = app.read(root / 'bundle-manifest.json')
    app.require(manifest['identity'] == identity and manifest['inventory'] == inventory
                and manifest['originalInputRoot'] == (input_root or str(config.plan.parent.resolve()))
                and app.read(root / 'assets' / 'frozen-app-plan.json') == core,
                'app_bundle_manifest_mismatch')
    return result


def inspect_bundle(bundle_path):
    """Consume the copied bundle without access to its original input files."""
    root = _safe_path(bundle_path)
    manifest_path = _safe_path(root / 'bundle-manifest.json')
    app.require(manifest_path.is_file(), 'app_bundle_manifest_missing')
    manifest = app.read(manifest_path)
    identity, inventory = manifest['identity'], manifest['inventory']
    core = app.read(root / 'assets' / 'frozen-app-plan.json')
    app.require(manifest == {'schemaVersion': 'sermon-app-delivery-bundle-v1',
        'status': 'prepared_not_published', 'workflowScope': SCOPE,
        'identity': identity, 'frozenAppPlanJsonSha256': app.digest(core),
        'originalInputRoot': manifest['originalInputRoot'],
        'inventory': inventory, 'publication': 'not_run',
        'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run'}, 'app_bundle_manifest_mismatch')
    app.require(app.digest(core) == identity['frozenAppPlanJsonSha256']
                and app.digest(inventory) == identity['assetInventorySha256'], 'app_bundle_inventory_binding_mismatch')
    app.require(app.read(root / 'prepare-intent.json') == identity, 'app_bundle_intent_mismatch')
    for row in inventory:
        app.artifact(root.resolve(), root / 'assets', row, object_required=False)
    inspection = app.inspect(root / 'assets' / 'frozen-app-plan.json',
                             rebase_source_root=manifest['originalInputRoot'])
    app.require(inspection['promotion']['status'] == 'eligible_not_published'
                and inspection['candidateJsonSha256'] == identity['candidateJsonSha256'],
                'app_bundle_copied_evidence_not_ready')
    return {'status': 'prepared_not_published', 'jobId': jobs._digest(identity),
            'manifestSha256': app.stage.file_sha(manifest_path),
            'assetCount': len(inventory)}


def _job_state(config, job_id):
    try:
        return jobs.peek_job(config.jobs, job_id)
    except FileNotFoundError:
        return None


def _reconciled(config, key, state):
    path = _safe_path(config.jobs / key / 'app-bundle-reconciliation.json')
    if not path.exists():
        return False
    receipt = app.read(path)
    root = _bundle(config, key)
    core = app.read(root / 'assets' / 'frozen-app-plan.json')
    manifest = app.read(root / 'bundle-manifest.json')
    identity = manifest['identity']
    inventory = manifest['inventory']
    app.require(jobs._digest(identity) == key and app.digest(core) == identity['frozenAppPlanJsonSha256']
                and app.digest(inventory) == identity['assetInventorySha256'], 'app_reconciled_bundle_binding_changed')
    prepared = _verify_bundle(config, identity, core, inventory,
                              input_root=manifest['originalInputRoot'])
    folder = config.jobs / key
    request = jobs._read(folder / 'request.json')
    app.require(jobs._request_valid(request, key) and request['identity'] == identity,
                'app_reconciled_request_binding_changed')
    app.require(receipt == {'schemaVersion': 'sermon-app-bundle-reconciliation-v1',
        'jobId': key, 'identity': identity,
        'originalRequestSha256': jobs._digest(request),
        'originalStateSha256': jobs._digest(jobs._read(folder / 'state.json')),
        'manifestSha256': prepared['manifestSha256']}, 'app_reconciliation_changed')
    return state['status'] in {'uncertain', 'failed'}


def snapshot(config_path, *, sunday=None):
    config = load_configuration(config_path, sunday=sunday)
    inspection, core, inventory, identity = observe(config)
    key = jobs._digest(identity)
    result = {'schemaVersion': 'sermon-app-delivery-workflow-state-v1', 'workflowScope': SCOPE,
        'sunday': config.sunday, 'workflowComplete': False, 'completionScope': SCOPE,
        'publication': 'not_run', 'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run',
        'configurationSha256': config.sha256, 'jobIdentity': identity,
        'candidateJsonSha256': inspection['candidateJsonSha256'],
        'appProductsReady': inspection['appProductsReady'], 'promotion': inspection['promotion'],
        'pdfAdHoc': inspection['pdfAdHoc'], 'production': inspection['production'],
        'bundle': None, 'workflowJob': None,
        'recommendedAction': {'action': ACTION, 'humanActionRequired': False}}
    # One stable job root across revisions. An older unknown/active attempt
    # cannot disappear behind a new source, candidate, config or implementation.
    if config.jobs.exists():
        for folder in sorted(config.jobs.iterdir()):
            if not re.fullmatch(r'[a-f0-9]{64}', folder.name):
                continue
            _safe_path(folder)
            state = _job_state(config, folder.name)
            if state and state['status'] in jobs.ACTIVE | {'uncertain'}:
                if state['status'] == 'uncertain' and _reconciled(config, folder.name, state):
                    continue
                result['workflowJob'] = state
                result['recommendedAction'] = {'action': 'wait_for_workflow_job' if state['status'] in jobs.ACTIVE
                    else 'inspect_app_delivery_job_failure', 'humanActionRequired': state['status'] == 'uncertain'}
                return result
    if inspection['promotion']['status'] != 'eligible_not_published':
        result['recommendedAction'] = {'action': 'waiting_app_delivery_review', 'humanActionRequired': True}
        return result
    state = _job_state(config, key)
    if state:
        result['workflowJob'] = state
        try:
            prepared = _verify_bundle(config, identity, core, inventory)
            if state['status'] != 'succeeded' and not _reconciled(config, key, state):
                raise ValueError('app_bundle_requires_reconciliation')
        except (ValueError, OSError, KeyError, TypeError):
            result['recommendedAction'] = {'action': 'inspect_app_delivery_job_failure', 'humanActionRequired': True}
        else:
            result.update(workflowComplete=True, bundle=prepared,
                recommendedAction={'action': 'complete', 'humanActionRequired': False})
    return result


def _worker_command(config, identity):
    return [sys.executable, str(Path(__file__).resolve()), 'worker', '--config', str(config.path),
            '--expected-job', jobs._digest(identity)]


def start(config_path, *, sunday=None, expected_revision=None):
    config = load_configuration(config_path, sunday=sunday)
    observed = snapshot(config.path, sunday=sunday)
    if observed['recommendedAction']['action'] != ACTION:
        return {'status': 'blocked' if observed['recommendedAction']['humanActionRequired'] else 'waiting',
                'dispatched': False, 'recommendedAction': observed['recommendedAction']}
    # Bind routing under a config-path-stable lock BEFORE admission. Otherwise
    # changing jobRoot could hide a living/unknown owner behind an empty root.
    route = _route_root(config)
    with jobs._lock(route.parent, route.name) as (_, _, held):
        if not held:
            return {'status': 'waiting', 'reasonCode': 'app_admission_busy', 'dispatched': False}
        current = load_configuration(config.path, sunday=sunday)
        app.require(_route_binding(current) == _route_binding(config), 'app_workflow_route_changed')
        route.mkdir(parents=True, exist_ok=True, mode=0o700)
        jobs._sync_directory_ancestry(route)
        binding_path = route / 'route.json'
        if not binding_path.exists():
            jobs._persist(binding_path, _route_binding(config))
        return _admit(config, observed, sunday=sunday, expected_revision=expected_revision)


def _admit(config, observed, *, sunday=None, expected_revision=None):
    with jobs._lock(config.jobs, jobs._digest({'purpose': 'app-delivery-admission-v1'})) as (_, _, held):
        if not held:
            return {'status': 'waiting', 'reasonCode': 'app_admission_busy', 'dispatched': False}
        fresh = snapshot(config.path, sunday=sunday)
        if app.digest(fresh) != (expected_revision or app.digest(observed)):
            return {'status': 'waiting', 'reasonCode': 'app_workflow_state_changed', 'dispatched': False}
        if fresh['recommendedAction']['action'] != ACTION:
            return {'status': 'blocked' if fresh['recommendedAction']['humanActionRequired'] else 'waiting',
                    'dispatched': False, 'recommendedAction': fresh['recommendedAction']}
        identity = fresh['jobIdentity']
        # start_job durably writes intent before spawn and rejects every repeated
        # failed/unknown identity. No catch-and-respawn path exists here.
        state = jobs.start_job(config.jobs, identity, _worker_command(config, identity),
                               timeout_seconds=TIMEOUT_SECONDS)
        return {'status': 'waiting', 'dispatched': True, 'job': state}


def _copy_verified(source, destination, expected):
    app.require(app.stage.file_sha(source) == expected, 'app_bundle_source_changed')
    _safe_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    jobs._sync_directory_ancestry(destination.parent)
    if destination.exists():
        app.require(destination.is_file() and app.stage.file_sha(destination) == expected,
                    'app_bundle_existing_asset_changed')
        return
    temporary = _safe_path(destination.with_name(destination.name + '.partial'))
    # The partial is never admitted. Recovery can overwrite it after checking
    # the immutable intent and acquiring both job and output writer locks.
    with source.open('rb') as original, temporary.open('wb') as copy:
        while chunk := original.read(1024 * 1024):
            copy.write(chunk)
        copy.flush()
        os.fsync(copy.fileno())
    app.require(app.stage.file_sha(temporary) == expected, 'app_bundle_copy_changed')
    temporary.replace(destination)
    jobs._sync_directory(destination.parent)


def _prepare(config, expected):
    inspection, core, inventory, identity = observe(config)
    app.require(identity == expected and inspection['promotion']['status'] == 'eligible_not_published',
                'app_bundle_inputs_or_approval_changed')
    root = _bundle(config, jobs._digest(identity))
    with work_lock(root):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        jobs._sync_directory_ancestry(root)
        intent = _safe_path(root / 'prepare-intent.json')
        if intent.exists():
            app.require(app.read(intent) == identity, 'app_bundle_intent_changed')
        else:
            jobs._persist(intent, identity)
        plan_path = _safe_path(root / 'assets' / 'frozen-app-plan.json')
        plan_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        jobs._sync_directory_ancestry(plan_path.parent)
        if plan_path.exists():
            app.require(app.read(plan_path) == core, 'app_bundle_plan_changed')
        else:
            jobs._persist(plan_path, core)
        for row in inventory:
            source = app.local_file(config.plan.parent.resolve(), config.plan.parent.resolve(), row['path'])
            _copy_verified(source, root / 'assets' / row['path'], row['sha256'])
        # No paid/mutable upstream call is repeated. Recheck original receipts
        # and source binding after all copies, before publishing the marker.
        final_inspection, final_core, final_inventory, final_identity = observe(load_configuration(config.path))
        app.require(final_identity == identity and final_core == core and final_inventory == inventory
                    and final_inspection['promotion']['status'] == 'eligible_not_published', 'app_bundle_inputs_changed_during_copy')
        manifest = {'schemaVersion': 'sermon-app-delivery-bundle-v1',
            'status': 'prepared_not_published', 'workflowScope': SCOPE, 'identity': identity,
            'frozenAppPlanJsonSha256': app.digest(core), 'inventory': inventory,
            'originalInputRoot': str(config.plan.parent.resolve()),
            'publication': 'not_run', 'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run'}
        marker = _safe_path(root / 'bundle-manifest.json')
        if marker.exists():
            app.require(app.read(marker) == manifest, 'app_bundle_existing_manifest_changed')
        else:
            jobs._persist(marker, manifest)
    return _verify_bundle(config, identity, core, inventory)


def worker(config_path, expected_job):
    config = load_configuration(config_path)
    _, _, _, identity = observe(config)
    app.require(jobs._digest(identity) == expected_job, 'app_worker_inputs_changed')
    folder = config.jobs / expected_job
    request = jobs._read(folder / 'request.json')
    app.require(jobs._request_valid(request, expected_job) and request['identity'] == identity
                and request['command'] == _worker_command(config, identity)
                and _job_state(config, expected_job)['status'] == 'running', 'app_worker_requires_bound_running_job')
    return _prepare(config, identity)


def recover(config_path, expected_job):
    """Explicit local repair under the original job lock; never automatic retry.

    Preserves failure/state/request evidence. Existing complete bytes are checked
    and reused, missing files are copied from the same currently approved input.
    """
    config = load_configuration(config_path)
    inspection, core, inventory, identity = observe(config)
    app.require(jobs._digest(identity) == expected_job
                and inspection['promotion']['status'] == 'eligible_not_published', 'app_recovery_binding_changed')
    with jobs._lock(config.jobs, expected_job) as (folder, _, held):
        app.require(held, 'app_recovery_job_owner_active')
        request = jobs._read(folder / 'request.json')
        state = jobs._read(folder / 'state.json')
        app.require(jobs._request_valid(request, expected_job) and request['identity'] == identity
                    and request['command'] == _worker_command(config, identity)
                    and state.get('status') in {'failed', 'uncertain'}, 'app_recovery_requires_original_job')
        pid = state.get('workerPid')
        if type(pid) is int and pid > 0:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError('app_recovery_job_owner_alive')
        # Raw queued/running is never repair authority, even with an available
        # lock. A dead owner must first be inspected/reconciled by durable jobs.
        prepared = _prepare(config, identity)
        receipt = {'schemaVersion': 'sermon-app-bundle-reconciliation-v1',
            'jobId': expected_job, 'identity': identity,
            'originalRequestSha256': jobs._digest(request), 'originalStateSha256': jobs._digest(state),
            'manifestSha256': prepared['manifestSha256']}
        jobs._persist(folder / 'app-bundle-reconciliation.json', receipt)
        # Do not rewrite the original failed/uncertain state into success.
        return {**prepared, 'status': 'reconciled_prepared_not_published'}


def run(config_path, *, mode='shadow', sunday=None):
    app.require(mode in {'shadow', 'execute'}, 'app_workflow_mode_invalid')
    observed = snapshot(config_path, sunday=sunday)
    action = observed['recommendedAction']['action']
    attempt = None
    if mode == 'execute' and action == ACTION:
        attempt = start(config_path, sunday=sunday, expected_revision=app.digest(observed))
        observed = snapshot(config_path, sunday=sunday)
    completed = observed['workflowComplete']
    return {'schemaVersion': 'sermon-app-delivery-run-v1',
        'workflowScope': SCOPE, 'completionScope': SCOPE, 'mode': mode,
        'status': 'complete' if completed else 'blocked' if observed['recommendedAction']['humanActionRequired']
            else 'advanced' if attempt and attempt.get('dispatched') else 'observed',
        'workflowComplete': completed, 'publication': 'not_run',
        'runtimeCodexTurns': 0, 'approvalWritten': False, 'notification': {'status': 'not_run'},
        'completionLatch': {'status': 'already_prepared' if completed else 'not_complete',
                            'scope': SCOPE, 'publication': 'not_run'},
        'attempt': attempt, 'finalSnapshot': observed}


def main(argv=None):
    parser = app.SafeArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'inspect-bundle', 'tick', 'worker', 'recover'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--mode', choices=('shadow', 'execute'), default='shadow')
    parser.add_argument('--expected-job')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect-bundle':
            app.require(args.bundle is not None and args.config is None, 'bundle_required')
            result = inspect_bundle(args.bundle)
        elif args.config is None or args.bundle is not None:
            raise ValueError('config_required')
        elif args.command == 'worker':
            app.require(args.expected_job is not None, 'expected_job_required')
            result = worker(args.config, args.expected_job)
        elif args.command == 'recover':
            app.require(args.expected_job is not None, 'expected_job_required')
            result = recover(args.config, args.expected_job)
        elif args.command == 'tick':
            result = run(args.config, mode=args.mode)
        else:
            result = snapshot(args.config)
    except (ValueError, OSError, KeyError, TypeError, WorkAlreadyRunning):
        parser.exit(2, 'App workflow failed: invalid_or_changed_evidence\n')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

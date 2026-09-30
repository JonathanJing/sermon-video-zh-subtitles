"""Explicit deterministic L2 recovery from complete returned response caches.

No credential loading, paid fallback, retry-budget reset or human approval.
Original durable job outcome stays unchanged; artifact reconciliation is separate.
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
from scripts import sermon_accounting as accounting
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path


def _returned_cache_files(lane, source, anchor, policy):
    request = layer2.producer.prepare_request(source, anchor, policy)
    plan = layer2.models.group_plan(request, anchor)
    output = lane['output']
    files = [output / 'request.json', output / 'run-identity.json']
    for index, _ in enumerate(plan, 1):
        for role in ('astra', 'sol'):
            parsed = _safe_path(output / f'group-{index:04d}-{role}.json')
            raw = _safe_path(parsed.with_suffix('.raw.json'))
            # A started marker without a response is never evidence of success.
            layer2.require(parsed.is_file() or raw.is_file(), 'complete_returned_model_cache_required')
            files.extend(path for path in (parsed, raw) if path.is_file())
    hashes = {}
    for path in files:
        _safe_path(path)
        layer2.require(path.is_file() and path.stat().st_size <= layer2.packages.MAX_JSON_BYTES,
                       'invalid_or_oversized_recovery_cache')
        hashes[path.name] = layer2.hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _unchanged(output, hashes):
    for name, expected in hashes.items():
        path = _safe_path(output / name)
        layer2.require(path.is_file() and layer2.hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                       'returned_cache_changed_during_recovery')


def _save_or_match(path, value):
    path = _safe_path(path)
    if path.exists():
        layer2.require(layer2.producer._load(path) == value, 'existing_recovery_artifact_conflict')
    else:
        layer2.models.save_new(path, value)


def recover(config_path, locale, expected_revision):
    layer2.require(durable.pipeline._sha(expected_revision), 'expected_revision_required')
    config = layer2.load_configuration(config_path)
    code = layer2.code_identity()
    layer2.require(locale in config.lanes, 'locale_not_registered')
    unit, lane = 'text.' + locale, config.lanes[locale]
    initial = layer2.snapshot(config)
    layer2.require(initial['stateRevision'] == expected_revision, 'stale_recovery_revision')
    package = layer2.package_view(config)
    if package['nodes'][unit]['status'] == 'validated':
        return {'status': 'validated_candidate_already_present', 'modelCalls': 0,
                'candidateJsonSha256': package['packageIdentities']['candidate.' + locale],
                'nextStep': 'inspect_durable_job_and_reconcile_if_required'}
    layer2.require(package['nodes'][unit]['status'] == 'ready'
                   and initial['nodes']['source']['status'] == 'validated', 'upstream_or_candidate_not_ready')
    ident = durable.identity(package, config.run_id, unit)
    key = jobs._digest(ident)
    folder = _safe_path(config.job_root / key)
    layer2.require(folder.is_dir(), 'existing_durable_job_required')
    with jobs._lock(config.job_root, layer2.ADMISSION_LOCK) as (_, _, admitted):
        layer2.require(admitted, 'admission_busy')
        fresh_config = layer2.load_configuration(config.path)
        layer2.require(fresh_config.sha256 == config.sha256 and layer2.code_identity() == code,
                       'configuration_or_code_changed')
        fresh = layer2.snapshot(fresh_config)
        layer2.require(fresh['stateRevision'] == expected_revision, 'stale_recovery_revision')
        row = next((r for r in fresh['durableJobInspection']['jobs'] if r['jobId'] == key), None)
        layer2.require(row is not None, 'existing_bound_job_required')
        with jobs._lock(config.job_root, key) as (folder, _, held):
            layer2.require(held, 'job_owner_still_active')
            with work_lock(lane['output']):
                def current_inputs():
                    current_config = layer2.load_configuration(config.path)
                    layer2.require(current_config.sha256 == config.sha256 and layer2.code_identity() == code,
                                   'configuration_or_code_changed')
                    current = layer2.package_view(current_config)
                    layer2.require(current['stateRevision'] == package['stateRevision']
                                   and current['nodes'][unit]['status'] == 'ready'
                                   and durable.identity(current, config.run_id, unit) == ident,
                                   'recovery_inputs_changed')
                    request = jobs._read(folder / 'request.json')
                    state = jobs._state(folder, key)
                    layer2.require(jobs._request_valid(request, key) and request['identity'] == ident
                                   and request['command'] == layer2._worker_command(config, locale, key, code)
                                   and request['timeoutSeconds'] == 21600.0
                                   and state is not None and state.get('requestSha256') == jobs._digest(request)
                                   and jobs._digest(request) == row['requestSha256']
                                   and jobs._digest(state) == row['stateSha256'],
                                   'original_execution_binding_changed')
                    return layer2._inputs(current_config, locale, current)
                source, anchor, policy = current_inputs()
                hashes = _returned_cache_files(lane, source, anchor, policy)
                def forbidden_call(*_args):
                    raise AssertionError('cache_only_transport_must_never_be_called')
                evidence = layer2.models.run_accounted(source, anchor, policy, lane['output'], '',
                    forbidden_call, None, lane['plugin'], None, None, cache_only=True)
                current_inputs()
                _unchanged(lane['output'], hashes)
                with accounting.accounting_session(lane['output'] / 'accounting', 'canonical_layer2_cache_recovery',
                        {'targetLocale': locale}, evidence_directory=lane['output']):
                    with accounting.stage('layer2.cache_candidate.' + locale, depends_on=[],
                            executor_type='deterministic_program', work_unit_id='l2.' + locale + '.cache_candidate'):
                        request = layer2.producer._load(lane['output'] / 'request.json')
                        plugin_sha = policy['languageReview']['pluginImplementationSha256']
                        receipt = layer2.producer.run_language_plugin(source, anchor, policy, request,
                            evidence, lane['plugin'], plugin_sha)
                        candidate = layer2.producer.admit_evidence(source, anchor, policy, request,
                            evidence, receipt, lane['plugin'], plugin_sha)
                        current_inputs()
                        _unchanged(lane['output'], hashes)
                        _save_or_match(lane['output'] / 'language-review.json', receipt)
                        _save_or_match(lane['candidate'], candidate)
                checked = layer2.package_view(config)
                layer2.require(checked['nodes'][unit]['status'] == 'validated', 'recovered_candidate_not_validated')
                return {'status': 'candidate_recovered_reconciliation_required', 'jobId': key,
                        'candidateJsonSha256': jobs._digest(candidate), 'modelCalls': 0,
                        'humanApprovalCreated': False, 'releaseEligible': False,
                        'returnedCacheSetSha256': jobs._digest(hashes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--locale', required=True, choices=layer2.pipeline.LOCALES)
    parser.add_argument('--expected-state-revision', required=True)
    args = parser.parse_args()
    print(json.dumps(recover(args.config, args.locale, args.expected_state_revision), sort_keys=True))


if __name__ == '__main__':
    main()

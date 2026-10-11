"""Read-only, producer-backed preflight for L2 and optional downstream evidence.

No model call, credential lookup, job dispatch, approval creation or filesystem
write is performed. Readiness here never establishes device/venue acceptance.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import canonical_layer2_controller as layer2
from scripts import inspect_canonical_packages as packages
from scripts import layer2_api_concurrency as capacity
from scripts import sermon_workflow_jobs as jobs

SCHEMA = 'sermon-unified-preflight-v1'
ERRORS = (ValueError, OSError, KeyError, TypeError)


def inspect_config(path, *, downstream_inspection=None, expected_code_identity=None):
    blockers = []
    result = {'schemaVersion': SCHEMA, 'mode': 'read_only', 'status': 'blocked',
              'layer2Ready': False, 'blockers': blockers, 'dispatched': False,
              'humanApproval': False, 'deviceAcceptance': 'not_run',
              'venueAcceptance': 'not_run', 'codeIdentitySha256': None,
              'maxConcurrentLocaleJobs': layer2.MAX_ACTIVE_LAYER2_JOBS,
              'maxInFlightApiCalls': capacity.MAX_IN_FLIGHT_API_CALLS,
              'maxGroupWorkersPerLocale': capacity.MAX_GROUP_WORKERS_PER_LOCALE,
              'capacityScope': 'host_local_per_job_root', 'jobRoot': None,
              'apiSlotRoot': None, 'locales': {}}

    def block(stage, code, **extra):
        blockers.append({'stage': stage, 'reasonCode': code, **extra})

    try:
        config = layer2.load_configuration(path)
    except ERRORS as exc:
        block('configuration', 'invalid_layer2_execution_configuration', detail=str(exc)[:300])
        return result
    result.update(productionRunId=config.run_id, configurationSha256=config.sha256,
                  jobRoot=str(config.job_root),
                  apiSlotRoot=str(config.job_root.parent / f'.{config.job_root.name}.layer2-api-slots'))
    try:
        result['codeIdentitySha256'] = layer2.code_identity()
        if expected_code_identity is not None and result['codeIdentitySha256'] != expected_code_identity:
            block('code', 'code_closure_changed')
        view = layer2.package_view(config)
        result['packageIdentities'] = view['packageIdentities']
        result['inspectionCoverage'] = view['inspectionCoverage']
        for stage, code in sorted(view['inspectionDiagnostics'].items()):
            block(stage, code)
        view = layer2.join_jobs(config, view)
        result['stateRevision'] = view['stateRevision']
        result['durableJobInspection'] = view['durableJobInspection']
    except ERRORS as exc:
        block('packages', 'package_or_job_inspection_failed', detail=str(exc)[:300])
        return result
    active = [row for row in view['durableJobInspection']['jobs']
              if row['workUnitId'].startswith('text.') and row['status'] in jobs.ACTIVE | {'uncertain'}]
    result['occupiedLocaleSlots'] = len(active)
    if len(active) >= layer2.MAX_ACTIVE_LAYER2_JOBS:
        block('capacity', 'locale_slot_occupied_until_completion_or_reconciliation')
    for locale, lane in sorted(config.lanes.items()):
        node = view['nodes']['text.' + locale]
        lane_result = {'status': node['status'], 'reasonCode': node.get('reasonCode'),
                       'pluginIdentityVerified': False, 'modelPolicyVerified': False}
        result['locales'][locale] = lane_result
        try:
            policy = packages._read_package(lane['policy'].parent, str(lane['policy']), {}, 'policy')
            actual = layer2.producer.plugin_implementation_sha256(lane['plugin'])
            lane_result['pluginImplementationSha256'] = actual
            if actual != policy['languageReview']['pluginImplementationSha256']:
                raise ValueError('plugin_does_not_match_frozen_policy')
            lane_result['pluginIdentityVerified'] = True
            layer2._inputs(config, locale, view)
            lane_result['modelPolicyVerified'] = True
            lane_result['configuredGroupWorkers'] = policy['batching']['workers']
        except ERRORS as exc:
            block('text.' + locale, 'fixed_layer2_admission_invalid', detail=str(exc)[:300])
        if node['status'] not in {'ready', 'validated'}:
            block('text.' + locale, node.get('reasonCode') or node['status'])
    result['layer2Ready'] = not blockers

    if downstream_inspection is None:
        for stage in ('audio', 'release'):
            block(stage, 'downstream_inspection_not_configured')
        result['downstreamCoverage'] = 'not_configured'
    else:
        try:
            downstream_path = Path(downstream_inspection).absolute()
            downstream_config = packages._read_package(downstream_path.parent, str(downstream_path), {}, 'configuration')
            downstream = packages.inspect_configuration(downstream_path.parent, downstream_config)
            result['downstreamCoverage'] = downstream['inspectionCoverage']
            result['downstreamNodes'] = downstream['nodes']
            for key in ['source', 'anchor'] + ['policy.' + locale for locale in config.lanes]:
                if (key not in view['packageIdentities']
                        or downstream['packageIdentities'].get(key) != view['packageIdentities'][key]):
                    block('downstream', 'downstream_upstream_identity_mismatch', identityKey=key)
            for locale in config.lanes:
                lane = downstream_config.get('locales', {}).get(locale, {})
                for field, stage in [('audio', 'audio.' + locale), ('release', 'page.' + locale)]:
                    if field not in lane:
                        block(stage, 'downstream_inspection_not_configured')
                    elif downstream['nodes'].get(stage, {}).get('status') != 'validated':
                        node = downstream['nodes'].get(stage, {})
                        block(stage, downstream['inspectionDiagnostics'].get(stage)
                              or node.get('reasonCode') or 'downstream_package_not_validated')
        except ERRORS as exc:
            block('downstream', 'downstream_inspection_failed', detail=str(exc)[:300])
    # A read-only preflight is a snapshot; execution must recheck under its lock.
    try:
        if (layer2.load_configuration(path).sha256 != config.sha256
                or layer2.code_identity() != result['codeIdentitySha256']
                or layer2.package_view(config)['packageIdentities'] != result['packageIdentities']):
            block('configuration', 'configuration_or_code_changed_during_preflight')
            result['layer2Ready'] = False
    except ERRORS:
        block('configuration', 'configuration_changed_during_preflight')
        result['layer2Ready'] = False
    result['status'] = 'ready' if not blockers else 'blocked'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--downstream-inspection', type=Path)
    parser.add_argument('--expected-code-identity')
    args = parser.parse_args()
    result = inspect_config(args.config, downstream_inspection=args.downstream_inspection,
                            expected_code_identity=args.expected_code_identity)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'ready' else 2


if __name__ == '__main__':
    raise SystemExit(main())

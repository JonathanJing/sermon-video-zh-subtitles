"""Opt-in fixed Layer 2 admission using canonical gates and existing durable jobs.

Default shadow is read-only. Execution creates machine-reviewed candidates only;
source and independent human review receipts must already exist. No audio, release,
publication, bounded agent or arbitrary command dispatch is implemented here.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import canonical_durable_jobs as durable
from scripts import production_spark_admission as spark_admission
from scripts import inspect_canonical_packages as packages
from scripts import canonical_pipeline_definition as pipeline
from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as models
from scripts import target_language_rule_preflight as rule_preflight
from scripts import sermon_accounting as accounting
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_job_liveness as liveness
from scripts import layer2_api_concurrency as api_concurrency
from scripts import canonical_layer2_budget as budget_tools
from contextlib import nullcontext
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'sermon-canonical-layer2-execution-v1'
CONCURRENT_SCHEMA = 'sermon-canonical-layer2-execution-v2'
MODES = ('deterministic_shadow', 'deterministic_execute')
ADMISSION_LOCK = jobs._digest({'purpose': 'canonical-layer2-admission-v1'})
MAX_CONFIG_BYTES = 1024 * 1024
MAX_ACTIVE_LAYER2_JOBS = 1
LIVENESS_POLICY = {'schemaVersion': liveness.SCHEMA, 'startTimeoutSeconds': 60,
                   'heartbeatIntervalSeconds': 30, 'heartbeatTimeoutSeconds': 90,
                   'noProgressTimeoutSeconds': 900}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def _json(path):
    path = _safe_path(path)
    require(path.is_file() and path.stat().st_size <= MAX_CONFIG_BYTES, 'invalid_configuration_file')
    value = jobs._read(path)
    require(isinstance(value, dict), 'invalid_configuration_object')
    return value


def _path(root, value):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 4096, 'invalid_configuration_path')
    return _safe_path(root / value)


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


@dataclass(frozen=True)
class Configuration:
    path: Path
    inspection_root: Path
    inspection: dict
    job_root: Path
    run_id: str
    lanes: dict
    sha256: str
    concurrency_profile: dict | None = None
    resource_policy: dict | None = None


def load_configuration(path):
    path = _safe_path(Path(path).absolute())
    value = _json(path)
    required_keys = {'schemaVersion', 'productionRunId', 'inspectionConfig', 'jobRoot', 'locales'}
    require(((set(value) == required_keys and value['schemaVersion'] == SCHEMA)
             or (set(value) == required_keys | {'concurrencyProfile', 'resourcePolicy'}
                 and value['schemaVersion'] == CONCURRENT_SCHEMA))
            and pipeline._sha(value['productionRunId'])
            and isinstance(value['locales'], dict) and bool(value['locales'])
            and set(value['locales']) <= set(pipeline.LOCALES), 'invalid_execution_configuration')
    inspection_path = _path(path.parent, value['inspectionConfig'])
    inspection = _json(inspection_path)
    require(inspection.get('schemaVersion') == packages.SCHEMA
            and isinstance(inspection.get('locales'), dict)
            and set(value['locales']) <= set(inspection['locales']), 'execution_locale_not_in_inspection')
    root = inspection_path.parent
    job_root = _path(path.parent, value['jobRoot'])
    input_paths = [path, inspection_path, _path(root, inspection.get('source')),
                   _path(root, inspection.get('anchor'))]
    concurrency_profile = resource_policy = None
    if 'concurrencyProfile' in value:
        from scripts.production_concurrency_profile import load_profile
        from scripts.sermon_unified import resources
        profile_path = _path(path.parent, value['concurrencyProfile'])
        resource_path = _path(path.parent, value['resourcePolicy'])
        concurrency_profile = load_profile(profile_path)
        resource_policy = resources.validate_policy(_json(resource_path))
        require(resource_policy['capacities']['codex_cli'] == concurrency_profile['totalCodexSlots'],
                'concurrency_profile_requires_shared_24_slot_broker')
        input_paths.extend((profile_path, resource_path))
    lanes, plugin_hashes = {}, {}
    for locale, lane in sorted(value['locales'].items()):
        require(isinstance(lane, dict) and set(lane) == {'outputDirectory', 'plugin'}, 'invalid_execution_lane')
        output, plugin = (_path(path.parent, lane[key]) for key in ('outputDirectory', 'plugin'))
        require(plugin.is_file() and not _overlap(output, job_root), 'invalid_execution_paths')
        inspect_lane = inspection['locales'][locale]
        require(isinstance(inspect_lane, dict), 'invalid_inspection_lane')
        policy = _path(root, inspect_lane.get('policy'))
        candidate = output / 'candidate.json'
        if 'candidate' in inspect_lane:
            require(_path(root, inspect_lane['candidate']) == candidate, 'candidate_output_path_changed')
        # No execution field can inject an argv/model/secret/approval override.
        lanes[locale] = {'output': output, 'plugin': plugin, 'policy': policy, 'candidate': candidate}
        plugin_hashes[locale] = producer.plugin_implementation_sha256(plugin)
        input_paths.extend((plugin, policy))
    outputs = [lane['output'] for lane in lanes.values()]
    require(not any(_overlap(output, path) for output in outputs for path in input_paths)
            and not any(_overlap(a, b) for i, a in enumerate(outputs) for b in outputs[i + 1:]),
            'execution_paths_overlap')
    binding = {'execution': value, 'inspection': inspection, 'plugins': plugin_hashes}
    if concurrency_profile is not None:
        binding.update(concurrencyProfile=concurrency_profile, resourcePolicy=resource_policy)
    sha = jobs._digest(binding)
    return Configuration(path, root, inspection, job_root, value['productionRunId'], lanes, sha,
                         concurrency_profile, resource_policy)


def code_identity():
    # Pin the runtime source/schema closure, not a branch name or stale commit
    # label. The worker rechecks it before any paid call and candidate admission.
    files = sorted([*ROOT.joinpath('scripts').rglob('*.py'), *ROOT.joinpath('schemas').rglob('*.json'),
                    ROOT / 'docs/series-terminology.zh.md'])
    return jobs._digest({str(p.relative_to(ROOT)): hashlib.sha256(_safe_path(p).read_bytes()).hexdigest() for p in files})


def package_view(config):
    effective = copy.deepcopy(config.inspection)
    for locale, lane in config.lanes.items():
        candidate = _safe_path(lane['candidate'])
        if candidate.exists():
            effective['locales'][locale]['candidate'] = str(candidate)
        else:
            # Only this registered future output may be absent. An existing
            # invalid package is always validated and blocks the lane.
            effective['locales'][locale].pop('candidate', None)
    return packages.inspect_configuration(config.inspection_root, effective)


def snapshot(config):
    view = durable.project(package_view(config), config.job_root, config.run_id)
    rejected = []
    for locale in config.lanes:
        unit = 'text.' + locale
        if view['nodes'].get(unit, {}).get('status') == 'ready':
            try:
                _inputs(config, locale, view)
            except (ValueError, OSError, KeyError, TypeError) as error:
                reason = 'layer2_rule_preflight_failed' if str(error).startswith('Layer 2 rule preflight:') else 'fixed_layer2_admission_invalid'
                view['nodes'][unit].update(status='blocked', reasonCode=reason)
                rejected.append(unit)
    view['stateRevision'] = jobs._digest({'packageAndJobs': view['stateRevision'],
                                        'configuration': config.sha256, 'rejectedLanes': sorted(rejected)})
    return view


def _inputs(config, locale, view):
    lane = config.lanes[locale]
    paths = {'source': _path(config.inspection_root, config.inspection['source']),
             'anchor': _path(config.inspection_root, config.inspection['anchor']),
             'policy.' + locale: lane['policy']}
    values = {key: packages._read_package(path.parent, str(path), {}, key) for key, path in paths.items()}
    require(all(jobs._digest(value) == view['packageIdentities'].get(key) for key, value in values.items()),
            'inputs_changed_after_inspection')
    policy = values['policy.' + locale]
    require(producer.plugin_implementation_sha256(lane['plugin']) == policy['languageReview']['pluginImplementationSha256'],
            'plugin_does_not_match_frozen_policy')
    # Fixed production models and the canonical runner's worker budget bound paid work.
    require(all(policy[role]['model'] == model and policy[role]['reasoningEffort'] == models.MODEL_EFFORTS[role] for role, model in models.MODEL_ROLES.items()), 'production_model_policy_changed')
    require(policy['batching']['batchSize'] == 1 and type(policy['batching']['workers']) is int
            and 1 <= policy['batching']['workers'] <= api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE,
            'invalid_production_worker_budget')
    request = producer.prepare_request(values['source'], values['anchor'], policy)
    plan = models.group_plan(request, values['anchor'])
    rule_preflight.preflight(request, policy, lane['plugin'], plan)
    return values['source'], values['anchor'], policy


def _worker_command(config, locale, job_id, code_sha, budget_authorization=None):
    command = [sys.executable, str(Path(__file__).resolve()), 'worker', '--config', str(config.path),
            '--locale', locale, '--expected-configuration', config.sha256,
            '--expected-code', code_sha, '--expected-job', job_id]
    if budget_authorization is not None:
        command += ['--budget-authorization', str(budget_authorization['path']),
                    '--expected-budget', budget_authorization['sha256']]
    return command


class Controller:
    def __init__(self, config_path, *, mode='deterministic_shadow', budget_authorization=None):
        require(mode in MODES, 'invalid_controller_mode')
        self.config = load_configuration(config_path)
        self.code_sha = code_identity()
        self.mode = mode
        self.budget_authorization = (budget_tools.load_authorization(
            self.config, budget_authorization, self.code_sha) if budget_authorization is not None else None)

    def _result(self, status, reason, **fields):
        return {'schemaVersion': 'sermon-canonical-layer2-controller-result-v1',
                'mode': self.mode, 'scope': 'four_layer_release_layer2_preparation',
                'productionRunId': self.config.run_id, 'configurationSha256': self.config.sha256,
                'codeIdentitySha256': self.code_sha, 'status': status, 'reasonCode': reason,
                'maxConcurrentLocaleJobs': (self.config.concurrency_profile['maxActiveLocales']
                                           if self.config.concurrency_profile else MAX_ACTIVE_LAYER2_JOBS),
                'maxInFlightApiCalls': api_concurrency.MAX_IN_FLIGHT_API_CALLS,
                'runtimeCodexTurns': 0, 'contentAcceptance': 'not_evaluated',
                'deviceAcceptance': 'not_run', **fields}

    def _fresh(self):
        current = load_configuration(self.config.path)
        require(current.sha256 == self.config.sha256 and code_identity() == self.code_sha, 'configuration_or_code_changed')
        if self.budget_authorization is not None:
            budget_tools.load_authorization(current, self.budget_authorization['path'], self.code_sha,
                                            self.budget_authorization['sha256'])
        return current, snapshot(current)

    def _capacity_full(self, view):
        # The canonical contract reserves one locale slot until completion or
        # reconciliation of an uncertain owner.
        active = [row for row in view['durableJobInspection']['jobs']
                  if row['workUnitId'].startswith('text.') and row['status'] in jobs.ACTIVE | {'uncertain'}]
        if any(row['status'] == 'uncertain' for row in active):
            return True  # preserve the existing run-wide unknown reconciliation barrier
        limit = self.config.concurrency_profile['maxActiveLocales'] if self.config.concurrency_profile else MAX_ACTIVE_LAYER2_JOBS
        return len(active) >= limit

    def _choose(self, view, requested_locale=None):
        if self._capacity_full(view):
            return None
        if requested_locale is not None:
            require(requested_locale in self.config.lanes, 'locale_not_registered')
        for locale in ([requested_locale] if requested_locale else sorted(self.config.lanes)):
            if view['nodes'].get('text.' + locale, {}).get('status') == 'ready':
                return locale
        return None

    def tick(self, *, requested_locale=None):
        try:
            config, observed = self._fresh()
        except (ValueError, OSError, KeyError, TypeError):
            return self._result('blocked', 'configuration_code_or_evidence_invalid', dispatched=False)
        locale = self._choose(observed, requested_locale)
        if self.mode == 'deterministic_shadow':
            return self._result('ready' if locale else 'waiting',
                                'layer2_capacity_reached' if self._capacity_full(observed) else 'shadow_only',
                                proposedWorkUnit='text.' + locale if locale else None,
                                stateRevision=observed['stateRevision'], nodes=observed['nodes'], dispatched=False)
        with jobs._lock(config.job_root, ADMISSION_LOCK) as (_, _, held):
            if not held:
                return self._result('waiting', 'admission_busy', dispatched=False)
            dispatch_attempted = False
            try:
                config, fresh = self._fresh()
                require(fresh['stateRevision'] == observed['stateRevision'], 'stale_state_revision')
                locale = self._choose(fresh, requested_locale)
                if locale is None:
                    reason = 'layer2_capacity_reached' if self._capacity_full(fresh) else 'no_admitted_layer2_work'
                    return self._result('waiting', reason, nodes=fresh['nodes'], dispatched=False)
                _inputs(config, locale, fresh)
                ident = durable.identity(fresh, config.run_id, 'text.' + locale)
                key = jobs._digest(ident)
                dispatch_attempted = True
                outcome = jobs.start_job(config.job_root, ident, _worker_command(config, locale, key, self.code_sha, self.budget_authorization),
                                         timeout_seconds=21600, liveness_policy=LIVENESS_POLICY)
            except (ValueError, OSError, KeyError, TypeError):
                # Any persisted job intent remains discoverable; never retry an
                # uncertain start merely because this controller got an error.
                return self._result('blocked', 'admission_or_dispatch_requires_inspection',
                                    dispatched=None if dispatch_attempted else False)
            return self._result('waiting', 'verify_durable_job_and_candidate_evidence',
                                workUnitId='text.' + locale, job=outcome, dispatched=True)


def execute(config_path, locale, expected_configuration, expected_code, expected_job, *, caller=None, api_key=None, budget_authorization=None, expected_budget=None):
    """Fixed worker body. New jobs use the bound project API budget transport."""
    config = load_configuration(config_path)
    require(locale in config.lanes and config.sha256 == expected_configuration
            and code_identity() == expected_code, 'worker_configuration_or_code_changed')
    budget_binding = (budget_tools.load_authorization(config, budget_authorization, expected_code, expected_budget)
                      if budget_authorization is not None else None)
    require((budget_authorization is None) == (expected_budget is None), 'budget_worker_binding_required')
    lane = config.lanes[locale]
    with work_lock(lane['output']), accounting.accounting_session(
            lane['output'] / 'accounting', 'canonical_layer2_worker',
            {'targetLocale': locale, 'jobSha256': expected_job, 'productionRunId': config.run_id}, evidence_directory=lane['output']):
        with accounting.stage('layer2.worker_admission.' + locale, depends_on=[],
                executor_type='deterministic_program', work_unit_id='l2.' + locale + '.worker_admission') as admission_span:
            current = package_view(config)
            require(current['nodes']['text.' + locale]['status'] == 'ready', 'worker_node_not_ready')
            joined = durable.project(current, config.job_root, config.run_id)
            require(joined['nodes']['source']['status'] == 'validated'
                    and joined['nodes']['text.' + locale]['status'] == 'waiting_job'
                    and joined['nodes']['text.' + locale].get('reasonCode') == 'durable_job_active',
                    'worker_durable_admission_changed')
            ident = durable.identity(current, config.run_id, 'text.' + locale)
            require(jobs._digest(ident) == expected_job, 'worker_inputs_changed')
            request_path = config.job_root / expected_job / 'request.json'
            request = jobs._read(request_path)
            require(jobs._request_valid(request, expected_job) and request['identity'] == ident
                    and request['command'] == _worker_command(config, locale, expected_job, expected_code, budget_binding)
                    and request.get('livenessPolicy') == LIVENESS_POLICY
                    and jobs.peek_job(config.job_root, expected_job)['status'] == 'running',
                    'worker_requires_active_bound_durable_job')
            source, anchor, policy = _inputs(config, locale, current)
        with liveness.report(request_path.parent, request) as progress:
            if caller is None:
                require(budget_binding is not None, 'bound_budget_authorization_required')
                spark_admission.require_session()
                from scripts.sermon_openai_runtime import selected_route
                route = selected_route()
                require(route is not None, 'openai_layer2_requires_explicit_dev_or_prod_launcher')
                api_key = os.environ['OPENAI_API_KEY']
                caller = budget_tools.BudgetedCaller(budget_binding, config, source, anchor, policy)
                caller.execution_identity = {
                    'schemaVersion': 'openai-layer2-budget-transport-identity-v1',
                    'backend': 'openai_api', 'route': route,
                    'budgetAuthorizationSha256': budget_binding['sha256']}
                caller = spark_admission.SessionBoundCaller(caller)
            elif budget_binding is not None:
                from scripts.strict_budget_capability import reject_codex_cli_transport
                reject_codex_cli_transport(caller)
                caller = budget_tools.BudgetedCaller(budget_binding, config, source, anchor, policy, transport=caller)
            def current_binding():
                fresh_config = load_configuration(config.path)
                require(fresh_config.sha256 == expected_configuration and code_identity() == expected_code,
                        'worker_configuration_or_code_changed_during_models')
                fresh = package_view(fresh_config)
                require(fresh['nodes']['text.' + locale]['status'] == 'ready'
                        and jobs._digest(durable.identity(fresh, config.run_id, 'text.' + locale)) == expected_job,
                        'worker_inputs_changed_during_models')
                return fresh_config
            def bound_call(key, payload):
                current_binding()
                with api_concurrency.request_slot(config.job_root):
                    current_binding()
                    progress.progress('model_request')
                    return caller(key, payload)
            # Preserve terminal decoding and transport identity through the
            # state-binding wrapper. A CLI envelope is not an API response.
            for attribute in ('execution_identity', 'completed_content', 'admit_resource', 'billing'):
                if hasattr(caller, attribute):
                    setattr(bound_call, attribute, getattr(caller, attribute))
            model_completion = []
            with (budget_tools.request_limits(budget_binding['limits']) if budget_binding else nullcontext()):
                evidence = models.run_accounted(source, anchor, policy, lane['output'], api_key,
                                             bound_call, None, lane['plugin'], None, None,
                                             progress_callback=progress.progress, predecessor_spans=[admission_span],
                                             completion_spans=model_completion)
            # Paid results remain recoverable if approval/source/config/code drifted
            # while a request was outstanding. Never turn those results into approval.
            with accounting.stage('layer2.post_model_binding.' + locale, depends_on=model_completion,
                    executor_type='deterministic_program', work_unit_id='l2.' + locale + '.post_model_binding') as binding_span:
                progress.progress('models_validated')
                fresh_config = current_binding()
            with accounting.stage('layer2.language_and_candidate.' + locale, depends_on=[binding_span],
                    executor_type='deterministic_program', work_unit_id='l2.' + locale + '.candidate_admission') as candidate_span:
                original_request = producer._load(lane['output'] / 'request.json')
                rule_receipt = producer._load(lane['output'] / 'rule-preflight.json')
                plugin_sha = policy['languageReview']['pluginImplementationSha256']
                receipt = producer.run_language_plugin(source, anchor, policy, original_request, evidence,
                    lane['plugin'], plugin_sha, rule_preflight_receipt=rule_receipt)
                candidate = producer.admit_evidence(source, anchor, policy, original_request, evidence,
                    receipt, lane['plugin'], plugin_sha, rule_preflight_receipt=rule_receipt)
                current_binding()
                progress.progress('candidate_validated')
                models.save_new(lane['output'] / 'language-review.json', receipt)
                models.save_new(lane['candidate'], candidate)
                accounting.record_workload('layer2.candidate_identity', {'candidateSha256': jobs._digest(candidate),
                    'languageReviewSha256': jobs._digest(receipt)})
            with accounting.stage('layer2.final_package_validation.' + locale, depends_on=[candidate_span],
                    executor_type='deterministic_program', work_unit_id='l2.' + locale + '.final_package_validation'):
                checked = package_view(fresh_config)
                require(checked['nodes']['text.' + locale]['status'] == 'validated', 'worker_candidate_not_validated')
            return {'status': 'machine_review_pass_human_review_pending',
                    'candidateJsonSha256': jobs._digest(candidate), 'releaseEligible': False}


def drive(config_path, locale, *, budget_authorization=None):
    """One restart-safe unified tick; explicit bound budget is mandatory.

    Returns waiting for a durable owner, never calls execute directly. A later
    tick independently validates the candidate and durable outcome. Unknown
    original jobs require explicit reconciliation, never a fresh paid attempt.
    """
    if budget_authorization is None:
        return {'status': 'blocked', 'reason': 'bound_budget_authorization_required', 'dispatched': False}
    controller = Controller(config_path, mode='deterministic_execute', budget_authorization=budget_authorization)
    config = controller.config
    require(locale in config.lanes, 'locale_not_registered')
    view = snapshot(config)
    node = view['nodes']['text.' + locale]
    if node['status'] == 'validated':
        return {'status': 'succeeded', 'artifact': 'verified', 'review': 'human_pending',
                'productionEligible': False, 'dispatched': False,
                'candidateJsonSha256': view['packageIdentities']['candidate.' + locale]}
    if node['status'] in {'blocked', 'reconciliation_required'}:
        return {'status': 'blocked', 'reason': node.get('reasonCode', 'reconciliation_required'), 'dispatched': False}
    result = controller.tick(requested_locale=locale)
    return {'status': 'waiting' if result.get('status') != 'blocked' else 'blocked',
            'reason': result['reasonCode'], 'dispatched': result.get('dispatched'), 'evidence': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    tick = commands.add_parser('tick')
    tick.add_argument('--config', required=True, type=Path)
    tick.add_argument('--mode', choices=MODES, default='deterministic_shadow')
    worker = commands.add_parser('worker')
    worker.add_argument('--config', required=True, type=Path)
    worker.add_argument('--locale', required=True, choices=pipeline.LOCALES)
    worker.add_argument('--expected-configuration', required=True)
    worker.add_argument('--expected-code', required=True)
    worker.add_argument('--expected-job', required=True)
    worker.add_argument('--budget-authorization', type=Path)
    worker.add_argument('--expected-budget')
    args = parser.parse_args()
    if args.command == 'tick':
        result = Controller(args.config, mode=args.mode).tick()
    else:
        result = execute(args.config, args.locale, args.expected_configuration, args.expected_code, args.expected_job,
                         budget_authorization=args.budget_authorization, expected_budget=args.expected_budget)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

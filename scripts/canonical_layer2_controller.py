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
from scripts import inspect_canonical_packages as packages
from scripts import canonical_pipeline_definition as pipeline
from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as models
from scripts import sermon_accounting as accounting
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'sermon-canonical-layer2-execution-v1'
MODES = ('deterministic_shadow', 'deterministic_execute')
ADMISSION_LOCK = jobs._digest({'purpose': 'canonical-layer2-admission-v1'})
MAX_CONFIG_BYTES = 1024 * 1024
MAX_ACTIVE_LAYER2_JOBS = 1


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


def load_configuration(path):
    path = _safe_path(Path(path).absolute())
    value = _json(path)
    require(set(value) == {'schemaVersion', 'productionRunId', 'inspectionConfig', 'jobRoot', 'locales'}
            and value['schemaVersion'] == SCHEMA and pipeline._sha(value['productionRunId'])
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
    sha = jobs._digest({'execution': value, 'inspection': inspection, 'plugins': plugin_hashes})
    return Configuration(path, root, inspection, job_root, value['productionRunId'], lanes, sha)


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
            except (ValueError, OSError, KeyError, TypeError):
                view['nodes'][unit].update(status='blocked', reasonCode='fixed_layer2_admission_invalid')
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
    # Existing fixed model/worker limits remain production admission gates.
    require(all(policy[role]['model'] == model for role, model in models.MODEL_ROLES.items()), 'production_model_policy_changed')
    require(policy['batching']['batchSize'] == 1 and type(policy['batching']['workers']) is int
            and 1 <= policy['batching']['workers'] <= 3, 'invalid_production_worker_budget')
    producer.prepare_request(values['source'], values['anchor'], policy)
    return values['source'], values['anchor'], policy


def _worker_command(config, locale, job_id, code_sha):
    return [sys.executable, str(Path(__file__).resolve()), 'worker', '--config', str(config.path),
            '--locale', locale, '--expected-configuration', config.sha256,
            '--expected-code', code_sha, '--expected-job', job_id]


class Controller:
    def __init__(self, config_path, *, mode='deterministic_shadow'):
        require(mode in MODES, 'invalid_controller_mode')
        self.config = load_configuration(config_path)
        self.code_sha = code_identity()
        self.mode = mode

    def _result(self, status, reason, **fields):
        return {'schemaVersion': 'sermon-canonical-layer2-controller-result-v1',
                'mode': self.mode, 'scope': 'four_layer_release_layer2_preparation',
                'productionRunId': self.config.run_id, 'configurationSha256': self.config.sha256,
                'codeIdentitySha256': self.code_sha, 'status': status, 'reasonCode': reason,
                'maxConcurrentLocaleJobs': MAX_ACTIVE_LAYER2_JOBS,
                'runtimeCodexTurns': 0, 'contentAcceptance': 'not_evaluated',
                'deviceAcceptance': 'not_run', **fields}

    def _fresh(self):
        current = load_configuration(self.config.path)
        require(current.sha256 == self.config.sha256 and code_identity() == self.code_sha, 'configuration_or_code_changed')
        return current, snapshot(current)

    def _capacity_full(self, view):
        # Initial fixed adapter permits one locale job at a time within this
        # production run. Existing policy still bounds its group workers 1..3.
        active = [row for row in view['durableJobInspection']['jobs']
                  if row['workUnitId'].startswith('text.') and row['status'] in jobs.ACTIVE]
        return len(active) >= MAX_ACTIVE_LAYER2_JOBS

    def _choose(self, view):
        if self._capacity_full(view):
            return None
        for locale in sorted(self.config.lanes):
            if view['nodes'].get('text.' + locale, {}).get('status') == 'ready':
                return locale
        return None

    def tick(self):
        try:
            config, observed = self._fresh()
        except (ValueError, OSError, KeyError, TypeError):
            return self._result('blocked', 'configuration_code_or_evidence_invalid', dispatched=False)
        locale = self._choose(observed)
        if self.mode == 'deterministic_shadow':
            return self._result('ready' if locale else 'waiting',
                                'layer2_capacity_reached' if self._capacity_full(observed) else 'shadow_only',
                                proposedWorkUnit='text.' + locale if locale else None,
                                stateRevision=observed['stateRevision'], nodes=observed['nodes'], dispatched=False)
        with jobs._lock(config.job_root, ADMISSION_LOCK) as (_, _, held):
            if not held:
                return self._result('waiting', 'admission_busy', dispatched=False)
            try:
                config, fresh = self._fresh()
                require(fresh['stateRevision'] == observed['stateRevision'], 'stale_state_revision')
                locale = self._choose(fresh)
                if locale is None:
                    reason = 'layer2_capacity_reached' if self._capacity_full(fresh) else 'no_admitted_layer2_work'
                    return self._result('waiting', reason, nodes=fresh['nodes'], dispatched=False)
                _inputs(config, locale, fresh)
                ident = durable.identity(fresh, config.run_id, 'text.' + locale)
                key = jobs._digest(ident)
                outcome = jobs.start_job(config.job_root, ident, _worker_command(config, locale, key, self.code_sha),
                                         timeout_seconds=21600)
            except (ValueError, OSError, KeyError, TypeError):
                # Any persisted job intent remains discoverable; never retry an
                # uncertain start merely because this controller got an error.
                return self._result('blocked', 'admission_or_dispatch_requires_inspection', dispatched=None)
            return self._result('waiting', 'verify_durable_job_and_candidate_evidence',
                                workUnitId='text.' + locale, job=outcome, dispatched=True)


def execute(config_path, locale, expected_configuration, expected_code, expected_job, *, caller=None, api_key=None):
    """Fixed worker body. Injected transport is for local tests; CLI uses policy API."""
    config = load_configuration(config_path)
    require(locale in config.lanes and config.sha256 == expected_configuration
            and code_identity() == expected_code, 'worker_configuration_or_code_changed')
    lane = config.lanes[locale]
    with work_lock(lane['output']):
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
                and request['command'] == _worker_command(config, locale, expected_job, expected_code)
                and jobs.peek_job(config.job_root, expected_job)['status'] == 'running',
                'worker_requires_active_bound_durable_job')
        source, anchor, policy = _inputs(config, locale, current)
        if caller is None:
            api_key = os.environ.get('OPENAI_API_KEY')
            require(bool(api_key), 'OPENAI_API_KEY_is_not_configured')
            caller = lambda key, payload: models.sermon_pipeline.chat_json(key, payload, retries=1)
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
            return caller(key, payload)
        evidence = models.run_accounted(source, anchor, policy, lane['output'], api_key,
                                         bound_call, None, lane['plugin'], None, None)
        # Paid results remain recoverable if approval/source/config/code drifted
        # while a request was outstanding. Never turn those results into approval.
        fresh_config = current_binding()
        with accounting.accounting_session(lane['output'] / 'accounting', 'canonical_layer2_candidate',
                                           {'targetLocale': locale}, evidence_directory=lane['output']):
            with accounting.stage('layer2.language_and_candidate.' + locale, depends_on=[],
                                  executor_type='deterministic_program', work_unit_id='l2.' + locale + '.candidate_admission'):
                original_request = producer._load(lane['output'] / 'request.json')
                plugin_sha = policy['languageReview']['pluginImplementationSha256']
                receipt = producer.run_language_plugin(source, anchor, policy, original_request, evidence, lane['plugin'], plugin_sha)
                candidate = producer.admit_evidence(source, anchor, policy, original_request, evidence, receipt, lane['plugin'], plugin_sha)
                models.save_new(lane['output'] / 'language-review.json', receipt)
                models.save_new(lane['candidate'], candidate)
        checked = package_view(fresh_config)
        require(checked['nodes']['text.' + locale]['status'] == 'validated', 'worker_candidate_not_validated')
        return {'status': 'machine_review_pass_human_review_pending',
                'candidateJsonSha256': jobs._digest(candidate), 'releaseEligible': False}


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
    args = parser.parse_args()
    if args.command == 'tick':
        result = Controller(args.config, mode=args.mode).tick()
    else:
        result = execute(args.config, args.locale, args.expected_configuration, args.expected_code, args.expected_job)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Run real Codex language calls through the existing isolated Layer 2 test loop.

Only test evidence: simulated Layer 1 receipts cannot produce a formal candidate.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_target_language_models as runner, sermon_accounting as accounting
from scripts import target_language_policy as policy_tools
from scripts import production_spark_admission as spark_admission
from scripts.codex_layer2_transport import CodexLayer2Transport, TEST_CONFIGURATION, validate_test_configuration


def bind_context(out_dir, context):
    """Persist implementation identity before dispatch, outside the empty run dir.

    A hard kill before the runner's first manifest still leaves a durable binding.
    Legacy directories must already have their final context; never infer it.
    """
    marker = out_dir.with_name(out_dir.name + '-pre-dispatch-context.json')
    existing = out_dir / 'test-context.json'
    if existing.exists() and json.loads(existing.read_text()) != context:
        raise ValueError('CLI test implementation or context changed; use a new output identity')
    if marker.exists():
        if json.loads(marker.read_text()) != context:
            raise ValueError('CLI pre-dispatch context changed; use a new output identity')
    else:
        if (out_dir / 'run-identity.json').exists() and not existing.exists():
            raise ValueError('Existing CLI run has no pre-dispatch context; reconcile before resume')
        runner.save_new(marker, context, private=True)



class FixtureLayer2Transport:
    """Replay complete, bound raw CLI receipts without any live transport."""
    billing = 'local'

    def __init__(self, responses_dir, *, group_count=13):
        self.root = Path(responses_dir).resolve()
        self.responses = {}
        inventory = {}
        origin = self.root / 'test-context.json'
        origin_identity = json.loads(origin.read_text())['modelTransportIdentity']
        inventory[origin.name] = hashlib.sha256(origin.read_bytes()).hexdigest()
        for index in range(1, group_count + 1):
            for suffix, role in [('astra', 'translator'), ('sol', 'reviewer')]:
                stem = f'group-{index:04d}-{suffix}'
                raw_path = self.root / (stem + '.raw.json')
                preview_path = self.root / (stem + '.policy-preview.json')
                raw = json.loads(raw_path.read_text())
                payload = json.loads(preview_path.read_text())['payload']
                expected = policy_tools.canonical_sha256({'payload': payload,
                    'modelTransportIdentity': origin_identity})
                if raw.get('payloadSha256') != expected:
                    raise ValueError('Fixture original payload binding differs: ' + stem)
                content = CodexLayer2Transport.completed_content(raw['response'], payload['model'], role)
                key = policy_tools.canonical_sha256(payload)
                if key in self.responses:
                    raise ValueError('Duplicate fixture request payload')
                self.responses[key] = {'schemaVersion': 'fixture-layer2-response-v1',
                    'id': 'fixture:' + hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    'content': content, 'requestedModel': payload['model'], 'role': role,
                    'completed': True, 'realModelCalls': False, 'historicalResponseId': raw['response']['id']}
                for path in (raw_path, preview_path):
                    inventory[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.execution_identity = {'schemaVersion': 'fixture-layer2-transport-identity-v1',
            'backend': 'fixture_replay', 'realModelCalls': False,
            'responsesSha256': policy_tools.canonical_sha256(inventory), 'files': inventory}
        if 'simulationModelConfiguration' in origin_identity:
            self.execution_identity['simulationModelConfiguration'] = copy.deepcopy(origin_identity['simulationModelConfiguration'])

    def __call__(self, api_key, payload):
        if api_key:
            raise ValueError('Fixture replay must not receive an API key')
        for name, expected in self.execution_identity['files'].items():
            if hashlib.sha256((self.root / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Fixture receipt changed after binding: ' + name)
        key = policy_tools.canonical_sha256(payload)
        if key not in self.responses:
            raise ValueError('Fixture replay has no exactly matching frozen payload')
        return dict(self.responses[key])

    @staticmethod
    def completed_content(response, model, role):
        if (response.get('schemaVersion') != 'fixture-layer2-response-v1'
                or response.get('requestedModel') != model or response.get('role') != role
                or response.get('realModelCalls') is not False or response.get('completed') is not True):
            raise ValueError('Invalid fixture terminal response')
        return response['content']


def run_diagnostic_test(fixture_dir, out_dir, *, cli_path, reviewer_tier='fast', timeout_seconds=180,
                        mock_responses_dir=None, resource_policy_path=None, translator_model=None,
                        session_verifier=None, backend='codex', reuse_api_receipts=None,
                        budget_config_path=None, reuse_from=None, partial_repair_brief=None):
    from scripts import codex_layer2_diagnostic as diagnostic
    inputs = diagnostic.load_fixture(fixture_dir)  # All gates before constructing a CLI transport.
    source, anchor, policy, plan, plugin, request, receipt, scope, manifest = inputs
    out_dir = diagnostic.artifact_directory(out_dir)
    configuration = policy.get('simulationModelConfiguration')
    if translator_model is not None and (configuration is None or policy['translator']['model'] != translator_model):
        raise ValueError('Diagnostic model configuration must be frozen in the fixture')
    if mock_responses_dir is not None and resource_policy_path is not None:
        raise ValueError('Fixture replay cannot claim real CLI resource admission')
    if backend not in ('codex','openai_api') or (backend=='openai_api' and mock_responses_dir is not None):
        raise ValueError('unsupported_diagnostic_model_backend')
    if reuse_api_receipts is not None and backend != 'openai_api':
        raise ValueError('diagnostic_api_receipt_reuse_requires_openai_backend')
    if partial_repair_brief is not None and (backend != 'openai_api' or reuse_from is None):
        raise ValueError('diagnostic_partial_repair_requires_api_and_prior_run')
    if reuse_from is not None and partial_repair_brief is None:
        raise ValueError('diagnostic_prior_run_reuse_requires_partial_repair')
    if partial_repair_brief is not None and (
            not isinstance(partial_repair_brief, dict)
            or not isinstance(partial_repair_brief.get('groups'), list)
            or len(partial_repair_brief['groups']) != 1):
        raise ValueError('diagnostic_partial_repair_must_target_exactly_one_group')
    options = {}
    if manifest.get('concurrencyProfile') is not None:
        options['concurrency_profile'] = manifest['concurrencyProfile']
        if resource_policy_path is None and mock_responses_dir is None:
            raise ValueError('Concurrent CLI diagnostics require the shared resource policy')
    if configuration is not None:
        options['simulation_model_configuration'] = configuration
    if resource_policy_path is not None:
        from scripts.sermon_unified import resources
        options['resource_policy'] = resources.validate_policy(json.loads(Path(resource_policy_path).read_text()))
    if mock_responses_dir is None:
        spark_admission.require_session(verifier=session_verifier)
    if backend=='openai_api':
        from scripts.openai_layer2_diagnostic_transport import OpenAILayer2DiagnosticTransport
        if resource_policy_path is None or manifest.get('concurrencyProfile') is None:
            raise ValueError('openai_diagnostic_shared_resource_policy_required')
        if budget_config_path is None or configuration is None:
            raise ValueError('openai_diagnostic_budget_and_model_binding_required')
        transport=OpenAILayer2DiagnosticTransport(receipts_dir=out_dir/'_api_calls',
            resource_policy=options['resource_policy'],concurrency_profile=manifest['concurrencyProfile'],
            timeout_seconds=timeout_seconds,reuse_receipts_dir=reuse_api_receipts,
            budget_config_path=budget_config_path,simulation_model_configuration=configuration,
            fixture_manifest_sha256=policy_tools.canonical_sha256(manifest))
    else:
        transport = (FixtureLayer2Transport(mock_responses_dir, group_count=len(plan)) if mock_responses_dir is not None
                     else CodexLayer2Transport(cli_path, reviewer_tier=reviewer_tier, timeout_seconds=timeout_seconds,
                                              receipts_dir=out_dir / '_cli_calls', **options))
    if mock_responses_dir is None and backend=='codex':
        transport = spark_admission.SessionBoundCaller(transport, verifier=session_verifier)
    structural = plugin.name == 'diagnostic_structural.py'
    context = {'schemaVersion': 'codex-layer2-diagnostic-test-run-v1', 'simulationOnly': True,
               'realModelCalls': mock_responses_dir is None, 'productionEligible': False, 'humanApproval': False,
               'fixtureDir': str(Path(fixture_dir).resolve()), 'fixtureManifestSha256': policy_tools.canonical_sha256(manifest),
               'diagnosticContextSha256': policy_tools.canonical_sha256(scope),
               'sourceMediaSha256': manifest['sourceMediaSha256'], 'sourceWindow': manifest['sourceWindow'],
               'modelTransportIdentity': transport.execution_identity, 'groupPlanSha256': policy_tools.canonical_sha256(plan),
               'rulePreflightSha256': policy_tools.canonical_sha256(receipt), 'ruleBundleSha256': receipt['ruleBundleSha256'],
               'pluginPath': str(plugin), 'pluginImplementationSha256': manifest['pluginImplementationSha256'],
               'qualityScope': 'structural_only_no_direct_scripture_acceptance' if structural else 'pinned_plugin_checks_only',
               'implementationSha256': {name: policy_tools.file_sha256(Path(module.__file__)) for name, module in
                   [('command', sys.modules[__name__]), ('diagnostic', diagnostic), ('runner', runner),
                    ('producer', runner.producer), ('policy', policy_tools), ('candidate_validator', runner.producer.handoff)]}}
    bind_context(out_dir, context)
    with accounting.accounting_session(out_dir / 'accounting', 'codex_layer2_diagnostic_test',
                                       {'targetLocale': policy['targetLocale']}, evidence_directory=out_dir):
        try:
            evidence, language, envelope = diagnostic.run_chain(inputs, out_dir, transport,
                reuse_from=Path(reuse_from).resolve() if reuse_from is not None else None,
                partial_repair_brief=partial_repair_brief)
        finally:
            if backend == 'openai_api':
                diagnostic.save(out_dir / 'api-transport-receipt.json', transport.concurrency_report())
            if (out_dir / 'run-identity.json').exists():
                diagnostic.save(out_dir / 'test-context.json', context)
    report = {**context, 'status': 'diagnostic_candidate_admitted_human_pending',
              'sourceUnits': len(anchor['sourceUnits']), 'groups': len(plan),
              'languagePlugin': 'executed_pass', 'canonicalCandidateAdmission': 'executed_diagnostic_only',
              'evidenceSha256': policy_tools.canonical_sha256(evidence),
              'languageReviewSha256': policy_tools.canonical_sha256(language),
              'diagnosticCandidateSha256': policy_tools.canonical_sha256(envelope)}
    if backend == 'openai_api':
        report['apiConcurrency'] = transport.concurrency_report()
        report['budgetConfigSha256'] = transport._budget_identity
        report['budgetHardLimitMicrousd'] = transport.budget_config['hardLimitMicrousd']
        report['budgetLedger'] = str(transport.budget_ledger_path)
    diagnostic.save(out_dir / 'test-report.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return report


def run_test(fixture_dir, policy_path, out_dir, *, cli_path, reviewer_tier='fast', timeout_seconds=180,
             mock_responses_dir=None, resource_policy_path=None, translator_model=None,
             diagnostic_fixture=False, session_verifier=None, backend='codex', budget_config_path=None,
             reuse_from=None, partial_repair_brief=None):
    if diagnostic_fixture:
        return run_diagnostic_test(fixture_dir, out_dir, cli_path=cli_path, reviewer_tier=reviewer_tier,
            timeout_seconds=timeout_seconds, mock_responses_dir=mock_responses_dir,
            resource_policy_path=resource_policy_path, translator_model=translator_model,
            session_verifier=session_verifier, backend=backend, budget_config_path=budget_config_path,
            reuse_from=reuse_from, partial_repair_brief=partial_repair_brief)
    if reuse_from is not None or partial_repair_brief is not None:
        raise ValueError('diagnostic_repair_requires_diagnostic_fixture')
    fixture_dir, out_dir = Path(fixture_dir).resolve(), Path(out_dir).resolve()
    root = Path(__file__).resolve().parents[1]
    if not out_dir.is_relative_to(root / 'artifacts') or out_dir == root / 'artifacts':
        raise ValueError('CLI test outputs must be a dedicated ignored artifacts directory')
    load = lambda name: json.loads((fixture_dir / name).read_text())
    scope = load('simulation-scope-report.json')
    if scope.get('simulationOnly') is not True or scope.get('productionEligible') is not False \
            or scope.get('actualHumanApproval') is not False:
        raise ValueError('CLI test requires explicitly simulated fixture scope')
    source, anchor = load('source.json'), load('anchor.json')
    policy = json.loads(Path(policy_path).read_text())
    if policy.get('targetLocale') != 'zh-Hans':
        raise ValueError('Fixed CLI test currently supports zh-Hans only')
    runner.validate_standalone_worker_budget(policy)
    if policy['batching']['workers'] != 1:
        raise ValueError('CLI test runs one group and locale at a time')
    units = anchor['sourceUnits']
    media_sha = source['source']['media']['sha256']
    if len(units) != 39 or media_sha != '79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b':
        raise ValueError('Not the frozen fixed three-minute fixture')
    groups = load('zh-Hans/candidate.json')['groups']
    # Consume ONLY upstream identities and original group membership, never old target text.
    plan = [{'translationGroupId': row['translationGroupId'], 'sourceUnitIds': row['sourceUnitIds']}
            for row in groups]
    if len(plan) != 13:
        raise ValueError('Fixed fixture requires thirteen original groups')
    simulation_configuration = None
    baseline_policy_sha256 = policy_tools.canonical_sha256(policy)
    if translator_model is not None or mock_responses_dir is None:
        if translator_model not in (None, 'gpt-6.1-sol') or mock_responses_dir is not None:
            raise ValueError('Explicit Sol 6.1 configuration requires a fresh live isolated test')
        policy_tools.validate_policy(policy)
        simulation_configuration = validate_test_configuration(TEST_CONFIGURATION)
        policy = copy.deepcopy(policy)
        for role in ('translator', 'reviewer'):
            policy[role].update({key: value for key, value in simulation_configuration[role].items() if key != 'serviceTier'})
            policy['componentSha256'][role] = policy_tools.canonical_sha256(policy[role])
        policy['simulationModelConfiguration'] = simulation_configuration
    request = {'schemaVersion': 'sermon-dry-run-layer2-request-v1',
               'simulationOnly': True, 'sourceLocale': 'en', 'targetLocale': 'zh-Hans',
               'englishSourcePackageJsonSha256': policy_tools.canonical_sha256(source),
               'anchorManifestSha256': policy_tools.canonical_sha256(anchor),
               'translationPolicySha256': policy_tools.canonical_sha256(policy),
               'sourceUnits': [{'sourceUnitId': u['sourceUnitId'], 'english': u['english']} for u in units],
               'generation': None, 'groups': None}
    if simulation_configuration is not None:
        request['simulationModelConfiguration'] = simulation_configuration
        request['baselineTranslationPolicySha256'] = baseline_policy_sha256
    runner.group_plan(request, anchor, plan)
    if mock_responses_dir is not None and resource_policy_path is not None:
        raise ValueError('Fixture replay cannot claim real CLI resource admission')
    resource_options = {}
    if resource_policy_path is not None:
        from scripts.sermon_unified import resources
        resource_options['resource_policy'] = resources.validate_policy(
            json.loads(Path(resource_policy_path).read_text()))
    if simulation_configuration is not None:
        resource_options['simulation_model_configuration'] = simulation_configuration
    if mock_responses_dir is None:
        spark_admission.require_session(verifier=session_verifier)
    transport = (FixtureLayer2Transport(mock_responses_dir) if mock_responses_dir is not None
                 else CodexLayer2Transport(cli_path, reviewer_tier=reviewer_tier,
                                    timeout_seconds=timeout_seconds, receipts_dir=out_dir / '_cli_calls', **resource_options))
    if mock_responses_dir is None:
        transport = spark_admission.SessionBoundCaller(transport, verifier=session_verifier)
    context = {'schemaVersion': 'codex-layer2-test-run-v1', 'simulationOnly': True,
               'realModelCalls': mock_responses_dir is None, 'productionEligible': False, 'humanApproval': False,
               'fixtureDir': str(fixture_dir), 'sourceMediaSha256': media_sha,
               'sourceDurationSeconds': source['source']['media']['durationSeconds'],
               'modelTransportIdentity': transport.execution_identity,
               'groupPlanSha256': policy_tools.canonical_sha256(plan),
               'commandImplementationSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'runnerImplementationSha256': hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
               'languagePlugin': 'not_run', 'canonicalCandidateAdmission': 'not_run'}
    if simulation_configuration is not None:
        context['simulationModelConfiguration'] = simulation_configuration
        context['baselineTranslationPolicySha256'] = baseline_policy_sha256
        context['effectiveTranslationPolicySha256'] = policy_tools.canonical_sha256(policy)
    context_path = out_dir / 'test-context.json'
    if context_path.exists() and json.loads(context_path.read_text()) != context:
        raise ValueError('CLI test implementation or context changed; use a new output identity')
    bind_context(out_dir, context)
    # Identity and request are persisted by the shared runner before the first model call.
    with accounting.accounting_session(out_dir / 'accounting', 'codex_layer2_fixed_180s_test',
                                       {'targetLocale': 'zh-Hans'}, evidence_directory=out_dir):
        try:
            evidence = runner._run_prepared_groups(request, anchor, policy, out_dir,
                                                  '', transport, plan, simulation_only=True)
        finally:
            if (out_dir / 'run-identity.json').exists():
                runner.save_new(context_path, context) if not context_path.exists() else None
    report = {**context, 'status': ('fixture_replay_pass_test_only' if mock_responses_dir is not None
              else 'machine_review_pass_test_only'), 'sourceUnits': len(units),
              'groups': len(evidence['groups']), 'evidenceSha256': policy_tools.canonical_sha256(evidence)}
    report_path = out_dir / 'test-report.json'
    if not report_path.exists():
        runner.save_new(report_path, report)
    elif json.loads(report_path.read_text()) != report:
        raise ValueError('CLI test report changed')
    print(json.dumps(report, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-dir', type=Path, required=True)
    parser.add_argument('--diagnostic-fixture', action='store_true', help='Frozen unapproved-source CLI/plugin/candidate diagnostic chain; arbitrary complete group count')
    parser.add_argument('--policy', type=Path, default=Path('config/target-language-policies/zh-Hans.json'))
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--codex-cli', type=Path, default=Path.home() / '.local/bin/codex')
    parser.add_argument('--mock-responses-dir', type=Path, help='Replay 26 bound historical raw receipts; no CLI or API calls')
    parser.add_argument('--translator-model', choices=['gpt-6.1-sol'], help='Isolated test override: GPT-6.1 Sol high fast; production CLI defaults')
    parser.add_argument('--reviewer-tier', choices=['default', 'fast'], default='fast')
    parser.add_argument('--timeout-seconds', type=int, default=180)
    parser.add_argument('--resource-policy', type=Path, help='Explicit shared host-local CLI admission policy')
    parser.add_argument('--backend', choices=['codex', 'openai_api'], default='codex',
                        help='Isolated diagnostic transport; OpenAI API requires --budget-config')
    parser.add_argument('--budget-config', type=Path, help='Bound request/cost cap for diagnostic OpenAI API calls')
    parser.add_argument('--reuse-from', type=Path, help='Prior diagnostic output for a one-group revision')
    parser.add_argument('--partial-repair-brief', type=Path, help='Source-bound one-group repair instruction JSON')
    args = parser.parse_args()
    from scripts.outcome_marker import run_with_outcome
    run_with_outcome(args.out_dir / 'outcome.json', 'codex-layer2-test', lambda: run_test(
        args.fixture_dir, args.policy, args.out_dir, cli_path=args.codex_cli,
        reviewer_tier=args.reviewer_tier, timeout_seconds=args.timeout_seconds,
        mock_responses_dir=args.mock_responses_dir, resource_policy_path=args.resource_policy,
        translator_model=args.translator_model, diagnostic_fixture=args.diagnostic_fixture,
        backend=args.backend, budget_config_path=args.budget_config,
        reuse_from=args.reuse_from,
        partial_repair_brief=(json.loads(args.partial_repair_brief.read_text())
                              if args.partial_repair_brief is not None else None)))


if __name__ == '__main__':
    main()

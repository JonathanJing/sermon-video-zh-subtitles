"""Isolated simulated-review continuation of an EXISTING bounded diagnostic.

Never changes the original run plan, provider config, budget or deadline. The
separate continuation identity records new reviewed adapter code. No ASR/source
rerun, production approval, admission, publication or credential discovery.
"""
import argparse
import json
import os
from pathlib import Path

from scripts import run_bounded_diagnostic as run
from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_log_profile as profile
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as models
from scripts.sermon_release_workflow import _safe_path


def prepare_continuation(plan, continuation):
    c.require(type(continuation) is dict and set(continuation) == {
        'schemaVersion', 'originalPlanSha256', 'executionIdentity', 'diagnosticContext'} and
        continuation['schemaVersion'] == 'sermon-diagnostic-continuation-v1',
        'invalid_diagnostic_continuation')
    c.require(type(plan) is dict and set(plan) == {'schemaVersion', 'runDirectory',
        'providerConfig', 'authority', 'executionIdentity', 'sourceClipPath'} and
        plan['schemaVersion'] == 'sermon-bounded-diagnostic-plan-v1', 'invalid_diagnostic_plan')
    c.require(c.canonical_sha256(plan) == continuation['originalPlanSha256'],
              'diagnostic_original_plan_changed')
    identity = accounting.execution_identity()
    c.require(identity['trackedWorkingTreeDirty'] is False and identity['gitCommit'] is not None and
              identity == continuation['executionIdentity'], 'diagnostic_continuation_code_changed')
    context = diagnostic.validate_context(continuation['diagnosticContext'])
    c.require(context['continuationCodeCommit'] == identity['gitCommit'],
              'diagnostic_continuation_code_changed')
    config = provider.validate_config(plan['providerConfig'])
    c.require(c.canonical_sha256(plan['executionIdentity']) == config['codeSha256'],
              'diagnostic_original_code_binding_changed')
    root = _safe_path(Path(plan['runDirectory']))
    c.require(root.is_absolute(), 'diagnostic_absolute_directory_required')
    saved, _ = c.read_snapshot(root / 'run-plan.json')
    c.require(saved == plan, 'diagnostic_original_plan_changed')
    run.verify_source_clip(plan['sourceClipPath'], config['sourceClipSha256'])
    store = budget.BudgetStore(root / 'budget', plan['authority'])
    c.require(context['runId'] == config['runId'] and
              context['runConfigSha256'] == c.canonical_sha256(config) and
              context['storeSha256'] == store.store_sha256, 'diagnostic_continuation_provider_changed')
    # No fresh store is permitted: preserve the already started clock/quota.
    c.require((store.root / budget.STORE_ID / 'provider-run' / 'state.json').is_file(),
              'diagnostic_existing_provider_required')
    subject = provider.DiagnosticProvider(store, config)
    with subject._locked() as (_, state):
        subject._remaining(state)
        c.require(state['requests'] and all(row['state'] in ('returned', 'rejected')
                  for row in state['requests'].values()), 'diagnostic_prior_outcome_requires_reconciliation')
        deadline = state['startedMonotonic'] + config['totalWallSeconds']
    return root, subject, context, deadline


def preflight_locale_inputs(subject, context, spec):
    c.require(type(spec) is dict and set(spec) == {'source', 'anchor', 'policy', 'rubric', 'graph',
        'pluginPath', 'pluginSha256', 'groupPlan'}, 'invalid_diagnostic_locale_spec')
    artifacts = [public.read_snapshot(Path(spec[name]))[1] for name in ('source', 'anchor', 'policy', 'rubric')]
    source, anchor, policy, rubric = map(c.decode_json, artifacts)
    diagnostic.validate_source(source, anchor, context)
    request = producer.prepare_request(source, anchor, policy, strict_rubric=rubric, diagnostic_context=context)
    plan = models.group_plan(request, anchor, spec['groupPlan'])
    prepared = [strict.prepare(*artifacts, group, request_limits=subject.limits,
                              diagnostic_context=context) for group in plan]
    subject.preflight_locale(prepared)
    models.require_plugin_identity(Path(spec['pluginPath']), spec['pluginSha256'])
    c.require(policy['languageReview']['pluginImplementationSha256'] == spec['pluginSha256'],
              'strict_locale_plugin_policy_changed')
    return artifacts, plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--continuation', type=Path, required=True)
    parser.add_argument('--phase', choices=('preflight', 'locale'), required=True)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--key-fd', type=int)
    args = parser.parse_args(argv)
    plan, _ = c.read_snapshot(args.plan)
    continuation, _ = c.read_snapshot(args.continuation)
    root, subject, context, deadline = prepare_continuation(plan, continuation)
    spec = None
    if args.input is not None:
        spec, _ = c.read_snapshot(args.input)
        artifacts, groups = preflight_locale_inputs(subject, context, spec)
    if args.phase == 'preflight':
        print(json.dumps({'status': 'prepared', 'newCalls': 0, 'credentialRead': False,
            'humanAcceptance': 'pending', 'productionEligible': False,
            'groupCount': len(groups) if spec is not None else None,
            'remainingSeconds': deadline-subject.monotonic(), 'budget': subject.snapshot()}))
        return
    c.require(args.input is not None and args.key_fd is not None and args.key_fd >= 3,
              'diagnostic_private_input_and_key_fd_required')
    with os.fdopen(args.key_fd, 'rb') as stream:
        key_bytes = stream.read(1025)
    c.require(0 < len(key_bytes) <= 1024, 'invalid_diagnostic_credential_length')
    key = key_bytes.decode('ascii').strip()
    evidence_root = root / 'diagnostic-continuations' / c.canonical_sha256(continuation)
    strict.save_once(evidence_root / 'continuation.json', continuation)
    runner = run.BoundedRun(subject, key, root, source_clip=plan['sourceClipPath'])
    with profile.session(root / 'continuation-logs', 'bounded-diagnostic-continuation',
            work_kind='production', evidence_mode='current_execution', production_run_id=subject.config['runId']):
        accounting.record_workload('diagnostic.simulated_review', {
            'simulatedHumanApproval': True, 'realHumanAcceptancePending': True,
            'productionEligible': False, 'continuationSha256': c.canonical_sha256(continuation),
            'sourceMediaSha256': subject.config['sourceMediaSha256']})
        result = runner.run_locale(*artifacts, graph=spec['graph'], plugin_path=Path(spec['pluginPath']),
            plugin_sha256=spec['pluginSha256'], group_plan=spec['groupPlan'], diagnostic_context=context)
        wrapped = {'schemaVersion': 'sermon-isolated-diagnostic-result-v1',
                   'humanAcceptance': 'pending', 'productionEligible': False,
                   'diagnosticContextSha256': c.canonical_sha256(context), 'result': result}
        strict.save_once(evidence_root / ('locale.'+c.canonical_sha256(wrapped)+'.json'), wrapped)
        print(json.dumps({'phase': 'locale', 'resultSha256': c.canonical_sha256(wrapped),
                         'status': result['status'], 'humanAcceptance': 'pending',
                         'productionEligible': False, 'budget': subject.snapshot()}))


if __name__ == '__main__':
    main()

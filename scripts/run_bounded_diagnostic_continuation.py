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
from scripts.sermon_diagnostic_source_evidence import validate_prior_source_evidence
from scripts.sermon_release_workflow import _safe_path


def prepare_continuation(plan, continuation, *, request_limits=None):
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
    # The continuation limit snapshot is execution identity, not a CLI default.
    # Validate an explicit replacement before constructing any dispatch surface.
    limits_path = root / 'continuation-request-limits.json'
    if limits_path.exists():
        saved_limits, _ = c.read_snapshot(limits_path)
        if request_limits is not None:
            c.require(request_limits == saved_limits, 'immutable_strict_artifact_changed')
        request_limits = saved_limits
    c.require(request_limits is not None, 'diagnostic_continuation_request_limits_required')
    selected_limits = provider.limits.validate_request_limits(request_limits)
    subject = provider.DiagnosticProvider(store, config, selected_limits)
    with subject._locked() as (_, state):
        subject._remaining(state)
        c.require(state['requests'] and all(row['state'] in ('returned', 'rejected')
                  for row in state['requests'].values()), 'diagnostic_prior_outcome_requires_reconciliation')
        source_evidence = validate_prior_source_evidence(root, state, context)
        deadline = state['startedMonotonic'] + config['totalWallSeconds']
    return root, subject, context, deadline, source_evidence


def preflight_locale_inputs(subject, context, spec):
    c.require(type(spec) is dict and set(spec) == {'source', 'anchor', 'policy', 'rubric', 'graph',
        'pluginPath', 'pluginSha256', 'groupPlan'}, 'invalid_diagnostic_locale_spec')
    artifacts = [public.read_snapshot(Path(spec[name]))[1] for name in ('source', 'anchor', 'policy', 'rubric')]
    from scripts.sermon_strict_locale import prepare_locale_inputs
    _, _, _, plan, prepared = prepare_locale_inputs(*artifacts,
        plugin_path=Path(spec['pluginPath']), expected_plugin_sha256=spec['pluginSha256'],
        group_plan=spec['groupPlan'], request_limits=subject.limits, diagnostic_context=context)
    subject.preflight_locale(prepared)
    return artifacts, plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--continuation', type=Path, required=True)
    parser.add_argument('--phase', choices=('preflight', 'locale'), required=True)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--key-fd', type=int)
    parser.add_argument('--resume-legacy-locale', action='store_true',
        help='Explicitly inspect/resume immutable v1 locale inputs; unproven old rules block new calls')
    parser.add_argument('--request-limits', type=Path, help='Initial request limits; resumes reuse the frozen snapshot')
    args = parser.parse_args(argv)
    plan, _ = c.read_snapshot(args.plan)
    continuation, _ = c.read_snapshot(args.continuation)
    root, subject, context, deadline, source_evidence = prepare_continuation(plan, continuation,
        request_limits=c.read_snapshot(args.request_limits)[0] if args.request_limits else None)
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
    strict.save_once(root / 'continuation-request-limits.json', subject.limits)
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
            'sourceMediaSha256': subject.config['sourceMediaSha256'], **source_evidence})
        result = runner.run_locale(*artifacts, resume_legacy=args.resume_legacy_locale, graph=spec['graph'], plugin_path=Path(spec['pluginPath']),
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

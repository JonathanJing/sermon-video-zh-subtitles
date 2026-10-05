#!/usr/bin/env python3
"""Run real Codex language calls through the existing isolated Layer 2 test loop.

Only test evidence: simulated Layer 1 receipts cannot produce a formal candidate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_target_language_models as runner, sermon_accounting as accounting
from scripts import target_language_policy as policy_tools
from scripts.codex_layer2_transport import CodexLayer2Transport


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


def run_test(fixture_dir, policy_path, out_dir, *, cli_path, reviewer_tier='fast', timeout_seconds=180):
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
    request = {'schemaVersion': 'sermon-dry-run-layer2-request-v1',
               'simulationOnly': True, 'sourceLocale': 'en', 'targetLocale': 'zh-Hans',
               'englishSourcePackageJsonSha256': policy_tools.canonical_sha256(source),
               'anchorManifestSha256': policy_tools.canonical_sha256(anchor),
               'translationPolicySha256': policy_tools.canonical_sha256(policy),
               'sourceUnits': [{'sourceUnitId': u['sourceUnitId'], 'english': u['english']} for u in units],
               'generation': None, 'groups': None}
    runner.group_plan(request, anchor, plan)
    transport = CodexLayer2Transport(cli_path, reviewer_tier=reviewer_tier,
                                    timeout_seconds=timeout_seconds, receipts_dir=out_dir / '_cli_calls')
    context = {'schemaVersion': 'codex-layer2-test-run-v1', 'simulationOnly': True,
               'realModelCalls': True, 'productionEligible': False, 'humanApproval': False,
               'fixtureDir': str(fixture_dir), 'sourceMediaSha256': media_sha,
               'sourceDurationSeconds': source['source']['media']['durationSeconds'],
               'modelTransportIdentity': transport.execution_identity,
               'groupPlanSha256': policy_tools.canonical_sha256(plan),
               'commandImplementationSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'runnerImplementationSha256': hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
               'languagePlugin': 'not_run', 'canonicalCandidateAdmission': 'not_run'}
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
    report = {**context, 'status': 'machine_review_pass_test_only', 'sourceUnits': len(units),
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
    parser.add_argument('--policy', type=Path, default=Path('config/target-language-policies/zh-Hans.json'))
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--codex-cli', type=Path, default=Path.home() / '.local/bin/codex')
    parser.add_argument('--reviewer-tier', choices=['default', 'fast'], default='fast')
    parser.add_argument('--timeout-seconds', type=int, default=180)
    args = parser.parse_args()
    run_test(args.fixture_dir, args.policy, args.out_dir, cli_path=args.codex_cli,
             reviewer_tier=args.reviewer_tier, timeout_seconds=args.timeout_seconds)


if __name__ == '__main__':
    main()

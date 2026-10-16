"""Explicit cache-only L2 revision under current producer and plugin validators.

Exact provider payload equality is mandatory, including model, prompt, complete
source-unit boundaries and request caps. No paid fallback, old human approval or
unknown/failed result is promoted. Original run files are never rewritten.
"""
from __future__ import annotations
import argparse
from contextvars import ContextVar
import copy
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import produce_target_language_candidate as producer
from scripts import target_language_policy as policy_tools
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock

CACHE_MIGRATION = ContextVar('explicit_layer2_cache_migration', default=None)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def migration_cache(role, payload):
    active = CACHE_MIGRATION.get()
    if active is None:
        return None
    fingerprint = policy_tools.canonical_sha256(payload)
    record = active.get((role, fingerprint))
    require(record is not None, 'Migration payload changed; new content requires a separate authorized revision')
    for path, expected in record['files'].items():
        require(policy_tools.file_sha256(path) == expected, 'Migration cache changed after admission')
    return record['parsed']


def _source_scope(source):
    window = source['source']['approvedWindow']
    return {'media': source['source']['media'],
            'window': {key: window[key] for key in ('startSeconds', 'endSeconds')},
            'transcriptSha256': source['transcript']['artifact']['sha256']}


def migrate(*, old_source, source, anchor, old_policy, policy, old_run: Path,
            old_plugin: Path, plugin: Path, out: Path, request_limits=None):
    from scripts import run_target_language_models as models
    from scripts import canonical_layer2_budget as bounded
    old_run, out = old_run.resolve(), out.resolve()
    require(old_run != out and old_run not in out.parents and out not in old_run.parents,
            'Migration requires separate sibling run directories')
    require(_source_scope(old_source) == _source_scope(source), 'Migration source media/window/transcript changed')
    old_request = producer.prepare_request(old_source, anchor, old_policy)
    new_request = producer.prepare_request(source, anchor, policy)
    require(old_request['sourceUnits'] == new_request['sourceUnits']
            and old_request['targetLocale'] == new_request['targetLocale'], 'Migration frozen source units changed')
    require(producer._load(old_run / 'request.json') == old_request, 'Migration prior run request changed')
    require(not list(old_run.glob('*.started.json')), 'Unknown prior request requires reconciliation before migration')
    old_evidence = producer._load(old_run / 'evidence.json')
    plan = models.group_plan(new_request, anchor)
    old_rule_path = old_run / 'rule-preflight.json'
    require(old_rule_path.is_file(), 'Migration prior cache lacks frozen rule receipt')
    old_rules = producer._load(old_rule_path)
    models.rule_preflight.verify_consumer_receipt(old_request, old_policy, old_plugin, old_evidence, old_rules)
    # This adapter admits only the original unwrapped API payload identity.
    # Omitting transport_identity intentionally rejects CLI cross-run caches.
    models.rule_preflight.verify_prior_model_inputs(old_run, old_request, old_policy, plan, old_rules)
    new_rules = models.rule_preflight.preflight(new_request, policy, plugin, plan)
    require(old_rules['modelRules'] == new_rules['modelRules']
            and old_rules['modelConfiguration'] == new_rules['modelConfiguration'],
            'Migration payload changed; new content requires a separate authorized revision')
    old_sha = old_policy['languageReview']['pluginImplementationSha256']
    old_receipt = producer.run_language_plugin(old_source, anchor, old_policy, old_request,
                                               old_evidence, old_plugin, old_sha,
                                               rule_preflight_receipt=old_rules)
    # Revalidate original semantic results and plugin output, not just presence
    # of JSON response files. A prior failure can only enter the repair workflow.
    producer.admit_evidence(old_source, anchor, old_policy, old_request, old_evidence,
                            old_receipt, old_plugin, old_sha, rule_preflight_receipt=old_rules)
    require([(g['translationGroupId'], g['sourceUnitIds']) for g in old_evidence['groups']] ==
            [(g['translationGroupId'], g['sourceUnitIds']) for g in plan], 'Migration group boundaries changed')
    active, hashes = {}, {}
    for index, group in enumerate(old_evidence['groups'], 1):
        for role, suffix in [('translator', 'astra'), ('reviewer', 'sol')]:
            parsed = old_run / f'group-{index:04d}-{suffix}.json'
            raw_path = parsed.with_suffix('.raw.json')
            require(parsed.is_file() and raw_path.is_file(), 'Migration requires complete original parsed and raw responses')
            cached, raw = producer._load(parsed), producer._load(raw_path)
            fingerprint = cached.get('payloadSha256')
            require(isinstance(fingerprint, str) and raw.get('payloadSha256') == fingerprint,
                    'Migration raw payload identity changed')
            response = raw['response']
            text = models.completed_response_content(response, old_policy[role]['model'], role)
            require(json.loads(text) == cached.get('result')
                    and response.get('id') == cached.get('requestId') == group[role + 'RequestId']
                    and cached.get('model') == old_policy[role]['model'], 'Migration parsed/raw/evidence response differs')
            preview = parsed.with_suffix('.policy-preview.json')
            files = {p: policy_tools.file_sha256(p) for p in (parsed, raw_path, preview)}
            hashes.update(files)
            key = (role, fingerprint)
            require(key not in active, 'Migration contains duplicate request identity')
            active[key] = {'parsed': parsed, 'files': files}
    for name in ('request.json', 'evidence.json', 'run-identity.json', 'rule-preflight.json'):
        path = old_run / name
        hashes[path] = policy_tools.file_sha256(path)

    def unchanged():
        require(not list(old_run.glob('*.started.json')), 'Prior run acquired an unknown request during migration')
        for path, expected in hashes.items():
            require(policy_tools.file_sha256(path) == expected, 'Original migration evidence changed')

    with work_lock(out):
        token = CACHE_MIGRATION.set(active)
        try:
            with bounded.request_limits(request_limits):
                def forbidden(*args, **kwargs):
                    raise AssertionError('Cache migration must never dispatch a provider call')
                evidence = models.run_accounted(source, anchor, policy, out, '', forbidden,
                                                 None, plugin, None, None, cache_only=True)
        finally:
            CACHE_MIGRATION.reset(token)
        unchanged()
        require(producer._load(out / 'rule-preflight.json') == new_rules,
                'Migration new frozen rule receipt changed')
        plugin_sha = policy['languageReview']['pluginImplementationSha256']
        receipt = producer.run_language_plugin(source, anchor, policy, new_request,
                                               evidence, plugin, plugin_sha,
                                               rule_preflight_receipt=new_rules)
        candidate = producer.admit_evidence(source, anchor, policy, new_request,
                                             evidence, receipt, plugin, plugin_sha,
                                             rule_preflight_receipt=new_rules)
        unchanged()
        result = {'schemaVersion': 'sermon-target-language-cache-migration-v1',
                  'status': 'machine_review_pass_human_review_pending', 'modelCalls': 0,
                  'reusedModelResponses': len(active), 'humanApprovalCreated': False, 'releaseEligible': False,
                  'oldPolicySha256': policy_tools.canonical_sha256(old_policy),
                  'newPolicySha256': policy_tools.canonical_sha256(policy),
                  'oldRulePreflightSha256': policy_tools.canonical_sha256(old_rules),
                  'newRulePreflightSha256': policy_tools.canonical_sha256(new_rules),
                  'oldEvidenceSha256': policy_tools.canonical_sha256(old_evidence),
                  'newEvidenceSha256': policy_tools.canonical_sha256(evidence),
                  'candidateSha256': policy_tools.canonical_sha256(candidate),
                  'originalCacheSetSha256': policy_tools.canonical_sha256({p.name: h for p, h in hashes.items()}),
                  'requestIds': {role: evidence['generation'][role]['requestIds'] for role in ('translator', 'reviewer')}}
        for name, value in [('language-review.json', receipt), ('candidate.json', candidate), ('migration.json', result)]:
            path = out / name
            if path.exists():
                require(producer._load(path) == value, 'Migration output already exists with different evidence')
            else:
                models.save_new(path, value)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('old-source', 'source', 'anchor', 'old-policy', 'policy', 'old-run', 'old-plugin', 'plugin', 'out'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--request-limits', type=Path)
    args = parser.parse_args()
    values = {key: producer._load(getattr(args, key)) for key in ('old_source', 'source', 'anchor', 'old_policy', 'policy')}
    result = migrate(**values, old_run=args.old_run, old_plugin=args.old_plugin, plugin=args.plugin, out=args.out,
                     request_limits=producer._load(args.request_limits) if args.request_limits else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

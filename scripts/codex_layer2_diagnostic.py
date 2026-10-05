"""Frozen, unapproved-source CLI/plugin/admission diagnostic; no release authority."""
from __future__ import annotations
import argparse
import copy
import json
import re
from pathlib import Path

from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as runner
from scripts import sermon_diagnostic_context as diagnostic
from scripts import target_language_policy as policies
from scripts.sermon_execution_harness import work_lock

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'codex-layer2-diagnostic-fixture-v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def save(path, value):
    if path.exists():
        require(producer._load(path) == value, 'Diagnostic immutable artifact changed: ' + path.name)
    else:
        runner.save_new(path, value, private=True)


def artifact_directory(path):
    path = Path(path).resolve()
    require(path.is_relative_to(ROOT / 'artifacts') and path != ROOT / 'artifacts',
            'Diagnostic outputs must be a dedicated ignored artifacts directory')
    return path


def freeze_fixture(source, anchor, policy, plan, plugin, out, *, authorization_ref, code_commit,
                   translator_model=None, scripture_classification='not_reviewed', source_quotation_units=()):
    """Freeze supplied unapproved Layer 1 bytes, never manufacture review receipts."""
    out, plugin = artifact_directory(out), Path(plugin).resolve()
    require(not out.exists(), 'Diagnostic fixture requires a new directory')
    require(isinstance(authorization_ref, str) and authorization_ref.strip(),
            'Diagnostic fixture requires a simulation authorization reference')
    baseline = copy.deepcopy(policy)
    policies.validate_policy(baseline)
    if translator_model is not None:
        from scripts.codex_layer2_transport import TEST_CONFIGURATION, validate_test_configuration
        require(translator_model == 'gpt-6.1-sol', 'Unsupported isolated diagnostic translator')
        configuration = validate_test_configuration(TEST_CONFIGURATION)
        policy = copy.deepcopy(policy)
        for role in ('translator', 'reviewer'):
            policy[role].update({k: v for k, v in configuration[role].items() if k != 'serviceTier'})
            policy['componentSha256'][role] = policies.canonical_sha256(policy[role])
        policy['simulationModelConfiguration'] = configuration
    material = {'source.json': source, 'anchor.json': anchor, 'policy.json': policy,
                'group-plan.json': plan}
    manifest = {'schemaVersion': SCHEMA, 'simulationOnly': True, 'productionEligible': False,
                'actualHumanApproval': False, 'files': {k: policies.canonical_sha256(v) for k, v in material.items()},
                'scriptureClassification': scripture_classification,
                'sourceQuotationUnits': list(source_quotation_units),
                'simulationAuthorizationRef': policies.canonical_sha256(authorization_ref),
                'continuationCodeCommit': code_commit,
                'baselinePolicySha256': policies.canonical_sha256(baseline),
                'pluginPath': str(plugin), 'pluginImplementationSha256': producer.plugin_implementation_sha256(plugin),
                'sourceMediaSha256': source['source']['media']['sha256'],
                'sourceWindow': {k: source['source']['approvedWindow'][k] for k in ('startSeconds', 'endSeconds')},
                'anchorTimeline': 'relative_to_frozen_window_start',
                'sourceUnits': len(anchor['sourceUnits']), 'groups': len(plan)}
    config_hash = policies.canonical_sha256(manifest)
    context = {'schemaVersion': diagnostic.SCHEMA, 'runId': config_hash,
               'runConfigSha256': config_hash, 'storeSha256': config_hash,
               'sourceCanonicalSha256': policies.canonical_sha256(source),
               'anchorCanonicalSha256': policies.canonical_sha256(anchor),
               'simulationAuthorizationRef': manifest['simulationAuthorizationRef'],
               'continuationCodeCommit': code_commit, 'humanAcceptance': 'pending', 'productionEligible': False}
    request = producer.prepare_request(source, anchor, policy, diagnostic_context=context)
    runner.group_plan(request, anchor, plan)
    _check_boundaries(source, anchor)
    _check_plugin_scope(policy, anchor, plugin, manifest)
    runner.rule_preflight.preflight(request, policy, plugin, plan)
    with work_lock(out):
        for name, value in material.items():
            save(out / name, value)
        save(out / 'fixture-manifest.json', manifest)
        save(out / 'diagnostic-context.json', context)
    return manifest


def _check_boundaries(source, anchor):
    """Canonical anchors are clip-relative; bind the parent window separately."""
    window = source['source']['approvedWindow']
    duration = window['endSeconds'] - window['startSeconds']
    previous_end = 0
    for unit in anchor['sourceUnits']:
        require(0 <= unit['start'] < unit['end'] <= duration + .01
                and unit['start'] >= previous_end - .001,
                'Diagnostic anchor timing is outside frozen window or overlaps')
        previous_end = unit['end']


def _check_plugin_scope(policy, anchor, plugin, manifest):
    require(manifest.get('scriptureClassification') in
            {'no_direct_quotations', 'contains_direct_quotations', 'not_reviewed'},
            'Diagnostic scripture classification missing')
    quotation_units = manifest.get('sourceQuotationUnits')
    ids = [unit['sourceUnitId'] for unit in anchor['sourceUnits']]
    require(isinstance(quotation_units, list) and len(set(quotation_units)) == len(quotation_units)
            and all(unit in ids for unit in quotation_units), 'Diagnostic source quotation unit binding changed')
    if plugin.resolve() == (ROOT / 'scripts/language_review_plugins/diagnostic_structural.py').resolve():
        from scripts.language_review_plugins import diagnostic_structural
        english = ' '.join(unit['english'] for unit in anchor['sourceUnits'])
        require(manifest['scriptureClassification'] == 'no_direct_quotations'
                and not quotation_units
                and not re.search(r'\bverse\s+\d+.{0,100}\b(?:says|reads|writes)\b|\bJohn\s+(?:says|writes)\b', english, re.I)
                and diagnostic_structural._reference_only(policy, english, ''),
                'Diagnostic structural plugin does not support direct or unreviewed scripture samples')


def load_fixture(directory):
    directory = Path(directory).resolve()
    manifest = producer._load(directory / 'fixture-manifest.json')
    require(manifest.get('schemaVersion') == SCHEMA and manifest.get('simulationOnly') is True
            and manifest.get('productionEligible') is False and manifest.get('actualHumanApproval') is False,
            'Diagnostic fixture scope changed')
    require(set(manifest['files']) == {'source.json', 'anchor.json', 'policy.json', 'group-plan.json'},
            'Diagnostic fixture inventory changed')
    material = {name: json.loads((directory / name).read_text()) for name in manifest['files']}
    require(all(policies.canonical_sha256(value) == manifest['files'][name] for name, value in material.items()),
            'Diagnostic fixture file changed')
    context = diagnostic.validate_context(producer._load(directory / 'diagnostic-context.json'))
    require(context['storeSha256'] == policies.canonical_sha256(manifest)
            and context['runId'] == context['runConfigSha256'] == context['storeSha256']
            and context['simulationAuthorizationRef'] == manifest['simulationAuthorizationRef']
            and context['continuationCodeCommit'] == manifest['continuationCodeCommit'],
            'Diagnostic fixture context binding changed')
    source, anchor, policy, plan = (material[name] for name in ('source.json', 'anchor.json', 'policy.json', 'group-plan.json'))
    plugin = Path(manifest['pluginPath'])
    require(producer.plugin_implementation_sha256(plugin) == manifest['pluginImplementationSha256']
            == policy['languageReview']['pluginImplementationSha256'], 'Diagnostic plugin identity changed')
    require(manifest['sourceMediaSha256'] == source['source']['media']['sha256']
            and manifest.get('anchorTimeline') == 'relative_to_frozen_window_start'
            and manifest['sourceWindow'] == {k: source['source']['approvedWindow'][k] for k in ('startSeconds', 'endSeconds')}
            and manifest['sourceUnits'] == len(anchor['sourceUnits']) and manifest['groups'] == len(plan),
            'Diagnostic fixture source/window/coverage changed')
    request = producer.prepare_request(source, anchor, policy, diagnostic_context=context)
    runner.validate_standalone_worker_budget(policy)
    require(policy['batching']['workers'] == 1, 'CLI diagnostic runs one group and locale at a time')
    runner.group_plan(request, anchor, plan)
    _check_boundaries(source, anchor)
    _check_plugin_scope(policy, anchor, plugin, manifest)
    receipt = runner.rule_preflight.preflight(request, policy, plugin, plan)
    return source, anchor, policy, plan, plugin, request, receipt, context, manifest


def run_chain(inputs, out, caller):
    source, anchor, policy, plan, plugin, request, receipt, context, manifest = inputs
    out = artifact_directory(out)
    with work_lock(out):
        evidence = runner._run_prepared_groups(request, anchor, policy, out, '', caller, plan, plugin,
            simulation_only=True, diagnostic_context=context)
        require(producer._load(out / 'rule-preflight.json') == receipt, 'Diagnostic rule receipt changed')
        # Check actual translator/reviewer payloads even on same-run cache resume.
        runner.rule_preflight.verify_prior_model_inputs(out, request, policy, plan, receipt,
            transport_identity=caller.execution_identity)
        language = producer.run_language_plugin(source, anchor, policy, request, evidence, plugin,
            manifest['pluginImplementationSha256'], diagnostic_context=context, rule_preflight_receipt=receipt)
        save(out / 'diagnostic-language-review.json', language)
        candidate = producer.admit_evidence(source, anchor, policy, request, evidence, language, plugin,
            manifest['pluginImplementationSha256'], diagnostic_context=context, rule_preflight_receipt=receipt)
        envelope = {'schemaVersion': 'codex-layer2-diagnostic-candidate-v1',
                    'simulationOnly': True, 'productionEligible': False, 'actualHumanApproval': False,
                    'humanAcceptance': 'pending', 'releaseEligible': False,
                    'diagnosticContextSha256': policies.canonical_sha256(context),
                    'rulePreflightSha256': policies.canonical_sha256(receipt),
                    'candidateSha256': policies.canonical_sha256(candidate), 'candidate': candidate}
        save(out / 'diagnostic-candidate.json', envelope)
        return evidence, language, envelope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'anchor', 'policy', 'group-plan', 'plugin', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--authorization-ref', required=True)
    parser.add_argument('--code-commit', required=True)
    parser.add_argument('--translator-model', choices=['gpt-6.1-sol'])
    parser.add_argument('--scripture-classification', choices=['no_direct_quotations', 'contains_direct_quotations', 'not_reviewed'], default='not_reviewed')
    parser.add_argument('--source-quotation-unit', action='append', default=[], help='Bound source risk annotation, not quotation approval')
    args = parser.parse_args()
    values = [json.loads(path.read_text()) for path in (args.source, args.anchor, args.policy, args.group_plan)]
    print(json.dumps(freeze_fixture(*values, args.plugin, args.out, authorization_ref=args.authorization_ref,
                                   code_commit=args.code_commit, translator_model=args.translator_model,
                                   scripture_classification=args.scripture_classification,
                                   source_quotation_units=args.source_quotation_unit), ensure_ascii=False))


if __name__ == '__main__':
    main()

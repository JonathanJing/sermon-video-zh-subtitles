"""Explicit strict L2 locale entry; produces a human-pending public candidate.

Transport, measured-usage resolver, approved budget and LOGC session are supplied
by the trusted caller. This is not a default production switch or an approval.
Groups consume frozen English context only; target-to-target dependencies require
a separate selective invalidation adapter and are rejected before transport.
"""
from pathlib import Path

from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as models
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import sermon_repair_planning as planning
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_candidate_bridge as bridge
from scripts import sermon_strict_controller as controller
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path


def run_locale(source_bytes, anchor_bytes, policy_bytes, rubric_bytes, *, root,
               store, job_root, production_run_id, graph, plugin_path,
               expected_plugin_sha256, api_key, caller, bounds,
               usage_resolver=None, group_plan=None, created_at=None, request_limits=None, diagnostic_context=None, depends_on=None,
               historical_reuse=None):
    """Run fixed groups and bounded repairs, then the real public/plugin bridge.

    All group inputs and the complete locale coverage are validated before the
    first call. Resume uses the existing durable per-group budget identities.
    Completed machine output is immutable and never replaces a human-approved
    candidate. A non-pass group prevents public assembly, not other groups.
    """
    c.require(profile.current() is not None, 'strict_requires_accounting_profile')
    if diagnostic_context is not None:
        from scripts.sermon_diagnostic_context import validate_runtime
        diagnostic_context = validate_runtime(diagnostic_context, run_id=production_run_id, store_sha256=store.store_sha256)
    raw = (source_bytes, anchor_bytes, policy_bytes, rubric_bytes)
    source, anchor, policy, rubric = map(c.decode_json, raw)
    request = producer.prepare_request(source, anchor, policy, strict_rubric=rubric, diagnostic_context=diagnostic_context)
    plan = models.group_plan(request, anchor, group_plan)
    # The current whole-locale Gate accepts at most 128 current revisions.
    # Do not spend on a locale that cannot reach that existing boundary.
    c.require(len(plan) <= 128, 'strict_locale_admission_inventory_limit')
    from scripts import target_language_rule_preflight as rule_preflight
    checked_plugin = _safe_path(Path(plugin_path))
    models.require_plugin_identity(checked_plugin, expected_plugin_sha256)
    c.require(policy['languageReview']['pluginImplementationSha256'] == expected_plugin_sha256,
              'strict_locale_plugin_policy_changed')
    rule_receipt = rule_preflight.preflight(request, policy, checked_plugin, plan)
    prepared = [strict.prepare(*raw, group, request_limits=request_limits, diagnostic_context=diagnostic_context, rule_preflight=rule_receipt) for group in plan]
    if historical_reuse is not None:
        from scripts.sermon_historical_layer2 import HistoricalLayer2Reuse
        c.require(type(historical_reuse) is HistoricalLayer2Reuse,'trusted_historical_layer2_required')
        historical_reuse._current()
        for item in prepared:historical_reuse.inspect(item)
    if hasattr(caller, 'preflight_locale'):
        caller.preflight_locale(prepared)
    units = [item['workUnitId'] for item in prepared]
    planning.dependency_closure(graph, units)
    by_id = {row['workUnitId']: row for row in graph}
    c.require({row['workUnitId'] for row in graph if row['layer'] == 2 and
               row['targetLocale'] == policy['targetLocale']} == set(units),
              'strict_locale_graph_coverage_changed')
    c.require(all(by_id[dep]['layer'] == 1 for unit in units
                  for dep in by_id[unit]['dependsOn']),
              'strict_locale_target_context_dispatch_not_supported')
    root, job_root, plugin_path = map(_safe_path, (Path(root), Path(job_root), Path(plugin_path)))
    protected = (job_root, _safe_path(store.root), plugin_path)
    c.require(not any(root == p or root in p.parents or p in root.parents for p in protected),
              'strict_locale_paths_overlap')
    models.require_plugin_identity(plugin_path, expected_plugin_sha256)
    c.require(policy['languageReview']['pluginImplementationSha256'] == expected_plugin_sha256,
              'strict_locale_plugin_policy_changed')
    binding = {'schemaVersion': 'sermon-strict-locale-input-v1',
        'productionRunId': production_run_id, 'targetLocale': policy['targetLocale'],
        'inputBytesSha256': [c.bytes_sha256(data) for data in raw],
        'groups': plan, 'graph': graph, 'pluginSha256': expected_plugin_sha256,
        'storeSha256': store.store_sha256, 'authoritySha256': store.authority_sha256,
        'bounds': bounds, 'rulePreflight': prepared[0]['rulePreflight'],
        **({'requestLimits': prepared[0]['requestLimits']} if request_limits is not None else {}),
        **({'diagnosticContext': diagnostic_context} if diagnostic_context is not None else {}),
        **({'historicalReuseSha256':c.canonical_sha256(historical_reuse.spec)} if historical_reuse is not None else {})}
    lock_key = c.canonical_sha256({'purpose': 'strict-locale-run',
        'productionRunId': production_run_id, 'targetLocale': policy['targetLocale']})
    with jobs._lock(job_root, lock_key) as (_, _, held):
        c.require(held, 'strict_locale_busy')
        with accounting.stage('rqc.locale_input_binding', depends_on=depends_on, executor_type='deterministic_program') as bound_span:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            strict.save_once(root / 'locale-input.json', binding)
            strict.save_once(root / 'rule-preflight.json', binding['rulePreflight'])
            jobs._sync_directory_ancestry(root)
            accounting.record_workload('rqc.locale_input', {
                'sourceMediaSha256': source['source']['media']['sha256'],
                'sourcePackageSha256': c.canonical_sha256(source),
                'policySha256': c.canonical_sha256(policy),
                'rubricSha256': c.canonical_sha256(rubric),
                'localeInputSha256': c.canonical_sha256(binding),
                'targetLocale': policy['targetLocale'], 'groupCount': len(prepared),
                **({'diagnosticContextSha256': c.canonical_sha256(diagnostic_context),
                    'simulatedHumanGate': True, 'humanAcceptancePending': True,
                    'productionEligible': False} if diagnostic_context is not None else {})})
        results, revisions, dependencies = [], [], [bound_span]
        for item in prepared:
            group_root=root/'groups'/c.canonical_sha256(item['group'])
            stop=caller.configuration_stop(item) if hasattr(caller,'configuration_stop') else None
            if stop is not None and not group_root.exists():
                skipped={'schemaVersion':'sermon-strict-group-not-started-v1','status':'not_started',
                    'reasonCode':'provider_configuration_blocked','workUnitId':item['workUnitId'],
                    'localeInputSha256':c.canonical_sha256(binding),'scopeSha256':stop['scopeSha256'],
                    'stopReceiptSha256':c.canonical_sha256(stop),'executionAuthority':'none'}
                folder=root/'not-started';folder.mkdir(mode=0o700,exist_ok=True)
                strict.save_once(folder/(c.canonical_sha256(skipped)+'.json'),skipped)
                jobs._sync_directory_ancestry(folder)
                with profile.context(workUnitId=item['workUnitId']):
                    with accounting.stage('rqc.locale_group_not_started',depends_on=dependencies,
                            executor_type='deterministic_program'):
                        accounting.record_log('rqc_configuration_stop',fields={
                            'status':'not_started','reasonCode':'provider_configuration_blocked'})
                results.append(skipped)
                continue
            completed = []
            if historical_reuse is not None:
                result=historical_reuse.run_group(item,root=group_root,
                    candidate_id='candidate.'+c.canonical_sha256(item['group']),api_key=api_key,caller=caller,
                    depends_on=dependencies,completion_spans=completed)
            else:
                result = controller.run_group(item, root=root / 'groups' / c.canonical_sha256(item['group']),
                    store=store, job_root=job_root, production_run_id=production_run_id,
                    graph=graph, candidate_id='candidate.' + c.canonical_sha256(item['group']),
                    api_key=api_key, caller=caller, bounds=bounds, usage_resolver=usage_resolver,
                    created_at=created_at, depends_on=dependencies, completion_spans=completed)
            results.append(result)
            if completed: dependencies = completed[-1:]
            if result['status'] == 'machine_review_passed':
                revisions.append((Path(result['root']), result['reviewAttempt']))
        if len(revisions) != len(prepared):
            return {'status': 'blocked', 'reasonCode': 'strict_locale_group_not_passed',
                    'groups': results, 'executionAuthority': 'none', 'output': None}
        with accounting.stage('rqc.locale_candidate_assembly', depends_on=dependencies,
                              executor_type='deterministic_program'):
            try:
                result = bridge.compile_candidate(*raw, revisions, plugin_path=plugin_path,
                    expected_plugin_sha256=expected_plugin_sha256, diagnostic_context=diagnostic_context)
            except bridge.LanguagePluginRejected as exc:
                # This is known machine evidence, not an approved candidate. Keep
                # the original plugin receipt before exposing a typed locale stop.
                failure = {'schemaVersion': 'sermon-strict-locale-plugin-failure-v1',
                    'status': 'blocked', 'reasonCode': 'strict_bridge_plugin_rejected',
                    'executionAuthority': 'none', 'localeInputSha256': c.canonical_sha256(binding),
                    'languageReceiptSha256': c.canonical_sha256(exc.language_receipt),
                    'revisionBindingsSha256': c.canonical_sha256({'groups': exc.revision_bindings}),
                    'failedGroups': exc.failed_groups}
                evidence = root / 'failures' / c.canonical_sha256(failure)
                evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
                language_bytes = public.save_once(evidence / 'language-review.json', exc.language_receipt)
                public.save_once(evidence / 'revision-bindings.json', {'groups': exc.revision_bindings})
                failure_bytes = public.save_once(evidence / 'failure.json', failure)
                jobs._sync_directory_ancestry(evidence)
                accounting.record_log('rqc_locale_candidate', fields={
                    'status': 'blocked', 'reasonCode': failure['reasonCode'],
                    'targetLocale': policy['targetLocale'],
                    'languageReceiptSha256': failure['languageReceiptSha256']})
                return {'status': 'blocked', 'reasonCode': failure['reasonCode'],
                    'groups': results, 'executionAuthority': 'none', 'output': None,
                    'failedGroups': exc.failed_groups, 'failureOutput': str(evidence),
                    'failureReceipt': {'artifactId': 'locale-plugin-failure', 'mediaType': 'application/json',
                        'canonicalJsonSha256': c.canonical_sha256(failure),
                        'fileBytesSha256': c.bytes_sha256(failure_bytes)},
                    'languageReceipt': {'artifactId': 'language-review', 'mediaType': 'application/json',
                        'canonicalJsonSha256': c.canonical_sha256(exc.language_receipt),
                        'fileBytesSha256': c.bytes_sha256(language_bytes)}}
            identity = c.canonical_sha256(result)
            output = root / 'machine-candidates' / identity
            output.mkdir(parents=True, exist_ok=True, mode=0o700)
            for name, value in (('candidate', result['candidate']),
                                ('language-review', result['languageReceipt']),
                                ('revision-bindings', {'groups': result['revisionBindings']})):
                public.save_once(output / (name + '.json'), value)
            jobs._sync_directory_ancestry(output)
            accounting.record_workload('rqc.locale_candidate', {
                'candidateSha256': c.canonical_sha256(result['candidate']),
                'revisionBindingsSha256': c.canonical_sha256(result['revisionBindings'])})
        return {'status': 'waiting_human', 'reasonCode': 'independent_translation_review_required',
                'groups': results, 'executionAuthority': 'none', 'output': str(output),
                'candidateSha256': c.canonical_sha256(result['candidate']),
                'revisions': [{'root': str(path), 'reviewAttempt': attempt} for path, attempt in revisions]}

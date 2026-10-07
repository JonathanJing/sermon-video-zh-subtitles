"""Frozen Fresh Source semantic recipe, separate from generic log syntax.

Only actual execution/receipt-validation leaves are accepted. This validator
cannot manufacture dependencies from containment, timestamps or empty arrays.
"""
from copy import deepcopy
from pathlib import Path

from scripts import sermon_accounting as accounting
from scripts import sermon_completion as completion
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-fresh-source-causality-v1'
ORDER = ('intake', 'transcription', 'sourceCheck', 'alignment', 'sourcePackage')
STAGES = {'intake': {'diagnostic.source_preflight'},
    'transcription': {'diagnostic.transcription', 'diagnostic.transcription_reuse'},
    'sourceCheck': {'diagnostic.source_model', 'diagnostic.source_model_reuse'},
    'alignment': {'diagnostic.alignment'}, 'sourcePackage': {'diagnostic.source_package'}}
KINDS = dict(zip(ORDER, ('frozen_recipe', 'provider_receipt', 'provider_receipt', 'aligned_segments', 'source_package')))
WORK_UNITS = dict(zip(ORDER, ('source.preflight', 'transcription.initial', 'source.initial', 'source.alignment', 'source.package')))


def _validate(value, events, *, plan, recipe, asr_ref, review_ref, aligned_sha256, source_sha256, order):
    c.require(type(value) is dict and set(value) == {'schemaVersion', 'runId', 'planSha256',
        'recipeSha256', 'logDirectory', 'handles'} and value['schemaVersion'] == SCHEMA
        and value['runId'] == plan['providerConfig']['runId']
        and value['planSha256'] == c.canonical_sha256(plan)
        and value['recipeSha256'] == c.canonical_sha256(recipe)
        and type(value['handles']) is dict and set(value['handles']) == set(order),
        'fresh_causality_binding_changed')
    root = _safe_path(Path(plan['runDirectory']))
    directory = _safe_path(Path(value['logDirectory']))
    c.require(directory.is_relative_to(root) and directory != root, 'fresh_causality_log_scope_changed')
    artifacts = (c.canonical_sha256(recipe), asr_ref['receiptSha256'] if asr_ref else None,
                 review_ref['receiptSha256'] if review_ref else None,
                 aligned_sha256, source_sha256)
    c.require(all(type(value) is str and len(value) == 64 for value in artifacts[:len(order)]),
        'fresh_causality_artifact_required')
    value = deepcopy(value)
    # Share integrity checks across this frozen prefix, retaining all semantic
    # checks below against the same private event bytes. No validated view escapes.
    events = deepcopy(events)
    checks, prior = [], None
    for key, artifact in zip(order, artifacts):
        handle = value['handles'][key]
        checks.append({'handle': handle, 'artifact_sha256': artifact,
            'dependencies': [] if prior is None else [prior['spanId']]})
        prior = handle
    completion.validate_many(checks, events, production_run_id=value['runId'])
    unique = {r['eventId']: r for r in events if r.get('contractVersion') == completion.log.VERSION}
    rows = list(unique.values())
    prior, log_run, spans = None, None, set()
    for key, artifact in zip(order, artifacts):
        handle = value['handles'][key]
        c.require(handle['stage'] in STAGES[key] and handle['artifactKind'] == KINDS[key]
            and handle['spanId'] not in spans and handle['workUnitId'] == WORK_UNITS[key], 'fresh_causality_stage_changed')
        c.require(log_run is None or log_run == handle['runId'], 'fresh_causality_cross_run')
        facts = [r for r in rows if r.get('runId') == handle['runId']
            and r.get('spanId') == handle['spanId']]
        binding_fields = {
            'intake': ('diagnostic.source_recipe_binding', 'recipeSha256'),
            'alignment': ('diagnostic.alignment_binding', 'alignedSegmentsSha256'),
            'sourcePackage': ('diagnostic.fresh_source_binding', 'sourceCanonicalSha256')}
        if key in binding_fields:
            event_stage, field = binding_fields[key]
            bindings = [r for r in facts if r['event'] == 'workload' and r['stage'] == event_stage]
            c.require(len(bindings) == 1 and bindings[0]['metrics'].get(field) == artifact,
                'fresh_causality_artifact_fact_changed')
            expected_execution = ('cache_replay' if bindings[0]['metrics'].get('alignmentCacheHit') is True
                else 'backend_execution_unobserved') if key == 'alignment' else 'deterministic_validation'
            c.require(handle['executionMode'] == expected_execution, 'fresh_causality_execution_mode_changed')
        expected_mode = 'cache_replay' if handle['stage'].endswith('_reuse') else None
        if key in {'transcription', 'sourceCheck'}:
            c.require(handle['executionMode'] == (expected_mode or 'current_execution'),
                'fresh_causality_execution_mode_changed')
            reference = asr_ref if key == 'transcription' else review_ref
            facts = [r for r in rows if r.get('runId') == handle['runId']
                and r.get('spanId') == handle['spanId']]
            if expected_mode:
                c.require(not any(r['event'].startswith('api_attempt') for r in facts)
                    and any(r['event'] == 'workload' and r['stage'] == 'diagnostic.source_response_recovery'
                        and r['metrics'].get('providerReceiptSha256') == reference['receiptSha256']
                        and r['metrics'].get('modelCallIdSha256') == c.canonical_sha256(reference['modelCallId'])
                        and r['metrics'].get('requestPayloadSha256') == reference['requestSha256']
                        for r in facts), 'fresh_causality_reuse_receipt_unbound')
            else:
                receipts = [r for r in facts if r['event'] == 'workload' and r['stage'] == 'diagnostic.provider_receipt']
                c.require(len(receipts) == 1 and receipts[0]['metrics'].get('providerReceiptSha256') == artifact
                    and receipts[0]['metrics'].get('requestPayloadSha256') == reference['requestSha256']
                    and receipts[0]['metrics'].get('modelCallIdSha256') == c.canonical_sha256(reference['modelCallId'])
                    and receipts[0]['metrics'].get('runConfigSha256') == c.canonical_sha256(plan['providerConfig']),
                    'fresh_causality_provider_artifact_fact_changed')
                calls = [r for r in facts if r['event'] == 'api_attempt']
                starts = [r for r in facts if r['event'] == 'api_attempt_started']
                c.require(len(calls) == 1 and calls[0]['status'] == 'completed'
                    and calls[0]['modelCallId'] == reference['modelCallId']
                    and calls[0]['stageAttemptId'] == handle['attemptId']
                    and len(starts) == 1 and starts[0]['settings'].get('requestPayloadSha256') == reference['requestSha256'],
                    'fresh_causality_provider_receipt_unbound')
        if prior is not None:
            start = next(r for r in rows if r['event'] == 'stage_started' and r.get('runId') == handle['runId']
                and r.get('spanId') == handle['spanId'])
            end = next(r for r in rows if r['event'] == 'stage_finished' and r.get('runId') == prior['runId']
                and r.get('spanId') == prior['spanId'])
            c.require(start.get('clockDomainId') == end.get('clockDomainId') and start.get('clockDomainId')
                and int(start['monotonicStartNs']) >= int(end['monotonicEndNs']),
                'fresh_causality_completion_not_observed_before_dispatch')
        prior, log_run = handle, handle['runId']; spans.add(handle['spanId'])
    return value


def validate(value, events, *, plan, recipe, asr_ref, review_ref, aligned_sha256, source_sha256):
    return _validate(value, events, plan=plan, recipe=recipe, asr_ref=asr_ref,
        review_ref=review_ref, aligned_sha256=aligned_sha256, source_sha256=source_sha256, order=ORDER)


def validate_prefix(value, events, *, through, plan, recipe, asr_ref=None,
                    review_ref=None, aligned_sha256=None, source_sha256=None):
    """Validate every actual completed predecessor before the next stage dispatch."""
    c.require(type(through) is str and through in ORDER, 'fresh_causality_prefix_invalid')
    return _validate(value, events, plan=plan, recipe=recipe, asr_ref=asr_ref,
        review_ref=review_ref, aligned_sha256=aligned_sha256, source_sha256=source_sha256,
        order=ORDER[:ORDER.index(through)+1])


def inspect(root, plan, recipe, *, asr_ref, review_ref, aligned_sha256, source_sha256):
    value, _ = public.read_snapshot(_safe_path(Path(root))/'fresh-source-causality.json')
    directory = _safe_path(Path(value['logDirectory']))
    c.require(directory.is_relative_to(_safe_path(Path(root))) and directory != Path(root),
        'fresh_causality_log_scope_changed')
    events, errors = accounting.read_events(directory)
    c.require(not errors, 'fresh_causality_log_damaged')
    return validate(value, events, plan=plan, recipe=recipe, asr_ref=asr_ref, review_ref=review_ref,
        aligned_sha256=aligned_sha256, source_sha256=source_sha256)

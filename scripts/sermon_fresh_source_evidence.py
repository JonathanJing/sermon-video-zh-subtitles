"""Fixed, read-only Fresh Source evidence validation, never execution authority.

Current receipts and closed-parent cache proofs are separate versioned contracts.
This module neither prepares Source nor enters a provider/budget lock. In
particular, it never substitutes Fresh evidence for the legacy four findings.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from scripts import sermon_mfa_identity as mfa_identity
from scripts import sermon_fresh_source_causality as causality
from scripts import sermon_accounting as accounting
from scripts import sermon_provider_limits as limits
from scripts import sermon_transcription_request as audio
from scripts import sermon_cached_fresh_diagnostic_source as cache
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_fresh_diagnostic_source as fresh
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-fresh-diagnostic-source-validation-v2'
CURRENT = 'sermon-fresh-diagnostic-source-evidence-v1'
CURRENT_V2 = 'sermon-fresh-diagnostic-source-evidence-v2'
CACHED = frozenset((cache.SCHEMA, 'sermon-cached-fresh-diagnostic-source-v2'))
CURRENT_KEYS = {'schemaVersion', 'asr', 'sourceCheck', 'alignmentMode', 'sourceCanonicalSha256',
    'anchorCanonicalSha256', 'alignedSegmentsSha256', 'sourceReviewStatus',
    'sourceReviewContentSha256', 'contextSha256', 'productionEligible', 'humanAcceptance'}


class _Snapshots:
    def __init__(self):
        self.refs = {}

    def file(self, path):
        ref = cache._ref(_safe_path(Path(path)))
        prior = self.refs.setdefault(ref['path'], ref)
        c.require(prior == ref, 'fresh_delivery_source_snapshot_changed')
        return ref['bytesSha256']

    def json(self, path):
        value, raw = public.read_snapshot(_safe_path(Path(path)))
        c.require(self.file(path) == c.bytes_sha256(raw), 'fresh_delivery_source_snapshot_changed')
        return value

    def artifact(self, artifact):
        c.require(type(artifact) is dict, 'fresh_delivery_source_artifact_changed')
        value = self.json(artifact['path'])
        c.require(self.file(artifact['path']) == artifact['sha256'] and
            (artifact.get('jsonSha256') is None or c.canonical_sha256(value) == artifact['jsonSha256']),
            'fresh_delivery_source_artifact_changed')
        return value

    def recheck(self):
        for ref in tuple(self.refs.values()):
            c.require(cache._ref(Path(ref['path'])) == ref, 'fresh_delivery_source_snapshot_changed')


def _current(root, plan, subject, context, evidence, files, state):
    keys = CURRENT_KEYS if evidence['schemaVersion'] == CURRENT else CURRENT_KEYS | {
        'mfaIdentityComparisonSha256', 'mfaIdentityPreflightSha256', 'sourceCausalitySha256'}
    c.require(set(evidence) == keys and evidence['productionEligible'] is False
        and evidence['humanAcceptance'] == evidence['sourceReviewStatus'] == 'pending'
        and evidence['contextSha256'] == c.canonical_sha256(context),
        'fresh_delivery_source_evidence_changed')
    c.require(files.json(root/'fresh-source-evidence.json') == evidence,
        'fresh_delivery_source_evidence_changed')
    recipe = files.json(root/'fresh-source-recipe.json')
    recipe_keys = {'files', 'runMFA', 'authorizationSha256'}
    c.require(type(recipe) is dict and (set(recipe) == recipe_keys or
        (set(recipe) == recipe_keys | {'schemaVersion'} and recipe['schemaVersion'] == 'sermon-fresh-source-recipe-v2'))
        and type(recipe['files']) is dict and type(recipe['runMFA']) is bool
        and {'prior_plan_path', 'prior_source_path', 'prior_aligned_path', 'prior_summary_path', 'audio_path'}
            <= set(recipe['files']), 'fresh_delivery_source_recipe_changed')
    for key, ref in recipe['files'].items():
        c.require(key.endswith('_path') and type(ref) is dict and set(ref) == {'path', 'sha256'}
            and files.file(ref['path']) == ref['sha256'], 'fresh_delivery_source_recipe_changed')
    audio_path = Path(recipe['files']['audio_path']['path'])
    c.require(files.file(audio_path) == subject.config['sourceAudioSha256'], 'fresh_delivery_source_audio_changed')
    simulation = files.json(root/'simulation-authorization.json')
    c.require(type(simulation) is dict and set(simulation) == {'schemaVersion', 'authorizationSha256',
        'sourceCanonicalSha256', 'anchorCanonicalSha256', 'sourceReviewReceiptSha256',
        'sourceReviewContentSha256', 'sourceReviewStatus', 'realHumanAcceptance', 'productionEligible'}
        and simulation['schemaVersion'] == 'sermon-fresh-diagnostic-simulation-v1'
        and simulation['authorizationSha256'] == recipe['authorizationSha256']
        and simulation['sourceReviewStatus'] == 'pending' and simulation['realHumanAcceptance'] == 'not_performed'
        and simulation['productionEligible'] is False
        and c.canonical_sha256(simulation) == context['simulationAuthorizationRef'],
        'fresh_delivery_source_simulation_changed')
    c.require(evidence['sourceCanonicalSha256'] == simulation['sourceCanonicalSha256'] == context['sourceCanonicalSha256']
        and evidence['anchorCanonicalSha256'] == simulation['anchorCanonicalSha256'] == context['anchorCanonicalSha256'],
        'fresh_delivery_source_evidence_changed')
    # Reconstruct the real source-check request with a fixed read-only state
    # reader. Calling subject.source_check_payload would acquire/create locks.
    folder = root/'budget'/budget.STORE_ID/'provider-run'
    @contextmanager
    def verified_state():
        yield folder, state
    reader = SimpleNamespace(config=subject.config, _locked=verified_state)
    payload = provider.DiagnosticProvider.source_check_payload(reader)
    asr, asr_ref = fresh.returned_receipt(root, subject.config, 'transcription.initial', 'gpt-transcribe')
    review, review_ref = fresh.returned_receipt(root, subject.config, 'source.initial', 'gpt-6-astra')
    for key, ref in (('asr', asr_ref), ('sourceCheck', review_ref)):
        c.require(evidence[key] == ref and files.file(folder/(ref['modelCallId']+'.json')) == ref['receiptSha256'],
            'fresh_delivery_source_receipt_changed')
    c.require(review['payloadSha256'] == c.canonical_sha256(payload)
        and simulation['sourceReviewReceiptSha256'] == review_ref['receiptSha256'],
        'fresh_delivery_source_payload_changed')
    prepared_audio = audio.build_request(audio_path.read_bytes(), subject.config['sourceAudioSha256'])
    c.require(asr['payloadSha256'] == prepared_audio['identitySha256']
        and asr.get('costEvidence') == audio.usage_cost_evidence(asr['response'], prepared_audio['identity']['audio']['decodedDurationSeconds'])
        and asr.get('reservationEvidence') == prepared_audio['budgetBounds'],
        'fresh_delivery_source_asr_request_changed')
    observed = {'requestedModel': 'gpt-6-astra', 'providerModel': review['response'].get('model'),
        'providerUsage': accounting.normalize_usage(review['response'].get('usage')),
        'elapsedSeconds': review['elapsedSeconds'], 'serviceTier': review['response'].get('service_tier', 'default')}
    c.require(review.get('usageObservation') == observed and review.get('costEvidence') == limits.usage_cost_evidence(observed),
        'fresh_delivery_source_usage_changed')
    choices = review['response'].get('choices')
    c.require(type(choices) is list and len(choices) == 1 and type(choices[0]) is dict
        and choices[0].get('finish_reason') == 'stop' and type(choices[0].get('message')) is dict
        and choices[0]['message'].get('refusal') is None and type(choices[0]['message'].get('content')) is str,
        'fresh_delivery_source_response_incomplete')
    content = c.decode_json(choices[0]['message']['content'].encode())
    c.require(type(content) is dict and c.canonical_sha256(content) == evidence['sourceReviewContentSha256']
        == simulation['sourceReviewContentSha256'], 'fresh_delivery_source_review_changed')
    source, anchor = files.json(root/'source.json'), files.json(root/'anchor-manifest.json')
    diagnostic.validate_source(source, anchor, context)
    repository = Path(__file__).resolve().parents[1]
    producers = plan['executionIdentity']['loadedProjectCodeSha256']
    c.require(all(producers.get('scripts/'+name+'.py') == files.file(repository/'scripts'/(name+'.py'))
        for name in cache.SOURCE_MODULES), 'fresh_delivery_source_producer_changed')
    c.require(source['implementation']['builderSha256'] == producers['scripts/build_english_source_package.py']
        and source['implementation']['anchorGeneratorSha256'] == producers['scripts/sermon_sentence_interpretation.py'],
        'fresh_delivery_source_producer_changed')
    aligned = files.artifact(source['transcript']['artifact'])
    c.require(Path(source['transcript']['artifact']['path']) == root/'aligned-segments.json'
        and files.file(root/'aligned-segments.json') == evidence['alignedSegmentsSha256']
        and type(aligned) is list and aligned and all(type(row) is dict for row in aligned)
        and fresh.normalized_text(' '.join(row['text'] for row in aligned)) == fresh.normalized_text(asr['response']['text'])
        and source['source']['media']['sha256'] == subject.config['sourceMediaSha256']
        and [source['source']['approvedWindow'][key] for key in ('startSeconds', 'endSeconds')] == subject.config['sourceWindowSeconds'],
        'fresh_delivery_source_alignment_changed')
    c.require(Path(source['anchors']['artifact']['path']) == root/'anchor-manifest.json'
        and files.artifact(source['anchors']['artifact']) == anchor, 'fresh_delivery_source_anchor_changed')
    summary = files.artifact(source['evidence']['pipelineSummary'])
    c.require(Path(source['evidence']['pipelineSummary']['path']) == root/'source-summary.json'
        and summary.get('diagnosticASRReceiptSha256') == asr_ref['receiptSha256']
        and summary.get('diagnosticAlignmentMode') == evidence['alignmentMode'], 'fresh_delivery_source_summary_changed')
    mode = evidence['alignmentMode']
    c.require(mode in {'validated_prior_alignment_cache', 'fresh_local_mfa'}, 'fresh_delivery_source_alignment_mode_changed')
    prior = files.json(recipe['files']['prior_plan_path']['path'])
    c.require(all(prior['providerConfig'][key] == subject.config[key] for key in cache.SOURCE_SCOPE[:4]),
        'fresh_delivery_source_prior_scope_changed')
    if mode == 'validated_prior_alignment_cache':
        old_asr, old_ref = fresh.returned_receipt(prior['runDirectory'], prior['providerConfig'], 'transcription.initial', 'gpt-transcribe')
        files.file(Path(prior['runDirectory'])/'budget'/budget.STORE_ID/'provider-run'/('state.json'))
        files.file(Path(prior['runDirectory'])/'budget'/budget.STORE_ID/'provider-run'/(old_ref['modelCallId']+'.json'))
        old_source = files.json(recipe['files']['prior_source_path']['path'])
        old_aligned = files.artifact(old_source['transcript']['artifact'])
        c.require(Path(old_source['transcript']['artifact']['path']) == Path(recipe['files']['prior_aligned_path']['path'])
            and old_aligned == aligned and fresh.normalized_text(old_asr['response']['text']) == fresh.normalized_text(asr['response']['text']),
            'fresh_delivery_source_prior_alignment_changed')
    causal_hash = evidence.get('sourceCausalitySha256')
    c.require(recipe.get('schemaVersion') != 'sermon-fresh-source-recipe-v2' or causal_hash is not None,
        'fresh_causality_required')
    if causal_hash is not None:
        causal = causality.inspect(root, plan, recipe, asr_ref=asr_ref, review_ref=review_ref,
            aligned_sha256=evidence['alignedSegmentsSha256'], source_sha256=evidence['sourceCanonicalSha256'])
        c.require(c.canonical_sha256(causal) == causal_hash, 'fresh_causality_receipt_changed')
        files.file(root/'fresh-source-causality.json')
        # The append-only event file can grow, but every bound terminal fact is
        # independently revalidated on the second delivery inspection.
    comparison = mfa_identity.inspect_source_alignment(plan, recipe, evidence, aligned, file_sha256=files.file)
    return asr_ref, review_ref, comparison


def validate_fresh_source_evidence(root, plan, subject, context, expected_evidence):
    """Validate one explicit Fresh schema; return hash-only pending evidence."""
    root = _safe_path(Path(root)); files = _Snapshots()
    c.require(type(plan) is dict and set(plan) == {'schemaVersion', 'runDirectory', 'providerConfig',
        'authority', 'executionIdentity', 'sourceClipPath'} and plan['schemaVersion'] == 'sermon-bounded-diagnostic-plan-v1'
        and Path(plan['runDirectory']) == root and files.json(root/'run-plan.json') == plan,
        'fresh_delivery_source_plan_changed')
    c.require(type(subject) is provider.DiagnosticProvider and subject.store.root == root/'budget'
        and subject.config == plan['providerConfig'] and subject.store.authority == plan['authority']
        and subject.config['codeSha256'] == c.canonical_sha256(plan['executionIdentity']),
        'fresh_delivery_source_provider_changed')
    context = diagnostic.validate_runtime(context, run_id=subject.config['runId'], store_sha256=subject.store.store_sha256)
    c.require(files.json(root/'diagnostic-context.json') == context and context['runConfigSha256'] == c.canonical_sha256(subject.config)
        and context['continuationCodeCommit'] == plan['executionIdentity']['gitCommit'], 'fresh_delivery_source_context_changed')
    c.require(type(expected_evidence) is dict and expected_evidence.get('schemaVersion') in CACHED | {CURRENT, CURRENT_V2},
        'fresh_delivery_source_schema_invalid')
    c.require(files.file(plan['sourceClipPath']) == subject.config['sourceClipSha256'], 'fresh_delivery_source_clip_changed')
    state = files.json(root/'budget'/budget.STORE_ID/'provider-run/state.json')
    c.require(state['config'] == subject.config and state['authoritySha256'] == subject.store.authority_sha256
        and all(row['state'] in {'returned', 'rejected'} for row in state['requests'].values()),
        'fresh_delivery_source_provider_outcome_unknown')
    comparison = None
    if expected_evidence['schemaVersion'] in CACHED:
        evidence = cache.validate_evidence(plan, subject, context, expected_evidence)
        c.require(not any(row['operationId'] in {'transcription.initial', 'source.initial'} for row in state['requests'].values()),
            'fresh_delivery_source_cache_current_calls_changed')
        for ref in evidence['files']:
            c.require(files.file(ref['path']) == ref['bytesSha256'], 'fresh_delivery_source_cache_refs_changed')
        path = root/'cached-source-proof.json'
        for name in ('cached-source-authorization.json', 'simulation-authorization.json', 'source.json', 'anchor-manifest.json'):
            files.json(root/name)
        historical, current = 2, 0
        asr_ref = review_ref = None
        execution = evidence['sourceExecution']
    else:
        evidence = expected_evidence
        asr_ref, review_ref, comparison = _current(root, plan, subject, context, evidence, files, state)
        path = root/'fresh-source-evidence.json'
        historical, current = 0, 2
        execution = 'current_returned_receipts_deterministic_inspection'
    c.require(files.json(path) == expected_evidence, 'fresh_delivery_source_evidence_changed')
    result = {'schemaVersion': SCHEMA, 'status': 'fresh_source_evidence_validated',
        'sourceEvidenceSchema': expected_evidence['schemaVersion'], 'sourceExecution': execution,
        'planFileSha256': files.file(root/'run-plan.json'), 'planCanonicalSha256': c.canonical_sha256(plan),
        'originalExecutionIdentitySha256': c.canonical_sha256(plan['executionIdentity']),
        'contextFileSha256': files.file(root/'diagnostic-context.json'), 'contextCanonicalSha256': c.canonical_sha256(context),
        'sourceFileSha256': files.file(root/'source.json'), 'anchorFileSha256': files.file(root/'anchor-manifest.json'),
        'sourceEvidenceFileSha256': files.file(path), 'sourceEvidenceCanonicalSha256': c.canonical_sha256(expected_evidence),
        'simulationFileSha256': files.file(root/'simulation-authorization.json'),
        'providerStateFileSha256': files.file(root/'budget'/budget.STORE_ID/'provider-run/state.json'),
        'historicalSourceProviderCalls': historical, 'currentSourceProviderCalls': current,
        'asrReceiptSha256': asr_ref['receiptSha256'] if asr_ref else None,
        'sourceCheckReceiptSha256': review_ref['receiptSha256'] if review_ref else None,
        'modelCalls': 0, 'newASRCalls': 0, 'newSourceCheckCalls': 0, 'newMFACalls': 0,
        'humanAcceptance': 'pending', 'productionEligible': False}
    if comparison is not None:
        result['identity_comparison'] = comparison
    files.recheck()
    return dict(result, resultSha256=c.canonical_sha256(result))

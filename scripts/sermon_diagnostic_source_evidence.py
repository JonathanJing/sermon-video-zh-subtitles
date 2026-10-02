"""Read-only binding of the existing text-only source review to its authorization.

This narrow continuation retains four NONCONFIRMED review candidates and their
pending HUMAN disposition. It never calls them machine passes, reruns a source
check, writes an approval, or loads credentials. The caller holds the existing
provider/store lock and supplies its validated state and trusted context. Only
fixed paths beneath that run root are read; receipt paths are never followed.
"""
from pathlib import Path
import json

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_provider_limits as limits
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_transcription_request as transcription
from scripts.sermon_release_workflow import _safe_path

REASONS = ('possible_boundary_fragment', 'title_orthography', 'speech_restart', 'unusual_wording')
PROHIBITED = {'production_approval', 'publication', 'deployment', 'new_ASR_or_source_check', 'new_budget_or_clock_reset'}


def _exact(value, keys, reason):
    c.require(type(value) is dict and set(value) == set(keys), reason)


def _normal(text):
    c.require(type(text) is str and text.strip(), 'diagnostic_source_text_missing')
    return ' '.join(text.split())


def source_payload(config, transcript):
    """Reconstruct the original fixed source-check input, without a provider call."""
    return limits.bounded_payload({'model': 'gpt-6-astra', 'reasoning_effort': 'high',
        'messages': [{'role': 'system', 'content': 'Check the supplied English ASR for internal uncertainty. Return JSON with issues and uncertainty. Do not translate, invent unheard words, or grant human approval.'},
            {'role': 'user', 'content': json.dumps({'sourceMediaSha256': config['sourceMediaSha256'],
                'sourceAudioSha256': config['sourceAudioSha256'], 'sourceWindowSeconds': config['sourceWindowSeconds'],
                'transcript': transcript}, sort_keys=True)}],
        'response_format': {'type': 'json_object'}}, limits.MAX_REQUEST_LIMITS)


def validate_prior_source_evidence(root, state, context):
    """Return hashes only; known pending concerns stay pending, not approved."""
    root = _safe_path(Path(root).absolute())
    context = diagnostic.validate_context(context)
    config = state['config']
    c.require(config['runId'] == context['runId'] and c.canonical_sha256(config) == context['runConfigSha256']
        and c.canonical_sha256({'root': str(root / 'budget'), 'schemaVersion': budget.SCHEMA}) == context['storeSha256'],
        'diagnostic_source_runtime_changed')
    captured = {}
    def read(relative):
        path = _safe_path(root / relative)
        value, raw = public.read_snapshot(path)
        captured[relative] = raw
        return value, raw
    authorization, auth_raw = read('simulated-review-inputs/simulation-authorization.json')
    _exact(authorization, ('schemaVersion', 'allowedScope', 'humanAcceptance', 'productionEligible',
        'originalRunConfigSha256', 'sourceCanonicalSha256', 'sourceReviewRequestSha256',
        'prohibited', 'userInstruction', 'userInstructionAt'), 'invalid_source_simulation_authorization')
    c.require(c.canonical_sha256(authorization) == context['simulationAuthorizationRef'] and
        authorization['schemaVersion'] == 'isolated-diagnostic-simulation-authorization-v1' and
        authorization['allowedScope'] == 'isolated_diagnostic_L2_machine_review_preview_TTS_delivery_preflight' and
        authorization['humanAcceptance'] == 'pending' and authorization['productionEligible'] is False and
        type(authorization['prohibited']) is list and len(authorization['prohibited']) == len(PROHIBITED) and
        set(authorization['prohibited']) == PROHIBITED and
        authorization['originalRunConfigSha256'] == context['runConfigSha256'] and
        authorization['sourceCanonicalSha256'] == context['sourceCanonicalSha256'],
        'diagnostic_source_authorization_changed')
    request, request_raw = read('source-review-request.json')
    _exact(request, ('schemaVersion', 'humanApproval', 'status', 'alignedSegmentsSha256',
        'anchorManifestJsonSha256', 'sourceUnitIds', 'requiredChecks', 'machineIssues',
        'sourceReviewReceiptSha256', 'sourceMediaSha256', 'sourceWindowSeconds', 'scope'),
        'invalid_original_source_review_request')
    c.require(c.canonical_sha256(request) == authorization['sourceReviewRequestSha256'] and
        request['schemaVersion'] == 'sermon-english-source-review-request-v1' and
        request['humanApproval'] is False and request['status'] == 'pending' and
        request['scope'] == 'review_request_not_approval_receipt' and
        request['requiredChecks'] == list(diagnostic.PENDING_CHECKS) and
        request['sourceMediaSha256'] == config['sourceMediaSha256'] and
        request['sourceWindowSeconds'] == config['sourceWindowSeconds'], 'diagnostic_source_request_changed')
    source, _ = read('simulated-review-inputs/source.json')
    anchor, anchor_raw = read('anchor-manifest.json')
    aligned, aligned_raw = read('aligned-segments.json')
    references, _ = read('reference-chunks.json')
    diagnostic.validate_source(source, anchor, context)
    c.require(source['evidence']['machineJudge'] is None, 'diagnostic_machine_judge_not_supported')
    c.require(source['source']['media']['sha256'] == config['sourceMediaSha256'] and
        [source['source']['approvedWindow'][key] for key in ('startSeconds', 'endSeconds')] == config['sourceWindowSeconds'] and
        request['alignedSegmentsSha256'] == c.bytes_sha256(aligned_raw) and
        request['anchorManifestJsonSha256'] == c.canonical_sha256(anchor) == context['anchorCanonicalSha256'] and
        anchor['input']['mfaSegmentsSha256'] == c.bytes_sha256(aligned_raw) and
        request['sourceUnitIds'] == [unit['sourceUnitId'] for unit in anchor['sourceUnits']],
        'diagnostic_original_source_binding_changed')
    for key, value, raw, relative in (('transcript', aligned, aligned_raw, 'aligned-segments.json'),
                                     ('anchors', anchor, anchor_raw, 'anchor-manifest.json')):
        artifact = source[key]['artifact']
        c.require(artifact['sha256'] == c.bytes_sha256(raw) and
            artifact['jsonSha256'] == c.canonical_sha256(value) and
            artifact['path'] == str(root / relative), 'diagnostic_original_artifact_changed')
    c.require(type(aligned) is list and aligned and type(references) is list and references,
              'diagnostic_original_transcript_missing')
    segments = {row['id']: row for row in aligned}
    c.require(len(segments) == len(aligned), 'diagnostic_source_segment_conflict')
    receipts = {}
    for operation, model in (('transcription.initial', 'gpt-transcribe'), ('source.initial', 'gpt-6-astra')):
        rows = [(call, row) for call, row in state['requests'].items() if row['operationId'] == operation]
        c.require(len(rows) == 1, 'diagnostic_original_provider_receipt_missing')
        call, row = rows[0]
        budget._label(call)
        c.require(row['state'] == 'returned' and row['model'] == model, 'diagnostic_source_execution_not_returned')
        value, raw = read('budget/' + budget.STORE_ID + '/provider-run/' + call + '.json')
        c.require(c.bytes_sha256(raw) == row['receiptSha256'] and value['modelCallId'] == call and
            value['payloadSha256'] == row['requestSha256'] and type(value.get('response')) is dict,
            'diagnostic_original_provider_receipt_changed')
        receipts[operation] = value, raw, row
    asr, asr_raw, asr_row = receipts['transcription.initial']
    text = asr['response']['text']
    c.require(_normal(text) == _normal(' '.join(row['text'] for row in aligned)) ==
        _normal(' '.join(row['text'] for row in references)), 'diagnostic_asr_transcript_changed')
    duration = config['sourceWindowSeconds'][1] - config['sourceWindowSeconds'][0]
    c.require(asr['response'].get('model', 'gpt-transcribe') == 'gpt-transcribe' and
        asr['costEvidence'] == transcription.usage_cost_evidence(asr['response'], duration) and
        asr['costEvidence']['providerDurationStatus'] in ('reported', 'not_reported') and
        (asr['costEvidence'].get('costMicrousd') is None or
         asr['costEvidence']['costMicrousd'] <= asr_row['bounds']['costMicrousd']),
        'diagnostic_asr_usage_changed')
    review, review_raw, review_row = receipts['source.initial']
    response, observed = review['response'], review['usageObservation']
    c.require(request['sourceReviewReceiptSha256'] == c.bytes_sha256(review_raw) and
        review['payloadSha256'] == c.canonical_sha256(source_payload(config, text)) and
        response['model'] == 'gpt-6-astra' and observed['requestedModel'] == observed['providerModel'] == 'gpt-6-astra' and
        observed['providerUsage'] == accounting.normalize_usage(response.get('usage')) and
        observed['elapsedSeconds'] == review['elapsedSeconds'] and
        observed['serviceTier'] == response.get('service_tier', 'default') and
        review['costEvidence'] == limits.usage_cost_evidence(observed), 'diagnostic_source_usage_or_payload_changed')
    usage = limits.usage_resolver(observed)
    c.require(usage is not None and all(usage[key] <= review_row['bounds'][key] for key in
        ('inputTokens', 'outputTokens', 'costMicrousd')), 'diagnostic_source_usage_not_verified')
    choices = response['choices']
    c.require(type(choices) is list and len(choices) == 1 and choices[0]['finish_reason'] == 'stop' and
        choices[0]['message'].get('refusal') is None, 'diagnostic_source_response_incomplete')
    content = c.decode_json(choices[0]['message']['content'].encode('utf-8'))
    _exact(content, ('sourceAudioSha256', 'sourceWindowSeconds', 'issues', 'uncertainty'),
           'diagnostic_source_response_not_review_candidates')
    uncertainty = content['uncertainty']
    _exact(uncertainty, ('scope', 'audio_available', 'explicit_uncertainty_markers_present',
                       'confirmed_asr_errors', 'summary'), 'diagnostic_source_uncertainty_changed')
    c.require(content['sourceAudioSha256'] == config['sourceAudioSha256'] and
        content['sourceWindowSeconds'] == config['sourceWindowSeconds'] and
        uncertainty['audio_available'] is False and uncertainty['explicit_uncertainty_markers_present'] is False and
        type(uncertainty['confirmed_asr_errors']) is int and uncertainty['confirmed_asr_errors'] == 0 and
        uncertainty['scope'] == 'Text-internal review only; factual claims were not evaluated.' and
        type(uncertainty['summary']) is str and bool(uncertainty['summary'].strip()),
        'diagnostic_source_confirmed_or_unknown_finding')
    issues, pending = content['issues'], request['machineIssues']
    c.require(type(issues) is list and type(pending) is list and len(issues) == len(pending) == len(REASONS),
              'diagnostic_source_findings_changed')
    for index, (issue, item, reason) in enumerate(zip(issues, pending, REASONS), 1):
        _exact(issue, ('type', 'text', 'issue', 'uncertainty'), 'diagnostic_source_issue_changed')
        _exact(item, ('issueId', 'reasonCode', 'confirmedError', 'reviewStatus', 'matchedSegmentIds',
            'clipTimeRangesSeconds', 'matchingMethod', 'privateEvidenceSha256'), 'diagnostic_source_review_item_changed')
        c.require(issue['type'] == item['reasonCode'] == reason and item['issueId'] == 'source.issue.' + str(index) and
            item['confirmedError'] is False and item['reviewStatus'] == 'human_pending' and
            item['matchingMethod'] == 'literal_normalized_text_substring_not_verified_audio' and
            item['privateEvidenceSha256'] == c.canonical_sha256(issue) and
            all(type(issue[k]) is str and issue[k].strip() for k in ('text', 'issue', 'uncertainty')),
            'diagnostic_source_review_disposition_changed')
        ids = item['matchedSegmentIds']
        c.require(type(ids) is list and ids and len(ids) == len(set(ids)) and all(i in segments for i in ids) and
            item['clipTimeRangesSeconds'] == [[segments[i]['start'], segments[i]['end']] for i in ids] and
            all(_normal(issue['text']).lower() in _normal(segments[i]['text']).lower() for i in ids),
            'diagnostic_source_issue_location_changed')
    for relative, raw in captured.items():
        c.require(public.read_snapshot(_safe_path(root / relative))[1] == raw, 'diagnostic_source_snapshot_changed')
    return {'simulationAuthorizationSha256': c.canonical_sha256(authorization),
        'sourceReviewRequestSha256': c.canonical_sha256(request),
        'sourceReviewReceiptSha256': c.bytes_sha256(review_raw), 'asrReceiptSha256': c.bytes_sha256(asr_raw),
        'sourceCanonicalSha256': context['sourceCanonicalSha256'], 'anchorCanonicalSha256': context['anchorCanonicalSha256'],
        'alignedSegmentsSha256': c.bytes_sha256(aligned_raw),
        'pendingReviewCandidatesSha256': c.canonical_sha256(pending),
        'rawSourceUncertaintySha256': c.canonical_sha256(uncertainty),
        'sourceEvidenceSnapshotSha256': c.canonical_sha256({k: c.bytes_sha256(v) for k, v in captured.items()})}

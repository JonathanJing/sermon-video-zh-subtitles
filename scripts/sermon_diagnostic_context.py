"""Explicit simulated-review context; never a production human approval.

Source/candidate bytes remain unchanged. Only the named pending-human gates and
one bounded reviewable clause warning may be traversed inside this diagnostic.
Production callers omit this context and retain every existing approval gate.
"""
from copy import deepcopy
import math
import re
from scripts import sermon_review_contracts as c

SCHEMA = 'sermon-diagnostic-context-v1'
HASH_FIELDS = ('runId', 'runConfigSha256', 'storeSha256', 'sourceCanonicalSha256',
               'anchorCanonicalSha256', 'simulationAuthorizationRef')
CLAUSE_WARNING = 'clause_unit_exceeds_target_without_safe_boundary'
PENDING_CHECKS = ('sourceIdentity', 'transcriptCompleteness', 'wordAlignment', 'sentenceAndPauseBoundaries')


def validate_context(context):
    c.require(type(context) is dict and set(context) == set(HASH_FIELDS) | {
        'schemaVersion', 'continuationCodeCommit', 'humanAcceptance', 'productionEligible'},
        'invalid_diagnostic_context')
    c.require(context['schemaVersion'] == SCHEMA and context['humanAcceptance'] == 'pending'
        and context['productionEligible'] is False, 'diagnostic_cannot_grant_production_approval')
    c.require(all(type(context[key]) is str and re.fullmatch('[a-f0-9]{64}', context[key])
                  for key in HASH_FIELDS), 'invalid_diagnostic_context_hash')
    c.require(type(context['continuationCodeCommit']) is str and
        re.fullmatch('[a-f0-9]{40}', context['continuationCodeCommit']), 'invalid_diagnostic_code_commit')
    return deepcopy(context)


def validate_runtime(context, *, run_id, store_sha256):
    context = validate_context(context)
    c.require(context['runId'] == run_id and context['storeSha256'] == store_sha256,
              'diagnostic_runtime_binding_changed')
    return context


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _anchor_issue(issue):
    c.require(type(issue) is dict and issue.get('type') == CLAUSE_WARNING and
        _number(issue.get('durationSeconds')) and _number(issue.get('maximumSeconds')) and
        0 < issue['maximumSeconds'] < issue['durationSeconds'] <= 9.01,
        'diagnostic_anchor_issue_not_permitted')


def validate_source(source, anchor, context):
    from scripts import prepare_target_language_speech_job as speech
    from scripts import build_english_source_package as english
    from scripts import sermon_sentence_interpretation as interpretation
    context = validate_context(context)
    c.require(c.canonical_sha256(source) == context['sourceCanonicalSha256'] and
        c.canonical_sha256(anchor) == context['anchorCanonicalSha256'], 'diagnostic_source_identity_changed')
    speech._validate_schema(source, 'sermon-english-source-package-v1.schema.json', 'diagnostic source')
    # This narrow continuation uses the separately bound text-only source-check
    # receipt. It cannot override a canonical machine judge whose findings are
    # not necessarily copied into package.issues by the Source builder.
    c.require(source['evidence']['machineJudge'] is None,
              'diagnostic_canonical_machine_judge_requires_reconciliation')
    c.require(source['status'] in ('blocked', 'candidate_ready_for_translation') and
        source['translationEligible'] is False and source['review']['humanApproval'] is False,
        'diagnostic_requires_unapproved_source')
    c.require(interpretation.is_supported_anchor_manifest(anchor), 'diagnostic_anchor_schema')
    speech._validate_schema(anchor, 'sermon-sentence-anchor-manifest-v2.schema.json', 'diagnostic anchor')
    units = anchor.get('sourceUnits')
    c.require(type(units) is list and units and all(type(u) is dict for u in units), 'diagnostic_anchor_units')
    ids = [u.get('sourceUnitId') for u in units]
    c.require(all(type(i) is str and i for i in ids) and len(set(ids)) == len(ids) and
        all(type(u.get('english')) is str and u['english'].strip() for u in units), 'diagnostic_anchor_units')
    anchor_hash = c.canonical_sha256(anchor)
    c.require(source['anchors']['artifact']['jsonSha256'] == anchor_hash and
        source['anchors']['sourceUnitCount'] == len(units), 'diagnostic_anchor_binding_changed')
    window = source['source']['approvedWindow']
    # Only the absent human-window decision is a simulated gate. Media identity
    # and numeric window coherence stay mandatory without inventing approval.
    issues = english.source_gate_issues(source['source']['media'], window['startSeconds'],
                                       window['endSeconds'], window['humanApproval'] is True)
    c.require(all(i['type'] == 'approved_sermon_window_missing' for i in issues),
              'diagnostic_source_media_or_window_invalid')
    c.require(source['alignment']['issueCount'] == 0 and
        source['alignment']['artifact'] == source['transcript']['artifact'], 'diagnostic_alignment_blocked')
    c.require(all(value in ('pending', 'approved') for value in source['review']['checks'].values()),
              'diagnostic_failed_source_review')
    anchor_issues = anchor.get('issues', [])
    c.require(type(anchor_issues) is list, 'diagnostic_anchor_issues')
    for issue in anchor_issues:
        _anchor_issue(issue)
    for issue in source['issues']:
        permitted = ((issue.get('stage') == 'source' and issue.get('type') == 'approved_sermon_window_missing') or
            (issue.get('stage') == 'review' and issue.get('type') in {name+'_review_pending' for name in PENDING_CHECKS}))
        if issue.get('stage') == 'anchors':
            _anchor_issue(issue.get('detail'))
            permitted = issue.get('type') == CLAUSE_WARNING and issue['detail'] in anchor_issues
        c.require(permitted, 'diagnostic_source_issue_not_permitted')
    identity = english.source_identity(source['source'], source['transcript']['artifact'],
        source['anchors']['artifact'], source['review'], source['evidence']['machineJudge'], source['implementation'])
    c.require(source['downstreamInvalidationKey'] == identity and
        source['packageId'] == 'english-source-'+identity[:24], 'diagnostic_source_derived_identity_changed')
    return anchor_hash


def require_policy_ready(identity, context=None):
    """Pending human terminology is simulated; every other policy blocker stays."""
    if context is None:
        c.require(identity['productionPolicyReady'], 'Production policy has unresolved gates')
        return
    validate_context(context)
    c.require(type(identity.get('unresolved')) is list and set(identity['unresolved']) <= {
        'terminology_review_pending', 'proper_name_approval_evidence_pending'},
        'diagnostic_policy_blocker_not_permitted')

"""Private receipt-backed delivery-intent binding for an existing release plan.

Opt-in API only: freeze_binding(...) and validate_preflight_binding(...). The
existing release preflight must call the latter before using this envelope;
no default release hook, publication, approval creation, media probe, or network
call is installed here. Existing Source/L2 and audio review validators consume
actual local packages and independent receipts. Legacy v1/v2 policies only;
strict v3 is rejected until a trusted whole-chain strict adapter is supplied. L3 artifact reconstruction,
complete decode, duration, HTTP, clients, and venue acceptance stay separate.

configuration = {pageId, source, anchor, locales: {locale: {
    policy, candidate, humanReview, audioPackage,
    [audioHumanReview, screening, spokenPolicy, spokenCandidate, spokenHumanReview]
}}}. Values are explicit local JSON paths relative to root, or absolute paths.
The source package's receipt/transcript paths are resolved by its existing
canonical inspector. Evidence entries expose hashes only, never host paths or
content. A required-audio lane needs an independent audio receipt; a text-only
lane needs the actual same-locale audio_unavailable package and no spoken inputs.
Short-script audio has its own policy/candidate/translation review chain.

This envelope binds the exact in-memory legacy prepared release plan (including
buildReportSha256) but does not assert that its assets currently match that report.
The caller must invoke validate_preflight_binding with freshly read inputs inside
its existing release admission boundary, then retain every existing release gate.
Successful receipt verification is not media validation or publication authority.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
import stat

from scripts import sermon_delivery_intent as intent
from scripts import inspect_canonical_packages as packages
from scripts import prepare_target_language_speech_job as handoff
from scripts import stage_formal_multilingual_dev as stage
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'private-sermon-delivery-release-binding-v1'
MAX_BYTES = packages.MAX_JSON_BYTES


def require(value, code):
    intent.require(value, code)


class _Evidence:
    def __init__(self, root):
        self.root = _safe_path(Path(root))
        self.files = {}
        self.identities = {}

    def read(self, reference, key, *, object_required=True):
        require(isinstance(reference, (str, Path)) and bool(str(reference)), 'invalid_delivery_evidence_reference')
        path = _safe_path(self.root / reference)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'invalid_delivery_evidence_file')
            with os.fdopen(os.dup(fd), 'rb') as stream: data = stream.read(MAX_BYTES + 1)
            after = os.fstat(fd); named = path.stat(follow_symlinks=False)
            identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
            require(identity(before) == identity(after) == identity(named), 'delivery_evidence_changed_during_read')
        finally:
            os.close(fd)
        require(len(data) <= MAX_BYTES, 'delivery_evidence_size_limit')
        value = json.loads(data.decode('utf-8'), object_pairs_hook=intent._pairs, parse_constant=intent._constant)
        require(not object_required or type(value) is dict, 'delivery_evidence_must_be_object')
        row = {'canonicalJsonSha256': intent.canonical_hash(value),
               'fileBytesSha256': hashlib.sha256(data).hexdigest()}
        if key in self.identities:
            require(row == self.identities[key], 'delivery_evidence_changed_during_validation')
        self.identities[key] = row
        self.files[key] = (path, object_required)
        return value

    def recheck(self):
        for key, (path, object_required) in list(self.files.items()):
            self.read(path, key, object_required=object_required)


def _schema(value, filename):
    handoff._validate_schema(value, filename, 'delivery evidence')


def _exact(value, keys, code):
    require(type(value) is dict and set(value) == set(keys), code)


def _plan(release_plan, request):
    intent.canonical_hash(release_plan)
    require(type(release_plan) is dict and release_plan.get('schemaVersion') == 'sermon-weekly-release-plan-v1'
            and release_plan.get('status') == 'prepared_not_deployed', 'unsupported_delivery_release_plan')
    require(type(release_plan.get('buildReportSha256')) is str and
            re.fullmatch(r'[a-f0-9]{64}', release_plan['buildReportSha256']), 'delivery_release_build_identity_missing')
    weeks = release_plan.get('weekIds')
    require(type(weeks) is list and all(type(week) is str for week in weeks)
            and len(weeks) == len(set(weeks)) and request['pageId'] in weeks, 'delivery_release_page_mismatch')
    require(release_plan.get('origin') == request['delivery']['appRootUrl'].rstrip('/'),
            'delivery_release_origin_mismatch')
    # Legacy plans have no locale/source fields. Scope is frozen in this envelope,
    # not injected into the legacy object or inferred from its historical pages.
    return intent.canonical_hash(release_plan)


def _source(expected, source, inspection, evidence):
    raw = source['source']; window = raw['approvedWindow']
    approval = evidence.read(window['evidence']['path'], 'source.windowApproval')
    english_review = evidence.read(source['review']['evidence']['path'], 'source.englishReview')
    evidence.read(source['evidence']['pipelineSummary']['path'], 'source.summary')
    evidence.read(source['transcript']['artifact']['path'], 'source.alignedTranscript', object_required=False)
    for key, artifact in (('source.windowApproval', window['evidence']),
                          ('source.englishReview', source['review']['evidence']),
                          ('source.summary', source['evidence']['pipelineSummary']),
                          ('source.alignedTranscript', source['transcript']['artifact'])):
        observed = evidence.identities[key]
        require(observed['fileBytesSha256'] == artifact['sha256']
                and (artifact.get('jsonSha256') is None
                     or observed['canonicalJsonSha256'] == artifact['jsonSha256']),
                'delivery_source_artifact_identity_changed')
    actual = {'sourceId': raw['sourceId'], 'sourceUrlHash': raw['sourceUrlHash'],
              'englishSourcePackageJsonSha256': intent.canonical_hash(source),
              'downstreamInvalidationKey': source['downstreamInvalidationKey'],
              'mediaSha256': raw['media']['sha256'], 'mediaDurationSeconds': raw['media'].get('durationSeconds'),
              'window': {'startSeconds': window['startSeconds'], 'endSeconds': window['endSeconds'],
                         'approvalReceiptJsonSha256': intent.canonical_hash(approval)}}
    require(actual == expected, 'delivery_source_media_or_window_mismatch')
    require(inspection['packageIdentities'].get('sourceWindowReview') == intent.canonical_hash(approval)
            and inspection['packageIdentities'].get('sourceSummary') == evidence.identities['source.summary']['canonicalJsonSha256'],
            'delivery_source_receipt_changed')
    require(approval.get('status') == 'approved' and approval.get('humanApproval') is True
            and english_review.get('humanApproval') is True, 'delivery_source_approval_missing')
    return actual


def _approved_text(expected, candidate, receipt, source, anchor, policy, locale):
    require(expected is not None, 'delivery_approved_text_identity_missing')
    _schema(candidate, 'sermon-target-language-candidate-v2.schema.json')
    handoff.validate_target_candidate(source, anchor, candidate)
    handoff.validate_policy_binding(candidate, policy)
    handoff.validate_human_review_receipt(source, anchor, candidate, receipt)
    require(candidate['targetLocale'] == locale and expected['candidateJsonSha256'] == intent.canonical_hash(candidate)
            and expected['humanReviewReceiptJsonSha256'] == intent.canonical_hash(receipt),
            'delivery_approved_text_mismatch')


def _audio(target, lane, source, candidate, evidence):
    locale = target['targetLocale']; prefix = locale + '.'
    audio = evidence.read(lane['audioPackage'], prefix + 'audioPackage')
    _schema(audio, 'sermon-target-language-audio-package-v1.schema.json')
    require(audio['targetLocale'] == locale and audio['englishSourcePackageJsonSha256'] == intent.canonical_hash(source)
            and audio['targetLanguageCandidateJsonSha256'] == intent.canonical_hash(candidate), 'delivery_audio_binding_mismatch')
    if target['audioRequirement'] == 'text_only':
        require(set(lane) == {'policy', 'candidate', 'humanReview', 'audioPackage'}, 'delivery_text_only_has_spoken_inputs')
        require(audio['status'] == 'audio_unavailable' and audio['voice'] is None and not audio['units']
                and audio['track'] is None and audio['captions'] is None and audio['schedule'] is None,
                'delivery_text_only_requires_unavailable_package')
        expected = dict(packageJsonSha256=intent.canonical_hash(audio),
            **{key: audio[key] for key in ('englishSourcePackageJsonSha256',
                'targetLanguageCandidateJsonSha256', 'targetLocale', 'status')})
        require(target['layer3AudioUnavailable'] == expected, 'delivery_unavailable_identity_mismatch')
        return {'audioPackageJsonSha256': intent.canonical_hash(audio), 'audioRequirement': 'text_only',
                'audioHumanReviewJsonSha256': None, 'measuredDurationSeconds': None, 'durationStatus': 'not_applicable'}
    require('audioHumanReview' in lane, 'delivery_audio_approval_missing')
    review = evidence.read(lane['audioHumanReview'], prefix + 'audioHumanReview')
    version = review.get('schemaVersion')
    require(version in {'sermon-target-language-audio-human-review-receipt-v1',
                        'sermon-target-language-audio-human-review-receipt-v2'}, 'unsupported_delivery_audio_review')
    _schema(review, version + '.schema.json')
    screening = evidence.read(lane['screening'], prefix + 'screening') if 'screening' in lane else None
    if screening is not None: _schema(screening, 'sermon-target-language-audio-screening-v1.schema.json')
    require(audio['status'] == 'human_reviewed' and audio['track'] is not None and audio['voice'] is not None
            and audio['voice']['authorizationStatus'] == 'authorized' and audio['voice']['targetLocaleCapability'] == 'reviewed'
            and audio['humanReview']['status'] == 'approved' and audio['humanReview']['humanApproval'] is True
            and audio['humanReview']['fullPlayback'] == 'approved'
            and audio['machineScreening']['coverage'] == 1 and not audio['issues'], 'delivery_audio_not_reviewed')
    stage.validate_audio_screening_review(audio, review, screening)
    groups = candidate['groups']
    expected = {'targetLocale': locale, 'englishSourcePackageJsonSha256': intent.canonical_hash(source),
        'targetLanguageCandidateJsonSha256': intent.canonical_hash(candidate),
        'targetLanguageAudioPackageJsonSha256': intent.canonical_hash(audio), 'trackSha256': audio['track']['sha256'],
        'reviewedBy': audio['humanReview']['reviewedBy'], 'reviewedAt': audio['humanReview']['reviewedAt'],
        'reviewedUnitIds': [group['translationGroupId'] for group in groups]}
    require(all(review[key] == value for key, value in expected.items()), 'delivery_audio_approval_mismatch')
    require([(row['textGroupId'], row['targetTextSha256']) for row in audio['units']] ==
            [(group['translationGroupId'], hashlib.sha256(group['targetText'].encode()).hexdigest()) for group in groups],
            'delivery_audio_text_units_mismatch')
    # Unit durations/package flags are not evidence of a current complete track
    # decode. We deliberately do not sum them or substitute zero for unknown.
    return {'audioPackageJsonSha256': intent.canonical_hash(audio), 'audioRequirement': 'required',
            'audioHumanReviewJsonSha256': intent.canonical_hash(review), 'measuredDurationSeconds': None,
            'durationStatus': 'unknown'}


def freeze_binding(manifest, release_plan, *, root, configuration, weekly_plan=None):
    """Verify existing receipts and freeze a private envelope; write nothing."""
    intent.validate_intent(manifest)
    request = manifest['request']
    _exact(configuration, ('pageId', 'source', 'anchor', 'locales'), 'invalid_delivery_binding_configuration')
    require(configuration['pageId'] == request['pageId'], 'delivery_page_mismatch')
    require(type(configuration['locales']) is dict and set(configuration['locales']) ==
            {target['targetLocale'] for target in request['requestedLocales']}, 'delivery_locale_set_mismatch')
    plan_sha = _plan(release_plan, request)
    evidence = _Evidence(root)
    source = evidence.read(configuration['source'], 'source.package')
    anchor = evidence.read(configuration['anchor'], 'source.anchor')
    lanes = {}; values = {}
    required = {'policy', 'candidate', 'humanReview', 'audioPackage'}
    optional = {'spokenPolicy', 'spokenCandidate', 'spokenHumanReview', 'audioHumanReview', 'screening'}
    for locale, lane in configuration['locales'].items():
        require(type(lane) is dict and required <= set(lane) and not set(lane) - required - optional,
                'invalid_delivery_locale_configuration')
        values[locale] = {key: evidence.read(lane[key], locale + '.' + key)
                          for key in ('policy', 'candidate', 'humanReview')}
        require(values[locale]['policy'].get('schemaVersion') != 'sermon-target-language-policy-v3',
                'delivery_strict_v3_adapter_required')
        lanes[locale] = {key: str(lane[key]) for key in ('policy', 'candidate', 'humanReview')}
    inspected = packages.inspect_configuration(evidence.root, {'schemaVersion': packages.SCHEMA,
        'source': str(configuration['source']), 'anchor': str(configuration['anchor']), 'locales': lanes})
    require(inspected['nodes']['source']['status'] == 'validated' and not inspected['inspectionDiagnostics'],
            'delivery_source_or_text_gate_blocked')
    require(inspected['packageIdentities'].get('source') == intent.canonical_hash(source)
            and inspected['packageIdentities'].get('anchor') == intent.canonical_hash(anchor), 'delivery_source_changed')
    source_binding = _source(request['source'], source, inspected, evidence)
    locale_bindings = {}
    for target in request['requestedLocales']:
        locale = target['targetLocale']; lane = configuration['locales'][locale]; current = values[locale]
        require(inspected['nodes']['text.' + locale]['status'] == 'validated'
                and inspected['packageIdentities'].get('review.' + locale) == intent.canonical_hash(current['humanReview']),
                'delivery_translation_review_missing')
        _approved_text(target['approvedFullText'], current['candidate'], current['humanReview'], source,
                       anchor, current['policy'], locale)
        spoken = current['candidate']
        if target['audioRequirement'] == 'required':
            approved = target['approvedSpokenText']
            require(approved is not None, 'delivery_spoken_review_missing')
            if approved['kind'] == 'short_script':
                require({'spokenCandidate', 'spokenHumanReview', 'spokenPolicy'} <= set(lane), 'delivery_short_script_receipts_missing')
                spoken = evidence.read(lane['spokenCandidate'], locale + '.spokenCandidate')
                review = evidence.read(lane['spokenHumanReview'], locale + '.spokenHumanReview')
                policy = evidence.read(lane['spokenPolicy'], locale + '.spokenPolicy')
            else:
                require(not {'spokenCandidate', 'spokenHumanReview', 'spokenPolicy'} & set(lane), 'delivery_full_text_has_short_script_inputs')
                review, policy = current['humanReview'], current['policy']
            _approved_text(approved, spoken, review, source, anchor, policy, locale)
        audio = _audio(target, lane, source, spoken, evidence)
        locale_bindings[locale] = dict(audio, fullText=deepcopy(target['approvedFullText']),
                                      spokenText=deepcopy(target['approvedSpokenText']))
    offline = intent.preflight(manifest, weekly_plan=weekly_plan)
    evidence.recheck()
    payload = {'schemaVersion': SCHEMA, 'visibility': 'private', 'intentId': manifest['intentId'],
        'intentSha256': manifest['intentSha256'], 'intentManifestJsonSha256': intent.canonical_hash(manifest),
        'releasePlanJsonSha256': plan_sha, 'pageId': request['pageId'],
        'requiredLocales': sorted(configuration['locales']), 'source': source_binding,
        'delivery': deepcopy(request['delivery']), 'locales': locale_bindings,
        'evidence': evidence.identities, 'offlinePreflight': offline,
        'validationScope': 'existing_package_and_independent_approval_receipt_bindings',
        'remainingGates': ['existing_layer3_artifact_and_voice_authorization_gates', 'complete_decode_and_duration',
                           'existing_release_asset_preflight', 'http_clients_qr_and_required_venue_acceptance'],
        'humanApprovalGranted': False, 'publicationAuthorized': False, 'defaultReleaseHookInstalled': False}
    return dict(payload, bindingSha256=intent.canonical_hash(payload))


def validate_preflight_binding(binding, manifest, release_plan, *, root, configuration, weekly_plan=None):
    """Existing release preflight opt-in hook: revalidate every actual binding.

    A successful return verifies this prerequisite only, never authorizes release.
    Callers retain their existing asset/decode/permission/publication gates.
    """
    expected = freeze_binding(manifest, release_plan, root=root, configuration=configuration, weekly_plan=weekly_plan)
    require(type(binding) is dict and binding == expected, 'delivery_release_binding_stale_or_changed')
    return {'bindingSha256': expected['bindingSha256'], 'intentSha256': expected['intentSha256'],
            'releasePlanJsonSha256': expected['releasePlanJsonSha256'], 'pageId': expected['pageId'],
            'requiredLocales': expected['requiredLocales'], 'status': 'bindings_verified',
            'durationStatus': expected['offlinePreflight']['offlineStatus'], 'publicationAuthorized': False}

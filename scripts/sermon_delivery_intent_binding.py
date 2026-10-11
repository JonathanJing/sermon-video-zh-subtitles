"""Private receipt-backed delivery-intent binding for an existing release plan.

Opt-in APIs: freeze_binding(...) and validate_preflight_binding(...) verify a
legacy plan's existing package/receipt prerequisites without media probing.
prepare_formal_delivery(...) separately invokes the existing formal three-locale
preflight (including full local decode), immutable staging and final revalidation.
It consumes actual formal asset-preparation output, never a fabricated legacy plan.
No default hook, model call, approval creation, network or publication is installed.
Strict v3 additionally requires a trusted AdmissionBoundary and its current durable
ledger/intent proof. L3 reconstruction/voice authorization, natural-duration intent
acceptance, HTTP, clients and venue acceptance remain separate gates.

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

from contextlib import contextmanager
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
from scripts import sermon_review_contracts as contracts
from scripts import sermon_review_budget as budget
from scripts import sermon_strict_gate_admission as admission
from scripts import sermon_accounting as accounting
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'private-sermon-delivery-release-binding-v1'
STRICT_SCHEMA = 'private-sermon-delivery-release-binding-v2'
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


def _approved_text(expected, candidate, receipt, source, anchor, policy, locale, *, strict_rubric=None):
    require(expected is not None, 'delivery_approved_text_identity_missing')
    _schema(candidate, 'sermon-target-language-candidate-v2.schema.json')
    handoff.validate_target_candidate(source, anchor, candidate)
    handoff.validate_policy_binding(candidate, policy, strict_rubric=strict_rubric)
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
                        'sermon-target-language-audio-human-review-receipt-v2',
                        'sermon-target-language-audio-human-review-receipt-v3',
                        'sermon-target-language-audio-human-review-receipt-v4'}, 'unsupported_delivery_audio_review')
    _schema(review, version + '.schema.json')
    screening = evidence.read(lane['screening'], prefix + 'screening') if 'screening' in lane else None
    if screening is not None:
        require(screening.get('schemaVersion') in handoff.AUDIO_SCREENING_VERSIONS, 'unsupported_delivery_audio_screening')
        _schema(screening, handoff.audio_screening_schema_file(screening))
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


@contextmanager
def _strict_current(admissions):
    """Hold the existing shared admission/store locks; never create an intent.

    These objects come from trusted controller configuration, never model output.
    Multiple strict locales must use the same authoritative lock and budget store.
    Every selected intent must already exist; this prerequisite grants no action.
    """
    if admissions is None or admissions == {}:
        yield {}, lambda: None
        return
    require(type(admissions) is dict and set(admissions) <= {'zh-Hans', 'ko', 'es'},
            'invalid_delivery_strict_admissions')
    for locale, value in admissions.items():
        _exact(value, ('boundary', 'intentId'), 'invalid_delivery_strict_admission')
        boundary = value['boundary']
        require(type(boundary) is admission.AdmissionBoundary and boundary.config.target_locale == locale,
                'trusted_delivery_admission_boundary_required')
        budget._hash(value['intentId'])
    first = next(iter(admissions.values()))['boundary']
    for value in admissions.values():
        boundary = value['boundary']
        require(boundary._path(boundary.config.job_root) == first._path(first.config.job_root)
                and boundary.config.production_run_id == first.config.production_run_id
                and boundary.store.root == first.store.root
                and boundary.store.store_sha256 == first.store.store_sha256
                and boundary.store.authority_sha256 == first.store.authority_sha256,
                'delivery_strict_shared_admission_store_required')
        registry = boundary.store.root / budget.STORE_ID / ('gate-' + boundary.key) / 'state.json'
        require(registry.is_file(), 'delivery_strict_existing_intent_required')
    with first._locked() as (_, _, _, ledger):
        def capture():
            current = {}
            live_ledger = contracts.read_snapshot(first.store.root / budget.STORE_ID / 'state.json')[0]
            require(live_ledger == ledger, 'delivery_strict_ledger_changed')
            for locale, value in admissions.items():
                boundary, intent_id = value['boundary'], value['intentId']
                registry = boundary.store.root / budget.STORE_ID / ('gate-' + boundary.key) / 'state.json'
                record, raw = contracts.read_snapshot(registry)
                require(type(record) is dict and set(record) == {'schemaVersion', 'binding', 'intents'}
                        and record['schemaVersion'] == admission.SCHEMA and record['binding'] == boundary.binding
                        and type(record['intents']) is dict, 'delivery_strict_registry_changed')
                permission = record['intents'].get(intent_id)
                require(type(permission) is dict and permission.get('intentId') == intent_id
                        and permission.get('action') == 'prepare_layer3'
                        and permission.get('executionAuthority') == 'existing_layer3_adapter_only'
                        and intent_id == contracts.canonical_sha256(permission.get('identity')),
                        'delivery_strict_existing_intent_required')
                snapshot = boundary._load(raw, ledger)
                validated, decisions, reasons = boundary._validate(snapshot, permission['createdAt'])
                require(not reasons and validated is not None and decisions
                        and all(d['admissionStatus'] == 'admitted' for d in decisions)
                        and validated['publicCandidateSha256'] == permission['publicCandidateSha256']
                        and validated['humanReceiptSha256'] == permission['humanReceiptSha256'],
                        'delivery_strict_current_chain_blocked')
                identity = permission['identity']
                legacy_identity = {'schemaVersion': admission.SCHEMA,
                    'productionRunId': boundary.config.production_run_id,
                    'targetLocale': locale, 'action': 'prepare_layer3',
                    'sourceIdentitySha256': snapshot.groups[0].current.source_identity_sha256,
                    'policySha256': snapshot.groups[0].current.policy_sha256,
                    'publicCandidateSha256': validated['publicCandidateSha256']}
                receipt_identity = dict(legacy_identity, humanReceiptSha256=validated['humanReceiptSha256'])
                # Both formats remain safe only after the current-chain receipt
                # check above. New permissions bind the receipt in their key.
                require(identity in (legacy_identity, receipt_identity),
                        'delivery_strict_intent_identity_changed')
                proof = {'intentId': intent_id, 'intentCanonicalJsonSha256': contracts.canonical_sha256(permission),
                    'stateRevision': snapshot.state_revision, 'snapshotSha256': snapshot.snapshot_sha256,
                    'budgetStoreSha256': boundary.store.store_sha256,
                    'budgetAuthoritySha256': boundary.store.authority_sha256,
                    'pluginImplementationSha256': boundary.config.plugin_sha256,
                    'currentEvidenceFileBytesSha256': {key: contracts.bytes_sha256(data)
                                                      for key, data in snapshot.files.items()}}
                current[locale] = {'snapshot': snapshot, 'proof': proof, 'boundary': boundary}
            return current
        captured = capture()
        def recheck():
            fresh = capture()
            require({key: row['proof'] for key, row in fresh.items()} ==
                    {key: row['proof'] for key, row in captured.items()}, 'delivery_strict_evidence_changed')
        yield captured, recheck


def freeze_binding(manifest, release_plan, *, root, configuration, weekly_plan=None, strict_admissions=None):
    """Freeze a private prerequisite using current receipts, never grant release.

    Strict v3 requires explicit trusted ``strict_admissions`` keyed by locale,
    each ``{'boundary': AdmissionBoundary, 'intentId': existing_D4_intent_id}``.
    All strict locales share the production run, existing admission lock and global budget store.
    Legacy bindings retain schema v1; strict bindings use v2 with safe current-proof hashes.
    No model calls, intent creation or publication occur. Existing lock files may
    be opened; no evidence is written. Strict short-script secondary chains are
    unsupported and block until independently integrated.
    """
    with _strict_current(strict_admissions) as (current, recheck):
        result = _freeze_binding(manifest, release_plan, root=root, configuration=configuration,
                                 weekly_plan=weekly_plan, strict_current=current)
        recheck()
        return result


def _freeze_binding(manifest, release_plan, *, root, configuration, weekly_plan=None, strict_current=None, formal_descriptor=None):
    """Verify existing receipts and freeze a private envelope; write nothing."""
    intent.validate_intent(manifest)
    request = manifest['request']
    _exact(configuration, ('pageId', 'source', 'anchor', 'locales'), 'invalid_delivery_binding_configuration')
    require(configuration['pageId'] == request['pageId'], 'delivery_page_mismatch')
    require(type(configuration['locales']) is dict and set(configuration['locales']) ==
            {target['targetLocale'] for target in request['requestedLocales']}, 'delivery_locale_set_mismatch')
    plan_sha = _plan(release_plan, request) if formal_descriptor is None else intent.canonical_hash(formal_descriptor)
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
        is_strict = values[locale]['policy'].get('schemaVersion') == 'sermon-target-language-policy-v3'
        require(is_strict == (locale in strict_current), 'delivery_strict_v3_adapter_required')
        if is_strict:
            snapshot = strict_current[locale]['snapshot']
            for key, name in (('source.package', 'source'), ('source.anchor', 'anchor'),
                              (locale + '.policy', 'policy'), (locale + '.candidate', 'public_candidate'),
                              (locale + '.humanReview', 'human_receipt')):
                require(evidence.identities[key]['fileBytesSha256'] == contracts.bytes_sha256(snapshot.files[name]),
                        'delivery_strict_config_evidence_mismatch')
        lanes[locale] = {key: str(lane[key]) for key in ('policy', 'candidate', 'humanReview')}
    require(set(strict_current) <= set(values), 'delivery_strict_extra_locale')
    inspected = packages.inspect_configuration(evidence.root, {'schemaVersion': packages.SCHEMA,
        'source': str(configuration['source']), 'anchor': str(configuration['anchor']), 'locales': lanes})
    require(inspected['nodes']['source']['status'] == 'validated'
            and all(node in {'text.' + locale for locale in strict_current} and reason == 'policy_not_validated'
                    for node, reason in inspected['inspectionDiagnostics'].items()),
            'delivery_source_or_text_gate_blocked')
    require(inspected['packageIdentities'].get('source') == intent.canonical_hash(source)
            and inspected['packageIdentities'].get('anchor') == intent.canonical_hash(anchor), 'delivery_source_changed')
    source_binding = _source(request['source'], source, inspected, evidence)
    locale_bindings = {}
    for target in request['requestedLocales']:
        locale = target['targetLocale']; lane = configuration['locales'][locale]; current = values[locale]
        require(locale in strict_current or (inspected['nodes']['text.' + locale]['status'] == 'validated'
                and inspected['packageIdentities'].get('review.' + locale) == intent.canonical_hash(current['humanReview'])),
                'delivery_translation_review_missing')
        rubric = contracts.decode_json(strict_current[locale]['snapshot'].files['rubric']) if locale in strict_current else None
        _approved_text(target['approvedFullText'], current['candidate'], current['humanReview'], source,
                       anchor, current['policy'], locale, strict_rubric=rubric)
        spoken = current['candidate']
        if target['audioRequirement'] == 'required':
            approved = target['approvedSpokenText']
            require(approved is not None, 'delivery_spoken_review_missing')
            if approved['kind'] == 'short_script':
                require(locale not in strict_current, 'delivery_strict_short_script_adapter_required')
                require({'spokenCandidate', 'spokenHumanReview', 'spokenPolicy'} <= set(lane), 'delivery_short_script_receipts_missing')
                spoken = evidence.read(lane['spokenCandidate'], locale + '.spokenCandidate')
                review = evidence.read(lane['spokenHumanReview'], locale + '.spokenHumanReview')
                policy = evidence.read(lane['spokenPolicy'], locale + '.spokenPolicy')
            else:
                require(not {'spokenCandidate', 'spokenHumanReview', 'spokenPolicy'} & set(lane), 'delivery_full_text_has_short_script_inputs')
                review, policy = current['humanReview'], current['policy']
            _approved_text(approved, spoken, review, source, anchor, policy, locale, strict_rubric=rubric)
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
    if strict_current:
        payload['schemaVersion'] = STRICT_SCHEMA
        payload['validationScope'] = 'strict_current_admission_and_existing_package_approval_bindings'
        payload['strictAdmissions'] = {locale: row['proof'] for locale, row in strict_current.items()}
    if formal_descriptor is not None:
        payload['schemaVersion'] = 'private-sermon-formal-delivery-binding-v1'
        payload['formalDescriptorJsonSha256'] = payload.pop('releasePlanJsonSha256')
    return dict(payload, bindingSha256=intent.canonical_hash(payload))


def validate_preflight_binding(binding, manifest, release_plan, *, root, configuration, weekly_plan=None, strict_admissions=None):
    """Existing release preflight opt-in hook: revalidate every actual binding.

    A successful return verifies this prerequisite only, never authorizes release.
    Callers retain their existing asset/decode/permission/publication gates.
    """
    expected = freeze_binding(manifest, release_plan, root=root, configuration=configuration, weekly_plan=weekly_plan,
                              strict_admissions=strict_admissions)
    require(type(binding) is dict and binding == expected, 'delivery_release_binding_stale_or_changed')
    return {'bindingSha256': expected['bindingSha256'], 'intentSha256': expected['intentSha256'],
            'releasePlanJsonSha256': expected['releasePlanJsonSha256'], 'pageId': expected['pageId'],
            'requiredLocales': expected['requiredLocales'], 'status': 'bindings_verified',
            'durationStatus': expected['offlinePreflight']['offlineStatus'], 'publicationAuthorized': False}


FORMAL_DESCRIPTOR = 'private-sermon-formal-delivery-descriptor-v1'
FORMAL_RESULT = 'private-sermon-formal-delivery-preparation-v1'
FORMAL_ASSIGNMENTS = {'candidate': 'candidate', 'human_review_receipt': 'humanReview',
                     'audio_package': 'audioPackage', 'audio_human_review_receipt': 'audioHumanReview',
                     'audio_screening_receipt': 'screening'}


def _formal_capture(manifest, args, preparation_receipt_path, *, root, configuration):
    """Invoke the existing complete local asset gate and freeze what it read."""
    intent.validate_intent(manifest)
    request = manifest['request']
    require(set(configuration['locales']) == set(stage.LOCALES)
            and all(row['audioRequirement'] == 'required' and row['approvedSpokenText'] is not None
                    and row['approvedSpokenText']['kind'] == 'full_text'
                    for row in request['requestedLocales']), 'formal_delivery_requires_three_full_audio_locales')
    require(args.page_id == request['pageId'] == configuration['pageId'], 'formal_delivery_page_mismatch')
    resolve = lambda path: _safe_path(Path(root) / path)
    require(resolve(args.source) == resolve(configuration['source']), 'formal_delivery_source_path_mismatch')
    inputs = _Evidence(root)
    inputs.read(args.source, 'source')
    arguments = {key: str(getattr(args, key)) for key in
                 ('source', 'asset_root', 'out', 'page_id', 'page_date', 'default_target', 'generated_at')}
    for attribute, name in FORMAL_ASSIGNMENTS.items():
        values = getattr(args, attribute, [])
        arguments[attribute] = list(values)
        paths = stage.assignment_map(values, '--' + attribute.replace('_', '-')) if values else {}
        for locale in stage.LOCALES:
            expected = configuration['locales'][locale].get(name)
            require((locale in paths) == (expected is not None)
                    and (expected is None or resolve(paths[locale]) == resolve(expected)),
                    'formal_delivery_lane_path_mismatch')
            if locale in paths: inputs.read(paths[locale], locale + '.' + name)
    for attribute in ('release', 'content_review_receipt', 'fingerprint_index'):
        values = getattr(args, attribute, [])
        arguments[attribute] = list(values)
        paths = stage.assignment_map(values, '--' + attribute.replace('_', '-')) if values else {}
        for locale, path in paths.items(): inputs.read(path, locale + '.' + attribute)
    prepared = inputs.read(preparation_receipt_path, 'assetPreparationReceipt')
    require(set(prepared) == {'schemaVersion', 'pageId', 'metadataApprovalJsonSha256', 'targetLocales', 'status'}
            and prepared['schemaVersion'] == 'sermon-formal-dev-release-asset-preparation-v1'
            and prepared['pageId'] == args.page_id and prepared['targetLocales'] == list(stage.LOCALES)
            and prepared['status'] == 'candidate_not_deployed'
            and type(prepared['metadataApprovalJsonSha256']) is str
            and re.fullmatch(r'[a-f0-9]{64}', prepared['metadataApprovalJsonSha256']),
            'formal_delivery_asset_preparation_receipt_invalid')
    # This is the actual existing preflight: independent translation/audio/content
    # receipts, source/date, complete decode, units, captions, schedules and assets.
    catalog, files, _ = stage.preflight(args)
    assets = {}
    for public_path, (path, expected_hash) in files.items():
        checked = resolve(path)
        require(stage.file_sha(checked) == expected_hash, 'formal_delivery_asset_changed')
        assets[public_path] = expected_hash
    inputs.recheck()
    descriptor = {'schemaVersion': FORMAL_DESCRIPTOR, 'pageId': args.page_id,
        'origin': request['delivery']['appRootUrl'].rstrip('/'),
        'intentManifestJsonSha256': intent.canonical_hash(manifest),
        'stageArgumentsSha256': intent.canonical_hash(arguments),
        'inputEvidence': inputs.identities, 'publicAssetFileBytesSha256': assets,
        'catalogCanonicalJsonSha256': intent.canonical_hash(catalog),
        'status': 'local_preflight_pass_not_deployed'}
    return descriptor


def _formal_binding(manifest, descriptor, *, root, configuration, weekly_plan, current):
    return _freeze_binding(manifest, None, root=root, configuration=configuration,
        weekly_plan=weekly_plan, strict_current=current, formal_descriptor=descriptor)


def _formal_output(args, descriptor, receipt):
    out = _safe_path(args.out)
    expected_paths = {path.lstrip('/') for path in descriptor['publicAssetFileBytesSha256']}
    expected_paths.update(('multilingual-v2.json', 'stage-receipt.json'))
    paths = {str(p.relative_to(out)) for p in out.rglob('*') if p.is_file()}
    require(paths == expected_paths, 'formal_delivery_output_inventory_changed')
    for path, expected in descriptor['publicAssetFileBytesSha256'].items():
        require(stage.file_sha(_safe_path(out / path.lstrip('/'))) == expected,
                'formal_delivery_output_asset_changed')
    catalog = contracts.read_snapshot(_safe_path(out / 'multilingual-v2.json'))[0]
    saved_receipt = contracts.read_snapshot(_safe_path(out / 'stage-receipt.json'))[0]
    require(saved_receipt == receipt and receipt['deploymentStatus'] == 'not_deployed'
            and receipt['httpVerification'] == receipt['deviceAcceptance'] == 'not_run'
            and stage.file_sha(out / 'multilingual-v2.json') == receipt['catalogSha256']
            and intent.canonical_hash(catalog) == descriptor['catalogCanonicalJsonSha256'],
            'formal_delivery_staged_catalog_or_receipt_changed')
    return {path: stage.file_sha(_safe_path(out / path)) for path in sorted(paths)}


def prepare_formal_delivery(manifest, *, root, configuration, stage_args, preparation_receipt_path,
                            weekly_plan=None, strict_admissions=None, depends_on=None,
                            completion_spans=None):
    """Run actual local preflight/staging as one measured deterministic operation.

    Explicit dependency IDs must name actual prior operations in the session.
    Missing queue/cross-process timing is not inferred. Logging failure after
    staging preserves output and requires reconciliation, never a fresh retry.
    """
    require(completion_spans is None or type(completion_spans) is list, 'invalid_formal_span_sink')
    with accounting.stage('rqc.formal_delivery', depends_on=depends_on,
                          executor_type='deterministic_program') as span:
        result = _prepare_formal_delivery(manifest, root=root, configuration=configuration,
            stage_args=stage_args, preparation_receipt_path=preparation_receipt_path,
            weekly_plan=weekly_plan, strict_admissions=strict_admissions)
        accounting.record_workload('rqc.formal_delivery_result', {
            'resultSha256': result['resultSha256'],
            'intentSha256': manifest['intentSha256'],
            'stageReceiptSha256': result['stageReceiptJsonSha256'],
            'outputFileCount': len(result['outputFileBytesSha256'])})
    if completion_spans is not None: completion_spans.append(span)
    return result


def _prepare_formal_delivery(manifest, *, root, configuration, stage_args, preparation_receipt_path,
                            weekly_plan=None, strict_admissions=None):
    """Prepare immutable local formal assets via actual preflight -> stage -> recheck.

    Consumes outputs from build_formal_dev_release_assets.build, including its
    preparation-receipt.json. It DOES NOT fabricate a weekly legacy release plan.
    Current formal producer supports exactly three fully reviewed full-text/audio
    locales. Metadata/audio human approvals are prerequisites, never created here.
    Strict callers provide the same trusted admissions as freeze_binding. The
    shared admission and budget locks remain held during decode and staging.

    This wrapper owns no deployment and emits no public approval. If final
    validation fails after stage wrote output, preserve it as untrusted local
    evidence; never delete, overwrite, or retry it as a fresh successful result.
    The caller retains existing release authorization/HTTP/device/venue gates.
    """
    args = deepcopy(stage_args)
    for name in ('source', 'asset_root', 'out'):
        setattr(args, name, _safe_path(Path(root) / getattr(args, name)))
    for name in (*FORMAL_ASSIGNMENTS, 'release', 'content_review_receipt', 'fingerprint_index'):
        values = getattr(args, name, [])
        paths = stage.assignment_map(values, '--' + name.replace('_', '-')) if values else {}
        setattr(args, name, [locale + '=' + str(_safe_path(Path(root) / path)) for locale, path in paths.items()])
    require(not args.out.exists(), 'formal_delivery_requires_new_output')
    with _strict_current(strict_admissions) as (current, recheck):
        for row in current.values():
            boundary = row['boundary']
            protected = [boundary.store.root, boundary._path(boundary.config.job_root),
                         *map(boundary._path, boundary.config.revision_roots)]
            require(not any(args.out == p or args.out in p.parents or p in args.out.parents for p in protected),
                    'formal_delivery_output_overlaps_admission')
        descriptor = _formal_capture(manifest, args, preparation_receipt_path, root=root, configuration=configuration)
        binding = _formal_binding(manifest, descriptor, root=root, configuration=configuration,
                                  weekly_plan=weekly_plan, current=current)
        recheck()
        try:
            receipt = stage.stage(args)
            final = _formal_capture(manifest, args, preparation_receipt_path, root=root, configuration=configuration)
            require(final == descriptor, 'formal_delivery_input_changed_after_stage')
            final_binding = _formal_binding(manifest, final, root=root, configuration=configuration,
                                           weekly_plan=weekly_plan, current=current)
            require(final_binding == binding, 'formal_delivery_binding_changed_after_stage')
            recheck()
            outputs = _formal_output(args, descriptor, receipt)
        except Exception as exc:
            if args.out.exists():
                raise intent.IntentError('formal_delivery_local_output_requires_reconciliation') from exc
            raise
        result = {'schemaVersion': FORMAL_RESULT, 'status': 'local_prepared_not_deployed',
            'descriptor': descriptor, 'binding': binding,
            'stageReceiptJsonSha256': intent.canonical_hash(receipt), 'outputFileBytesSha256': outputs,
            'modelCalls': 0, 'fullDecodeValidation': 'existing_formal_preflight_pass',
            'intentDurationStatus': binding['offlinePreflight']['offlineStatus'],
            'humanApprovalGranted': False, 'publicationAuthorized': False,
            'remainingGates': ['existing_layer3_voice_authorization_and_package_reconstruction',
                               'required_content_quality_and_delivery_acceptance',
                               'release_authorization_http_device_venue']}
        return dict(result, resultSha256=intent.canonical_hash(result))

"""Version-bound delivery planning and evidence validation (no network or approval synthesis)."""
from __future__ import annotations
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import backend as _delivery


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def source_identity(package):
    """Public immutable source binding, without local paths or reviewer details."""
    source = package['source']
    window = source['approvedWindow']
    require(window['status'] == 'approved' and window['humanApproval'] is True
            and isinstance(window.get('evidence'), dict), 'Approved source window evidence required')
    identity = {'sourceId': source['sourceId'], 'sourceUrlHash': source['sourceUrlHash'],
                'mediaSha256': source['media']['sha256'], 'durationSeconds': source['media']['durationSeconds'],
                'window': {key: window[key] for key in ('startSeconds', 'endSeconds')}}
    identity['window']['approvalReceiptSha256'] = window['evidence']['sha256']
    require(0 <= window['startSeconds'] < window['endSeconds'] <= identity['durationSeconds'], 'Source window exceeds media')
    require(all(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) for value in
                (identity['sourceUrlHash'], identity['mediaSha256'], identity['window']['approvalReceiptSha256'])),
            'Full source URL/media/window approval hashes required')
    return identity


RELEASE_V3 = 'sermon-target-language-release-package-v3'
RELEASE_V4 = 'sermon-target-language-release-package-v4'
FOUR_PRODUCT_RELEASES = (RELEASE_V3, RELEASE_V4)
CATALOG_V3 = 'sermon-multilingual-catalog-v3'
CATALOG_V4 = 'sermon-multilingual-catalog-v4'
CATALOG_V5 = 'sermon-multilingual-catalog-v5'
CATALOG_FILES = {CATALOG_V3: 'multilingual-v3.json', CATALOG_V4: 'multilingual-v4.json',
                 CATALOG_V5: 'multilingual-v5.json'}
MACHINE_CHECKED = 'machine_checked'


def _schema(version):
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads(_delivery.current().schemas.path(version + '.schema.json').read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def machine_checked(entry):
    """A release or catalog target admitted by a machine quality waiver (never a human approval)."""
    return MACHINE_CHECKED in (entry.get('contentStatus'), entry.get('audioStatus'))


def video_matches_source(delivery, edition, media_sha):
    return (isinstance(delivery, dict)
            and delivery.get('canonicalUrl') == f"/pages/{edition}/full-video-browser.mp4"
            and delivery.get('sha256') == media_sha
            and re.fullmatch(
                r'https://storage\.googleapis\.com/ai-for-god-sermon-media-(?:dev|prod)/weekly/'
                + re.escape(edition) + '/' + media_sha + r'\.mp4',
                delivery.get('storageUrl', '')) is not None)


def release_path(release):
    """Machine-checked releases live under /releases-v4/ so v3-only clients never reach them."""
    directory = 'releases-v4' if release['schemaVersion'] == RELEASE_V4 else 'releases-v2'
    return f"/{directory}/{release['pageId']}/{release['targetLocale']}.json"


def validate_release_schema(release):
    version = release.get('schemaVersion')
    require(version in ('sermon-target-language-release-package-v2', *FOUR_PRODUCT_RELEASES), 'Unsupported release version')
    _schema(version).validate(release)
    if version == RELEASE_V4:
        require(release['disclosure']['locale'] == release['targetLocale'], 'Release disclosure is for another locale')


def validate_catalog_schema(catalog):
    version = catalog.get('schemaVersion')
    require(version in CATALOG_FILES, 'Unsupported catalog version')
    _schema(version).validate(catalog)
    for page in catalog['pages']:
        for locale, target in page['targets'].items():
            directory = 'releases-v4' if machine_checked(target) else 'releases-v2'
            per_target = version == CATALOG_V5 and page['sourceMode'] == 'per_target'
            edition = target['editionId'] if per_target else page['id']
            require(target['releasePackageUrl'] == f"/{directory}/{edition}/{locale}.json",
                    'Catalog release path differs from edition/locale')
            if per_target:
                require(video_matches_source(target['videoDelivery'], edition, target['sourceMediaSha256']),
                        'Target video delivery differs from its source edition')
                binding = target.get('audioFingerprint')
                require(binding is None or (binding['pageId'] == edition
                                             and binding['sourceSha256'] == target['sourceMediaSha256']),
                        'Target fingerprint differs from its source edition')
    return catalog


def target_source_identity(page, target):
    """The immutable edition/source join for one catalog target."""
    if page.get('sourceMode') == 'per_target':
        return target['editionId'], target['sourceIdentitySha256'], target['sourceMediaSha256']
    return page['id'], page['sourceIdentitySha256'], page.get('sourceMediaSha256')


def validate_release_target(release, page, locale):
    """Reject cross-edition release reuse even when page title/family are shared."""
    edition, source_sha, media_sha = target_source_identity(page, page['targets'][locale])
    require(release['pageId'] == edition and release['targetLocale'] == locale
            and release.get('englishSourcePackageJsonSha256') == source_sha
            and release.get('sourceIdentity', {}).get('mediaSha256') == media_sha,
            'Release differs from target edition/source identity')
    return release


def validate_v2_release_target(release, page, locale):
    """A human v2 release has no source identity, but must still name this target.

    Mirrors what the Web and iOS readers admit: edition, locales, path, the catalog
    statuses and a passed HTTP verification. The bound content proves the source.
    """
    validate_release_schema(release)
    target = page['targets'][locale]
    edition = target_source_identity(page, target)[0]
    require(release['schemaVersion'] == 'sermon-target-language-release-package-v2'
            and release['pageId'] == edition and release['sourceLocale'] == 'en'
            and all(release[key] == locale for key in ('targetLocale', 'contentLocale', 'audioLocale', 'interfaceLocale'))
            and target['releasePackageUrl'] == release_path(release)
            and (release['contentStatus'], release['audioStatus']) == (target['contentStatus'], target['audioStatus'])
            and release['status'] == 'published_http_verified' and release['httpVerification']['status'] == 'pass'
            and not release['issues'],
            'Release differs from target edition/locale/status')
    return release


def validate_content_target(content, page, locale):
    """Legacy v2 releases still prove their target source through bound content bytes."""
    edition, source_sha, media_sha = target_source_identity(page, page['targets'][locale])
    require(content.get('pageId') == edition and content.get('targetLocale') == locale
            and content.get('englishSourcePackageJsonSha256') == source_sha
            and content.get('sourceMediaSha256') == media_sha,
            'Content differs from target edition/source identity')
    return content


def upgrade_catalog(catalog):
    """A v3 catalog is a valid v4 catalog with only human-reviewed targets."""
    if catalog.get('schemaVersion') == CATALOG_V4:
        return copy.deepcopy(catalog)
    require(catalog.get('schemaVersion') == CATALOG_V3, 'Unsupported catalog version')
    return {**copy.deepcopy(catalog), 'schemaVersion': CATALOG_V4}


def upgrade_catalog_v5(catalog):
    """Preserve a legacy catalog as explicit single-source v5 pages."""
    if catalog.get('schemaVersion') == CATALOG_V5:
        return copy.deepcopy(catalog)
    value = upgrade_catalog(catalog)
    value['schemaVersion'] = CATALOG_V5
    for page in value['pages']:
        page['sourceMode'] = 'single_source'
    return validate_catalog_schema(value)


def project_human_catalog(catalog):
    """The v3 catalog old clients read: every machine-checked target removed.

    Pages left without targets disappear; a removed default moves to a remaining
    locale or to the latest remaining page that is not a simulation or diagnostic
    test page (any page only when no other remains). Nothing else changes.
    """
    require(catalog.get('schemaVersion') == CATALOG_V4, 'Projection requires a v4 catalog')
    result = {**copy.deepcopy(catalog), 'schemaVersion': CATALOG_V3}
    pages = []
    for page in result['pages']:
        targets = {locale: target for locale, target in page['targets'].items() if not machine_checked(target)}
        if not targets:
            continue
        if page['defaultTargetLocale'] not in targets:
            page['defaultTargetLocale'] = next((locale for locale in ('zh-Hans', 'ko', 'es') if locale in targets), sorted(targets)[0])
        page['targets'] = targets
        pages.append(page)
    require(pages, 'A catalog with only machine-checked pages has no human-only projection')
    if result['defaultPageId'] not in {page['id'] for page in pages}:
        # A Dev test page dated after every reviewed page must not become what old clients open first.
        real = [page for page in pages if page.get('simulationOnly') is not True and page.get('diagnosticOnly') is not True]
        result['defaultPageId'] = max(real or pages, key=lambda page: page['date'])['id']
    result['pages'] = pages
    return result


def project_legacy_catalog_v4(catalog):
    """Split a v5 presentation family into honest single-source v4 edition pages."""
    require(catalog.get('schemaVersion') == CATALOG_V5, 'Legacy projection requires a v5 catalog')
    result = {'schemaVersion': CATALOG_V4, 'generatedAt': catalog['generatedAt'],
              'defaultPageId': None, 'pages': []}
    by_id = {}
    default_edition = None
    # Each edition page's default is the v5 page default when that locale lands on
    # the edition, else the fixed locale order: never the targets' key order, which
    # a sorted write and reload changes.
    declared_default = {}
    for page in catalog['pages']:
        for locale, target in page['targets'].items():
            per_target = page['sourceMode'] == 'per_target'
            edition = target['editionId'] if per_target else page['id']
            source_identity = target['sourceIdentitySha256'] if per_target else page['sourceIdentitySha256']
            source_media = target['sourceMediaSha256'] if per_target else page.get('sourceMediaSha256')
            video = target['videoDelivery'] if per_target else page.get('videoDelivery')
            if locale == page['defaultTargetLocale']:
                declared_default.setdefault(edition, locale)
                default_edition = edition if page['id'] == catalog['defaultPageId'] else default_edition
            projected_target = {key: copy.deepcopy(value) for key, value in target.items()
                                if key not in {'editionId', 'sourceIdentitySha256', 'sourceMediaSha256', 'videoDelivery'}}
            projected = by_id.get(edition)
            if projected is None:
                projected = {'id': edition, 'date': page['date'], 'title': page['title'], 'sourceLocale': 'en',
                             'sourceIdentitySha256': source_identity,
                             'defaultTargetLocale': locale, 'targets': {}}
                for key in ('displayCategory', 'mediaType', 'sourceUrl', 'simulationOnly', 'diagnosticOnly'):
                    if key in page:
                        projected[key] = copy.deepcopy(page[key])
                by_id[edition] = projected
                result['pages'].append(projected)
                if source_media is not None:
                    projected['sourceMediaSha256'] = source_media
                if video is not None:
                    projected['videoDelivery'] = copy.deepcopy(video)
            require(projected['sourceIdentitySha256'] == source_identity
                    and projected.get('sourceMediaSha256') == source_media
                    and projected.get('videoDelivery') == video,
                    'Locales sharing an edition have different source identities')
            projected['targets'][locale] = projected_target
    require(default_edition in by_id, 'Default v5 target edition is missing')
    result['defaultPageId'] = default_edition
    for page in result['pages']:
        page['defaultTargetLocale'] = declared_default.get(page['id']) or next(
            (locale for locale in ('zh-Hans', 'ko', 'es') if locale in page['targets']), sorted(page['targets'])[0])
    return validate_catalog_schema(result)


def carry_single_source_into_v5(baseline_v5, merged_v4, page_id):
    """Apply an ordinary single-source v4 merge to the v5 catalog the baseline v4 projects from.

    A single-source v5 page is its v4 page plus ``sourceMode``, so the merged page is
    carried over (replaced in place or appended) and the result must project back to
    exactly ``merged_v4``. A page that is, or is an edition inside, a per_target
    family is refused: sealing it single-source would split the family.
    """
    require(baseline_v5.get('schemaVersion') == CATALOG_V5 and merged_v4.get('schemaVersion') == CATALOG_V4,
            'Single-source v5 carry needs a v5 baseline and a merged v4 catalog')
    require(not any(page['sourceMode'] == 'per_target'
                    and (page['id'] == page_id
                         or any(target['editionId'] == page_id for target in page['targets'].values()))
                    for page in baseline_v5['pages']),
            'Single-source release targets a mixed-source family; seal it per_target')
    page = next(item for item in merged_v4['pages'] if item['id'] == page_id)
    carried = {**copy.deepcopy(page), 'sourceMode': 'single_source'}
    result = copy.deepcopy(baseline_v5)
    result['generatedAt'] = merged_v4['generatedAt']
    index = next((i for i, item in enumerate(result['pages']) if item['id'] == page_id), None)
    if index is None:
        result['pages'].append(carried)
    else:
        result['pages'][index] = carried
    validate_catalog_schema(result)
    require(project_legacy_catalog_v4(result) == merged_v4,
            'Single-source release differs between v5 and its v4 projection')
    return result


def promote_page_to_per_target(page, incoming_targets=None):
    """Move a legacy page source onto each target before adding another source edition."""
    require(page.get('sourceMode') == 'single_source'
            and page.get('sourceIdentitySha256') and page.get('sourceMediaSha256'),
            'Single-source page lacks source identity for mixed-source promotion')
    video = page.get('videoDelivery')
    if incoming_targets is not None:
        require(all(locale in incoming_targets
                    and incoming_targets[locale].get('editionId') == page['id']
                    and incoming_targets[locale].get('sourceIdentitySha256') == page['sourceIdentitySha256']
                    and incoming_targets[locale].get('sourceMediaSha256') == page['sourceMediaSha256']
                    and video_matches_source(incoming_targets[locale].get('videoDelivery'),
                                             page['id'], page['sourceMediaSha256'])
                    for locale in page['targets']),
                'Incoming target cannot supply the legacy page video binding')
        incoming_videos = [incoming_targets[locale]['videoDelivery'] for locale in page['targets']]
        require(all(value == incoming_videos[0] for value in incoming_videos),
                'Existing locales disagree on promotion video delivery')
        if video is None:
            video = incoming_videos[0]
        else:
            require(all(value == video for value in incoming_videos),
                    'Existing page video delivery changed during promotion')
    require(video_matches_source(video, page['id'], page['sourceMediaSha256']),
            'Single-source page lacks source/video identity for mixed-source promotion')
    result = copy.deepcopy(page)
    for target in result['targets'].values():
        target.update(editionId=page['id'], sourceIdentitySha256=page['sourceIdentitySha256'],
                      sourceMediaSha256=page['sourceMediaSha256'],
                      videoDelivery=copy.deepcopy(video))
    result['sourceMode'] = 'per_target'
    for key in ('sourceIdentitySha256', 'sourceMediaSha256', 'videoDelivery'):
        result.pop(key, None)
    return result


def build_mixed_source_candidate(baseline, *, family_page_id, locale_editions, generated_at):
    """Build a one-page v5 overlay from already published single-source edition bytes."""
    value = upgrade_catalog_v5(baseline)
    pages = {page['id']: page for page in value['pages']}
    require(len(pages) == len(value['pages']) and family_page_id in pages,
            'Mixed-source family page is missing or duplicated')
    family = copy.deepcopy(pages[family_page_id])
    require(set(locale_editions) and set(locale_editions) <= {'zh-Hans', 'ko', 'es'},
            'Mixed-source locale editions are invalid')
    targets = {}
    for locale, edition_id in locale_editions.items():
        require(edition_id in pages and locale in pages[edition_id]['targets'],
                'Mixed-source edition target is missing')
        # A typo naming another week's edition would publish it under this family and
        # absorb (remove) its own archive page; only same-sermon editions qualify.
        require(pages[edition_id]['date'] == family['date'],
                'Mixed-source edition is from a different sermon date')
        edition = promote_page_to_per_target(pages[edition_id])
        target = edition['targets'][locale]
        require(target['editionId'] == edition_id, 'Mixed-source edition identity changed')
        targets[locale] = copy.deepcopy(target)
    family['sourceMode'] = 'per_target'
    family['targets'] = targets
    for key in ('sourceIdentitySha256', 'sourceMediaSha256', 'videoDelivery'):
        family.pop(key, None)
    if family['defaultTargetLocale'] not in targets:
        family['defaultTargetLocale'] = next((locale for locale in ('zh-Hans', 'ko', 'es') if locale in targets),
                                             sorted(targets)[0])
    candidate = {'schemaVersion': CATALOG_V5, 'generatedAt': generated_at,
                 'defaultPageId': family_page_id, 'pages': [family]}
    return validate_catalog_schema(candidate)


def validate_public_study(release, *, reader):
    """Validate public study bytes and all four immutable product identities.

    reader accepts a release-relative path and returns bytes, locally or over HTTP.
    Legacy v2 is not an implicit study approval.
    """
    validate_release_schema(release)
    require(release['schemaVersion'] in FOUR_PRODUCT_RELEASES, 'Four-product delivery requires release v3 or v4')
    products = release['fourProducts']
    source = release['sourceIdentity']
    require(0 <= source['window']['startSeconds'] < source['window']['endSeconds'] <= source['durationSeconds'], 'Public source window exceeds media')
    require(products['sourcePackageSha256'] == release['englishSourcePackageJsonSha256']
            and products['textCandidateSha256'] == release['targetLanguageCandidateJsonSha256']
            and products['audioPackageSha256'] == release['targetLanguageAudioPackageJsonSha256'], 'Public product identity differs')
    values = {}
    for role, filename in (('outline', 'outline'), ('meditation', 'meditation'), ('product_manifest', 'products')):
        rows = [row for row in release['assets'] if row['role'] == role]
        require(len(rows) == 1, 'Missing or duplicate public study asset: ' + role)
        row = rows[0]
        require(row['path'] == f"/study/{release['pageId']}/{release['targetLocale']}/{filename}.json", 'Public study path differs')
        payload = reader(row['path'])
        require(hashlib.sha256(payload).hexdigest() == row['sha256'], 'Public study bytes changed: ' + role)
        values[role] = json.loads(payload)
    manifest = values['product_manifest']
    require(manifest == {'schemaVersion': 'sermon-public-app-products-v1', 'pageId': release['pageId'],
                         'locale': release['targetLocale'], 'sourceIdentity': release['sourceIdentity'],
                         'fourProducts': products}, 'Public product manifest differs')
    from . import study_artifacts  # study_artifacts imports this module
    for kind in ('outline', 'meditation'):
        artifact = values[kind]
        study_artifacts.validate(artifact, 'sermon-study-artifact-v1.schema.json')
        require(artifact['kind'] == kind and artifact['pageId'] == release['pageId']
                and artifact['locale'] == release['targetLocale']
                and artifact['sourcePackageSha256'] == products['sourcePackageSha256']
                and artifact['textCandidateSha256'] == products['textCandidateSha256']
                and sha(artifact) == products[kind + 'ArtifactSha256'], 'Public study artifact identity differs')
    join = {'source': products['sourcePackageSha256'], 'products': {
        'text': products['textCandidateSha256'], 'audio': products['audioPackageSha256'],
        **{kind: {'status': 'human_reviewed', 'artifactSha256': products[kind + 'ArtifactSha256'],
                  'reviewSha256': products[kind + 'ReviewSha256']} for kind in ('outline', 'meditation')}}}
    require(products['candidateSha256'] == sha({'products': sha(join), 'metadataApproval': products['metadataApprovalSha256'],
                                               'contentSha256': products['contentSha256']}), 'Public App candidate hash differs')
    contents = [row for row in release['assets'] if row['role'] == 'content']
    require(len(contents) == 1 and contents[0]['sha256'] == products['contentSha256'], 'Public content hash differs')
    return values


def timestamp(value):
    require(isinstance(value, str), 'Missing evidence time')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Evidence time must include timezone')
    return parsed


def validate_intent(intent, routes):
    require(intent.get('schemaVersion') == 'sermon-release-intent-v1', 'Unsupported release intent')
    route = routes.get(intent.get('environment'))
    require(isinstance(route, dict), 'Unknown environment')
    channels = route.get('channels', [route.get('channel')])
    require(intent.get('channel') in channels, 'Release route mismatch: channel')
    for key in ('project', 'site', 'origin'):
        require(bool(route.get(key)) and intent.get(key) == route[key], 'Release route mismatch: ' + key)
    require(intent['origin'] == 'https://' + intent['site'] + '.web.app', 'Origin/site mismatch')
    require(intent.get('environment') in ('dev', 'production'), 'Unsupported environment')
    return intent


def validate_metadata(fields, *, measured_duration=None):
    for key in ('title', 'series', 'speaker', 'scripture'):
        value = fields.get(key)
        require(isinstance(value, str) and bool(value.strip()), 'Missing metadata: ' + key)
        require(not re.search(r'待补|待定|见全文|placeholder|\btbd\b|\bunknown\b', value, re.I), 'Placeholder metadata: ' + key)
    if measured_duration is not None:
        duration = fields.get('durationSeconds')
        require(isinstance(duration, (int, float)) and not isinstance(duration, bool)
                and abs(duration - measured_duration) <= 1, 'Displayed duration differs from media')


def merge_catalog(baseline, candidate, plan, *, anchor=None):
    """CAS-bound locale overlay; unchanged pages/targets survive byte-for-byte as objects.

    A plan is frozen against the live v3 catalog. When merging into a v4 baseline,
    ``anchor`` is that v3 catalog, which must be the baseline's human-only projection.
    """
    require(plan.get('schemaVersion') == 'sermon-locale-release-plan-v1', 'Unsupported locale plan')
    if anchor is not None:
        require(baseline.get('schemaVersion') == CATALOG_V4 and project_human_catalog(baseline) == anchor,
                'v4 baseline differs from its v3 projection')
    baseline_key = 'baselineCatalogV5Sha256' if baseline.get('schemaVersion') == CATALOG_V5 else 'baselineCatalogSha256'
    require(plan.get(baseline_key) == sha(baseline if anchor is None else anchor), 'Baseline changed; rebuild release')
    require(plan.get('baselineVersion'), 'Live baseline version required')
    require(baseline.get('schemaVersion') == candidate.get('schemaVersion') in CATALOG_FILES, 'Catalog schema mismatch')
    page_id = plan.get('pageId')
    require(len(candidate['pages']) == 1 and candidate['pages'][0]['id'] == page_id, 'Candidate must contain only planned page')
    incoming = candidate['pages'][0]
    locales = set(plan.get('locales', []))
    require(locales and len(locales) == len(plan['locales']) and locales == set(incoming['targets']), 'Locale plan mismatch')
    required = set(plan.get('requiredLocales', []))
    require(required and locales <= required, 'Missing or invalid release join requirement')
    require(plan.get('mode') in ('incremental', 'joined'), 'Unknown release mode')
    result = copy.deepcopy(baseline)
    require(len({p['id'] for p in result['pages']}) == len(result['pages']), 'Duplicate baseline page')
    previous = next((p for p in result['pages'] if p['id'] == page_id), None)
    promotion = False
    if previous:
        previous_index = result['pages'].index(previous)
        if baseline['schemaVersion'] != CATALOG_V5:
            require(previous['sourceIdentitySha256'] == incoming['sourceIdentitySha256'], 'Source changed; sibling targets must be rebuilt')
        else:
            if previous['sourceMode'] != incoming['sourceMode']:
                require(previous['sourceMode'] == 'single_source' and incoming['sourceMode'] == 'per_target',
                        'Page source mode changed')
                require(set(previous['targets']) <= locales,
                        'Mixed-source promotion must replace every existing target')
                require(all(locale in incoming['targets']
                            and incoming['targets'][locale].get('editionId') == previous['id']
                            and incoming['targets'][locale].get('sourceIdentitySha256') == previous['sourceIdentitySha256']
                            and incoming['targets'][locale].get('sourceMediaSha256') == previous['sourceMediaSha256']
                            for locale in previous['targets']),
                        'Mixed-source promotion changed an existing target source')
                promoted = promote_page_to_per_target(previous, incoming['targets'])
                require(all(all(incoming['targets'][locale].get(key) == promoted['targets'][locale][key]
                                    for key in ('editionId', 'sourceIdentitySha256', 'sourceMediaSha256'))
                            for locale in previous['targets']),
                        'Mixed-source promotion changed an existing target source')
                previous = promoted
                promotion = True
            require(previous['sourceMode'] == incoming['sourceMode'], 'Page source mode changed')
        require(all(previous.get(k) == incoming.get(k) for k in ('date', 'sourceLocale')), 'Page identity changed')
        if promotion:
            # Full promotion replaces every target, so the incoming family also owns
            # the shared presentation (title, default locale, category, and so on).
            merged = copy.deepcopy(incoming)
        else:
            if baseline['schemaVersion'] == CATALOG_V5 and previous['sourceMode'] == 'per_target':
                previous_shared = {key: value for key, value in previous.items() if key != 'targets'}
                incoming_shared = {key: value for key, value in incoming.items() if key != 'targets'}
                require(previous_shared == incoming_shared,
                        'Shared page presentation changed during incremental target merge')
            merged = copy.deepcopy(previous)
            merged['targets'].update(copy.deepcopy(incoming['targets']))
        result['pages'][previous_index] = merged
        if promotion:
            editions = {target['editionId'] for target in incoming['targets'].values()}
            absorbed = []
            for sibling in result['pages']:
                if sibling['id'] == page_id or sibling['id'] not in editions:
                    continue
                promoted_sibling = promote_page_to_per_target(sibling, incoming['targets'])
                require(set(sibling['targets']) <= locales
                        and all(locale in incoming['targets']
                                and incoming['targets'][locale] == promoted_sibling['targets'][locale]
                                for locale in sibling['targets']),
                        'Mixed-source edition absorption differs from existing target')
                absorbed.append(sibling)
            result['pages'] = [page for page in result['pages'] if page not in absorbed]
            result['defaultPageId'] = candidate['defaultPageId']
    else:
        result['pages'].append(copy.deepcopy(incoming))
        merged = result['pages'][-1]
    if plan['mode'] == 'joined':
        require(required <= set(merged['targets']), 'Release join incomplete')
    result['generatedAt'] = candidate['generatedAt']
    return result


def rollback_locale(current, previous, *, page_id, locale, expected_current_sha):
    require(sha(current) == expected_current_sha, 'Rollback baseline changed')
    result = copy.deepcopy(current)
    page = next(p for p in result['pages'] if p['id'] == page_id)
    old_page = next((p for p in previous['pages'] if p['id'] == page_id), None)
    old = old_page.get('targets', {}).get(locale) if old_page else None
    if old:
        if current['schemaVersion'] == CATALOG_V5:
            # A single-source target has no per-target binding to carry into a
            # per_target page (or back); undo a promotion as a whole page instead.
            require(old_page.get('sourceMode', 'single_source') == page['sourceMode'],
                    'Rollback crosses a source-mode promotion; restore the whole page')
        if page.get('sourceMode', 'single_source') == 'single_source':
            require(old_page['sourceIdentitySha256'] == page['sourceIdentitySha256'], 'Rollback source differs')
        page['targets'][locale] = copy.deepcopy(old)
    else:
        page['targets'].pop(locale, None)
    require(bool(page['targets']), 'Rollback would leave an empty page')
    if page['defaultTargetLocale'] not in page['targets']:
        page['defaultTargetLocale'] = sorted(page['targets'])[0]
    return result


def new_attempt(intent, *, catalog_sha, assets_sha, baseline_version):
    require(baseline_version, 'Baseline live version required')
    return {'schemaVersion': 'sermon-deployment-attempt-v2', 'attemptId': str(uuid4()),
            'intent': copy.deepcopy(intent), 'catalogSha256': catalog_sha, 'assetsSha256': assets_sha,
            'baselineVersion': baseline_version, 'newVersion': None,
            'startedAt': datetime.now(timezone.utc).isoformat(), 'completedAt': None,
            'status': 'prepared'}


def verify_attempt(attempt, http, *, intent, catalog_sha, assets_sha):
    require(attempt.get('schemaVersion') == 'sermon-deployment-attempt-v2', 'Legacy deployment cannot be promoted')
    require(attempt.get('status') == 'deployed' and attempt.get('newVersion') and attempt.get('baselineVersion'), 'Deployment outcome unverified')
    require(attempt.get('intent') == intent and attempt.get('catalogSha256') == catalog_sha
            and attempt.get('assetsSha256') == assets_sha, 'Deployment identity differs')
    require(timestamp(attempt['completedAt']) >= timestamp(attempt['startedAt']), 'Invalid deployment chronology')
    require(http.get('passed') is True and not http.get('failures'), 'HTTP verification failed')
    require(http.get('attemptId') == attempt['attemptId'] and http.get('deploymentSha256') == sha(attempt)
            and http.get('origin') == intent['origin'] and http.get('catalogSha256') == catalog_sha
            and http.get('assetsSha256') == assets_sha, 'Old or mismatched HTTP evidence')
    require(timestamp(http['startedAt']) >= timestamp(attempt['completedAt'])
            and timestamp(http['completedAt']) >= timestamp(http['startedAt']), 'HTTP evidence predates deployment')
    return {'publication': 'published_http_verified', 'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run'}


def playback_acceptance(receipts, *, candidate_sha, locales, channels=('beta', 'dev', 'production_ios', 'production_web')):
    required = {(channel, locale) for channel in channels for locale in locales}
    passed = set()
    for row in receipts:
        key = (row.get('channel'), row.get('locale'))
        require(key in required and key not in passed, 'Unexpected or duplicate playback evidence')
        require(row.get('candidateSha256') == candidate_sha, 'Playback evidence is stale')
        require(row.get('humanApproval') is True and row.get('reviewedBy'), 'Playback requires human evidence')
        timestamp(row.get('reviewedAt'))
        checks = row.get('checks', {})
        require(all(checks.get(k) == 'pass' for k in ('actualPlayback', 'captions', 'sourceVideoMuted', 'synchronizationAt1x')), 'Media ready is not playback acceptance')
        passed.add(key)
    return {'status': 'pass' if passed == required else 'partial', 'missing': sorted(required - passed), 'deviceAcceptance': 'separate', 'venueAcceptance': 'not_run'}


def validate_readback(receipt, *, expected_intent, candidate_sha, reader):
    """Re-fetch exact catalog/content/asset URLs; reader returns HTTP status and bytes."""
    from jsonschema import Draft202012Validator, FormatChecker
    version = receipt.get('schemaVersion')
    require(version in ('sermon-client-readback-v1', 'sermon-client-readback-v2'), 'Unsupported client readback version')
    schema = json.loads(_delivery.current().schemas.path(version + '.schema.json').read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)
    require(receipt['intent'] == expected_intent and receipt['candidateSha256'] == candidate_sha, 'Readback identity differs')
    observed = []
    for row in receipt['resources']:
        require(row['url'].startswith(expected_intent['origin'] + '/'), 'Readback resource outside target origin')
        status, data = reader(row['url'])
        require(status == 200 and isinstance(data, bytes), 'Readback HTTP failure')
        require(hashlib.sha256(data).hexdigest() == row['sha256'], 'Readback bytes changed')
        observed.append(row['role'])
    require({'catalog', 'content', 'release'} <= set(observed), 'Incomplete client readback')
    return {'status': 'pass', 'readbackSha256': sha(receipt), 'candidateSha256': candidate_sha}


def verify_client_acceptance(receipt, *, expected_intent, candidate_sha, reader, evidence_root, study_requirements=None):
    """Validate actual playback telemetry plus independent human signoff and fresh readback.

    Native device and venue acceptance remain explicit separate fields. Browser
    telemetry cannot promote those fields.
    """
    readback = validate_readback(receipt['readback'], expected_intent=expected_intent,
                                 candidate_sha=candidate_sha, reader=reader)
    rows = receipt.get('playback', [])
    require(rows, 'Playback evidence missing')
    root = Path(evidence_root).resolve()
    for row in rows:
        require(row.get('candidateSha256') == candidate_sha, 'Playback candidate changed')
        path = (root / row['evidencePath']).resolve()
        require(path.is_relative_to(root) and path.is_file(), 'Playback evidence outside evidence root')
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == row.get('evidenceSha256'), 'Playback evidence hash differs')
        telemetry = json.loads(data)
        require(telemetry.get('schemaVersion') == 'sermon-playback-observation-v1'
                and telemetry.get('candidateSha256') == candidate_sha
                and telemetry.get('locale') == row.get('locale')
                and telemetry.get('origin') == expected_intent['origin'], 'Playback telemetry identity differs')
        require(telemetry.get('runner') in ('browser', 'ios_device'), 'Unknown playback runner')
        if expected_intent['channel'] in ('beta', 'production_ios'):
            require(telemetry.get('runner') == 'ios_device' and telemetry.get('deviceId') and telemetry.get('appBuild'), 'Native endpoint requires physical device playback evidence')
        require(telemetry.get('paused') is False and telemetry.get('ended') is False
                and telemetry.get('currentTimeEnd', 0) - telemetry.get('currentTimeStart', 0) >= 2,
                'Playback did not advance')
        require(telemetry.get('playbackRate') == 1 and telemetry.get('sourceVideoMuted') is True
                and telemetry.get('captionText') and telemetry.get('captionLocale') == row.get('locale'), 'Playback/caption controls failed')
        require(isinstance(telemetry.get('syncErrorSeconds'), (int, float))
                and abs(telemetry['syncErrorSeconds']) <= 8, 'Playback synchronization exceeds policy')
        if study_requirements is not None:
            expected_study = study_requirements.get(row.get('locale'))
            require(expected_study and telemetry.get('studyArtifacts') == expected_study
                    and telemetry.get('studyDisplayed') is True
                    and all(row.get('checks', {}).get(kind) == 'pass' for kind in ('outline', 'meditation')),
                    'Endpoint did not display both current approved study artifacts')
    accepted = playback_acceptance(rows, candidate_sha=candidate_sha,
                                   locales=receipt['locales'], channels=(expected_intent['channel'],))
    return {**accepted, 'readback': readback}


def snapshot_catalog_v4(snapshot):
    """The snapshot's v4 catalog, or its v3 catalog upgraded when v4 was never published."""
    public = Path(snapshot) / 'public'
    path = public / CATALOG_FILES[CATALOG_V4]
    if path.exists():
        return json.loads(path.read_text())
    return upgrade_catalog(json.loads((public / CATALOG_FILES[CATALOG_V3]).read_text()))


def snapshot_catalog_v5(snapshot):
    """Return v5 when present; otherwise callers continue through the v4 compatibility view."""
    public = Path(snapshot) / 'public'
    path = public / CATALOG_FILES[CATALOG_V5]
    return json.loads(path.read_text()) if path.exists() else upgrade_catalog_v5(snapshot_catalog_v4(snapshot))


def validate_catalog_snapshot(snapshot):
    """Validate a complete immutable local Hosting snapshot before an overlay.

    Returns the v3 catalog. When the snapshot also has a v4 catalog, the v3 file
    must be exactly its human-only projection, and every v4 target is checked too.
    """
    root = Path(snapshot)
    public = (root / 'public').resolve()
    report = json.loads((root / 'seal-report.json').read_text())
    catalog_path = public / 'multilingual-v3.json'
    catalog = json.loads(catalog_path.read_text())
    file_sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    require(report['catalogSha256'] == file_sha(catalog_path), 'Baseline catalog differs')
    v4_path = public / CATALOG_FILES[CATALOG_V4]
    v5_path = public / CATALOG_FILES[CATALOG_V5]
    catalogs = [catalog]
    if v4_path.exists() or report.get('catalogV4Sha256') is not None:
        require(v4_path.is_file() and report.get('catalogV4Sha256') == file_sha(v4_path), 'Baseline v4 catalog differs')
        v4 = validate_catalog_schema(json.loads(v4_path.read_text()))
        require(project_human_catalog(v4) == catalog, 'Baseline v3 catalog is not the human-only projection of v4')
        catalogs.append(v4)
    if v5_path.exists() or report.get('catalogV5Sha256') is not None:
        require(v5_path.is_file() and report.get('catalogV5Sha256') == file_sha(v5_path), 'Baseline v5 catalog differs')
        v5 = validate_catalog_schema(json.loads(v5_path.read_text()))
        require(project_legacy_catalog_v4(v5) == catalogs[-1], 'Baseline v4 is not the edition projection of v5')
        catalogs.append(v5)
    files = {row['path'].lstrip('/'): row for row in report['files']}
    require(len(files) == len(report['files']), 'Duplicate baseline asset')
    actual = {str(path.relative_to(public)) for path in public.rglob('*') if path.is_file()}
    require(actual == set(files), 'Baseline snapshot is incomplete')
    for name, row in files.items():
        path = public / name
        require(not path.is_symlink() and path.resolve().is_relative_to(public), 'Unsafe baseline path')
        require(file_sha(path) == row['sha256'] and path.stat().st_size == row['bytes'], 'Baseline asset differs')
    for page in (page for value in catalogs for page in value['pages']):
        for locale, target in page['targets'].items():
            name = target['releasePackageUrl'].lstrip('/')
            require(name in files and files[name]['sha256'] == target['releasePackageJsonSha256'], 'Missing baseline release')
            release = json.loads((public / name).read_text())
            if release.get('schemaVersion') in FOUR_PRODUCT_RELEASES:
                validate_release_target(release, page, locale)
                require(release['targetLocale'] == locale and target['releasePackageUrl'] == release_path(release)
                        and (release['contentStatus'], release['audioStatus']) == (target['contentStatus'], target['audioStatus']),
                        'Baseline release locale/status differs from its catalog target')
                validate_public_study(release, reader=lambda url: (public / url.lstrip('/')).read_bytes())
            elif page.get('sourceMode') == 'per_target':
                validate_v2_release_target(release, page, locale)
                content_rows = [asset for asset in release['assets'] if asset['role'] == 'content']
                require(len(content_rows) == 1, 'Mixed-source release needs one content asset')
                validate_content_target(json.loads((public / content_rows[0]['path'].lstrip('/')).read_text()),
                                        page, locale)
            for asset in release['assets']:
                name = asset['path'].lstrip('/')
                require(name in files and files[name]['sha256'] == asset['sha256'], 'Missing baseline release asset')
    return catalog

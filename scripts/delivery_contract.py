"""Version-bound delivery planning and evidence validation (no network or approval synthesis)."""
from __future__ import annotations
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


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
CATALOG_FILES = {CATALOG_V3: 'multilingual-v3.json', CATALOG_V4: 'multilingual-v4.json'}
MACHINE_CHECKED = 'machine_checked'


def _schema(version):
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas' / (version + '.schema.json')).read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def machine_checked(entry):
    """A release or catalog target admitted by a machine quality waiver (never a human approval)."""
    return MACHINE_CHECKED in (entry.get('contentStatus'), entry.get('audioStatus'))


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
            require(target['releasePackageUrl'] == f"/{directory}/{page['id']}/{locale}.json", 'Catalog release path differs from page/locale')
    return catalog


def upgrade_catalog(catalog):
    """A v3 catalog is a valid v4 catalog with only human-reviewed targets."""
    if catalog.get('schemaVersion') == CATALOG_V4:
        return copy.deepcopy(catalog)
    require(catalog.get('schemaVersion') == CATALOG_V3, 'Unsupported catalog version')
    return {**copy.deepcopy(catalog), 'schemaVersion': CATALOG_V4}


def project_human_catalog(catalog):
    """The v3 catalog old clients read: every machine-checked target removed.

    Pages left without targets disappear; a removed default moves to a remaining
    locale or to the latest remaining page. Nothing else changes.
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
        result['defaultPageId'] = max(pages, key=lambda page: page['date'])['id']
    result['pages'] = pages
    return result


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
    from scripts import study_artifacts
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
    require(plan.get('baselineCatalogSha256') == sha(baseline if anchor is None else anchor), 'Baseline changed; rebuild release')
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
    if previous:
        require(previous['sourceIdentitySha256'] == incoming['sourceIdentitySha256'], 'Source changed; sibling targets must be rebuilt')
        merged = copy.deepcopy(previous)
        merged['targets'].update(copy.deepcopy(incoming['targets']))
        # Shared page fields cannot silently change while preserving other locales.
        require(all(previous.get(k) == incoming.get(k) for k in ('date', 'sourceLocale')), 'Page identity changed')
        result['pages'][result['pages'].index(previous)] = merged
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
    schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas' / (version + '.schema.json')).read_text())
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
    catalogs = [catalog]
    if v4_path.exists() or report.get('catalogV4Sha256') is not None:
        require(v4_path.is_file() and report.get('catalogV4Sha256') == file_sha(v4_path), 'Baseline v4 catalog differs')
        v4 = validate_catalog_schema(json.loads(v4_path.read_text()))
        require(project_human_catalog(v4) == catalog, 'Baseline v3 catalog is not the human-only projection of v4')
        catalogs.append(v4)
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
                require(release['pageId'] == page['id'] and release['englishSourcePackageJsonSha256'] == page['sourceIdentitySha256'],
                        'Baseline release source/page differs')
                require(release['targetLocale'] == locale and target['releasePackageUrl'] == release_path(release)
                        and (release['contentStatus'], release['audioStatus']) == (target['contentStatus'], target['audioStatus']),
                        'Baseline release locale/status differs from its catalog target')
                validate_public_study(release, reader=lambda url: (public / url.lstrip('/')).read_bytes())
            for asset in release['assets']:
                name = asset['path'].lstrip('/')
                require(name in files and files[name]['sha256'] == asset['sha256'], 'Missing baseline release asset')
    return catalog

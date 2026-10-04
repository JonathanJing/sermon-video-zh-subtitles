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


def merge_catalog(baseline, candidate, plan):
    """CAS-bound locale overlay; unchanged pages/targets survive byte-for-byte as objects."""
    require(plan.get('schemaVersion') == 'sermon-locale-release-plan-v1', 'Unsupported locale plan')
    require(plan.get('baselineCatalogSha256') == sha(baseline), 'Baseline changed; rebuild release')
    require(plan.get('baselineVersion'), 'Live baseline version required')
    require(baseline.get('schemaVersion') == candidate.get('schemaVersion') == 'sermon-multilingual-catalog-v3', 'Catalog schema mismatch')
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
    schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas/sermon-client-readback-v1.schema.json').read_text())
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


def verify_client_acceptance(receipt, *, expected_intent, candidate_sha, reader, evidence_root):
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
    accepted = playback_acceptance(rows, candidate_sha=candidate_sha,
                                   locales=receipt['locales'], channels=(expected_intent['channel'],))
    return {**accepted, 'readback': readback}


def validate_catalog_snapshot(snapshot):
    """Validate a complete immutable local Hosting snapshot before an overlay."""
    root = Path(snapshot)
    public = (root / 'public').resolve()
    report = json.loads((root / 'seal-report.json').read_text())
    catalog_path = public / 'multilingual-v3.json'
    catalog = json.loads(catalog_path.read_text())
    file_sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    require(report['catalogSha256'] == file_sha(catalog_path), 'Baseline catalog differs')
    files = {row['path'].lstrip('/'): row for row in report['files']}
    require(len(files) == len(report['files']), 'Duplicate baseline asset')
    actual = {str(path.relative_to(public)) for path in public.rglob('*') if path.is_file()}
    require(actual == set(files), 'Baseline snapshot is incomplete')
    for name, row in files.items():
        path = public / name
        require(not path.is_symlink() and path.resolve().is_relative_to(public), 'Unsafe baseline path')
        require(file_sha(path) == row['sha256'] and path.stat().st_size == row['bytes'], 'Baseline asset differs')
    for page in catalog['pages']:
        for target in page['targets'].values():
            name = target['releasePackageUrl'].lstrip('/')
            require(name in files and files[name]['sha256'] == target['releasePackageJsonSha256'], 'Missing baseline release')
            release = json.loads((public / name).read_text())
            for asset in release['assets']:
                name = asset['path'].lstrip('/')
                require(name in files and files[name]['sha256'] == asset['sha256'], 'Missing baseline release asset')
    return catalog

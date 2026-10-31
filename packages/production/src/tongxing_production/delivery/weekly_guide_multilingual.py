"""Prepare private Korean/Spanish guide staging and guarded v2 fragments.

Inputs and outputs contain licensed text: keep them in ignored artifacts. This
module never uploads or deploys. It does not translate or approve content.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
from contextlib import contextmanager

from tongxing_production.delivery import weekly_guide_staging as v1

SOURCE_SHA256 = '3eb6cca50c898c8fcb82be73bcdce67deaad64267ad7041581e363aa39757708'
LOCALES = ('ko', 'es')
REVIEW = 'machine_translation_not_human_reviewed'
WEEK_PAGES = {1:(26,39,[164]), 2:(40,49,[165]), 3:(50,63,[166]), 4:(64,77,[167]),
              5:(78,85,[168]), 6:(86,95,[169]), 7:(96,107,[170]), 8:(108,117,[171]),
              9:(118,129,[172]), 10:(130,143,[173]), 11:(144,153,[174,175]), 12:(154,161,[176])}
# Exact source scripture pages, including the intentional 8:1 overlap in
# weeks 4 and 5. Display strings are generated from these reviewed boundaries.
SCRIPTURE_RANGES = {1:'1:1–20', 2:'2:1–3:22', 3:'4:1–5:14', 4:'6:1–8:1',
                    5:'8:1–9:21', 6:'10:1–11:19', 7:'12:1–13:18', 8:'14:1–20',
                    9:'15:1–16:21', 10:'17:1–19:10', 11:'19:11–21:8', 12:'21:9–22:21'}
BOOK_NAMES = {'ko': '요한계시록', 'es': 'Apocalipsis'}
ENGLISH_PAGE = re.compile(r'^=== PAGE (\d+) \(pdf page (\d+), id ([^)]+)\) ===\n(.*?)(?=^=== PAGE \d+ \(pdf page|\Z)', re.S | re.M)
# Known internal extraction marker, not a general content-quality check.
INTERNAL_PLACEHOLDERS = ('[Original graphic/table requires visual review]',)


def _hash(value):
    return isinstance(value, str) and bool(v1.HEX.fullmatch(value))


def scripture_for_week(week, locale):
    if locale not in BOOK_NAMES or week not in SCRIPTURE_RANGES:
        raise ValueError('unsupported scripture week or locale')
    return f'{BOOK_NAMES[locale]} {SCRIPTURE_RANGES[week]}'


def _guide(guide, locale, translation_sha, source_pages=None):
    if not isinstance(guide, dict) or set(guide) != {'week', 'title', 'scripture', 'sections'}:
        raise ValueError('invalid draft guide fields')
    week = guide['week']
    if not isinstance(week, int) or isinstance(week, bool) or not 1 <= week <= 12:
        raise ValueError('invalid week')
    if any(not isinstance(guide[k], str) or not guide[k].strip() for k in ('title', 'scripture')):
        raise ValueError('empty guide title or scripture')
    if any(marker.casefold() in guide[k].casefold()
           for marker in INTERNAL_PLACEHOLDERS for k in ('title', 'scripture')):
        raise ValueError('internal guide placeholder cannot be published')
    if guide['scripture'] != scripture_for_week(week, locale):
        raise ValueError('scripture does not match fixed weekly source range')
    sections = guide['sections']
    if not isinstance(sections, list) or not sections:
        raise ValueError('guide sections required')
    ids = set()
    for s in sections:
        fields = {'id', 'title', 'subtitle', 'symbol', 'body'}
        if source_pages is not None:
            fields |= {'sourcePage', 'sourcePageID', 'sourcePageSHA256'}
        if (not isinstance(s, dict) or set(s) != fields
            or any(not isinstance(s[k], str) for k in ('id', 'title', 'subtitle', 'symbol', 'body'))
            or not s['id'].strip() or not s['title'].strip() or not s['body'].strip()
            or s['id'] in ids):
            raise ValueError('invalid or duplicate guide section')
        if any(marker.casefold() in s[k].casefold()
               for marker in INTERNAL_PLACEHOLDERS for k in ('title', 'subtitle', 'body')):
            raise ValueError('internal guide placeholder cannot be published')
        ids.add(s['id'])
    if source_pages is not None:
        start, end, appendix = WEEK_PAGES[week]
        expected = list(range(start, end + 1)) + appendix
        if [s['sourcePage'] for s in sections] != expected:
            raise ValueError('guide source pages missing, duplicated, out of order, or wrong week')
        for section in sections:
            ident, sha = source_pages[section['sourcePage']]
            if section['sourcePageID'] != ident or section['sourcePageSHA256'] != sha:
                raise ValueError('guide source page identity mismatch')
    return {'schemaVersion': 'tongxing-weekly-guide-staging-v2', 'seriesID': v1.SERIES_ID,
            'sermonPageId': None, 'locale': locale, **guide, 'review': REVIEW,
            'humanApproval': False, 'sourceSHA256': SOURCE_SHA256, 'translationSHA256': translation_sha}


def _source_pages(source):
    pages = {}
    for number, pdf, ident, body in ENGLISH_PAGE.findall(source.decode('utf-8')):
        n = int(number)
        if n in pages or int(pdf) != n - 1:
            raise ValueError('duplicate or invalid English source page')
        pages[n] = (ident, v1.digest(body.strip().encode('utf-8')))
    if sorted(pages) != list(range(1, 181)):
        raise ValueError('incomplete English source pages')
    return pages


def staged_guides(source, draft, reviews, review_records):
    if v1.digest(source) != SOURCE_SHA256:
        raise ValueError('English source hash mismatch')
    data = json.loads(draft)
    if not isinstance(data, dict) or data.get('schemaVersion') != 'tongxing-weekly-guide-translation-draft-v3':
        raise ValueError('invalid translation draft schema')
    locale = data.get('locale')
    guides = data.get('guides')
    if locale not in LOCALES or not isinstance(guides, list) or not guides:
        raise ValueError('invalid draft locale or guides')
    sha = v1.digest(draft)
    source_pages = _source_pages(source)
    result = [_guide(g, locale, sha, source_pages) for g in guides]
    if len({g['week'] for g in result}) != len(result):
        raise ValueError('duplicate week in draft')
    receipt = json.loads(reviews)
    records = receipt.get('reviews') if isinstance(receipt, dict) else None
    if receipt.get('schemaVersion') != 'tongxing-weekly-guide-reviews-v1' or not isinstance(records, list) or len(records) != len(guides):
        raise ValueError('review evidence coverage mismatch')
    indexed = {}
    for record in records:
        if not isinstance(record, dict) or record.get('week') in indexed:
            raise ValueError('duplicate or invalid review evidence')
        indexed[record['week']] = record
    root = Path(review_records).resolve()
    for guide in guides:
        record = indexed.get(guide['week'])
        required = {'week', 'locale', 'sourceSHA256', 'translationSHA256', 'guideSHA256', 'method', 'decision', 'humanApproval', 'reviewer', 'reviewRecordSHA256'}
        if (not isinstance(record, dict) or set(record) != required or record['locale'] != locale
            or record['sourceSHA256'] != SOURCE_SHA256 or record['translationSHA256'] != sha
            or record['guideSHA256'] != v1.digest(v1.encoded(guide)) or record['method'] != 'machine'
            or record['decision'] != 'pass' or record['humanApproval'] is not False
            or not isinstance(record['reviewer'], str) or not record['reviewer'].strip() or not _hash(record['reviewRecordSHA256'])):
            raise ValueError('review evidence does not bind this week, locale, source and translation')
        review_raw = v1._safe_asset(root, '/' + record['reviewRecordSHA256'] + '.json').read_bytes()
        if v1.digest(review_raw) != record['reviewRecordSHA256']:
            raise ValueError('review record hash mismatch')
        review_doc = json.loads(review_raw)
        expected_review = {k: record[k] for k in required - {'reviewRecordSHA256'}}
        if (not isinstance(review_doc, dict) or review_doc.get('schemaVersion') != 'tongxing-weekly-guide-machine-review-v1'
            or any(review_doc.get(k) != value for k, value in expected_review.items())
            or not isinstance(review_doc.get('limitations'), list) or not review_doc['limitations']
            or any(not isinstance(x, str) or not x.strip() for x in review_doc['limitations'])):
            raise ValueError('independent review record identity mismatch')
    return result


def prepare_stage(source, draft, reviews, review_records, out):
    guides = staged_guides(source, draft, reviews, review_records)
    files = []
    for g in guides:
        raw = v1.encoded(g)
        if len(raw) > v1.GUIDE_LIMIT:
            raise ValueError('staged guide too large')
        files.append((g, raw))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    entries = []
    for g, raw in files:
        name = f"{g['locale']}-week-{g['week']:02d}.json"
        (out / name).write_bytes(raw)
        entries.append({'locale': g['locale'], 'week': g['week'], 'sermonPageId': None,
                        'file': name, 'sha256': v1.digest(raw), 'bytes': len(raw)})
    manifest = {'schemaVersion': 'tongxing-weekly-guide-staging-manifest-v2', 'seriesID': v1.SERIES_ID,
                'sourceSHA256': SOURCE_SHA256, 'translationSHA256': guides[0]['translationSHA256'],
                'locale': guides[0]['locale'], 'review': REVIEW, 'humanApproval': False,
                'reviewEvidenceSHA256': v1.digest(reviews), 'entries': entries}
    (out / 'staging-manifest-v2.json').write_bytes(v1.encoded(manifest))
    return manifest


def _staged(staging, source, draft, reviews, review_records):
    expected = {g['week']: v1.encoded(g) for g in staged_guides(source, draft, reviews, review_records)}
    staging = Path(staging).resolve()
    manifest = json.loads(v1._safe_asset(staging, '/staging-manifest-v2.json').read_bytes())
    sample = json.loads(next(iter(expected.values())))
    if (manifest.get('schemaVersion') != 'tongxing-weekly-guide-staging-manifest-v2'
        or manifest.get('seriesID') != v1.SERIES_ID or manifest.get('sourceSHA256') != SOURCE_SHA256
        or manifest.get('translationSHA256') != v1.digest(draft) or manifest.get('locale') != sample['locale']
        or manifest.get('reviewEvidenceSHA256') != v1.digest(reviews)
        or manifest.get('review') != REVIEW or manifest.get('humanApproval') is not False):
        raise ValueError('staging provenance mismatch')
    entries = manifest.get('entries')
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ValueError('staging entries mismatch')
    result = {}
    for e in entries:
        week = e.get('week')
        if week in result or week not in expected or e.get('locale') != sample['locale'] or e.get('sermonPageId') is not None:
            raise ValueError('staging identity mismatch')
        if e.get('file') != f"{sample['locale']}-week-{week:02d}.json":
            raise ValueError('invalid staging filename')
        raw = v1._safe_asset(staging, '/' + e['file']).read_bytes()
        if len(raw) != e.get('bytes') or v1.digest(raw) != e.get('sha256') or raw != expected[week]:
            raise ValueError('staged content differs from draft')
        result[week] = json.loads(raw)
    return result


def _target(catalog, page_id, locale, verify_file):
    from tongxing_production.delivery import contract
    pages = [p for p in catalog.get('pages', []) if p.get('id') == page_id]
    if len(pages) != 1:
        raise ValueError('page not unique in catalog')
    p = pages[0]
    target = p.get('targets', {}).get(locale)
    if (any(p.get(k) is True for k in ('simulationOnly', 'diagnosticOnly', 'revoked', 'withdrawn'))
        or p.get('status') in ('revoked', 'withdrawn') or not isinstance(target, dict)
        or target.get('contentStatus') not in ('human_reviewed', 'machine_checked')
        or any(target.get(k) is True for k in ('simulationOnly', 'diagnosticOnly', 'revoked', 'withdrawn'))
        or target.get('status') in ('revoked', 'withdrawn')):
        raise ValueError('published locale target required')
    edition = target.get('editionId', page_id)
    identity = target.get('sourceIdentitySha256') if p.get('sourceMode') == 'per_target' else p.get('sourceIdentitySha256')
    media = target.get('sourceMediaSha256') if p.get('sourceMode') == 'per_target' else p.get('sourceMediaSha256')
    release_sha = target.get('releasePackageJsonSha256')
    if not isinstance(edition, str) or not v1.PAGE_ID.fullmatch(edition) or not all(_hash(x) for x in (identity, media, release_sha)):
        raise ValueError('incomplete target identity')
    raw = verify_file(target.get('releasePackageUrl'))
    if v1.digest(raw) != release_sha:
        raise ValueError('release hash mismatch')
    release = json.loads(raw)
    if release.get('pageId') != edition or release.get('targetLocale') != locale:
        raise ValueError('release locale identity mismatch')
    schema = release.get('schemaVersion')
    if (release.get('status') != 'published_http_verified' or release.get('httpVerification', {}).get('status') != 'pass'
        or release.get('contentStatus') != target.get('contentStatus') or release.get('audioStatus') != target.get('audioStatus')
        or release.get('issues') != []):
        raise ValueError('release publication, HTTP evidence or target status mismatch')
    ridentity = release.get('englishSourcePackageJsonSha256')
    if schema == 'sermon-target-language-release-package-v2':
        contract.validate_v2_release_target(release, p, locale)
        if ridentity is not None and ridentity != identity:
            raise ValueError('release source mismatch')
    elif schema in ('sermon-target-language-release-package-v3', 'sermon-target-language-release-package-v4'):
        contract.validate_release_target(release, p, locale)
        contract.validate_public_study(release, reader=verify_file)
        if target.get('releasePackageUrl') != contract.release_path(release):
            raise ValueError('release path does not match target')
        if ridentity != identity:
            raise ValueError('release source mismatch')
    else:
        raise ValueError('unsupported release schema')
    release_source = release.get('sourceIdentity')
    if release_source is not None and (not isinstance(release_source, dict) or release_source.get('mediaSha256') != media):
        raise ValueError('release media mismatch')
    assets = [a for a in release.get('assets', []) if a.get('role') == 'content']
    if len(assets) != 1:
        raise ValueError('unique content asset required')
    content_raw = verify_file(assets[0].get('path'))
    if v1.digest(content_raw) != assets[0].get('sha256'):
        raise ValueError('content hash mismatch')
    content = json.loads(content_raw)
    contract.validate_content_target(content, p, locale)
    if (content.get('status') != release.get('contentStatus')
        or not _hash(release.get('targetLanguageCandidateJsonSha256'))
        or content.get('targetLanguageCandidateJsonSha256') != release.get('targetLanguageCandidateJsonSha256')):
        raise ValueError('content review status or candidate identity mismatch')
    if (content.get('pageId') != edition or content.get('targetLocale') != locale
        or content.get('englishSourcePackageJsonSha256') != identity or content.get('sourceMediaSha256') != media):
        raise ValueError('content identity mismatch')
    return edition, identity, release_sha


def _entry_valid(e, *, minimal=False):
    if (not isinstance(e, dict) or not isinstance(e.get('pageID'), str) or not v1.PAGE_ID.fullmatch(e['pageID'])
        or e.get('locale') not in LOCALES or not isinstance(e.get('week'), int) or isinstance(e['week'], bool)
        or not 1 <= e['week'] <= 12 or not isinstance(e.get('editionId'), str) or not v1.PAGE_ID.fullmatch(e['editionId'])
        or not all(_hash(e.get(k)) for k in ('sourceIdentitySha256', 'releasePackageJsonSha256'))
        or e.get('status') not in ('available', 'revoked')):
        raise ValueError('invalid v2 entry')
    if e['status'] == 'available' and not minimal:
        if (e.get('sourceSHA256') != SOURCE_SHA256 or not _hash(e.get('translationSHA256'))
            or e.get('review') != REVIEW or e.get('humanApproval') is not False
            or not _hash(e.get('sha256')) or not isinstance(e.get('bytes'), int) or isinstance(e['bytes'], bool)
            or not 0 < e['bytes'] <= v1.GUIDE_LIMIT or e.get('path') != f"/weekly-guides/published/{e['sha256']}.json"):
            raise ValueError('invalid available v2 entry')


def _content_valid(e, raw):
    if len(raw) != e['bytes'] or v1.digest(raw) != e['sha256']:
        raise ValueError('v2 resource hash mismatch')
    g = json.loads(raw)
    for field, expected in [('id', e['pageID']), ('locale', e['locale']), ('week', e['week']),
                            ('review', e['review']), ('sourceSHA256', e['sourceSHA256']),
                            ('translationSHA256', e['translationSHA256'])]:
        if g.get(field) != expected:
            raise ValueError('v2 content identity mismatch')
    if g.get('humanApproval') is not False:
        raise ValueError('invalid content approval')
    _guide({k: g.get(k) for k in ('week', 'title', 'scripture', 'sections')}, e['locale'], e['translationSHA256'])


def existing_v2(rows, verify_file, *, skip_assets=frozenset()):
    path = '/weekly-guides/manifest-v2.json'
    if path not in rows:
        return [], {}
    raw = verify_file(path)
    if len(raw) > v1.MANIFEST_LIMIT:
        raise ValueError('v2 manifest too large')
    obj = json.loads(raw)
    if obj.get('schemaVersion') != 'tongxing-weekly-guide-manifest-v2' or obj.get('seriesID') != v1.SERIES_ID or not isinstance(obj.get('entries'), list):
        raise ValueError('invalid v2 manifest')
    entries, assets, seen = obj['entries'], {}, set()
    for e in entries:
        if not isinstance(e, dict):
            raise ValueError('invalid v2 entry')
        key = (e.get('pageID'), e.get('locale'))
        _entry_valid(e, minimal=key in skip_assets)
        if key in seen:
            raise ValueError('duplicate v2 identity')
        seen.add(key)
        if e['status'] == 'available' and key not in skip_assets:
            data = verify_file(e['path'])
            _content_valid(e, data)
            assets[e['path']] = data
    return entries, assets


def _tombstone(prior):
    return {**{k: prior[k] for k in ('pageID', 'locale', 'week', 'editionId',
        'sourceIdentitySha256', 'releasePackageJsonSha256')}, 'status': 'revoked'}


def prepare_fragment(staging, source, draft, reviews, review_records, snapshot, environment, bindings, out, *, bundle_evidence_bytes=None, alias_evidence_bytes=None, skip_assets=frozenset()):
    """Bind verified v1 or frozen bundle week mappings to a locale v5 release."""
    staged = _staged(staging, source, draft, reviews, review_records)
    rows, verify, receipt = v1.verified_live_snapshot(snapshot, environment)
    chinese, _ = v1.existing_manifest(snapshot, rows, verify, initialize_empty='/weekly-guides/manifest-v1.json' not in rows)
    bundle = v1.validated_bundle_evidence(bundle_evidence_bytes, environment, v1.BUNDLE_EVIDENCE_SHA256) if bundle_evidence_bytes is not None else None
    aliases = v1.validated_alias_evidence(alias_evidence_bytes, environment, v1.ALIAS_EVIDENCE_SHA256) if alias_evidence_bytes is not None else None
    if '/weekly-guides/manifest-v2.json' not in rows and (Path(snapshot) / 'public/weekly-guides/manifest-v2.json').exists():
        raise ValueError('v2 manifest absent from verified live receipt')
    old, assets = existing_v2(rows, verify, skip_assets=skip_assets)
    entries = [dict(e) for e in old]
    by_key = {(e['pageID'], e['locale']): e for e in entries}
    catalog = json.loads(verify('/multilingual-v5.json'))
    if catalog.get('schemaVersion') != 'sermon-multilingual-catalog-v5':
        raise ValueError('v5 catalog required')
    if not isinstance(bindings, list) or not bindings:
        raise ValueError('explicit bindings required')
    seen = set()
    locale = next(iter(staged.values()))['locale']
    for b in bindings:
        page, week, kind = b.get('pageID'), b.get('week'), b.get('operation', 'add')
        if not isinstance(page, str) or not v1.PAGE_ID.fullmatch(page) or not isinstance(week, int) or isinstance(week, bool) or kind not in ('add', 'update', 'revoke'):
            raise ValueError('invalid binding')
        key = (page, locale)
        if key in seen:
            raise ValueError('duplicate binding')
        seen.add(key)
        prior = by_key.get(key)
        if kind == 'add' and prior:
            raise ValueError('existing entry')
        if kind in ('update', 'revoke'):
            if not prior or prior['week'] != week or b.get('expectedEntrySha256') != v1.digest(v1.encoded(prior)) or not str(b.get('reason', '')).strip():
                raise ValueError('prior identity and reason required')
        if kind == 'revoke':
            if prior['status'] == 'revoked':
                raise ValueError('already revoked')
            revised = _tombstone(prior)
        else:
            if week not in staged:
                raise ValueError('staged week required')
            matches = [e for e in chinese if e.get('pageID') == page and e.get('locale') == 'zh-Hans']
            family = [p for p in catalog.get('pages', []) if p.get('id') == page]
            if len(family) != 1 or family[0].get('sourceMode') not in ('single_source', 'per_target'):
                raise ValueError('unique supported v5 family required')
            per_target = family[0]['sourceMode'] == 'per_target'
            if matches and (len(matches) != 1 or matches[0].get('week') != week):
                raise ValueError('Chinese manifest week differs')
            if matches and matches[0].get('status') == 'available':
                week_identity = matches[0].get('sourceIdentitySha256')
                if per_target:
                    zh_edition, zh_identity, zh_release = _target(catalog, page, 'zh-Hans', verify)
                    if (zh_edition != matches[0].get('editionId') or zh_identity != week_identity
                        or zh_release != matches[0].get('releasePackageJsonSha256')):
                        raise ValueError('Chinese manifest family identity differs from live release')
            else:
                # A Chinese-only guide revocation does not revoke a separate
                # language. It cannot itself prove a week mapping; use the
                # independently frozen bundle and live-source evidence instead.
                if bundle is None:
                    raise ValueError('verified Chinese week mapping or frozen bundle evidence required')
                proof = v1.bundled_tombstone({'pageID': page, 'week': week}, catalog, bundle, verify, aliases)
                # Legacy weekly.json binds media and timeline, but does not
                # provide a v5 source package identity. Do not infer equivalence.
                week_identity = proof.get('sourceIdentitySha256')
                if not _hash(week_identity):
                    raise ValueError('legacy bundle lacks a verified v5 source identity')
                zh_edition, zh_identity, zh_release = _target(catalog, page, 'zh-Hans', verify)
                if (zh_edition != proof.get('editionId') or zh_identity != week_identity
                    or zh_release != proof.get('releasePackageJsonSha256')):
                    raise ValueError('bundle and live Chinese release identity mismatch')
            edition, identity, release_sha = _target(catalog, page, locale, verify)
            # A per_target family deliberately permits distinct source editions.
            # Both joins above are verified within this exact catalog family;
            # do not conflate its target language identity with Chinese.
            if not per_target and week_identity != identity:
                raise ValueError('locale and week source identity mismatch')
            g = staged[week]
            guide = {'id': page, **{k: g[k] for k in ('locale', 'week', 'title', 'scripture', 'review', 'humanApproval', 'sourceSHA256', 'translationSHA256')},
                     'sections': [{k: s[k] for k in ('id', 'title', 'subtitle', 'symbol', 'body')} for s in g['sections']]}
            raw = v1.encoded(guide)
            if len(raw) > v1.GUIDE_LIMIT:
                raise ValueError('guide too large')
            sha = v1.digest(raw)
            path = f'/weekly-guides/published/{sha}.json'
            assets[path] = raw
            revised = {'pageID': page, 'locale': locale, 'week': week, 'editionId': edition,
                       'sourceIdentitySha256': identity, 'releasePackageJsonSha256': release_sha,
                       'status': 'available', 'path': path, 'sha256': sha, 'bytes': len(raw),
                       'review': REVIEW, 'humanApproval': False, 'sourceSHA256': SOURCE_SHA256,
                       'translationSHA256': g['translationSHA256']}
            _entry_valid(revised)
            _content_valid(revised, raw)
        if prior:
            entries[entries.index(prior)] = revised
        else:
            entries.append(revised)
        by_key[key] = revised
    manifest = {'schemaVersion': 'tongxing-weekly-guide-manifest-v2', 'seriesID': v1.SERIES_ID, 'entries': entries}
    raw = v1.encoded(manifest)
    if len(raw) > v1.MANIFEST_LIMIT:
        raise ValueError('manifest too large')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'published').mkdir()
    for path, data in assets.items():
        (out / 'published' / Path(path).name).write_bytes(data)
    (out / 'manifest-v2.json').write_bytes(raw)
    (out / 'plan.json').write_bytes(v1.encoded({'status': 'prepared_not_uploaded', 'environment': environment,
        'baselineVersion': receipt['baselineVersion'], 'manifestSHA256': v1.digest(raw), 'liveRecheck': 'required_before_deploy'}))
    return manifest


def _reject_public_symlinks(public):
    """Inspect directories without traversing links, before any baseline copy."""
    if public.is_symlink() or not public.is_dir():
        raise ValueError('public baseline must be a non-symlink directory')
    pending = [public]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise ValueError('public baseline contains a symlink')
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))


def _open_directory(name, *, dir_fd=None):
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        raise ValueError('baseline directory changed or contains a symlink') from exc


def _pinned_snapshot(snapshot):
    """Walk from the filesystem root without following any snapshot ancestor."""
    fd = _open_directory('/')
    try:
        for part in snapshot.parts[1:]:
            child = _open_directory(part, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _pinned_publisher_lock(snapshot_fd):
    """Lock the publisher's same file inside the pinned snapshot directory."""
    try:
        lock_fd = os.open('hosting-publisher.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                          0o600, dir_fd=snapshot_fd)
    except OSError as exc:
        raise ValueError('publisher lock changed or is a symlink') from exc
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise ValueError('publisher lock is not a regular file')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Publisher is still running; wait for completion before reconciliation') from None
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def _read_pinned_file(directory_fd, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except OSError as exc:
        raise ValueError('baseline file changed or contains a symlink') from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('baseline file is not regular')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def _scan_public_fd(public_fd):
    """Check the entire source tree by pinned descriptors without following links."""
    def scan(fd):
        for name in os.listdir(fd):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError('public baseline contains a symlink')
            if stat.S_ISDIR(info.st_mode):
                child = _open_directory(name, dir_fd=fd)
                try:
                    now = os.fstat(child)
                    if (now.st_dev, now.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError('public directory changed during scan')
                    scan(child)
                finally:
                    os.close(child)
            elif not stat.S_ISREG(info.st_mode):
                raise ValueError('public baseline contains a non-regular file')
    scan(public_fd)


def _copy_public_without_following(public_fd, destination):
    """Copy via directory descriptors so links swapped in after scanning fail closed."""
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    def open_checked(path, flags, *, dir_fd=None):
        try:
            return os.open(path, flags, dir_fd=dir_fd)
        except OSError as exc:
            raise ValueError('public baseline changed or contains a symlink') from exc
    root_fd = os.dup(public_fd)
    try:
        destination.mkdir()
        def copy_directory(src_fd, dst):
            for name in os.listdir(src_fd):
                info = os.stat(name, dir_fd=src_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError('public baseline contains a symlink')
                if stat.S_ISDIR(info.st_mode):
                    child_fd = open_checked(name, directory_flags, dir_fd=src_fd)
                    try:
                        opened = os.fstat(child_fd)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise ValueError('public directory changed during copy')
                        child = dst / name
                        child.mkdir()
                        copy_directory(child_fd, child)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(info.st_mode):
                    file_fd = open_checked(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=src_fd)
                    try:
                        opened = os.fstat(file_fd)
                        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise ValueError('public file changed during copy')
                        with os.fdopen(file_fd, 'rb', closefd=False) as source_file, (dst / name).open('xb') as output_file:
                            shutil.copyfileobj(source_file, output_file)
                    finally:
                        os.close(file_fd)
                else:
                    raise ValueError('public baseline contains a non-regular file')
        copy_directory(root_fd, destination)
    finally:
        os.close(root_fd)


def prepare_revoke_fragment(locale, bindings, snapshot, environment, out, *, skip_assets=frozenset()):
    """Revoke only existing verified entries; no new translation is read."""
    if locale not in LOCALES or not isinstance(bindings, list) or not bindings:
        raise ValueError('revoke locale and bindings required')
    rows, verify, receipt = v1.verified_live_snapshot(snapshot, environment)
    if '/weekly-guides/manifest-v2.json' not in rows:
        raise ValueError('cannot revoke without a live v2 manifest')
    entries, _ = existing_v2(rows, verify, skip_assets=skip_assets)
    entries = [dict(e) for e in entries]
    by_key = {(e['pageID'], e['locale']): e for e in entries}
    seen = set()
    for binding in bindings:
        if (not isinstance(binding, dict) or not {'pageID', 'operation', 'expectedEntrySha256', 'reason'} <= binding.keys()
            or not binding.keys() <= {'pageID', 'operation', 'expectedEntrySha256', 'reason', 'week'}
            or binding['operation'] != 'revoke'):
            raise ValueError('revoke-only input may contain only explicit revocations')
        page = binding['pageID']
        if not isinstance(page, str) or not v1.PAGE_ID.fullmatch(page):
            raise ValueError('invalid revoke page')
        key = (page, locale)
        if key in seen:
            raise ValueError('duplicate revoke identity')
        seen.add(key)
        prior = by_key.get(key)
        if (not prior or prior['status'] != 'available'
            or binding.get('expectedEntrySha256') != v1.digest(v1.encoded(prior))
            or not isinstance(binding.get('reason'), str) or not binding['reason'].strip()
            or ('week' in binding and binding['week'] != prior['week'])):
            raise ValueError('prior identity and reason required for revocation')
        revised = _tombstone(prior)
        entries[entries.index(prior)] = revised
        by_key[key] = revised
    manifest = {'schemaVersion': 'tongxing-weekly-guide-manifest-v2', 'seriesID': v1.SERIES_ID, 'entries': entries}
    raw = v1.encoded(manifest)
    if len(raw) > v1.MANIFEST_LIMIT:
        raise ValueError('manifest too large')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'published').mkdir()
    (out / 'manifest-v2.json').write_bytes(raw)
    (out / 'plan.json').write_bytes(v1.encoded({'status': 'prepared_not_uploaded', 'environment': environment,
        'baselineVersion': receipt['baselineVersion'], 'manifestSHA256': v1.digest(raw), 'liveRecheck': 'required_before_deploy'}))
    return manifest


def prepare_batch_candidate(inputs, snapshot, environment, out):
    snapshot = Path(snapshot).resolve(strict=True)
    snapshot_fd = _pinned_snapshot(snapshot)
    try:
        # Same inode and OS flock as publication.publisher_lock, opened through
        # the pinned directory so ancestor replacement cannot redirect it.
        with _pinned_publisher_lock(snapshot_fd):
            public_fd = _open_directory('public', dir_fd=snapshot_fd)
            try:
                return _prepare_batch_candidate(inputs, snapshot, environment, out, snapshot_fd, public_fd)
            finally:
                os.close(public_fd)
    finally:
        os.close(snapshot_fd)


def _prepare_batch_candidate(inputs, snapshot, environment, out, snapshot_fd, public_fd):
    """Apply independently verified changes to one frozen baseline; never deploy.

    Every operation is evaluated against the same live receipt. A repeated
    page/locale is rejected even if the caller supplies a plausible intermediate
    entry hash: no intermediate candidate is ever presented as a live baseline.
    """
    from tongxing_production.delivery import baseline, contract

    out = Path(out).resolve()
    if out.exists() or out == snapshot or out.is_relative_to(snapshot) or snapshot.is_relative_to(out):
        raise ValueError('unsafe candidate output location')
    if not isinstance(inputs, list) or not inputs:
        raise ValueError('nonempty batch inputs required')
    input_dirs = []
    touched = set()
    revoke_keys = set()
    operations = []
    for item in inputs:
        if not isinstance(item, dict):
            raise ValueError('invalid batch input')
        if 'locale' in item:
            if set(item) != {'locale', 'bindings'}:
                raise ValueError('revoke-only input cannot contain draft or new content')
            locale = item['locale']
        else:
            staging = Path(item['staging']).resolve()
            input_dirs.extend((staging, Path(item['review_records']).resolve()))
            draft_data = json.loads(item['draft'])
            locale = draft_data.get('locale') if isinstance(draft_data, dict) else None
        bindings = item.get('bindings')
        if locale not in LOCALES or not isinstance(bindings, list) or not bindings:
            raise ValueError('invalid batch locale or bindings')
        for binding in bindings:
            if 'locale' in item and (not isinstance(binding, dict) or binding.get('operation') != 'revoke'):
                raise ValueError('revoke-only input may contain only explicit revocations')
            page = binding.get('pageID') if isinstance(binding, dict) else None
            if not isinstance(page, str) or not v1.PAGE_ID.fullmatch(page):
                raise ValueError('invalid batch page')
            key = (page, locale)
            if key in touched:
                raise ValueError('duplicate batch page and locale')
            touched.add(key)
            if binding.get('operation') == 'revoke':
                revoke_keys.add(key)
            operations.append({'pageID': page, 'locale': locale, 'operation': binding.get('operation', 'add'),
                **{k: binding[k] for k in ('week', 'expectedEntrySha256', 'reason') if k in binding}})
    if any(out == path or out.is_relative_to(path) or path.is_relative_to(out) for path in input_dirs):
        raise ValueError('unsafe candidate output location')
    _scan_public_fd(public_fd)
    receipt_bytes = _read_pinned_file(snapshot_fd, 'baseline-receipt.json')
    firebase_bytes = _read_pinned_file(snapshot_fd, 'firebase.json')
    seal_bytes = _read_pinned_file(snapshot_fd, 'seal-report.json')
    receipt = json.loads(receipt_bytes)
    if v1.digest(firebase_bytes) != receipt.get('firebaseJsonSha256'):
        raise ValueError('baseline Firebase config differs from receipt')
    try:
        os.stat('deployment-attempt-v2.json', dir_fd=snapshot_fd, follow_symlinks=False)
    except FileNotFoundError:
        attempt_present = False
    else:
        attempt_present = True
    if attempt_present:
        attempt = json.loads(_read_pinned_file(snapshot_fd, 'deployment-attempt-v2.json'))
        target = baseline.hosting_target(environment)
        expected_intent = {**{k: target[k] for k in ('project', 'site', 'origin', 'channel')}, 'environment': environment}
        try:
            os.stat('publish-config.json', dir_fd=snapshot_fd, follow_symlinks=False)
        except FileNotFoundError:
            expected_version = receipt['baselineVersion']
        else:
            expected_version = json.loads(_read_pinned_file(snapshot_fd, 'publish-config.json'))['baseline_version']
        if (attempt.get('status') != 'deployed' or not attempt.get('newVersion')
            or any(attempt.get('intent', {}).get(k) != value for k, value in expected_intent.items())
            or attempt.get('baselineVersion') != expected_version
            or attempt.get('catalogSha256') != v1.digest(_read_pinned_file(public_fd, 'multilingual-v3.json'))):
            raise ValueError('Prior publication remains uncertain or differs from baseline')
        if attempt['newVersion'] != receipt.get('baselineVersion'):
            raise ValueError('prior publication changed the baseline; capture a fresh live snapshot')
    out.mkdir(parents=True, exist_ok=False)
    # Descriptor-relative no-follow opens also protect against a link swapped
    # in after the initial tree scan, including replacement of the root itself.
    _copy_public_without_following(public_fd, out / 'public')
    _reject_public_symlinks(out / 'public')
    for name, raw in (('firebase.json', firebase_bytes), ('baseline-receipt.json', receipt_bytes), ('seal-report.json', seal_bytes)):
        (out / name).write_bytes(raw)
    if ((out / 'baseline-receipt.json').read_bytes() != receipt_bytes
        or (out / 'firebase.json').read_bytes() != firebase_bytes):
        raise ValueError('copied baseline identity changed')
    rows, verify, frozen = v1.verified_live_snapshot(out, environment)
    if frozen != receipt:
        raise ValueError('copied baseline receipt changed')
    for path, row in rows.items():
        if row.get('managed') is True:
            continue
        raw = v1._safe_asset(out / 'public', path).read_bytes()
        if len(raw) != row.get('rawBytes') or v1.digest(raw) != row.get('rawSha256'):
            raise ValueError('copied baseline differs from live receipt')
    if '/weekly-guides/manifest-v2.json' not in rows and (out / 'public/weekly-guides/manifest-v2.json').exists():
        raise ValueError('v2 manifest absent from verified live receipt')
    old, _ = existing_v2(rows, verify, skip_assets=revoke_keys)
    baseline_entries = {(e['pageID'], e['locale']): e for e in old}
    merged = dict(baseline_entries)
    fragments = []
    for number, item in enumerate(inputs):
        fragment = out / 'guide-v2-fragments' / f'{number:04d}'
        if 'locale' in item:
            locale = item['locale']
            manifest = prepare_revoke_fragment(locale, item['bindings'], out, environment, fragment, skip_assets=revoke_keys)
        else:
            manifest = prepare_fragment(item['staging'], item['source'], item['draft'], item['reviews'],
                item['review_records'], out, environment, item['bindings'], fragment,
                bundle_evidence_bytes=item.get('bundle_evidence_bytes'), alias_evidence_bytes=item.get('alias_evidence_bytes'),
                skip_assets=revoke_keys)
            locale = json.loads(item['draft'])['locale']
        keys = {(b['pageID'], locale) for b in item['bindings']}
        fragment_entries = {(e['pageID'], e['locale']): e for e in manifest['entries']}
        if len(fragment_entries) != len(manifest['entries']) or not keys <= fragment_entries.keys():
            raise ValueError('fragment missing or duplicating requested entry')
        if any(fragment_entries.get(k) != value for k, value in baseline_entries.items() if k not in keys):
            raise ValueError('fragment unexpectedly changed another baseline entry')
        if set(fragment_entries) != set(baseline_entries) | keys:
            raise ValueError('fragment contains unexpected entries')
        for key in keys:
            merged[key] = fragment_entries[key]
        fragments.append(fragment)
    manifest = {'schemaVersion': 'tongxing-weekly-guide-manifest-v2', 'seriesID': v1.SERIES_ID,
                'entries': list(merged.values())}
    manifest_raw = v1.encoded(manifest)
    if len(manifest_raw) > v1.MANIFEST_LIMIT:
        raise ValueError('manifest too large')
    dest = out / 'public/weekly-guides'
    published = dest / 'published'
    published.mkdir(parents=True, exist_ok=True)
    for fragment in fragments:
        for asset in sorted((fragment / 'published').glob('*.json')):
            target = published / asset.name
            if target.exists() and target.read_bytes() != asset.read_bytes():
                raise ValueError('immutable guide collision')
            if not target.exists():
                shutil.copyfile(asset, target)
    (dest / 'manifest-v2.json').write_bytes(manifest_raw)
    next_seal = out / 'seal-report.next.json'
    baseline.write(next_seal, {**baseline.catalog_report(out / 'public'), 'files': baseline.files_report(out / 'public')})
    next_seal.replace(out / 'seal-report.json')
    contract.validate_catalog_snapshot(out)
    config = baseline.publication_config(out, out, environment=environment)
    if config.get('baseline_version') != receipt.get('baselineVersion') or config.get('baseline_catalog_sha') != receipt.get('catalogSha256'):
        raise ValueError('guarded config differs from frozen baseline')
    baseline.write(out / 'publish-config.json', config)
    baseline.write(out / 'weekly-guide-v2-overlay-plan.json', {
        'schemaVersion': 'tongxing-weekly-guide-overlay-plan-v2', 'status': 'prepared_not_uploaded',
        'environment': environment, 'baselineVersion': receipt['baselineVersion'],
        'manifestSHA256': v1.digest((dest / 'manifest-v2.json').read_bytes()),
        'entryCount': len(manifest['entries']), 'liveRecheck': 'required_before_deploy',
        'clientAcceptance': 'not_run', 'operations': operations})
    return manifest


def prepare_candidate(staging, source, draft, reviews, review_records, snapshot, environment, bindings, out, *, bundle_evidence_bytes=None, alias_evidence_bytes=None):
    return prepare_batch_candidate([{'staging': staging, 'source': source, 'draft': draft, 'reviews': reviews,
        'review_records': review_records, 'bindings': bindings, 'bundle_evidence_bytes': bundle_evidence_bytes,
        'alias_evidence_bytes': alias_evidence_bytes}], snapshot, environment, out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    stage = sub.add_parser('stage')
    stage.add_argument('--source', required=True, type=Path)
    stage.add_argument('--draft', required=True, type=Path)
    stage.add_argument('--reviews', required=True, type=Path)
    stage.add_argument('--review-records', required=True, type=Path)
    stage.add_argument('--output', required=True, type=Path)
    for action in ('bind', 'candidate'):
        bind = sub.add_parser(action)
        for flag in ('source', 'draft', 'reviews', 'review-records', 'staging', 'snapshot', 'bindings', 'output'):
            bind.add_argument('--' + flag, required=True, type=Path)
        bind.add_argument('--environment', required=True, choices=('dev', 'production'))
        bind.add_argument('--bundle-evidence', type=Path)
        bind.add_argument('--alias-evidence', type=Path)
    batch = sub.add_parser('batch-candidate')
    batch.add_argument('--plan', required=True, type=Path)
    batch.add_argument('--snapshot', required=True, type=Path)
    batch.add_argument('--environment', required=True, choices=('dev', 'production'))
    batch.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    output = v1.safe_output(args.output)
    if args.action == 'batch-candidate':
        plan = json.loads(args.plan.read_bytes())
        if (not isinstance(plan, dict) or plan.get('schemaVersion') != 'tongxing-weekly-guide-batch-v1'
            or not isinstance(plan.get('inputs'), list) or not plan['inputs']):
            raise ValueError('invalid batch plan')
        def input_path(value):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('invalid batch input path')
            path = Path(value)
            return path if path.is_absolute() else args.plan.resolve().parent / path
        inputs = []
        required = {'source', 'draft', 'reviews', 'reviewRecords', 'staging', 'bindings'}
        allowed = required | {'bundleEvidence', 'aliasEvidence'}
        for item in plan['inputs']:
            if isinstance(item, dict) and 'locale' in item:
                if set(item) != {'locale', 'bindings'}:
                    raise ValueError('revoke-only input cannot contain draft or new content')
                inputs.append({'locale': item['locale'], 'bindings': item['bindings']})
                continue
            if not isinstance(item, dict) or not required <= item.keys() or not item.keys() <= allowed:
                raise ValueError('invalid batch input fields')
            inputs.append({'source': input_path(item['source']).read_bytes(), 'draft': input_path(item['draft']).read_bytes(),
                'reviews': input_path(item['reviews']).read_bytes(), 'review_records': input_path(item['reviewRecords']),
                'staging': input_path(item['staging']), 'bindings': item['bindings'],
                'bundle_evidence_bytes': input_path(item['bundleEvidence']).read_bytes() if 'bundleEvidence' in item else None,
                'alias_evidence_bytes': input_path(item['aliasEvidence']).read_bytes() if 'aliasEvidence' in item else None})
        result = prepare_batch_candidate(inputs, args.snapshot, args.environment, output)
        print(json.dumps({'status': 'prepared_not_uploaded', 'count': len(result['entries'])}))
        return 0
    source, draft, reviews = args.source.read_bytes(), args.draft.read_bytes(), args.reviews.read_bytes()
    if args.action == 'stage':
        result = prepare_stage(source, draft, reviews, args.review_records, output)
    else:
        value = json.loads(args.bindings.read_bytes())
        if value.get('schemaVersion') != 'tongxing-weekly-guide-bindings-v2':
            raise ValueError('invalid bindings schema')
        build = prepare_candidate if args.action == 'candidate' else prepare_fragment
        result = build(args.staging, source, draft, reviews, args.review_records, args.snapshot, args.environment, value.get('bindings'), output,
                       bundle_evidence_bytes=args.bundle_evidence.read_bytes() if args.bundle_evidence else None,
                       alias_evidence_bytes=args.alias_evidence.read_bytes() if args.alias_evidence else None)
    print(json.dumps({'status': 'prepared_not_uploaded', 'count': len(result['entries'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

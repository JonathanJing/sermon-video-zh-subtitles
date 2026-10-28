"""Prepare private Korean/Spanish guide staging and guarded v2 fragments.

Inputs and outputs contain licensed text: keep them in ignored artifacts. This
module never uploads or deploys. It does not translate or approve content.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

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


def _entry_valid(e):
    if (not isinstance(e, dict) or not isinstance(e.get('pageID'), str) or not v1.PAGE_ID.fullmatch(e['pageID'])
        or e.get('locale') not in LOCALES or not isinstance(e.get('week'), int) or isinstance(e['week'], bool)
        or not 1 <= e['week'] <= 12 or not isinstance(e.get('editionId'), str) or not v1.PAGE_ID.fullmatch(e['editionId'])
        or not all(_hash(e.get(k)) for k in ('sourceIdentitySha256', 'releasePackageJsonSha256'))
        or e.get('status') not in ('available', 'revoked')):
        raise ValueError('invalid v2 entry')
    if e['status'] == 'available':
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


def existing_v2(rows, verify_file):
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
        _entry_valid(e)
        key = (e['pageID'], e['locale'])
        if key in seen:
            raise ValueError('duplicate v2 identity')
        seen.add(key)
        if e['status'] == 'available':
            data = verify_file(e['path'])
            _content_valid(e, data)
            assets[e['path']] = data
    return entries, assets


def prepare_fragment(staging, source, draft, reviews, review_records, snapshot, environment, bindings, out, *, bundle_evidence_bytes=None, alias_evidence_bytes=None):
    """Bind verified v1 or frozen bundle week mappings to a locale v5 release."""
    staged = _staged(staging, source, draft, reviews, review_records)
    rows, verify, receipt = v1.verified_live_snapshot(snapshot, environment)
    chinese, _ = v1.existing_manifest(snapshot, rows, verify, initialize_empty='/weekly-guides/manifest-v1.json' not in rows)
    bundle = v1.validated_bundle_evidence(bundle_evidence_bytes, environment, v1.BUNDLE_EVIDENCE_SHA256) if bundle_evidence_bytes is not None else None
    aliases = v1.validated_alias_evidence(alias_evidence_bytes, environment, v1.ALIAS_EVIDENCE_SHA256) if alias_evidence_bytes is not None else None
    if '/weekly-guides/manifest-v2.json' not in rows and (Path(snapshot) / 'public/weekly-guides/manifest-v2.json').exists():
        raise ValueError('v2 manifest absent from verified live receipt')
    old, assets = existing_v2(rows, verify)
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
            revised = {**prior, 'status': 'revoked'}
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


def prepare_candidate(staging, source, draft, reviews, review_records, snapshot, environment, bindings, out, *, bundle_evidence_bytes=None, alias_evidence_bytes=None):
    """Copy the entire verified live baseline and overlay v2, without deployment."""
    from tongxing_production.delivery import baseline, contract

    staging, snapshot, out = Path(staging).resolve(), Path(snapshot).resolve(), Path(out).resolve()
    if (out.exists() or out == snapshot or out == staging or out.is_relative_to(snapshot)
        or snapshot.is_relative_to(out) or out.is_relative_to(staging) or staging.is_relative_to(out)):
        raise ValueError('unsafe candidate output location')
    receipt_bytes = (snapshot / 'baseline-receipt.json').read_bytes()
    firebase_bytes = (snapshot / 'firebase.json').read_bytes()
    receipt = json.loads(receipt_bytes)
    if v1.digest(firebase_bytes) != receipt.get('firebaseJsonSha256'):
        raise ValueError('baseline Firebase config differs from receipt')
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(snapshot / 'public', out / 'public')
    for name in ('firebase.json', 'baseline-receipt.json', 'seal-report.json'):
        shutil.copyfile(snapshot / name, out / name)
    if ((out / 'baseline-receipt.json').read_bytes() != receipt_bytes
        or (out / 'firebase.json').read_bytes() != firebase_bytes):
        raise ValueError('copied baseline identity changed')
    rows, _, frozen = v1.verified_live_snapshot(out, environment)
    if frozen != receipt:
        raise ValueError('copied baseline receipt changed')
    for path, row in rows.items():
        if row.get('managed') is True:
            continue
        raw = v1._safe_asset(out / 'public', path).read_bytes()
        if len(raw) != row.get('rawBytes') or v1.digest(raw) != row.get('rawSha256'):
            raise ValueError('copied baseline differs from live receipt')
    fragment = out / 'guide-v2-fragment'
    manifest = prepare_fragment(staging, source, draft, reviews, review_records, out, environment, bindings, fragment,
                                bundle_evidence_bytes=bundle_evidence_bytes, alias_evidence_bytes=alias_evidence_bytes)
    dest = out / 'public/weekly-guides'
    published = dest / 'published'
    published.mkdir(parents=True, exist_ok=True)
    for asset in sorted((fragment / 'published').glob('*.json')):
        target = published / asset.name
        if target.exists() and target.read_bytes() != asset.read_bytes():
            raise ValueError('immutable guide collision')
        if not target.exists():
            shutil.copyfile(asset, target)
    shutil.copyfile(fragment / 'manifest-v2.json', dest / 'manifest-v2.json')
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
        'clientAcceptance': 'not_run'})
    return manifest


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
    args = parser.parse_args(argv)
    output = v1.safe_output(args.output)
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

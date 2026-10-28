"""Synthetic data only; no source text or translated manuscript."""
import json
from pathlib import Path

from jsonschema import ValidationError
import pytest

from tongxing_production.delivery import weekly_guide_multilingual as m
from tongxing_production.delivery import weekly_guide_staging as v1


def source_bytes():
    return ''.join(f'=== PAGE {n} (pdf page {n-1}, id id{n}) ===\nsource {n}\n\n' for n in range(1, 181)).encode()


def draft(locale='ko', body='synthetic content'):
    pages = m._source_pages(source_bytes())
    sections = [{'id': f'page-{n}', 'title': 'sample', 'subtitle': '', 'symbol': 'book', 'body': body,
                 'sourcePage': n, 'sourcePageID': pages[n][0], 'sourcePageSHA256': pages[n][1]}
                for n in [*range(108, 118), 171]]
    return v1.encoded({'schemaVersion': 'tongxing-weekly-guide-translation-draft-v3', 'locale': locale,
        'guides': [{'week': 8, 'title': 'sample', 'scripture': m.scripture_for_week(8, locale), 'sections': sections}]})


def reviews_for(source, trans, root):
    guide = json.loads(trans)['guides'][0]
    fields = {'week': guide['week'], 'locale': json.loads(trans)['locale'], 'sourceSHA256': v1.digest(source),
              'translationSHA256': v1.digest(trans), 'guideSHA256': v1.digest(v1.encoded(guide)),
              'method': 'machine', 'decision': 'pass', 'humanApproval': False, 'reviewer': 'synthetic'}
    raw = v1.encoded({'schemaVersion': 'tongxing-weekly-guide-machine-review-v1', **fields,
                      'limitations': ['synthetic machine check; no human or visual approval']})
    root.mkdir(exist_ok=True)
    (root / (v1.digest(raw) + '.json')).write_bytes(raw)
    return v1.encoded({'schemaVersion': 'tongxing-weekly-guide-reviews-v1',
                       'reviews': [{**fields, 'reviewRecordSHA256': v1.digest(raw)}]})


def mock_contract(monkeypatch):
    from tongxing_production.delivery import contract
    monkeypatch.setattr(contract, 'validate_release_target', lambda *a: None)
    monkeypatch.setattr(contract, 'validate_public_study', lambda *a, **kw: None)
    monkeypatch.setattr(contract, 'validate_content_target', lambda *a: None)
    monkeypatch.setattr(contract, 'release_path', lambda r: '/zh-release.json' if r['targetLocale'] == 'zh-Hans' else '/release.json')


@pytest.fixture
def context(tmp_path, monkeypatch):
    source = source_bytes()
    monkeypatch.setattr(m, 'SOURCE_SHA256', v1.digest(source))
    trans = draft()
    records = tmp_path / 'reviews'
    reviews = reviews_for(source, trans, records)
    stage = tmp_path / 'stage'
    m.prepare_stage(source, trans, reviews, records, stage)
    mock_contract(monkeypatch)
    content = {'pageId': 'edition-8', 'targetLocale': 'ko', 'englishSourcePackageJsonSha256': 'a' * 64,
               'sourceMediaSha256': 'b' * 64, 'status': 'machine_checked', 'targetLanguageCandidateJsonSha256': 'f' * 64}
    content_raw = v1.encoded(content)
    release = {'schemaVersion': 'sermon-target-language-release-package-v3', 'pageId': 'edition-8',
        'targetLocale': 'ko', 'englishSourcePackageJsonSha256': 'a' * 64, 'targetLanguageCandidateJsonSha256': 'f' * 64,
        'status': 'published_http_verified', 'httpVerification': {'status': 'pass'}, 'contentStatus': 'machine_checked',
        'audioStatus': 'machine_checked', 'issues': [], 'assets': [{'role': 'content', 'path': '/content.json', 'sha256': v1.digest(content_raw)}]}
    release_raw = v1.encoded(release)
    catalog = {'schemaVersion': 'sermon-multilingual-catalog-v5', 'pages': [{'id': 'sermon-8', 'sourceMode': 'single_source',
        'sourceIdentitySha256': 'a' * 64, 'sourceMediaSha256': 'b' * 64,
        'targets': {'ko': {'editionId': 'edition-8', 'contentStatus': 'machine_checked', 'audioStatus': 'machine_checked',
            'releasePackageUrl': '/release.json', 'releasePackageJsonSha256': v1.digest(release_raw)}}}]}
    files = {'/multilingual-v5.json': v1.encoded(catalog), '/release.json': release_raw, '/content.json': content_raw}
    monkeypatch.setattr(v1, 'verified_live_snapshot', lambda *a: ({k: {} for k in files}, files.__getitem__, {'baselineVersion': 'verified'}))
    zh = [{'pageID': 'sermon-8', 'week': 8, 'locale': 'zh-Hans', 'status': 'available', 'sourceIdentitySha256': 'a' * 64}]
    monkeypatch.setattr(v1, 'existing_manifest', lambda *a, **kw: (zh, {}))
    return {'source': source, 'draft': trans, 'stage': stage, 'files': files, 'catalog': catalog,
            'content': content, 'release': release, 'zh': zh, 'tmp': tmp_path, 'reviews': reviews, 'records': records}


def bind(c, name='out', binding=None):
    return m.prepare_fragment(c['stage'], c['source'], c['draft'], c['reviews'], c['records'], c['tmp'], 'dev',
        [binding or {'pageID': 'sermon-8', 'week': 8}], c['tmp'] / name)


def test_unbound_stage_is_deterministic_and_bound_to_inputs(context):
    c = context
    manifest = json.loads((c['stage'] / 'staging-manifest-v2.json').read_bytes())
    assert manifest['locale'] == 'ko' and manifest['humanApproval'] is False
    entry = manifest['entries'][0]
    assert entry['sermonPageId'] is None and entry['week'] == 8
    staged = json.loads((c['stage'] / entry['file']).read_bytes())
    assert staged['translationSHA256'] == v1.digest(c['draft']) and staged['sourceSHA256'] == v1.digest(c['source'])
    with pytest.raises(ValueError, match='source hash'):
        m.staged_guides(b'other source', c['draft'], c['reviews'], c['records'])
    with pytest.raises(ValueError, match='differs from draft'):
        (c['stage'] / entry['file']).write_text('{}')
        bind(c)


def test_staging_rejects_path_traversal_and_symlink_escape(context):
    c = context
    path = c['stage'] / 'staging-manifest-v2.json'
    manifest = json.loads(path.read_bytes())
    entry = manifest['entries'][0]
    original = entry['file']
    entry['file'] = '../outside.json'
    path.write_bytes(v1.encoded(manifest))
    with pytest.raises(ValueError, match='filename'):
        bind(c)
    entry['file'] = original
    path.write_bytes(v1.encoded(manifest))
    inside = c['stage'] / original
    outside = c['tmp'] / 'outside.json'
    outside.write_bytes(inside.read_bytes())
    inside.unlink()
    inside.symlink_to(outside)
    with pytest.raises(ValueError, match='escapes snapshot'):
        bind(c)


def test_verified_binding_includes_exact_locale_and_review(context):
    c = context
    entry = bind(c)['entries'][0]
    raw = (c['tmp'] / 'out/published' / (entry['sha256'] + '.json')).read_bytes()
    assert entry['locale'] == 'ko' and entry['review'] == m.REVIEW and entry['humanApproval'] is False
    assert entry['path'].endswith(entry['sha256'] + '.json')
    assert json.loads(raw)['id'] == 'sermon-8'
    m._content_valid(entry, raw)
    changed = {**entry, 'locale': 'es'}
    with pytest.raises(ValueError, match='identity mismatch'):
        m._content_valid(changed, raw)


def test_future_page_and_wrong_mapping_are_rejected(context):
    c = context
    with pytest.raises(ValueError, match='supported v5 family'):
        bind(c, binding={'pageID': 'future-sermon', 'week': 8})
    with pytest.raises(ValueError, match='staged week'):
        bind(c, binding={'pageID': 'sermon-8', 'week': 9})
    c['zh'][0]['sourceIdentitySha256'] = 'f' * 64
    with pytest.raises(ValueError, match='source identity'):
        bind(c)


def test_locale_release_and_content_are_checked(context):
    c = context
    c['release']['targetLocale'] = 'es'
    release = v1.encoded(c['release'])
    c['files']['/release.json'] = release
    c['catalog']['pages'][0]['targets']['ko']['releasePackageJsonSha256'] = v1.digest(release)
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    with pytest.raises(ValueError, match='release locale'):
        bind(c)


def test_locale_scoped_revocation_preserves_other_language(context):
    c = context
    ko = bind(c)['entries'][0]
    ko_raw = (c['tmp'] / 'out/published' / (ko['sha256'] + '.json')).read_bytes()
    esguide = json.loads(ko_raw)
    esguide['locale'] = 'es'
    esguide['scripture'] = m.scripture_for_week(8, 'es')
    es_raw = v1.encoded(esguide)
    sha = v1.digest(es_raw)
    es = {**ko, 'locale': 'es', 'sha256': sha, 'bytes': len(es_raw), 'path': f'/weekly-guides/published/{sha}.json'}
    manifest = {'schemaVersion': 'tongxing-weekly-guide-manifest-v2', 'seriesID': v1.SERIES_ID, 'entries': [ko, es]}
    c['files']['/weekly-guides/manifest-v2.json'] = v1.encoded(manifest)
    c['files'][ko['path']] = ko_raw
    c['files'][es['path']] = es_raw
    revoke = {'pageID': 'sermon-8', 'week': 8, 'operation': 'revoke',
              'expectedEntrySha256': v1.digest(v1.encoded(ko)), 'reason': 'synthetic test'}
    result = bind(c, 'revoked', revoke)
    assert result['entries'][0]['status'] == 'revoked' and result['entries'][1] == es
    assert (c['tmp'] / 'revoked/published' / (sha + '.json')).read_bytes() == es_raw
    revoke['expectedEntrySha256'] = '0' * 64
    with pytest.raises(ValueError, match='prior identity'):
        bind(c, 'bad', revoke)


def test_update_requires_exact_prior_and_retains_immutable_resource(context):
    c = context
    old = bind(c)['entries'][0]
    raw = (c['tmp'] / 'out/published' / (old['sha256'] + '.json')).read_bytes()
    c['files']['/weekly-guides/manifest-v2.json'] = v1.encoded({
        'schemaVersion': 'tongxing-weekly-guide-manifest-v2', 'seriesID': v1.SERIES_ID, 'entries': [old]})
    c['files'][old['path']] = raw
    c['draft'] = draft(body='corrected synthetic text')
    c['stage'] = c['tmp'] / 'stage-updated'
    c['reviews'] = reviews_for(c['source'], c['draft'], c['records'])
    m.prepare_stage(c['source'], c['draft'], c['reviews'], c['records'], c['stage'])
    change = {'pageID': 'sermon-8', 'week': 8, 'operation': 'update',
              'expectedEntrySha256': v1.digest(v1.encoded(old)), 'reason': 'synthetic correction'}
    updated = bind(c, 'updated', change)['entries'][0]
    assert updated['sha256'] != old['sha256']
    assert (c['tmp'] / 'updated/published' / (old['sha256'] + '.json')).read_bytes() == raw
    change.pop('reason')
    with pytest.raises(ValueError, match='prior identity'):
        bind(c, 'missing-reason', change)


def test_manifest_duplicate_and_missing_review_fail_closed(context):
    c = context
    entry = bind(c)['entries'][0]
    raw = (c['tmp'] / 'out/published' / (entry['sha256'] + '.json')).read_bytes()
    obj = {'schemaVersion': 'tongxing-weekly-guide-manifest-v2', 'seriesID': v1.SERIES_ID, 'entries': [entry, entry]}
    files = {'/weekly-guides/manifest-v2.json': v1.encoded(obj), entry['path']: raw}
    with pytest.raises(ValueError, match='duplicate'):
        m.existing_v2(files, files.__getitem__)
    obj['entries'] = [{**entry, 'humanApproval': True}]
    files['/weekly-guides/manifest-v2.json'] = v1.encoded(obj)
    with pytest.raises(ValueError, match='available'):
        m.existing_v2(files, files.__getitem__)


@pytest.fixture
def guarded_context(tmp_path, monkeypatch):
    from tongxing_production.delivery import baseline, contract
    source = source_bytes()
    monkeypatch.setattr(m, 'SOURCE_SHA256', v1.digest(source))
    trans = draft()
    records = tmp_path / 'reviews'
    reviews = reviews_for(source, trans, records)
    stage = tmp_path / 'stage'
    m.prepare_stage(source, trans, reviews, records, stage)
    mock_contract(monkeypatch)
    snapshot = tmp_path / 'snapshot'
    public = snapshot / 'public'
    (public / 'weekly-guides').mkdir(parents=True)
    content = {'pageId': 'edition-8', 'targetLocale': 'ko', 'englishSourcePackageJsonSha256': 'a' * 64, 'sourceMediaSha256': 'b' * 64, 'status': 'machine_checked', 'targetLanguageCandidateJsonSha256': 'f' * 64}
    content_raw = v1.encoded(content)
    (public / 'content.json').write_bytes(content_raw)
    release = {'schemaVersion': 'sermon-target-language-release-package-v3', 'pageId': 'edition-8', 'targetLocale': 'ko',
        'englishSourcePackageJsonSha256': 'a' * 64, 'targetLanguageCandidateJsonSha256': 'f' * 64, 'status': 'published_http_verified', 'httpVerification': {'status': 'pass'}, 'contentStatus': 'machine_checked',
        'audioStatus': 'machine_checked', 'issues': [], 'assets': [{'role': 'content', 'path': '/content.json', 'sha256': v1.digest(content_raw)}]}
    release_raw = v1.encoded(release)
    (public / 'release.json').write_bytes(release_raw)
    catalog = {'schemaVersion': 'sermon-multilingual-catalog-v5', 'pages': [{'id': 'sermon-8', 'sourceMode': 'single_source', 'sourceIdentitySha256': 'a' * 64,
        'sourceMediaSha256': 'b' * 64, 'targets': {'ko': {'editionId': 'edition-8', 'contentStatus': 'machine_checked', 'audioStatus': 'machine_checked',
        'releasePackageUrl': '/release.json', 'releasePackageJsonSha256': v1.digest(release_raw)}}}]}
    (public / 'multilingual-v5.json').write_bytes(v1.encoded(catalog))
    (public / 'multilingual-v3.json').write_bytes(v1.encoded({'fixture': 'old catalog'}))
    (public / 'other.json').write_bytes(b'keep unrelated bytes')
    op = {'pageID': 'sermon-8', 'week': 8, 'operation': 'add', 'editionId': 'sermon-8', 'sourceIdentitySha256': 'a' * 64,
          'releasePackageJsonSha256': 'c' * 64, 'guide': {'id': 'sermon-8', 'week': 8, 'title': 'sample',
          'scripture': 'sample', 'sections': [{'id': 'a', 'title': 'a', 'subtitle': '', 'symbol': 'book', 'body': 'sample'}]}}
    v1.write_published([op], tmp_path / 'v1', [], {})
    import shutil
    shutil.copytree(tmp_path / 'v1' / 'published', public / 'weekly-guides/published')
    shutil.copyfile(tmp_path / 'v1' / 'manifest-v1.json', public / 'weekly-guides/manifest-v1.json')
    esguide = {'id': 'sermon-8', 'locale': 'es', 'week': 8, 'title': 'sample', 'scripture': m.scripture_for_week(8, 'es'),
        'sections': [{'id': 's', 'title': 's', 'subtitle': '', 'symbol': 'book', 'body': 'synthetic'}],
        'review': m.REVIEW, 'humanApproval': False, 'sourceSHA256': m.SOURCE_SHA256, 'translationSHA256': 'd' * 64}
    esraw = v1.encoded(esguide)
    sha = v1.digest(esraw)
    es = {'pageID': 'sermon-8', 'locale': 'es', 'week': 8, 'editionId': 'edition-es', 'sourceIdentitySha256': 'a' * 64,
        'releasePackageJsonSha256': 'e' * 64, 'status': 'available', 'path': f'/weekly-guides/published/{sha}.json',
        'sha256': sha, 'bytes': len(esraw), 'review': m.REVIEW, 'humanApproval': False,
        'sourceSHA256': m.SOURCE_SHA256, 'translationSHA256': 'd' * 64}
    (public / 'weekly-guides/published' / (sha + '.json')).write_bytes(esraw)
    (public / 'weekly-guides/manifest-v2.json').write_bytes(v1.encoded({'schemaVersion': 'tongxing-weekly-guide-manifest-v2', 'seriesID': v1.SERIES_ID, 'entries': [es]}))
    target = baseline.hosting_target('dev')
    (snapshot / 'firebase.json').write_bytes(v1.encoded({'hosting': {'site': target['site'], 'public': 'public'}}))
    seal = {**baseline.catalog_report(public), 'files': baseline.files_report(public)}
    (snapshot / 'seal-report.json').write_bytes(v1.encoded(seal))
    rows = [{'path': r['path'], 'rawBytes': r['bytes'], 'rawSha256': r['sha256'], 'managed': False} for r in seal['files']]
    receipt = {'status': 'complete_verified_not_deployed', 'environment': 'dev', 'project': target['project'], 'site': target['site'],
        'origin': target['origin'], 'baselineVersion': f"sites/{target['site']}/versions/abc", 'catalogSha256': seal['catalogSha256'],
        'firebaseJsonSha256': baseline.digest(snapshot / 'firebase.json'), 'rows': rows}
    (snapshot / 'baseline-receipt.json').write_bytes(v1.encoded(receipt))
    monkeypatch.setattr(contract, 'validate_catalog_snapshot', lambda _: None)
    return locals()


def test_guarded_candidate_preserves_existing_languages_and_live_files(guarded_context):
    locals_ = guarded_context
    tmp_path, stage, source, trans, reviews, records, snapshot, es, rows, public, receipt = (locals_[k] for k in ('tmp_path', 'stage', 'source', 'trans', 'reviews', 'records', 'snapshot', 'es', 'rows', 'public', 'receipt'))
    out = tmp_path / 'candidate'
    result = m.prepare_candidate(stage, source, trans, reviews, records, snapshot, 'dev', [{'pageID': 'sermon-8', 'week': 8}], out)
    assert result['entries'][0] == es and result['entries'][1]['locale'] == 'ko'
    for row in rows:
        if row['path'] == '/weekly-guides/manifest-v2.json':
            continue
        assert (out / 'public' / row['path'].lstrip('/')).read_bytes() == (public / row['path'].lstrip('/')).read_bytes()
    new = result['entries'][1]
    assert v1.digest((out / 'public' / new['path'].lstrip('/')).read_bytes()) == new['sha256']
    assert json.loads((out / 'weekly-guide-v2-overlay-plan.json').read_bytes())['status'] == 'prepared_not_uploaded'
    assert json.loads((out / 'publish-config.json').read_bytes())['baseline_version'] == receipt['baselineVersion']
    with pytest.raises(ValueError, match='unsafe candidate'):
        m.prepare_candidate(stage, source, trans, reviews, records, snapshot, 'dev', [], out)


def test_frozen_bundle_week_mapping_checks_pinned_evidence_and_live_zh_release(context, monkeypatch):
    from tongxing_production.delivery import baseline
    c = context
    c['zh'].clear()
    zh_content = {'pageId': 'sermon-8', 'targetLocale': 'zh-Hans',
                  'englishSourcePackageJsonSha256': 'a' * 64, 'sourceMediaSha256': 'b' * 64, 'status': 'machine_checked', 'targetLanguageCandidateJsonSha256': 'f' * 64}
    zh_content_raw = v1.encoded(zh_content)
    zh_release = {'schemaVersion': 'sermon-target-language-release-package-v3', 'pageId': 'sermon-8',
                  'targetLocale': 'zh-Hans', 'englishSourcePackageJsonSha256': 'a' * 64, 'targetLanguageCandidateJsonSha256': 'f' * 64,
                  'status': 'published_http_verified', 'httpVerification': {'status': 'pass'}, 'contentStatus': 'machine_checked', 'audioStatus': 'machine_checked', 'issues': [],
                  'assets': [{'role': 'content', 'path': '/zh-content.json', 'sha256': v1.digest(zh_content_raw)}]}
    zh_release_raw = v1.encoded(zh_release)
    c['files']['/zh-content.json'] = zh_content_raw
    c['files']['/zh-release.json'] = zh_release_raw
    c['catalog']['pages'][0]['targets']['zh-Hans'] = {'contentStatus': 'machine_checked', 'audioStatus': 'machine_checked',
        'releasePackageUrl': '/zh-release.json', 'releasePackageJsonSha256': v1.digest(zh_release_raw)}
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    row = {'week': 8, 'pageID': 'sermon-8', 'locale': 'zh-Hans', 'editionId': 'sermon-8',
           'sourceIdentitySha256': 'a' * 64, 'releasePackageJsonSha256': v1.digest(zh_release_raw)}
    evidence = v1.encoded({'schemaVersion': 'tongxing-weekly-guide-identity-evidence-v1',
        'environments': {'dev': {'origin': baseline.hosting_target('dev')['origin'], 'v5': [row], 'legacy': []}}})
    monkeypatch.setattr(v1, 'BUNDLE_EVIDENCE_SHA256', v1.digest(evidence))
    def run(output, ev=evidence, binding=None):
        return m.prepare_fragment(c['stage'], c['source'], c['draft'], c['reviews'], c['records'], c['tmp'], 'dev',
            [binding or {'pageID': 'sermon-8', 'week': 8}], c['tmp'] / output, bundle_evidence_bytes=ev)
    assert run('bundle-ok')['entries'][0]['locale'] == 'ko'
    with pytest.raises(ValueError, match='hash mismatch'):
        run('bad-hash', evidence + b' ')
    with pytest.raises(ValueError, match='supported v5 family'):
        run('wrong-page', binding={'pageID': 'other-page', 'week': 8})
    c['files']['/zh-content.json'] = b'tampered'
    with pytest.raises(ValueError, match='content hash mismatch'):
        run('tampered-content')
    c['files']['/zh-content.json'] = zh_content_raw
    c['catalog']['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256'] = 'f' * 64
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    with pytest.raises(ValueError, match='bundle identity differs'):
        run('changed-release')
    c['catalog']['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256'] = v1.digest(zh_release_raw)
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    c['zh'].append({'pageID': 'sermon-8', 'week': 8, 'locale': 'zh-Hans', 'status': 'revoked'})
    assert run('zh-revoked')['entries'][0]['locale'] == 'ko'


def test_legacy_bundle_must_not_infer_v5_identity(context, monkeypatch):
    from tongxing_production.delivery import baseline
    c = context
    c['zh'].clear()
    source = {'id': 'sermon-8', 'sourceId': 'source', 'sourceUrl': 'https://example.test/source',
              'sourceSha256': 'b' * 64, 'sourceStartSeconds': 100, 'sourceEndSeconds': 200}
    c['files']['/weekly.json'] = v1.encoded({'weeks': [source]})
    legacy = {'week': 8, 'pageID': 'sermon-8', 'locale': 'zh-Hans', 'sourceIdentityComplete': True,
        'sourceIdSHA256': v1.digest(b'source'), 'sourceUrlSHA256': v1.digest(b'https://example.test/source'),
        'sourceMediaSHA256': 'b' * 64, 'sourceStartSeconds': 100, 'sourceEndSeconds': 200}
    evidence = v1.encoded({'schemaVersion': 'tongxing-weekly-guide-identity-evidence-v1',
        'environments': {'dev': {'origin': baseline.hosting_target('dev')['origin'], 'v5': [], 'legacy': [legacy]}}})
    monkeypatch.setattr(v1, 'BUNDLE_EVIDENCE_SHA256', v1.digest(evidence))
    with pytest.raises(ValueError, match='legacy bundle lacks a verified v5 source identity'):
        m.prepare_fragment(c['stage'], c['source'], c['draft'], c['reviews'], c['records'], c['tmp'], 'dev',
            [{'pageID': 'sermon-8', 'week': 8}], c['tmp'] / 'legacy', bundle_evidence_bytes=evidence)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'reverse', 'wrong_week', 'wrong_hash', 'wrong_id'])
def test_source_page_binding_rejects_corruption(context, mutation):
    c = context
    value = json.loads(c['draft'])
    guide = value['guides'][0]
    sections = guide['sections']
    if mutation == 'missing': sections.pop()
    elif mutation == 'duplicate': sections[1] = dict(sections[0], id='different')
    elif mutation == 'reverse': sections.reverse()
    elif mutation == 'wrong_week':
        guide['week'] = 7
        guide['scripture'] = m.scripture_for_week(7, 'ko')
    elif mutation == 'wrong_hash': sections[0]['sourcePageSHA256'] = '0' * 64
    elif mutation == 'wrong_id': sections[0]['sourcePageID'] = 'wrong'
    with pytest.raises(ValueError, match='source page'):
        m.staged_guides(c['source'], v1.encoded(value), c['reviews'], c['records'])


@pytest.mark.parametrize('field,changed', [('week', 7), ('locale', 'es'), ('translationSHA256', '0' * 64),
                                          ('guideSHA256', '0' * 64), ('sourceSHA256', '0' * 64),
                                          ('method', 'human'), ('decision', 'waived'), ('humanApproval', True)])
def test_review_evidence_must_match_week_locale_and_translation(context, field, changed):
    c = context
    value = json.loads(c['reviews'])
    value['reviews'][0][field] = changed
    with pytest.raises(ValueError, match='review evidence'):
        m.staged_guides(c['source'], c['draft'], v1.encoded(value), c['records'])


def test_review_record_bytes_must_match_separate_receipt(context):
    c = context
    receipt = json.loads(c['reviews'])['reviews'][0]
    (c['records'] / (receipt['reviewRecordSHA256'] + '.json')).write_bytes(b'changed')
    with pytest.raises(ValueError, match='review record hash'):
        m.staged_guides(c['source'], c['draft'], c['reviews'], c['records'])


@pytest.mark.parametrize('field,value', [('status', 'candidate'), ('httpVerification', {'status': 'fail'}),
                                         ('contentStatus', 'human_reviewed'), ('audioStatus', 'unavailable'),
                                         ('issues', ['unresolved'])])
def test_release_requires_published_http_and_catalog_status_consistency(context, field, value):
    c = context
    c['release'][field] = value
    raw = v1.encoded(c['release'])
    c['files']['/release.json'] = raw
    c['catalog']['pages'][0]['targets']['ko']['releasePackageJsonSha256'] = v1.digest(raw)
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    with pytest.raises(ValueError, match='publication, HTTP evidence or target status'):
        bind(c)


def test_four_product_join_validation_is_required(context, monkeypatch):
    from tongxing_production.delivery import contract
    c = context
    def reject(*args, **kwargs):
        raise ValueError('four-product join mismatch')
    monkeypatch.setattr(contract, 'validate_public_study', reject)
    with pytest.raises(ValueError, match='four-product join mismatch'):
        bind(c)


def test_real_v2_release_contract_rejects_http_evidence_and_content_join():
    page_id, locale = 'page-8', 'ko'
    sha = 'a' * 64
    content = {'pageId': page_id, 'targetLocale': locale, 'englishSourcePackageJsonSha256': sha,
               'sourceMediaSha256': sha, 'status': 'human_reviewed', 'targetLanguageCandidateJsonSha256': sha}
    content_raw = v1.encoded(content)
    release = {'schemaVersion': 'sermon-target-language-release-package-v2', 'packageId': 'page-8-ko',
        'pageId': page_id, 'sourceLocale': 'en', 'targetLocale': locale,
        'targetLanguageCandidateJsonSha256': sha, 'spokenTargetLanguageCandidateJsonSha256': sha,
        'targetLanguageAudioPackageJsonSha256': sha, 'status': 'published_http_verified',
        'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed', 'interfaceLocale': locale,
        'contentLocale': locale, 'audioLocale': locale, 'assets': [
            {'role': 'page', 'path': '/pages/page-8/ko/index.html', 'sha256': sha},
            {'role': 'content', 'path': '/content/page-8/ko.json', 'sha256': v1.digest(content_raw)},
            {'role': 'captions', 'path': '/captions/page-8/ko.json', 'sha256': sha},
            {'role': 'audio', 'path': '/media/page-8/ko.mp3', 'sha256': sha}],
        'httpVerification': {'status': 'pass', 'evidenceSha256': sha},
        'deviceAcceptance': {'status': 'not_run', 'evidenceSha256': None},
        'venueAcceptance': {'status': 'not_run', 'evidenceSha256': None}, 'issues': []}
    path = '/releases-v2/page-8/ko.json'
    target = {'releasePackageUrl': path, 'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed'}
    catalog = {'pages': [{'id': page_id, 'sourceIdentitySha256': sha, 'sourceMediaSha256': sha, 'targets': {locale: target}}]}
    files = {'/content/page-8/ko.json': content_raw}
    def set_release():
        files[path] = v1.encoded(release)
        target['releasePackageJsonSha256'] = v1.digest(files[path])
    set_release()
    assert m._target(catalog, page_id, locale, files.__getitem__)[0] == page_id
    release['httpVerification'].pop('evidenceSha256')
    set_release()
    with pytest.raises(ValidationError):
        m._target(catalog, page_id, locale, files.__getitem__)
    release['httpVerification']['evidenceSha256'] = sha
    content['targetLanguageCandidateJsonSha256'] = 'b' * 64
    files['/content/page-8/ko.json'] = v1.encoded(content)
    release['assets'][1]['sha256'] = v1.digest(files['/content/page-8/ko.json'])
    set_release()
    with pytest.raises(ValueError, match='candidate identity'):
        m._target(catalog, page_id, locale, files.__getitem__)


@pytest.mark.parametrize('locale', ['ko', 'es'])
def test_all_weekly_scripture_labels_are_canonical(locale):
    label = '요한계시록' if locale == 'ko' else 'Apocalipsis'
    assert m.scripture_for_week(1, locale) == f'{label} 1:1–20'
    assert m.scripture_for_week(4, locale) == f'{label} 6:1–8:1'
    assert m.scripture_for_week(5, locale) == f'{label} 8:1–9:21'
    assert m.scripture_for_week(10, locale) == f'{label} 17:1–19:10'
    assert m.scripture_for_week(11, locale) == f'{label} 19:11–21:8'
    assert m.scripture_for_week(12, locale) == f'{label} 21:9–22:21'
    assert len({m.scripture_for_week(n, locale) for n in range(1, 13)}) == 12


@pytest.mark.parametrize('scripture', ['요한계시록 13:1–18', '창세기 14:1–20', 'Apocalipsis 14:1–20',
                                      '요한계시록 14:2–20', '요한계시록 14:1–19', '요한계시록 14:1–15:20'])
def test_unverified_wrong_week_book_language_or_boundary_is_never_displayed(context, scripture):
    c = context
    value = json.loads(c['draft'])
    value['guides'][0]['scripture'] = scripture
    with pytest.raises(ValueError, match='scripture does not match'):
        m.staged_guides(c['source'], v1.encoded(value), c['reviews'], c['records'])


def test_existing_public_payload_cannot_carry_wrong_scripture_even_if_rehashed(context):
    c = context
    entry = bind(c)['entries'][0]
    raw = (c['tmp'] / 'out/published' / (entry['sha256'] + '.json')).read_bytes()
    value = json.loads(raw)
    value['scripture'] = '요한계시록 13:1–18'
    changed = v1.encoded(value)
    sha = v1.digest(changed)
    entry = {**entry, 'sha256': sha, 'bytes': len(changed), 'path': f'/weekly-guides/published/{sha}.json'}
    with pytest.raises(ValueError, match='scripture does not match'):
        m._content_valid(entry, changed)


@pytest.mark.parametrize('field', ['title', 'section_title', 'subtitle', 'body'])
def test_staging_rejects_known_internal_placeholder_in_display_text(context, field):
    c = context
    value = json.loads(c['draft'])
    guide = value['guides'][0]
    marker = '[original graphic/table requires visual review]'
    if field == 'title':
        guide['title'] = marker
    else:
        key = 'title' if field == 'section_title' else field
        guide['sections'][0][key] = 'Before ' + marker + ' after'
    with pytest.raises(ValueError, match='internal guide placeholder'):
        m.staged_guides(c['source'], v1.encoded(value), c['reviews'], c['records'])


def test_existing_payload_rejects_known_internal_placeholder_even_if_rehashed(context):
    c = context
    entry = bind(c)['entries'][0]
    raw = (c['tmp'] / 'out/published' / (entry['sha256'] + '.json')).read_bytes()
    guide = json.loads(raw)
    guide['sections'][0]['body'] = 'Before [Original graphic/table requires visual review] after'
    changed = v1.encoded(guide)
    sha = v1.digest(changed)
    entry = {**entry, 'sha256': sha, 'bytes': len(changed), 'path': f'/weekly-guides/published/{sha}.json'}
    with pytest.raises(ValueError, match='internal guide placeholder'):
        m._content_valid(entry, changed)
    manifest_path = '/weekly-guides/manifest-v2.json'
    files = {manifest_path: v1.encoded({'schemaVersion': 'tongxing-weekly-guide-manifest-v2',
                                       'seriesID': v1.SERIES_ID, 'entries': [entry]}),
             entry['path']: changed}
    with pytest.raises(ValueError, match='internal guide placeholder'):
        m.existing_v2(files, files.__getitem__)


def test_normal_graphic_reference_and_natural_language_are_not_blocked(context):
    c = context
    value = json.loads(c['draft'])
    value['guides'][0]['sections'][0]['body'] = (
        '그래픽은 원본 안내서를 참조하세요. Refer to the original graphic for a visual review.'
    )
    trans = v1.encoded(value)
    reviews = reviews_for(c['source'], trans, c['records'])
    staged = m.staged_guides(c['source'], trans, reviews, c['records'])
    assert staged[0]['sections'][0]['body'] == value['guides'][0]['sections'][0]['body']


def test_per_target_bundle_family_binds_separate_sources_but_not_other_family(context, monkeypatch):
    from tongxing_production.delivery import baseline
    c = context
    c['zh'].clear()
    p = c['catalog']['pages'][0]
    p['sourceMode'] = 'per_target'
    p['targets']['ko'].update(sourceIdentitySha256='a'*64, sourceMediaSha256='b'*64)
    zh_content = {'pageId': 'zh-edition', 'targetLocale': 'zh-Hans',
                  'englishSourcePackageJsonSha256': 'c'*64, 'sourceMediaSha256': 'd'*64,
                  'status': 'machine_checked', 'targetLanguageCandidateJsonSha256': 'f'*64}
    zh_content_raw = v1.encoded(zh_content)
    zh_release = {'schemaVersion': 'sermon-target-language-release-package-v3', 'pageId': 'zh-edition',
                  'targetLocale': 'zh-Hans', 'englishSourcePackageJsonSha256': 'c'*64,
                  'targetLanguageCandidateJsonSha256': 'f'*64, 'status': 'published_http_verified',
                  'httpVerification': {'status': 'pass'}, 'contentStatus': 'machine_checked',
                  'audioStatus': 'machine_checked', 'issues': [],
                  'assets': [{'role': 'content', 'path': '/zh-content.json', 'sha256': v1.digest(zh_content_raw)}]}
    zh_raw = v1.encoded(zh_release)
    p['targets']['zh-Hans'] = {'editionId': 'zh-edition', 'sourceIdentitySha256': 'c'*64,
        'sourceMediaSha256': 'd'*64, 'contentStatus': 'machine_checked', 'audioStatus': 'machine_checked',
        'releasePackageUrl': '/zh-release.json', 'releasePackageJsonSha256': v1.digest(zh_raw)}
    c['files']['/zh-release.json'] = zh_raw
    c['files']['/zh-content.json'] = zh_content_raw
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    row = {'week': 8, 'pageID': 'sermon-8', 'locale': 'zh-Hans', 'editionId': 'zh-edition',
           'sourceIdentitySha256': 'c'*64, 'releasePackageJsonSha256': v1.digest(zh_raw)}
    evidence = v1.encoded({'schemaVersion': 'tongxing-weekly-guide-identity-evidence-v1',
        'environments': {'dev': {'origin': baseline.hosting_target('dev')['origin'], 'v5': [row], 'legacy': []}}})
    monkeypatch.setattr(v1, 'BUNDLE_EVIDENCE_SHA256', v1.digest(evidence))
    def run(name, page='sermon-8'):
        return m.prepare_fragment(c['stage'], c['source'], c['draft'], c['reviews'], c['records'], c['tmp'], 'dev',
            [{'pageID': page, 'week': 8}], c['tmp'] / name, bundle_evidence_bytes=evidence)
    entry = run('distinct')['entries'][0]
    assert entry['editionId'] == 'edition-8' and entry['sourceIdentitySha256'] == 'a'*64
    assert entry['sourceIdentitySha256'] != row['sourceIdentitySha256']
    wrong_family = dict(p, id='other-family')
    c['catalog']['pages'].append(wrong_family)
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    with pytest.raises(ValueError, match='unique frozen bundle identity'):
        run('wrong-family', 'other-family')
    c['release']['targetLocale'] = 'es'
    bad_raw = v1.encoded(c['release'])
    c['files']['/release.json'] = bad_raw
    p['targets']['ko']['releasePackageJsonSha256'] = v1.digest(bad_raw)
    c['files']['/multilingual-v5.json'] = v1.encoded(c['catalog'])
    with pytest.raises(ValueError, match='release locale identity'):
        run('wrong-locale')


@pytest.fixture
def batch_context(guarded_context, monkeypatch):
    from tongxing_production.delivery import baseline, contract
    import shutil
    c = guarded_context
    tmp, public, snapshot = c['tmp_path'], c['public'], c['snapshot']
    source = c['source']
    catalog = c['catalog']
    monkeypatch.setattr(contract, 'release_path', lambda r: f"/release-{r['pageId']}-{r['targetLocale']}.json")
    def target(page, edition, locale):
        content = {'pageId': edition, 'targetLocale': locale, 'englishSourcePackageJsonSha256': 'a'*64,
                   'sourceMediaSha256': 'b'*64, 'status': 'machine_checked', 'targetLanguageCandidateJsonSha256': 'f'*64}
        cr = v1.encoded(content)
        content_path = f'/content-{edition}-{locale}.json'
        (public / content_path[1:]).write_bytes(cr)
        release = {'schemaVersion': 'sermon-target-language-release-package-v3', 'pageId': edition, 'targetLocale': locale,
            'englishSourcePackageJsonSha256': 'a'*64, 'targetLanguageCandidateJsonSha256': 'f'*64,
            'status': 'published_http_verified', 'httpVerification': {'status': 'pass'}, 'contentStatus': 'machine_checked',
            'audioStatus': 'machine_checked', 'issues': [], 'assets': [{'role':'content','path':content_path,'sha256':v1.digest(cr)}]}
        rr = v1.encoded(release); release_path = f'/release-{edition}-{locale}.json'
        (public / release_path[1:]).write_bytes(rr)
        return {'editionId':edition,'contentStatus':'machine_checked','audioStatus':'machine_checked',
                'releasePackageUrl':release_path,'releasePackageJsonSha256':v1.digest(rr)}
    catalog['pages'][0]['targets'] = {'ko':target('sermon-8','edition-8','ko'), 'es':target('sermon-8','edition-8','es')}
    catalog['pages'].append({'id':'sermon-9','sourceMode':'single_source','sourceIdentitySha256':'a'*64,
                             'sourceMediaSha256':'b'*64,'targets':{'ko':target('sermon-9','edition-9','ko')}})
    (public/'multilingual-v5.json').write_bytes(v1.encoded(catalog))
    oldop = c['op']
    op9 = {**oldop, 'pageID':'sermon-9', 'week':9, 'editionId':'sermon-9',
           'guide':{**oldop['guide'],'id':'sermon-9','week':9}}
    v1.write_published([oldop,op9], tmp/'v1-batch', [], {})
    shutil.copytree(tmp/'v1-batch/published',public/'weekly-guides/published',dirs_exist_ok=True)
    shutil.copyfile(tmp/'v1-batch/manifest-v1.json',public/'weekly-guides/manifest-v1.json')
    seal={**baseline.catalog_report(public),'files':baseline.files_report(public)}
    (snapshot/'seal-report.json').write_bytes(v1.encoded(seal))
    receipt=c['receipt'];receipt['catalogSha256']=seal['catalogSha256'];receipt['rows']=[{'path':r['path'],'rawBytes':r['bytes'],'rawSha256':r['sha256'],'managed':False} for r in seal['files']]
    (snapshot/'baseline-receipt.json').write_bytes(v1.encoded(receipt))
    def make_input(locale, week, page, operation='add'):
        value=json.loads(draft(locale));guide=value['guides'][0];guide['week']=week;guide['scripture']=m.scripture_for_week(week,locale)
        first,last,appendix=m.WEEK_PAGES[week];pages=m._source_pages(source)
        guide['sections']=[{'id':f'page-{n}','title':'sample','subtitle':'','symbol':'book','body':'synthetic',
            'sourcePage':n,'sourcePageID':pages[n][0],'sourcePageSHA256':pages[n][1]} for n in [*range(first,last+1),*appendix]]
        dr=v1.encoded(value);records=tmp/f'records-{locale}-{week}';reviews=reviews_for(source,dr,records)
        staging=tmp/f'stage-{locale}-{week}';m.prepare_stage(source,dr,reviews,records,staging)
        binding={'pageID':page,'week':week,'operation':operation}
        if operation=='update':binding.update(expectedEntrySha256=v1.digest(v1.encoded(c['es'])),reason='synthetic update')
        return {'source':source,'draft':dr,'reviews':reviews,'review_records':records,'staging':staging,'bindings':[binding]}
    return {**c,'make_input':make_input}


def test_batch_multiple_weeks_and_locales_preserves_every_baseline_asset(batch_context):
    c=batch_context;inputs=[c['make_input']('ko',8,'sermon-8'),c['make_input']('es',8,'sermon-8','update'),
                            c['make_input']('ko',9,'sermon-9')]
    out=c['tmp_path']/'batch';result=m.prepare_batch_candidate(inputs,c['snapshot'],'dev',out)
    entries={(e['pageID'],e['locale']):e for e in result['entries']}
    assert set(entries)=={('sermon-8','es'),('sermon-8','ko'),('sermon-9','ko')}
    assert entries[('sermon-8','es')]['sha256'] != c['es']['sha256']
    for e in entries.values():
        raw=(out/'public'/e['path'].lstrip('/')).read_bytes()
        assert v1.digest(raw)==e['sha256']
    for row in c['receipt']['rows']:
        if row['path']=='/weekly-guides/manifest-v2.json':continue
        assert (out/'public'/row['path'].lstrip('/')).read_bytes()==(c['public']/row['path'].lstrip('/')).read_bytes()
    plan=json.loads((out/'weekly-guide-v2-overlay-plan.json').read_bytes())
    assert plan['status']=='prepared_not_uploaded' and plan['liveRecheck']=='required_before_deploy'
    assert (out/'baseline-receipt.json').read_bytes()==(c['snapshot']/'baseline-receipt.json').read_bytes()


def test_batch_rejects_duplicate_identity_and_stale_update(batch_context):
    c=batch_context;ko=c['make_input']('ko',8,'sermon-8');es=c['make_input']('es',8,'sermon-8','update')
    with pytest.raises(ValueError,match='duplicate batch page and locale'):
        m.prepare_batch_candidate([ko,ko],c['snapshot'],'dev',c['tmp_path']/'duplicate')
    es['bindings'][0]['expectedEntrySha256']='0'*64
    with pytest.raises(ValueError,match='prior identity and reason'):
        m.prepare_batch_candidate([ko,es],c['snapshot'],'dev',c['tmp_path']/'stale')
    assert (c['tmp_path']/'stale/public/weekly-guides/manifest-v2.json').read_bytes()==(c['snapshot']/'public/weekly-guides/manifest-v2.json').read_bytes()


def test_batch_rejects_one_bad_evidence_without_applying_any_fragment(batch_context):
    c=batch_context;ko=c['make_input']('ko',8,'sermon-8');other=c['make_input']('ko',9,'sermon-9')
    review=json.loads(other['reviews']);review['reviews'][0]['translationSHA256']='0'*64
    other['reviews']=v1.encoded(review)
    out=c['tmp_path']/'bad-review'
    with pytest.raises(ValueError,match='review evidence'):
        m.prepare_batch_candidate([ko,other],c['snapshot'],'dev',out)
    assert (out/'public/weekly-guides/manifest-v2.json').read_bytes()==(c['snapshot']/'public/weekly-guides/manifest-v2.json').read_bytes()


def test_batch_revoke_is_scoped_and_requires_previous_hash(batch_context):
    c=batch_context;ko=c['make_input']('ko',8,'sermon-8');es=c['make_input']('es',8,'sermon-8')
    es['bindings'][0].update(operation='revoke',expectedEntrySha256=v1.digest(v1.encoded(c['es'])),reason='synthetic withdrawal')
    result=m.prepare_batch_candidate([ko,es],c['snapshot'],'dev',c['tmp_path']/'revoked-batch')
    entries={(e['pageID'],e['locale']):e for e in result['entries']}
    assert entries[('sermon-8','es')]['status']=='revoked' and entries[('sermon-8','ko')]['status']=='available'
    old=c['es'];assert (c['tmp_path']/'revoked-batch/public'/old['path'].lstrip('/')).read_bytes()==(c['public']/old['path'].lstrip('/')).read_bytes()
    es['bindings'][0]['expectedEntrySha256']='0'*64
    with pytest.raises(ValueError,match='prior identity and reason'):
        m.prepare_batch_candidate([ko,es],c['snapshot'],'dev',c['tmp_path']/'revoked-stale')


def test_batch_cli_resolves_plan_paths_and_passes_explicit_evidence(tmp_path, monkeypatch, capsys):
    root=tmp_path/'plan-root';root.mkdir()
    for name in ('source','draft','reviews','bundle','alias'):(root/name).write_bytes(name.encode())
    (root/'records').mkdir();(root/'stage').mkdir()
    plan={'schemaVersion':'tongxing-weekly-guide-batch-v1','inputs':[{'source':'source','draft':'draft',
        'reviews':'reviews','reviewRecords':'records','staging':'stage','bindings':[{'pageID':'p','week':1}],
        'bundleEvidence':'bundle','aliasEvidence':'alias'}]}
    (root/'plan.json').write_bytes(v1.encoded(plan))
    called=[]
    monkeypatch.setattr(v1,'safe_output',lambda p:p)
    monkeypatch.setattr(m,'prepare_batch_candidate',lambda items,snapshot,env,out: called.append((items,snapshot,env,out)) or {'entries':[]})
    assert m.main(['batch-candidate','--plan',str(root/'plan.json'),'--snapshot',str(root),'--environment','dev','--output',str(root/'out')])==0
    items,snapshot,env,out=called[0];assert items[0]['draft']==b'draft' and items[0]['bundle_evidence_bytes']==b'bundle'
    assert items[0]['alias_evidence_bytes']==b'alias' and items[0]['review_records']==root/'records'
    assert env=='dev' and json.loads(capsys.readouterr().out)['status']=='prepared_not_uploaded'


@pytest.mark.parametrize('kind', ['file-matching', 'file-different', 'extra-file', 'directory', 'public-root'])
def test_batch_rejects_all_public_symlinks_before_copy(batch_context, monkeypatch, kind):
    c=batch_context;source=c['public'];tmp=c['tmp_path'];outside=tmp/'outside';outside.mkdir()
    if kind.startswith('file-'):
        target=source/'other.json';payload=target.read_bytes() if kind=='file-matching' else b'not the original'
        (outside/'payload').write_bytes(payload);target.unlink();target.symlink_to(outside/'payload')
    elif kind=='extra-file':
        (outside/'payload').write_bytes(b'extra');(source/'unlisted').symlink_to(outside/'payload')
    elif kind=='directory':
        (outside/'payload').write_bytes(b'extra');(source/'unlisted-directory').symlink_to(outside,target_is_directory=True)
    else:
        import shutil
        shutil.copytree(source,outside/'public');shutil.rmtree(source);source.symlink_to(outside/'public',target_is_directory=True)
    monkeypatch.setattr(m.shutil,'copytree',lambda *a,**k:pytest.fail('must not copy before rejecting link'))
    item=c['make_input']('ko',8,'sermon-8');out=tmp/'unsafe'
    with pytest.raises(ValueError,match='symlink'):
        m.prepare_batch_candidate([item],c['snapshot'],'dev',out)
    assert not out.exists()


@pytest.mark.parametrize('status', ['outcome_unknown','deployed','rebuild_required'])
def test_uncertain_source_attempt_is_not_silently_discarded(batch_context,monkeypatch,status):
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');attempt=c['snapshot']/'deployment-attempt-v2.json'
    attempt.write_bytes(v1.encoded({'status':status,'baselineVersion':c['receipt']['baselineVersion'],'newVersion':None}))
    monkeypatch.setattr(m.shutil,'copytree',lambda *a,**k:pytest.fail('must not copy before attempt reconciliation'))
    out=c['tmp_path']/'unknown-attempt'
    with pytest.raises(ValueError,match='uncertain or differs'):
        m.prepare_batch_candidate([item],c['snapshot'],'dev',out)
    assert not out.exists() and json.loads(attempt.read_bytes())['status']==status


def test_revoke_only_needs_live_manifest_and_never_creates_body(batch_context):
    c=batch_context
    binding={'pageID':'sermon-8','operation':'revoke','expectedEntrySha256':v1.digest(v1.encoded(c['es'])),
             'reason':'withdraw stale guide'}
    revoke={'locale':'es','bindings':[binding]}
    out=c['tmp_path']/'revoke-only';result=m.prepare_batch_candidate([revoke],c['snapshot'],'dev',out)
    assert len(result['entries'])==1 and result['entries'][0]['status']=='revoked'
    assert list((out/'guide-v2-fragments/0000/published').iterdir())==[]
    old=c['es'];assert (out/'public'/old['path'].lstrip('/')).read_bytes()==(c['public']/old['path'].lstrip('/')).read_bytes()
    binding['expectedEntrySha256']='0'*64
    with pytest.raises(ValueError,match='prior identity'):
        m.prepare_batch_candidate([revoke],c['snapshot'],'dev',c['tmp_path']/'revoke-wrong-sha')
    binding['expectedEntrySha256']=v1.digest(v1.encoded(old));binding['reason']=''
    with pytest.raises(ValueError,match='prior identity'):
        m.prepare_batch_candidate([revoke],c['snapshot'],'dev',c['tmp_path']/'revoke-no-reason')
    binding['reason']='reason';binding['operation']='add'
    with pytest.raises(ValueError,match='only explicit revocations'):
        m.prepare_batch_candidate([revoke],c['snapshot'],'dev',c['tmp_path']/'revoke-add')
    binding['operation']='revoke';revoke['draft']=b'injected'
    with pytest.raises(ValueError,match='cannot contain draft'):
        m.prepare_batch_candidate([revoke],c['snapshot'],'dev',c['tmp_path']/'revoke-injected')


def test_batch_revoke_only_mixes_with_verified_add(batch_context):
    c=batch_context;ko=c['make_input']('ko',9,'sermon-9')
    revoke={'locale':'es','bindings':[{'pageID':'sermon-8','operation':'revoke',
        'expectedEntrySha256':v1.digest(v1.encoded(c['es'])),'reason':'withdraw'}]}
    result=m.prepare_batch_candidate([ko,revoke],c['snapshot'],'dev',c['tmp_path']/'mixed')
    entries={(e['pageID'],e['locale']):e for e in result['entries']}
    assert entries[('sermon-8','es')]['status']=='revoked' and entries[('sermon-9','ko')]['status']=='available'


def test_batch_generated_publish_config_refuses_stale_live_version(batch_context):
    from scripts import tongxing_host  # noqa: F401
    from tongxing_production.delivery import publication
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');out=c['tmp_path']/'publish-candidate'
    m.prepare_batch_candidate([item],c['snapshot'],'dev',out)
    config=json.loads((out/'publish-config.json').read_bytes());site=config['intent']['site'];calls=[]
    def request(method,url,**kwargs):
        if '/channels/live' in url:return {'release':{'version':{'name':f'sites/{site}/versions/newer'}}}
        if method=='POST':return {'generation':'5'}
        if method=='DELETE':calls.append('lease-released');return {}
        if method=='GET':return {'generation':'5'}
        raise AssertionError((method,url))
    def run(*args,**kwargs):pytest.fail('stale baseline must never deploy')
    with pytest.raises(ValueError,match='Live version changed'):
        publication.publish(out,intent=config['intent'],routes=config['routes'],baseline_version=config['baseline_version'],
            baseline_catalog_sha=config['baseline_catalog_sha'],baseline_catalog_v4_sha=config['baseline_catalog_v4_sha'],
            baseline_catalog_v5_sha=config['baseline_catalog_v5_sha'],lease_bucket=config['lease_bucket'],
            request=request,reader=lambda _: (200,b''),run=run)
    assert json.loads((out/'deployment-attempt-v2.json').read_bytes())['status']=='rebuild_required'
    assert calls==['lease-released']


@pytest.mark.parametrize('resource', ['missing', 'tampered'])
def test_revocation_does_not_require_old_resource_even_in_mixed_batch(batch_context, resource):
    from tongxing_production.delivery import baseline
    c=batch_context;asset=c['public']/c['es']['path'].lstrip('/')
    if resource=='missing':asset.unlink()
    else:asset.write_bytes(b'invalid old content')
    seal={**baseline.catalog_report(c['public']),'files':baseline.files_report(c['public'])}
    (c['snapshot']/'seal-report.json').write_bytes(v1.encoded(seal))
    receipt=c['receipt'];receipt['catalogSha256']=seal['catalogSha256'];receipt['rows']=[{'path':r['path'],'rawBytes':r['bytes'],
        'rawSha256':r['sha256'],'managed':False} for r in seal['files']]
    (c['snapshot']/'baseline-receipt.json').write_bytes(v1.encoded(receipt))
    ko=c['make_input']('ko',9,'sermon-9')
    revoke={'locale':'es','bindings':[{'pageID':'sermon-8','operation':'revoke',
        'expectedEntrySha256':v1.digest(v1.encoded(c['es'])),'reason':'remove invalid resource'}]}
    out=c['tmp_path']/'missing-or-bad-resource'
    result=m.prepare_batch_candidate([ko,revoke],c['snapshot'],'dev',out)
    entries={(e['pageID'],e['locale']):e for e in result['entries']}
    assert entries[('sermon-8','es')]['status']=='revoked' and entries[('sermon-9','ko')]['status']=='available'
    assert list((out/'guide-v2-fragments/0001/published').iterdir())==[]


def test_symlink_introduced_after_scan_is_rejected_without_following(batch_context, monkeypatch):
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');out=c['tmp_path']/'raced'
    outside=c['tmp_path']/'outside-race';outside.write_bytes(b'sensitive')
    original=m._scan_public_fd
    def raced_scan(fd):
        original(fd)
        (c['public']/'race-link').symlink_to(outside)
    monkeypatch.setattr(m,'_scan_public_fd',raced_scan)
    with pytest.raises(ValueError,match='symlink'):
        m.prepare_batch_candidate([item],c['snapshot'],'dev',out)
    assert not (out/'public/race-link').exists()


@pytest.mark.parametrize('risk', ['symlink','unknown-attempt'])
def test_single_candidate_uses_same_precopy_guards(guarded_context,risk):
    c=guarded_context;out=c['tmp_path']/f'single-{risk}'
    if risk=='symlink':
        outside=c['tmp_path']/'outside';outside.write_bytes(b'external')
        (c['public']/'extra-symlink').symlink_to(outside)
        expected='symlink'
    else:
        (c['snapshot']/'deployment-attempt-v2.json').write_bytes(v1.encoded({'status':'outcome_unknown'}))
        expected='uncertain or differs'
    with pytest.raises(ValueError,match=expected):
        m.prepare_candidate(c['stage'],c['source'],c['trans'],c['reviews'],c['records'],c['snapshot'],'dev',
            [{'pageID':'sermon-8','week':8}],out)
    assert not out.exists()


def test_public_root_swapped_to_symlink_after_scan_is_not_followed(batch_context,monkeypatch):
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');out=c['tmp_path']/'root-race'
    outside=c['tmp_path']/'outside-root';outside.mkdir();(outside/'private').write_bytes(b'sensitive')
    original=m._scan_public_fd
    def raced_scan(fd):
        original(fd)
        c['public'].rename(c['tmp_path']/'displaced-public')
        c['public'].symlink_to(outside,target_is_directory=True)
    monkeypatch.setattr(m,'_scan_public_fd',raced_scan)
    m.prepare_batch_candidate([item],c['snapshot'],'dev',out)
    assert not (out/'public/private').exists()


def test_batch_cli_accepts_revoke_only_without_any_draft_paths(tmp_path,monkeypatch,capsys):
    plan={'schemaVersion':'tongxing-weekly-guide-batch-v1','inputs':[{'locale':'es','bindings':[{'pageID':'p',
        'operation':'revoke','expectedEntrySha256':'a'*64,'reason':'withdraw'}]}]}
    path=tmp_path/'plan.json';path.write_bytes(v1.encoded(plan));called=[]
    monkeypatch.setattr(v1,'safe_output',lambda p:p)
    monkeypatch.setattr(m,'prepare_batch_candidate',lambda items,*args: called.extend(items) or {'entries':[]})
    assert m.main(['batch-candidate','--plan',str(path),'--snapshot',str(tmp_path),'--environment','dev',
                   '--output',str(tmp_path/'out')])==0
    assert called==plan['inputs'] and json.loads(capsys.readouterr().out)['status']=='prepared_not_uploaded'


@pytest.mark.parametrize('defect', ['review','humanApproval','sourceSHA256','path','bytes','legacy'])
def test_revoke_damaged_optional_metadata_produces_minimal_decodable_tombstone(batch_context, defect):
    from tongxing_production.delivery import baseline
    c=batch_context;bad=dict(c['es'])
    bad[defect]={'unexpected':'type'}
    mf=c['public']/'weekly-guides/manifest-v2.json'
    mf.write_bytes(v1.encoded({'schemaVersion':'tongxing-weekly-guide-manifest-v2','seriesID':v1.SERIES_ID,'entries':[bad]}))
    seal={**baseline.catalog_report(c['public']),'files':baseline.files_report(c['public'])}
    (c['snapshot']/'seal-report.json').write_bytes(v1.encoded(seal))
    c['receipt']['rows']=[{'path':r['path'],'rawBytes':r['bytes'],'rawSha256':r['sha256'],'managed':False} for r in seal['files']]
    (c['snapshot']/'baseline-receipt.json').write_bytes(v1.encoded(c['receipt']))
    binding={'pageID':'sermon-8','operation':'revoke','expectedEntrySha256':v1.digest(v1.encoded(bad)),'reason':'unsafe metadata'}
    out=c['tmp_path']/'repair';result=m.prepare_batch_candidate([{'locale':'es','bindings':[binding]}],c['snapshot'],'dev',out)
    assert result['entries']==[{k:bad[k] for k in ('pageID','locale','week','editionId','sourceIdentitySha256','releasePackageJsonSha256')}|{'status':'revoked'}]
    entry=json.loads((out/'public/weekly-guides/manifest-v2.json').read_bytes())['entries'][0]
    assert set(entry)=={'pageID','locale','week','editionId','sourceIdentitySha256','releasePackageJsonSha256','status'}
    assert isinstance(entry['week'],int) and all(isinstance(entry[k],str) for k in entry if k!='week')
    plan=json.loads((out/'weekly-guide-v2-overlay-plan.json').read_bytes())
    assert plan['operations'][0]['expectedEntrySha256']==binding['expectedEntrySha256'] and plan['operations'][0]['reason']==binding['reason']
    if defect=='bytes':
        # Compile the actual app's private Decodable entry definitions in a
        # tiny Foundation harness: the old malformed optional value must fail,
        # while the minimal server tombstone must decode across the manifest.
        import re, shutil, subprocess
        swift=shutil.which('swift')
        if swift:
            app=(Path(__file__).resolve().parents[1]/'apps/tongxing-ios/App/WeeklyGuideData.swift').read_text()
            definitions=[]
            for name in ('Entry','LegacyEntry'):
                match=re.search(r'private struct '+name+r': Decodable \{[^}]+\}',app)
                assert match
                definitions.append(match.group().replace('private struct','struct',1))
            program='import Foundation\n'+'\n'.join(definitions)+'''\nfunc canDecode(_ path: String) -> Bool {
    guard let bytes = try? Data(contentsOf: URL(fileURLWithPath: path)),
          let object = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any],
          let entries = object["entries"] as? [[String: Any]] else { return false }
    return entries.allSatisfy { entry in
        guard let data = try? JSONSerialization.data(withJSONObject: entry) else { return false }
        return (try? JSONDecoder().decode(Entry.self, from: data)) != nil
    }
}
guard !canDecode(CommandLine.arguments[1]), canDecode(CommandLine.arguments[2]) else { exit(1) }
'''
            script=c['tmp_path']/'decode.swift';script.write_text(program)
            completed=subprocess.run([swift,str(script),str(mf),str(out/'public/weekly-guides/manifest-v2.json')],
                                     capture_output=True,text=True,timeout=60)
            assert completed.returncode==0, completed.stderr


def test_revoke_minimal_validation_rejects_bad_identity_and_duplicate(batch_context):
    from tongxing_production.delivery import baseline
    c=batch_context;bad={**c['es'],'sourceIdentitySha256':'bad'}
    mf=c['public']/'weekly-guides/manifest-v2.json'
    def reseal(rows):
        mf.write_bytes(v1.encoded({'schemaVersion':'tongxing-weekly-guide-manifest-v2','seriesID':v1.SERIES_ID,'entries':rows}))
        seal={**baseline.catalog_report(c['public']),'files':baseline.files_report(c['public'])}
        (c['snapshot']/'seal-report.json').write_bytes(v1.encoded(seal))
        c['receipt']['rows']=[{'path':r['path'],'rawBytes':r['bytes'],'rawSha256':r['sha256'],'managed':False} for r in seal['files']]
        (c['snapshot']/'baseline-receipt.json').write_bytes(v1.encoded(c['receipt']))
    revoke=lambda entry:{'locale':'es','bindings':[{'pageID':'sermon-8','operation':'revoke',
                    'expectedEntrySha256':v1.digest(v1.encoded(entry)),'reason':'withdraw'}]}
    reseal([bad])
    with pytest.raises(ValueError,match='invalid v2 entry'):
        m.prepare_batch_candidate([revoke(bad)],c['snapshot'],'dev',c['tmp_path']/'bad-identity')
    reseal([c['es'],c['es']])
    with pytest.raises(ValueError,match='duplicate v2 identity'):
        m.prepare_batch_candidate([revoke(c['es'])],c['snapshot'],'dev',c['tmp_path']/'duplicate-existing')


def test_snapshot_lock_is_same_as_publisher_lock(batch_context):
    from tongxing_production.delivery import publication
    c=batch_context;item=c['make_input']('ko',8,'sermon-8')
    with publication.publisher_lock(c['snapshot']):
        with pytest.raises(ValueError,match='Publisher is still running'):
            m.prepare_batch_candidate([item],c['snapshot'],'dev',c['tmp_path']/'locked')
    assert not (c['tmp_path']/'locked').exists()


@pytest.mark.parametrize('swap', ['snapshot','ancestor'])
def test_snapshot_or_ancestor_swapped_after_scan_uses_pinned_original(batch_context,monkeypatch,swap):
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');tmp=c['tmp_path'];snapshot=c['snapshot']
    if swap=='ancestor':
        scope=tmp/'scope';scope.mkdir();snapshot.rename(scope/'snapshot');snapshot=scope/'snapshot';victim=scope
    else:victim=snapshot
    outside=tmp/'evil';outside.mkdir();(outside/'secret').write_bytes(b'external data')
    original=m._scan_public_fd
    def raced(fd):
        original(fd)
        victim.rename(tmp/'displaced')
        victim.symlink_to(outside,target_is_directory=True)
    monkeypatch.setattr(m,'_scan_public_fd',raced)
    out=tmp/'pinned-result';result=m.prepare_batch_candidate([item],snapshot,'dev',out)
    assert any(e['locale']=='ko' for e in result['entries'])
    assert (out/'public/other.json').read_bytes()==b'keep unrelated bytes'
    assert not (out/'public/secret').exists()


def test_file_swapped_to_fifo_during_copy_cannot_block(batch_context,monkeypatch):
    import os
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');original=os.open;changed=[]
    def raced_open(path,flags,*args,**kwargs):
        if path=='other.json' and kwargs.get('dir_fd') is not None and not changed:
            assert flags & os.O_NONBLOCK
            (c['public']/'other.json').unlink();os.mkfifo(c['public']/'other.json');changed.append(True)
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(m.os,'open',raced_open)
    with pytest.raises(ValueError,match='public file changed'):
        m.prepare_batch_candidate([item],c['snapshot'],'dev',c['tmp_path']/'fifo')
    assert changed


def test_snapshot_ancestor_swapped_before_fd_walk_fails_closed(batch_context,monkeypatch):
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');tmp=c['tmp_path'];scope=tmp/'scope'
    scope.mkdir();c['snapshot'].rename(scope/'snapshot');outside=tmp/'external';outside.mkdir()
    original=m._pinned_snapshot
    def raced(path):
        scope.rename(tmp/'displaced-scope')
        scope.symlink_to(outside,target_is_directory=True)
        return original(path)
    monkeypatch.setattr(m,'_pinned_snapshot',raced)
    with pytest.raises(ValueError,match='symlink'):
        m.prepare_batch_candidate([item],scope/'snapshot','dev',tmp/'no-output')
    assert not (tmp/'no-output').exists()


def test_batch_candidates_share_existing_remote_lease_after_unknown_outcome(batch_context):
    from scripts import tongxing_host  # noqa: F401
    from tongxing_production.delivery import publication
    from urllib.parse import urlparse
    c=batch_context;item=c['make_input']('ko',8,'sermon-8');tmp=c['tmp_path']
    first=tmp/'first-candidate';second=tmp/'second-candidate'
    m.prepare_batch_candidate([item],c['snapshot'],'dev',first)
    m.prepare_batch_candidate([item],c['snapshot'],'dev',second)
    config=json.loads((first/'publish-config.json').read_bytes());remote={'held':False,'attempts':0}
    def request(method,url,**kwargs):
        if '/channels/live' in url:return {'release':{'version':{'name':config['baseline_version']}}}
        if method=='POST':
            remote['attempts']+=1
            if remote['held']:raise ValueError('HTTP 412: lease exists')
            remote['held']=True;return {'generation':'5'}
        if method=='GET':return {'generation':'5'}
        if method=='DELETE':remote['held']=False;return {}
        raise AssertionError((method,url))
    def reader(url):
        path=c['public']/urlparse(url).path.lstrip('/')
        return (200,path.read_bytes()) if path.is_file() else (404,b'')
    def interrupted(*args,**kwargs):raise TimeoutError('unknown deploy outcome')
    def publish(candidate,run):
        cfg=json.loads((candidate/'publish-config.json').read_bytes())
        return publication.publish(candidate,intent=cfg['intent'],routes=cfg['routes'],baseline_version=cfg['baseline_version'],
            baseline_catalog_sha=cfg['baseline_catalog_sha'],baseline_catalog_v4_sha=cfg['baseline_catalog_v4_sha'],
            baseline_catalog_v5_sha=cfg['baseline_catalog_v5_sha'],lease_bucket=cfg['lease_bucket'],
            request=request,reader=reader,run=run)
    with pytest.raises(TimeoutError):publish(first,interrupted)
    assert remote['held'] and json.loads((first/'deployment-attempt-v2.json').read_bytes())['status']=='outcome_unknown'
    with pytest.raises(ValueError,match='HTTP 412'):
        publish(second,lambda *a,**kw:pytest.fail('second deploy must not execute'))
    assert remote['held'] and remote['attempts']==2

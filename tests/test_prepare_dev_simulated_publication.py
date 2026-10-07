"""Offline helper checks; no media build, model calls or Hosting operations."""
import copy
import gzip
import hashlib
import io
import json

import pytest
from scripts import build_dev_180s_simulated_inputs as fixture
from scripts import build_full_video_app_release as builder
from scripts import delivery_contract as contract
from scripts import prepare_dev_simulated_publication as publication


def test_fresh_identity_and_explicit_legacy_id():
    first = fixture.fixture_identity()
    second = fixture.fixture_identity()
    assert first != second
    assert first[1].endswith(first[0])
    assert fixture.fixture_identity('retry-2', fixture.LEGACY_PAGE_ID) == ('retry-2', fixture.LEGACY_PAGE_ID)
    assert fixture.fixture_identity('retry-2')[1] == 'mockup-dev-180s-retry-2'


@pytest.mark.parametrize('run_id,page_id', [('../outside', None), ('', None),
    ('test', '../mockup-test'), ('test', 'production-page'), ('test', 'mockup-a/b'),
    ('test', 'mockup-a?week=b')])
def test_unsafe_identity_rejected(run_id, page_id):
    with pytest.raises(ValueError, match='Unsafe'):
        fixture.fixture_identity(run_id, page_id)


def test_fixture_output_never_overwrites_or_escapes(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, 'TEST_ROOT', tmp_path)
    out = fixture.fixture_output(None, 'test')
    assert out == tmp_path / 'test/simulated-inputs'
    out.mkdir(parents=True)
    (out / 'operator-file').write_text('keep')
    with pytest.raises(ValueError, match='new simulated'):
        fixture.fixture_output(out, 'test')
    assert (out / 'operator-file').read_text() == 'keep'
    with pytest.raises(ValueError, match='inside'):
        fixture.fixture_output(tmp_path.parent / 'outside', 'test')
    with pytest.raises(ValueError, match='inside'):
        fixture.fixture_output(tmp_path, 'test')


@pytest.fixture
def plan_inputs(tmp_path, monkeypatch):
    base = tmp_path / 'baseline'
    public = base / 'public'
    public.mkdir(parents=True)
    release = public / 'old-release.json'
    release.write_text(json.dumps({'assets': []}))
    catalog = {'schemaVersion': 'sermon-multilingual-catalog-v3',
               'generatedAt': '2026-10-04T20:00:00Z', 'defaultPageId': 'mockup-original',
               'pages': [{'id': 'mockup-original', 'date': '2026-10-04', 'sourceLocale': 'en',
                          'sourceIdentitySha256': 'a' * 64, 'defaultTargetLocale': 'zh-Hans',
                          'targets': {'zh-Hans': {'releasePackageUrl': '/old-release.json',
                                      'releasePackageJsonSha256': publication.digest(release)}}}]}
    path = public / 'multilingual-v3.json'
    path.write_text(json.dumps(catalog, indent=3) + '\n')
    publication.write(base / 'seal-report.json', {'catalogSha256': publication.digest(path),
                                               'files': publication.files_report(public)})
    receipt = {'status': 'complete_verified_not_deployed', 'project': publication.PROJECT,
               'site': publication.SITE, 'origin': publication.ORIGIN,
               'baselineVersion': 'sites/test/versions/initial', 'catalogSha256': publication.digest(path)}
    publication.write(base / 'baseline-receipt.json', receipt)
    manifest = {'pageId': 'mockup-new-run', 'date': '2026-10-04', 'title': 'Simulated',
                'englishSourcePackageJsonSha256': 'b' * 64,
                'releases': {locale: {'releasePath': f'/new/{locale}.json', 'releaseSha256': 'c' * 64}
                             for locale in ('zh-Hans', 'ko', 'es')}}
    # The fixture checks this helper's contract; full producer asset validation has its own tests.
    monkeypatch.setattr(builder, 'verified_assets', lambda prepared: (copy.deepcopy(manifest), []))
    return base, tmp_path / 'prepared', catalog, receipt, manifest


def test_release_plan_uses_canonical_catalog_hash_and_preserves_default(plan_inputs, tmp_path):
    base, prepared, catalog, receipt, manifest = plan_inputs
    plan = publication.bound_release_plan(base, prepared)
    assert plan['baselineCatalogSha256'] == contract.sha(catalog)
    assert plan['baselineCatalogSha256'] != receipt['catalogSha256']
    assert plan['baselineVersion'] == receipt['baselineVersion']
    assert plan['mode'] == 'joined'
    assert plan['locales'] == plan['requiredLocales'] == ['es', 'ko', 'zh-Hans']
    candidate = {'schemaVersion': catalog['schemaVersion'], 'generatedAt': catalog['generatedAt'],
                 'defaultPageId': manifest['pageId'], 'pages': [{
                     'id': manifest['pageId'], 'targets': {locale: {} for locale in plan['locales']}}]}
    merged = contract.merge_catalog(catalog, candidate, plan)
    assert merged['defaultPageId'] == catalog['defaultPageId']
    assert merged['pages'][:-1] == catalog['pages']
    raw_plan = {**plan, 'baselineCatalogSha256': receipt['catalogSha256']}
    with pytest.raises(ValueError, match='Baseline changed'):
        contract.merge_catalog(catalog, candidate, raw_plan)
    out = tmp_path / 'release-plan.json'
    publication.release_plan(base, prepared, out)
    assert publication.read(out) == plan
    with pytest.raises(ValueError, match='already exists'):
        publication.release_plan(base, prepared, out)


def test_release_plan_joins_final_deployment_version(plan_inputs):
    base, prepared, _, receipt, _ = plan_inputs
    attempt = {'status': 'deployed', 'newVersion': 'sites/test/versions/new',
               'baselineVersion': receipt['baselineVersion'], 'catalogSha256': receipt['catalogSha256'],
               'intent': {'environment': 'dev', 'channel': 'dev', 'project': publication.PROJECT,
                          'site': publication.SITE, 'origin': publication.ORIGIN}}
    path = base / 'deployment-attempt-v2.json'
    publication.write(path, attempt)
    assert publication.bound_release_plan(base, prepared)['baselineVersion'] == attempt['newVersion']
    for field, value in [('status', 'outcome_unknown'), ('newVersion', None),
                         ('catalogSha256', 'stale'), ('baselineVersion', 'stale')]:
        path.write_text(json.dumps({**attempt, field: value}))
        with pytest.raises(ValueError, match='uncertain or differs'):
            publication.bound_release_plan(base, prepared)


def test_release_plan_rejects_reused_page_id_and_wrong_receipt(plan_inputs):
    base, prepared, _, receipt, manifest = plan_inputs
    manifest['pageId'] = 'mockup-original'
    with pytest.raises(ValueError, match='already exists'):
        publication.bound_release_plan(base, prepared)
    manifest['pageId'] = 'mockup-a/../outside'
    with pytest.raises(ValueError, match='test page required'):
        publication.bound_release_plan(base, prepared)
    manifest['pageId'] = 'mockup-new-run'
    (base / 'baseline-receipt.json').write_text(json.dumps({**receipt, 'catalogSha256': 'old'}))
    with pytest.raises(ValueError, match='baseline receipt required'):
        publication.bound_release_plan(base, prepared)


def test_simulated_page_joins_v4_so_v3_stays_its_human_projection(tmp_path):
    human = lambda locale: {'releasePackageUrl': f'/releases-v2/{{}}/{locale}.json', 'releasePackageJsonSha256': 'a' * 64,
                            'contentStatus': 'human_reviewed', 'audioStatus': 'human_reviewed', 'capabilities': ['text', 'captions', 'audio']}
    machine = {'releasePackageUrl': '/releases-v4/{}/ko.json', 'releasePackageJsonSha256': 'b' * 64,
               'contentStatus': 'machine_checked', 'audioStatus': 'machine_checked', 'capabilities': ['text', 'captions', 'audio']}
    page = lambda page_id, date, targets: {'id': page_id, 'date': date, 'title': page_id, 'sourceLocale': 'en',
        'sourceIdentitySha256': 'c' * 64, 'defaultTargetLocale': next(iter(targets)),
        'targets': {locale: {**target, 'releasePackageUrl': target['releasePackageUrl'].format(page_id)} for locale, target in targets.items()}}
    v4 = {'schemaVersion': 'sermon-multilingual-catalog-v4', 'generatedAt': '2026-10-04T00:00:00Z', 'defaultPageId': 'week-2',
          'pages': [page('week-2', '2026-10-04', {'zh-Hans': human('zh-Hans'), 'ko': machine}),
                    page('machine-only', '2026-09-27', {'ko': machine}),
                    page('week-1', '2026-09-20', {'zh-Hans': human('zh-Hans')})]}
    v3 = contract.project_human_catalog(v4)
    simulated = page('dev-run', '2026-10-05', {'zh-Hans': {**human('zh-Hans'), 'simulationOnly': True, 'diagnosticOnly': True}})
    for index in range(len(v3['pages']) + 1):
        catalog = {**copy.deepcopy(v3), 'generatedAt': '2026-10-05T00:00:00Z'}
        catalog['pages'].insert(index, simulated)
        result = publication.with_simulated_page(v4, catalog, 'dev-run')
        assert contract.project_human_catalog(result) == catalog
        assert [p['id'] for p in result['pages'] if p['id'] != 'dev-run'] == [p['id'] for p in v4['pages']]
        assert next(p for p in result['pages'] if p['id'] == 'machine-only') == v4['pages'][1]
    # The simulated page never changes an existing page of either catalog.
    catalog = copy.deepcopy(v3); catalog['pages'].append(simulated); catalog['pages'][0]['title'] = 'changed'
    with pytest.raises(ValueError, match='projection'):
        publication.with_simulated_page(v4, catalog, 'dev-run')


def test_catalog_report_adds_the_v4_hash_only_once_published(tmp_path):
    (tmp_path / 'multilingual-v3.json').write_text('{}')
    assert set(publication.catalog_report(tmp_path)) == {'catalogSha256'}
    (tmp_path / 'multilingual-v4.json').write_text('{"v": 4}')
    assert publication.catalog_report(tmp_path)['catalogV4Sha256'] == publication.digest(tmp_path / 'multilingual-v4.json')


class _LiveResponse:
    def __init__(self, body, headers):
        self.status, self.headers, self._body = 200, headers, io.BytesIO(body)

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, body, headers):
    monkeypatch.setattr(publication, 'urlopen', lambda request, timeout: _LiveResponse(body, headers))


def test_live_gzip_file_is_bound_by_its_bytes(tmp_path, monkeypatch):
    raw = b'{"enabled": false}'
    packed = gzip.compress(raw)
    _serve(monkeypatch, packed, {'Content-Encoding': 'gzip', 'ETag': '"ignored"'})
    target = tmp_path / 'a.json'
    assert publication.fetch_live_file('a.json', hashlib.sha256(packed).hexdigest(), target) == 'live_get_version_hash_verified'
    assert target.read_bytes() == raw
    _serve(monkeypatch, packed, {'Content-Encoding': 'gzip', 'ETag': '"stale"'})
    with pytest.raises(ValueError, match='no longer matches'):
        publication.fetch_live_file('b.json', 'stale', tmp_path / 'b.json')


def test_uncompressed_small_file_is_bound_by_version_etag(tmp_path, monkeypatch):
    raw = b'{"enabled": false}'
    version_hash = hashlib.sha256(gzip.compress(raw)).hexdigest()
    _serve(monkeypatch, raw, {'ETag': '"' + version_hash + '"'})
    target = tmp_path / 'engagement.json'
    assert publication.fetch_live_file('engagement.json', version_hash, target) == 'live_get_identity_etag_verified'
    assert target.read_bytes() == raw
    for name, headers in (('c.json', {'ETag': '"other"'}), ('e.json', {})):
        _serve(monkeypatch, raw, headers)
        with pytest.raises(ValueError, match='no longer matches'):
            publication.fetch_live_file(name, version_hash, tmp_path / name)
    _serve(monkeypatch, raw, {'Content-Encoding': 'br', 'ETag': '"' + version_hash + '"'})
    with pytest.raises(ValueError, match='Unsupported'):
        publication.fetch_live_file('d.json', version_hash, tmp_path / 'd.json')

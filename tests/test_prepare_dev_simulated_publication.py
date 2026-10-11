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


def test_cloud_run_and_function_rewrites_preserved_for_production():
    config = {'rewrites': [
        {'glob': '/api/**', 'run': {'serviceId': 'sermon-feedback-api', 'region': 'us-west1'}},
        {'glob': '/other/**', 'function': {'functionId': 'legacy', 'region': 'us-west1'}},
        {'glob': '**', 'path': '/index.html'}]}
    converted = publication.firebase_config(config, environment='production')['hosting']
    assert converted['site'] == 'ai-for-god-sermon-audio'
    assert converted['rewrites'] == [
        {'source': '/api/**', 'run': config['rewrites'][0]['run']},
        {'source': '/other/**', 'function': config['rewrites'][1]['function']},
        {'source': '**', 'destination': '/index.html'}]


@pytest.mark.parametrize('encoding', ['gzip', 'identity'])
def test_production_baseline_acquires_frozen_version_and_config(tmp_path, monkeypatch, encoding):
    target = publication.hosting_target('production')
    version = 'sites/' + target['site'] + '/versions/frozen'
    raw = b'{"pages": []}'
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    compressed = compressed[:9] + bytes([19]) + compressed[10:]
    sha = hashlib.sha256(compressed).hexdigest()
    config = {'rewrites': [{'glob': '/api/**', 'run': {'serviceId': 'sermon-feedback-api', 'region': 'us-west1'}}]}
    calls, origins = [], []
    def request(method, url):
        calls.append(url)
        if url.endswith('/files?pageSize=1000'):
            return {'files': [{'path': '/multilingual-v3.json', 'status': 'ACTIVE', 'hash': sha}]}
        assert url.endswith('/' + version)
        return {'status': 'FINALIZED', 'config': config}
    class Response(io.BytesIO):
        status = 200
        headers = {'Content-Encoding': encoding, 'Etag': '"' + sha + '"'}
    def download(req, timeout):
        origins.append(req.full_url)
        return Response(compressed if encoding == 'gzip' else raw)
    monkeypatch.setattr(publication.publisher, 'authenticated_transport', lambda: request)
    monkeypatch.setattr(publication.publisher, 'live_version', lambda req, site: version if site == target['site'] else 'wrong')
    monkeypatch.setattr(publication, 'urlopen', download)
    out = tmp_path / 'production-baseline'
    result = publication.baseline(out, environment='production')
    assert result['status'] == 'complete_verified_not_deployed'
    receipt = publication.read(out / 'baseline-receipt.json')
    assert receipt['project'] == target['project'] and receipt['site'] == target['site']
    assert receipt['environment'] == 'production' and receipt['channel'] == 'production_web'
    assert receipt['firebaseJsonSha256'] == publication.digest(out / 'firebase.json')
    assert receipt['configSemanticEqual'] is True
    assert receipt['rows'][0]['liveGzipSha256'] == sha
    assert (out / 'public/multilingual-v3.json').read_bytes() == raw
    assert origins == [target['origin'] + '/multilingual-v3.json']
    assert publication.read(out / 'firebase.json')['hosting']['rewrites'][0]['run'] == config['rewrites'][0]['run']


def test_gzip_identity_hash_rejects_changed_bytes(tmp_path):
    path = tmp_path / 'raw'
    path.write_bytes(b'known media bytes')
    compressed = gzip.compress(path.read_bytes(), compresslevel=9, mtime=0)
    expected = hashlib.sha256(compressed[:9] + bytes([19]) + compressed[10:]).hexdigest()
    assert expected in publication.firebase_cli_gzip_hashes(path)
    path.write_bytes(b'different media bytes')
    assert expected not in publication.firebase_cli_gzip_hashes(path)

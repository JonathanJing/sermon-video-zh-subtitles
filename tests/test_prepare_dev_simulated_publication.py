"""Offline helper checks; no media build, model calls or Hosting operations."""
import copy
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

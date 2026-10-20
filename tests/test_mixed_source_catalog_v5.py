import copy
import json
from pathlib import Path

import pytest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.delivery import app_release
from tongxing_production.delivery import contract
from tongxing_production.delivery import baseline as baseline_tools
from tongxing_production.delivery import unified_stage


NOW = '2026-10-18T16:00:00Z'
SOURCE_A, SOURCE_B = 'a' * 64, 'b' * 64
MEDIA_A, MEDIA_B = 'c' * 64, 'd' * 64


def video(edition, media):
    return {'schemaVersion': 'sermon-video-delivery-v1',
            'canonicalUrl': f'/pages/{edition}/full-video-browser.mp4',
            'storageUrl': f'https://storage.googleapis.com/ai-for-god-sermon-media-prod/weekly/{edition}/{media}.mp4',
            'sha256': media, 'bytes': 100}


def target(locale, edition, source, media):
    return {'releasePackageUrl': f'/releases-v4/{edition}/{locale}.json',
            'releasePackageJsonSha256': ('1' if locale == 'zh-Hans' else '2' if locale == 'es' else '3') * 64,
            'contentStatus': 'machine_checked', 'audioStatus': 'machine_checked',
            'capabilities': ['text', 'captions', 'audio'], 'editionId': edition,
            'sourceIdentitySha256': source, 'sourceMediaSha256': media,
            'videoDelivery': video(edition, media)}


def catalog(locales=('zh-Hans', 'es', 'ko')):
    targets = {}
    for locale in locales:
        if locale == 'zh-Hans':
            targets[locale] = target(locale, 'broadcast-edition', SOURCE_A, MEDIA_A)
        else:
            targets[locale] = target(locale, 'family-page', SOURCE_B, MEDIA_B)
    return {'schemaVersion': contract.CATALOG_V5, 'generatedAt': NOW,
            'defaultPageId': 'family-page', 'pages': [{
                'id': 'family-page', 'date': '2026-10-18', 'title': 'One family title',
                'sourceLocale': 'en', 'sourceMode': 'per_target',
                'defaultTargetLocale': 'zh-Hans' if 'zh-Hans' in targets else next(iter(targets)),
                'targets': targets}]}


def release(locale, edition, source, media):
    return {'pageId': edition, 'targetLocale': locale,
            'englishSourcePackageJsonSha256': source,
            'sourceIdentity': {'mediaSha256': media}}


def test_v5_projects_mixed_family_to_two_honest_legacy_pages():
    value = contract.validate_catalog_schema(catalog())
    legacy = contract.project_legacy_catalog_v4(value)
    pages = {page['id']: page for page in legacy['pages']}
    assert set(pages) == {'family-page', 'broadcast-edition'}
    assert set(pages['family-page']['targets']) == {'es', 'ko'}
    assert pages['family-page']['sourceIdentitySha256'] == SOURCE_B
    assert set(pages['broadcast-edition']['targets']) == {'zh-Hans'}
    assert pages['broadcast-edition']['sourceIdentitySha256'] == SOURCE_A
    assert legacy['defaultPageId'] == 'broadcast-edition'



def test_v5_projection_defaults_do_not_depend_on_target_order():
    value = catalog(('zh-Hans', 'ko', 'es'))
    reordered = copy.deepcopy(value)
    reordered['pages'][0]['targets'] = dict(sorted(reordered['pages'][0]['targets'].items(), reverse=True))
    first, second = (contract.project_legacy_catalog_v4(item) for item in (value, reordered))
    defaults = lambda legacy: {page['id']: page['defaultTargetLocale'] for page in legacy['pages']}
    assert defaults(first) == defaults(second) == {'broadcast-edition': 'zh-Hans', 'family-page': 'ko'}
    value['pages'][0]['defaultTargetLocale'] = 'es'
    assert defaults(contract.project_legacy_catalog_v4(value))['family-page'] == 'es'


def test_v5_incremental_merge_allows_target_source_to_differ_from_siblings():
    baseline = catalog(('es', 'ko'))
    candidate = catalog(('zh-Hans',))
    candidate['pages'][0]['defaultTargetLocale'] = baseline['pages'][0]['defaultTargetLocale']
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogV5Sha256': contract.sha(baseline), 'baselineVersion': 'v1',
            'pageId': 'family-page', 'locales': ['zh-Hans'],
            'requiredLocales': ['zh-Hans', 'es', 'ko'], 'mode': 'joined'}
    merged = contract.merge_catalog(baseline, candidate, plan)
    assert set(merged['pages'][0]['targets']) == {'zh-Hans', 'es', 'ko'}
    assert merged['pages'][0]['targets']['es'] == baseline['pages'][0]['targets']['es']
    assert merged['pages'][0]['targets']['zh-Hans']['sourceIdentitySha256'] == SOURCE_A


def test_v5_incremental_merge_rejects_shared_presentation_changes():
    baseline = catalog(('es', 'ko'))
    candidate = catalog(('zh-Hans',))
    candidate['pages'][0]['defaultTargetLocale'] = baseline['pages'][0]['defaultTargetLocale']
    candidate['pages'][0]['title'] = 'A different family title'
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogV5Sha256': contract.sha(baseline), 'baselineVersion': 'v1',
            'pageId': 'family-page', 'locales': ['zh-Hans'],
            'requiredLocales': ['zh-Hans', 'es', 'ko'], 'mode': 'incremental'}
    with pytest.raises(ValueError, match='Shared page presentation changed'):
        contract.merge_catalog(baseline, candidate, plan)


def test_v5_merge_promotes_existing_single_source_siblings_without_rewriting_release_identity():
    legacy = contract.project_legacy_catalog_v4(catalog(('es', 'ko')))
    baseline = contract.upgrade_catalog_v5(legacy)
    candidate = catalog()
    candidate['pages'][0]['title'] = 'Incoming family title'
    candidate['pages'][0]['displayCategory'] = {
        'schemaVersion': 'sermon-page-display-category-v1',
        'labels': {'en': 'Full Sermon', 'zh-Hans': '完整讲道'}}
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogV5Sha256': contract.sha(baseline), 'baselineVersion': 'v1',
            'pageId': 'family-page', 'locales': ['zh-Hans', 'es', 'ko'],
            'requiredLocales': ['zh-Hans', 'es', 'ko'], 'mode': 'joined'}
    merged = contract.merge_catalog(baseline, candidate, plan)
    page = merged['pages'][0]
    assert page['sourceMode'] == 'per_target'
    assert 'sourceIdentitySha256' not in page
    assert page['targets']['es']['editionId'] == 'family-page'
    assert page['targets']['es']['sourceIdentitySha256'] == SOURCE_B
    assert page['targets']['zh-Hans']['editionId'] == 'broadcast-edition'
    assert page['title'] == 'Incoming family title'
    assert page['defaultTargetLocale'] == 'zh-Hans'
    assert page['displayCategory'] == candidate['pages'][0]['displayCategory']
    assert merged['defaultPageId'] == 'family-page'
    projected = contract.project_legacy_catalog_v4(merged)
    projected_pages = {item['id']: item for item in projected['pages']}
    assert {item['title'] for item in projected_pages.values()} == {'Incoming family title'}
    assert projected['defaultPageId'] == 'broadcast-edition'


def test_v5_merge_rejects_partial_or_cross_hash_single_source_promotion():
    legacy = contract.project_legacy_catalog_v4(catalog(('es', 'ko')))
    baseline = contract.upgrade_catalog_v5(legacy)
    partial = catalog(('zh-Hans',))
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogV5Sha256': contract.sha(baseline), 'baselineVersion': 'v1',
            'pageId': 'family-page', 'locales': ['zh-Hans'],
            'requiredLocales': ['zh-Hans', 'es', 'ko'], 'mode': 'incremental'}
    with pytest.raises(ValueError, match='replace every existing target'):
        contract.merge_catalog(baseline, partial, plan)
    crossed = catalog()
    crossed['pages'][0]['targets']['es']['sourceIdentitySha256'] = SOURCE_A
    plan['locales'] = ['zh-Hans', 'es', 'ko']; plan['mode'] = 'joined'
    with pytest.raises(ValueError, match='changed an existing target source'):
        contract.merge_catalog(baseline, crossed, plan)


def test_v5_promotion_can_fill_missing_legacy_video_only_from_identical_old_locale_targets():
    legacy = contract.project_legacy_catalog_v4(catalog(('es', 'ko')))
    del legacy['pages'][0]['videoDelivery']
    baseline = contract.upgrade_catalog_v5(legacy)
    candidate = catalog()
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogV5Sha256': contract.sha(baseline), 'baselineVersion': 'v1',
            'pageId': 'family-page', 'locales': ['zh-Hans', 'es', 'ko'],
            'requiredLocales': ['zh-Hans', 'es', 'ko'], 'mode': 'joined'}
    merged = contract.merge_catalog(baseline, candidate, plan)
    page = merged['pages'][0]
    assert page['targets']['es']['videoDelivery'] == page['targets']['ko']['videoDelivery']
    assert page['targets']['es']['videoDelivery'] == video('family-page', MEDIA_B)

    inconsistent = copy.deepcopy(candidate)
    inconsistent['pages'][0]['targets']['ko']['videoDelivery']['bytes'] += 1
    with pytest.raises(ValueError, match='disagree on promotion video'):
        contract.merge_catalog(baseline, inconsistent, plan)

    wrong = copy.deepcopy(candidate)
    wrong['pages'][0]['targets']['es']['videoDelivery'] = video('broadcast-edition', MEDIA_B)
    with pytest.raises(ValueError, match='cannot supply the legacy page video'):
        contract.merge_catalog(baseline, wrong, plan)


def test_v5_promotion_absorbs_existing_edition_page_but_legacy_projection_keeps_it():
    legacy = contract.project_legacy_catalog_v4(catalog())
    baseline = contract.upgrade_catalog_v5(legacy)
    candidate = catalog()
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogV5Sha256': contract.sha(baseline), 'baselineVersion': 'v1',
            'pageId': 'family-page', 'locales': ['zh-Hans', 'es', 'ko'],
            'requiredLocales': ['zh-Hans', 'es', 'ko'], 'mode': 'joined'}
    merged = contract.merge_catalog(baseline, candidate, plan)
    assert [page['id'] for page in merged['pages']] == ['family-page']
    projected = contract.project_legacy_catalog_v4(merged)
    assert {page['id'] for page in projected['pages']} == {'family-page', 'broadcast-edition'}

    crossed = catalog()
    crossed['pages'][0]['targets']['zh-Hans']['releasePackageJsonSha256'] = 'f' * 64
    with pytest.raises(ValueError, match='edition absorption'):
        contract.merge_catalog(baseline, crossed, plan)


def test_catalog_only_candidate_reuses_published_edition_targets_byte_for_byte():
    legacy = contract.project_legacy_catalog_v4(catalog())
    candidate = contract.build_mixed_source_candidate(
        legacy, family_page_id='family-page',
        locale_editions={'zh-Hans': 'broadcast-edition', 'es': 'family-page', 'ko': 'family-page'},
        generated_at='2026-10-18T17:00:00Z')
    page = candidate['pages'][0]
    assert page['sourceMode'] == 'per_target'
    assert page['targets']['zh-Hans']['editionId'] == 'broadcast-edition'
    assert page['targets']['es']['editionId'] == 'family-page'
    projected = contract.project_legacy_catalog_v4(candidate)
    original = {p['id']: p for p in legacy['pages']}
    rebuilt = {p['id']: p for p in projected['pages']}
    assert rebuilt['broadcast-edition']['targets'] == original['broadcast-edition']['targets']
    assert rebuilt['family-page']['targets'] == original['family-page']['targets']

    with pytest.raises(ValueError, match='target is missing'):
        contract.build_mixed_source_candidate(
            legacy, family_page_id='family-page', locale_editions={'zh-Hans': 'family-page'},
            generated_at='2026-10-18T17:00:00Z')


def test_v5_rejects_cross_hash_video_and_release_reuse():
    value = catalog()
    crossed = copy.deepcopy(value)
    crossed['pages'][0]['targets']['zh-Hans']['videoDelivery']['sha256'] = MEDIA_B
    with pytest.raises(ValueError, match='video delivery'):
        contract.validate_catalog_schema(crossed)
    crossed = copy.deepcopy(value)
    crossed['pages'][0]['targets']['zh-Hans']['videoDelivery']['storageUrl'] = video(
        'family-page', MEDIA_A)['storageUrl']
    with pytest.raises(ValueError, match='video delivery'):
        contract.validate_catalog_schema(crossed)
    page = value['pages'][0]
    contract.validate_release_target(release('zh-Hans', 'broadcast-edition', SOURCE_A, MEDIA_A), page, 'zh-Hans')
    with pytest.raises(ValueError, match='edition/source'):
        contract.validate_release_target(release('zh-Hans', 'family-page', SOURCE_B, MEDIA_B), page, 'zh-Hans')


def test_v4_single_source_behavior_is_unchanged():
    legacy = contract.project_legacy_catalog_v4(catalog())
    upgraded = contract.upgrade_catalog_v5(legacy)
    assert all(page['sourceMode'] == 'single_source' for page in upgraded['pages'])
    assert contract.project_legacy_catalog_v4(upgraded) == legacy


def test_human_v2_and_machine_v4_targets_share_family_without_rewriting_either_source():
    value = catalog()
    zh = value['pages'][0]['targets']['zh-Hans']
    zh.update(releasePackageUrl='/releases-v2/broadcast-edition/zh-Hans.json',
              contentStatus='human_reviewed', audioStatus='human_reviewed')
    contract.validate_catalog_schema(value)
    zh_release = {'schemaVersion': 'sermon-target-language-release-package-v2',
                  'pageId': 'broadcast-edition', 'targetLocale': 'zh-Hans'}
    zh_content = {'pageId': 'broadcast-edition', 'targetLocale': 'zh-Hans',
                  'englishSourcePackageJsonSha256': SOURCE_A, 'sourceMediaSha256': MEDIA_A}
    zh_item = {'editionId': 'broadcast-edition', 'sourceIdentitySha256': SOURCE_A,
               'sourceMediaSha256': MEDIA_A, 'videoDelivery': video('broadcast-edition', MEDIA_A)}
    app_release.validate_mixed_target_identity(zh_release, zh_content, zh_item, 'zh-Hans')
    es_release = {'schemaVersion': contract.RELEASE_V4, 'pageId': 'family-page', 'targetLocale': 'es',
                  'englishSourcePackageJsonSha256': SOURCE_B, 'sourceIdentity': {'mediaSha256': MEDIA_B}}
    es_content = {'pageId': 'family-page', 'targetLocale': 'es'}
    es_item = {'editionId': 'family-page', 'sourceIdentitySha256': SOURCE_B,
               'sourceMediaSha256': MEDIA_B, 'videoDelivery': video('family-page', MEDIA_B)}
    app_release.validate_mixed_target_identity(es_release, es_content, es_item, 'es')
    crossed = copy.deepcopy(zh_content); crossed['sourceMediaSha256'] = MEDIA_B
    with pytest.raises(ValueError, match='mixed-source target identity'):
        app_release.validate_mixed_target_identity(zh_release, crossed, zh_item, 'zh-Hans')


def test_catalog_only_overlay_keeps_assets_and_writes_v5_plus_two_legacy_editions(tmp_path, monkeypatch):
    mixed = catalog()
    for locale, target_value in mixed['pages'][0]['targets'].items():
        target_value.update(contentStatus='human_reviewed', audioStatus='human_reviewed',
                            releasePackageUrl=f"/releases-v2/{target_value['editionId']}/{locale}.json")
    legacy_v4 = contract.project_legacy_catalog_v4(mixed)
    legacy_v3 = contract.project_human_catalog(legacy_v4)
    base = tmp_path / 'base'; public = base / 'public'; public.mkdir(parents=True)
    baseline_tools.write(public / 'multilingual-v4.json', legacy_v4)
    baseline_tools.write(public / 'multilingual-v3.json', legacy_v3)
    (public / 'unchanged.bin').write_bytes(b'published bytes')
    hosting = baseline_tools.hosting_target('production')
    baseline_tools.write(base / 'firebase.json', {'hosting': {
        'site': hosting['site'], 'public': 'public',
        'headers': [{'source': '**', 'headers': [{'key': 'Content-Security-Policy',
                     'value': "default-src 'self'; media-src 'self' blob:"}]}]}})
    baseline_tools.write(base / 'baseline-receipt.json', {
        'status': 'complete_verified_not_deployed', 'baselineVersion': 'sites/test/versions/1',
        **{key: hosting[key] for key in ('project', 'site', 'origin')}})
    baseline_tools.write(base / 'seal-report.json', {
        **baseline_tools.catalog_report(public), 'files': baseline_tools.files_report(public)})
    candidate = contract.build_mixed_source_candidate(
        legacy_v4, family_page_id='family-page',
        locale_editions={'zh-Hans': 'broadcast-edition', 'es': 'family-page', 'ko': 'family-page'},
        generated_at='2026-10-18T17:00:00Z')
    candidate_path = tmp_path / 'candidate.json'; baseline_tools.write(candidate_path, candidate)
    current = contract.upgrade_catalog_v5(legacy_v4)
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1',
            'baselineCatalogV5Sha256': contract.sha(current), 'baselineVersion': 'sites/test/versions/1',
            'pageId': 'family-page', 'locales': ['zh-Hans', 'es', 'ko'],
            'requiredLocales': ['zh-Hans', 'es', 'ko'], 'mode': 'joined'}
    plan_path = tmp_path / 'plan.json'; baseline_tools.write(plan_path, plan)
    monkeypatch.setattr(contract, 'validate_catalog_snapshot', lambda path: legacy_v3)
    out = tmp_path / 'out'
    baseline_tools.mixed_source_catalog_overlay(base, candidate_path, plan_path, out)
    assert (out / 'public/unchanged.bin').read_bytes() == b'published bytes'
    v5 = baseline_tools.read(out / 'public/multilingual-v5.json')
    assert [page['id'] for page in v5['pages']] == ['family-page']
    v4 = baseline_tools.read(out / 'public/multilingual-v4.json')
    assert {page['id'] for page in v4['pages']} == {'family-page', 'broadcast-edition'}
    overlay = baseline_tools.read(out / 'mixed-source-catalog-plan.json')
    assert overlay['editionAssetsChanged'] is False
    assert '/published-weeks.mjs' in overlay['changedPaths']
    config = baseline_tools.read(out / 'firebase.json')
    redirects = {row['source']: row['destination'] for row in config['hosting']['redirects']}
    assert redirects == {
        '/pages/broadcast-edition/full-video-browser.mp4': video('broadcast-edition', MEDIA_A)['storageUrl'],
        '/pages/family-page/full-video-browser.mp4': video('family-page', MEDIA_B)['storageUrl']}

    conflicting = baseline_tools.read(base / 'firebase.json')
    conflicting['hosting']['redirects'] = [{
        'source': '/pages/broadcast-edition/full-video-browser.mp4',
        'destination': 'https://storage.googleapis.com/wrong/video.mp4', 'type': 302}]
    (base / 'firebase.json').unlink(); baseline_tools.write(base / 'firebase.json', conflicting)
    with pytest.raises(ValueError, match='redirect conflicts'):
        baseline_tools.mixed_source_catalog_overlay(base, candidate_path, plan_path, tmp_path / 'conflict')


def test_video_bucket_must_match_publication_environment():
    prod = video('family-page', MEDIA_B)
    baseline_tools.require_video_environment(prod, 'production')
    dev = copy.deepcopy(prod)
    dev['storageUrl'] = dev['storageUrl'].replace('sermon-media-prod', 'sermon-media-dev')
    baseline_tools.require_video_environment(dev, 'dev')
    with pytest.raises(ValueError, match='publication environment'):
        baseline_tools.require_video_environment(dev, 'production')
    with pytest.raises(ValueError, match='publication environment'):
        baseline_tools.require_video_environment(prod, 'dev')


def test_endpoint_readback_admits_target_bound_v2_beside_v4_and_rejects_cross_source(tmp_path):
    public = tmp_path / 'public'; public.mkdir()
    value = catalog(('zh-Hans', 'es'))
    page = value['pages'][0]
    zh_target = page['targets']['zh-Hans']
    zh_target.update(releasePackageUrl='/releases-v2/broadcast-edition/zh-Hans.json',
                     contentStatus='human_reviewed', audioStatus='human_reviewed')
    zh_content = {'pageId': 'broadcast-edition', 'targetLocale': 'zh-Hans',
                  'englishSourcePackageJsonSha256': SOURCE_A, 'sourceMediaSha256': MEDIA_A}
    zh_content_path = public / 'content/broadcast-edition/zh-Hans.json'
    baseline_tools.write(zh_content_path, zh_content)
    zh_release = {'schemaVersion': 'sermon-target-language-release-package-v2',
                  'pageId': 'broadcast-edition', 'targetLocale': 'zh-Hans',
                  'status': 'published_http_verified', 'contentStatus': 'human_reviewed',
                  'audioStatus': 'human_reviewed', 'assets': [{
                      'role': 'content', 'path': '/content/broadcast-edition/zh-Hans.json',
                      'sha256': baseline_tools.digest(zh_content_path)}]}
    zh_release_path = public / 'releases-v2/broadcast-edition/zh-Hans.json'
    baseline_tools.write(zh_release_path, zh_release)
    zh_target['releasePackageJsonSha256'] = baseline_tools.digest(zh_release_path)

    es_target = page['targets']['es']
    es_content = {'pageId': 'family-page', 'targetLocale': 'es'}
    es_content_path = public / 'content/family-page/es.json'; baseline_tools.write(es_content_path, es_content)
    es_release = {'schemaVersion': contract.RELEASE_V4, 'pageId': 'family-page', 'targetLocale': 'es',
                  'status': 'published_http_verified', 'contentStatus': 'machine_checked',
                  'audioStatus': 'machine_checked', 'englishSourcePackageJsonSha256': SOURCE_B,
                  'sourceIdentity': {'mediaSha256': MEDIA_B}, 'assets': [{
                      'role': 'content', 'path': '/content/family-page/es.json',
                      'sha256': baseline_tools.digest(es_content_path)}]}
    es_release_path = public / 'releases-v4/family-page/es.json'; baseline_tools.write(es_release_path, es_release)
    es_target['releasePackageJsonSha256'] = baseline_tools.digest(es_release_path)

    assert unified_stage._endpoint_release(public, page, 'zh-Hans')[2] == zh_release
    assert unified_stage._endpoint_release(public, page, 'es')[2] == es_release
    crossed = dict(zh_content, sourceMediaSha256=MEDIA_B)
    zh_content_path.unlink(); baseline_tools.write(zh_content_path, crossed)
    zh_release['assets'][0]['sha256'] = baseline_tools.digest(zh_content_path)
    zh_release_path.unlink(); baseline_tools.write(zh_release_path, zh_release)
    zh_target['releasePackageJsonSha256'] = baseline_tools.digest(zh_release_path)
    with pytest.raises(ValueError, match='Content differs from target edition/source'):
        unified_stage._endpoint_release(public, page, 'zh-Hans')


def test_mixed_endpoint_marks_v2_study_not_applicable_and_v4_study_verified():
    expected = {'outline': 'a' * 64, 'meditation': 'b' * 64}
    unified_stage._validate_study_observation(
        {'studyDisplayed': True, 'studyArtifacts': expected},
        {'checks': {'outline': 'pass', 'meditation': 'pass'}}, expected)
    v2_telemetry = {'studyDisplayed': False, 'studyArtifacts': None}
    v2_playback = {'checks': {'outline': 'not_applicable', 'meditation': 'not_applicable'}}
    unified_stage._validate_study_observation(v2_telemetry, v2_playback, None)
    forged = {'studyDisplayed': True, 'studyArtifacts': expected}
    with pytest.raises(ValueError, match='not applicable'):
        unified_stage._validate_study_observation(forged, v2_playback, None)


def test_v5_rollback_rejects_crossing_a_source_mode_promotion():
    previous = contract.upgrade_catalog_v5(contract.project_legacy_catalog_v4(catalog(('es', 'ko'))))
    current = catalog()
    with pytest.raises(ValueError, match='crosses a source-mode promotion'):
        contract.rollback_locale(current, previous, page_id='family-page', locale='es',
                                 expected_current_sha=contract.sha(current))
    older = catalog()
    older['pages'][0]['targets']['es']['releasePackageJsonSha256'] = '9' * 64
    restored = contract.rollback_locale(current, older, page_id='family-page', locale='es',
                                        expected_current_sha=contract.sha(current))
    assert restored['pages'][0]['targets']['es'] == older['pages'][0]['targets']['es']
    contract.validate_catalog_schema(restored)


def test_mixed_source_v2_release_must_name_its_target_edition_locale_and_status():
    fixture = Path(__file__).resolve().parents[1] / (
        'apps/tongxing-ios/Core/Tests/TongxingCoreTests/Fixtures/shared-release-contracts.json')
    template = json.loads(fixture.read_text())['cases'][0]['release']
    value = catalog(('zh-Hans', 'es'))
    page = value['pages'][0]
    page['targets']['zh-Hans'].update(releasePackageUrl='/releases-v2/broadcast-edition/zh-Hans.json',
                                      contentStatus='human_reviewed', audioStatus='human_reviewed')
    good = dict(copy.deepcopy(template), pageId='broadcast-edition')
    assert contract.validate_v2_release_target(good, page, 'zh-Hans') == good
    for change in ({'pageId': 'family-page'}, {'targetLocale': 'es'}, {'audioLocale': 'es'},
                   {'audioStatus': 'unavailable'}, {'status': 'candidate'}):
        with pytest.raises(ValueError, match='Release differs from target edition/locale/status'):
            contract.validate_v2_release_target(dict(copy.deepcopy(good), **change), page, 'zh-Hans')
    with pytest.raises(Exception):
        contract.validate_v2_release_target({k: v for k, v in good.items() if k != 'packageId'}, page, 'zh-Hans')

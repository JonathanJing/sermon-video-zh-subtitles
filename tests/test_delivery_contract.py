import copy
import hashlib
import json
import pytest
from scripts import delivery_contract as d
from scripts import study_artifacts as study

SHA = 'a' * 64
NOW = '2026-10-04T20:00:00+00:00'


def catalogs():
    old = {'schemaVersion': 'sermon-multilingual-catalog-v3', 'generatedAt': NOW, 'defaultPageId': 'p', 'pages': [
        {'id': 'p', 'date': '2026-10-04', 'sourceLocale': 'en', 'sourceIdentitySha256': SHA,
         'defaultTargetLocale': 'zh-Hans', 'targets': {'zh-Hans': {'release': 'old-zh'}}},
        {'id': 'older', 'targets': {'es': {'release': 'older-es'}}}]}
    new = copy.deepcopy(old)
    new['pages'] = [new['pages'][0]]
    new['pages'][0]['targets'] = {'es': {'release': 'new-es'}}
    plan = {'schemaVersion': 'sermon-locale-release-plan-v1', 'baselineCatalogSha256': d.sha(old),
            'baselineVersion': 'v1', 'pageId': 'p', 'locales': ['es'], 'requiredLocales': ['zh-Hans', 'ko', 'es'], 'mode': 'incremental'}
    return old, new, plan


def test_overlay_and_rollback_preserve_siblings():
    old, new, plan = catalogs()
    merged = d.merge_catalog(old, new, plan)
    assert merged['pages'][1] == old['pages'][1]
    assert merged['pages'][0]['targets']['zh-Hans'] == old['pages'][0]['targets']['zh-Hans']
    restored = d.rollback_locale(merged, old, page_id='p', locale='es', expected_current_sha=d.sha(merged))
    assert restored == old
    with pytest.raises(ValueError, match='Baseline changed'):
        d.merge_catalog(merged, new, plan)
    plan['mode'] = 'joined'
    with pytest.raises(ValueError, match='join incomplete'):
        d.merge_catalog(old, new, plan)


def test_source_replacement_cannot_keep_sibling_assets():
    old, new, plan = catalogs()
    new['pages'][0]['sourceIdentitySha256'] = 'b' * 64
    with pytest.raises(ValueError, match='Source changed'):
        d.merge_catalog(old, new, plan)


def test_old_deployments_and_http_cannot_promote():
    intent = {'origin': 'https://example.web.app'}
    attempt = d.new_attempt(intent, catalog_sha=SHA, assets_sha=SHA, baseline_version='v1')
    attempt.update(status='deployed', newVersion='v2', startedAt=NOW, completedAt=NOW)
    http = {'passed': True, 'failures': [], 'attemptId': attempt['attemptId'], 'deploymentSha256': d.sha(attempt),
            'origin': intent['origin'], 'catalogSha256': SHA, 'assetsSha256': SHA, 'startedAt': NOW, 'completedAt': NOW}
    assert d.verify_attempt(attempt, http, intent=intent, catalog_sha=SHA, assets_sha=SHA)['deviceAcceptance'] == 'not_run'
    for field in ('attemptId', 'deploymentSha256', 'origin', 'catalogSha256', 'assetsSha256'):
        stale = {**http, field: 'old'}
        with pytest.raises(ValueError):
            d.verify_attempt(attempt, stale, intent=intent, catalog_sha=SHA, assets_sha=SHA)
    with pytest.raises(ValueError):
        d.verify_attempt(attempt, {**http, 'passed': False}, intent=intent, catalog_sha=SHA, assets_sha=SHA)
    for field in ('schemaVersion', 'status', 'intent', 'catalogSha256'):
        with pytest.raises(ValueError):
            d.verify_attempt({**attempt, field: 'old'}, http, intent=intent, catalog_sha=SHA, assets_sha=SHA)


def test_study_independent_review_and_join():
    def pair(kind):
        artifact = study.produce(kind, [{'title': 'Title', 'body': 'Body', 'sourceUnitIds': ['u1']}],
                                 page_id='p', locale='es', source_sha=SHA, text_sha=SHA, producer_identity='test')
        receipt = {'schemaVersion': 'sermon-study-review-v1', **{k: artifact[k] for k in ('kind', 'pageId', 'locale', 'sourcePackageSha256', 'textCandidateSha256')},
                   'artifactSha256': d.sha(artifact), 'decision': 'approved', 'humanApproval': True,
                   'reviewedBy': 'test-reviewer', 'reviewedAt': NOW,
                   'checks': {'faithfulness': 'pass', 'scriptureIntegrity': 'pass', 'localeReadability': 'pass'}}
        return artifact, receipt
    outline, review = pair('outline')
    med, med_review = pair('meditation')
    assert study.join_artifacts(source_sha=SHA, text_sha=SHA, audio_sha=SHA)['status'] == 'partial'
    result = study.join_artifacts(source_sha=SHA, text_sha=SHA, audio_sha=SHA, outline=outline, outline_review=review, meditation=med, meditation_review=med_review)
    assert result['status'] == 'complete'
    outline['sections'][0]['body'] = 'changed'
    with pytest.raises(ValueError, match='bind artifact'):
        study.ingest_review(outline, review)


def test_readback_rechecks_bytes_and_rejects_media_ready(tmp_path):
    intent = {'schemaVersion': 'sermon-release-intent-v1', 'environment': 'dev', 'channel': 'dev', 'project': 'example-project', 'site': 'example-site', 'origin': 'https://example-site.web.app'}
    payload = b'content'
    readback = {'schemaVersion': 'sermon-client-readback-v1', 'intent': intent, 'candidateSha256': SHA, 'observedAt': NOW,
                'resources': [{'role': key, 'url': intent['origin'] + '/' + key, 'sha256': hashlib.sha256(payload).hexdigest()} for key in ['catalog', 'content', 'release']]}
    assert d.validate_readback(readback, expected_intent=intent, candidate_sha=SHA, reader=lambda url: (200, payload))['status'] == 'pass'
    with pytest.raises(ValueError, match='bytes changed'):
        d.validate_readback(readback, expected_intent=intent, candidate_sha=SHA, reader=lambda url: (200, b'old'))
    telemetry = {'schemaVersion': 'sermon-playback-observation-v1', 'candidateSha256': SHA, 'locale': 'es', 'origin': intent['origin'], 'runner': 'browser', 'paused': True}
    path = tmp_path / 'playback.json'
    path.write_text(json.dumps(telemetry))
    receipt = {'readback': readback, 'locales': ['es'], 'playback': [{'candidateSha256': SHA, 'locale': 'es', 'evidencePath': path.name, 'evidenceSha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}
    with pytest.raises(ValueError, match='did not advance'):
        d.verify_client_acceptance(receipt, expected_intent=intent, candidate_sha=SHA, reader=lambda url: (200, payload), evidence_root=tmp_path)


def test_metadata_and_route_preflight():
    with pytest.raises(ValueError, match='Placeholder'):
        d.validate_metadata({'title': 'Title', 'series': 'Series', 'speaker': '讲员信息待补充', 'scripture': 'John 1'})
    with pytest.raises(ValueError, match='duration'):
        d.validate_metadata({'title': 'Title', 'series': 'Series', 'speaker': 'Speaker', 'scripture': 'John 1', 'durationSeconds': 1}, measured_duration=60)
    with pytest.raises(ValueError, match='route mismatch'):
        d.validate_intent({'schemaVersion': 'sermon-release-intent-v1', 'environment': 'dev', 'channel': 'production'}, {'dev': {'channel': 'beta'}})

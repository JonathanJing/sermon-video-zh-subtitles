import hashlib
import json
import pytest
from scripts import sermon_unified_reviews as reviews
from scripts import delivery_contract as d
from scripts.sermon_production_supervisor import stable_hash, json_digest


def save(path, value):
    path.write_text(json.dumps(value))
    return {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def test_english_ingest_uses_original_receipt_and_rejects_changed_text(tmp_path):
    aligned = tmp_path / 'aligned.json'; aligned.write_text('[]')
    anchor = {'sourceUnits': [{'sourceUnitId': 'u1'}]}
    anchor_path = tmp_path / 'anchor.json'; save(anchor_path, anchor)
    receipt = {'schemaVersion': 'sermon-english-source-review-v1', 'alignedSegmentsSha256': hashlib.sha256(aligned.read_bytes()).hexdigest(),
               'anchorManifestJsonSha256': d.sha(anchor), 'humanApproval': True, 'reviewedBy': 'operator', 'reviewedAt': '2026-10-04T20:00:00Z', 'reviewedSourceUnitIds': ['u1'],
               'checks': {key: 'approved' for key in ['sourceIdentity', 'transcriptCompleteness', 'wordAlignment', 'sentenceAndPauseBoundaries']}}
    path = tmp_path / 'review.json'; save(path, receipt)
    assert reviews.validate_review('english', path, inputs={'aligned': aligned, 'anchor': anchor_path})['status'] == 'validated'
    aligned.write_text('[1]')
    with pytest.raises(ValueError, match='different aligned'):
        reviews.validate_review('english', path, inputs={'aligned': aligned, 'anchor': anchor_path})


def test_window_reuses_operator_receipt_with_exact_media_and_timeline(tmp_path):
    url = 'https://www.youtube.com/watch?v=test'
    media_sha = 'a' * 64
    timeline = {'schemaVersion': 2, 'stage': 'source_media_verified', 'boundaryMethod': 'operator_supplied', 'status': 'requires_operator_review',
                'sourceUrl': url, 'sunday': '2026-10-04', 'durationSeconds': 60, 'audioSha256': media_sha, 'audioSizeBytes': 100}
    receipt = {'status': 'approved', 'humanApproval': True, 'sunday': '2026-10-04', 'sourceUrlHash': stable_hash(url), 'startTime': '00:00:00', 'endTime': '00:01:00',
               'approvedBy': 'operator', 'timelineReportSha256': json_digest(timeline)}
    descriptor = {'sourceUrl': url, 'sourceId': 'test', 'mediaSha256': media_sha, 'sunday': '2026-10-04'}
    bindings = {key: save(tmp_path / (key + '.json'), obj) for key, obj in [('windowApproval', receipt), ('timelineReport', timeline), ('sourceDescriptor', descriptor)]}
    manifest = {'source': {'sourceUrlHash': hashlib.sha256(url.encode()).hexdigest(), 'sourceId': 'test', 'mediaSha256': media_sha, 'durationSeconds': 60,
                           'window': {'startSeconds': 0, 'endSeconds': 60, 'approvalReceiptSha256': bindings['windowApproval']['sha256']}}, 'bindings': bindings}
    assert reviews.validate_window(manifest, base=tmp_path)['status'] == 'validated'
    manifest['source']['window']['endSeconds'] = 59
    with pytest.raises(ValueError, match='bounds_changed'):
        reviews.validate_window(manifest, base=tmp_path)


def test_english_review_cannot_approve_another_active_source(tmp_path):
    from test_build_english_source_package import EnglishSourcePackageTests
    fixture = EnglishSourcePackageTests()
    fixture.setUp()
    try:
        source = fixture.build()
        source_path = tmp_path / 'source.json'; save(source_path, source)
        receipt = {'schemaVersion': 'sermon-english-source-review-v1', 'alignedSegmentsSha256': hashlib.sha256(fixture.segments_path.read_bytes()).hexdigest(),
                   'anchorManifestJsonSha256': d.sha(fixture.manifest), 'humanApproval': True, 'reviewedBy': 'operator', 'reviewedAt': '2026-10-04T20:00:00Z',
                   'reviewedSourceUnitIds': [row['sourceUnitId'] for row in fixture.manifest['sourceUnits']],
                   'checks': {key: 'approved' for key in ['sourceIdentity', 'transcriptCompleteness', 'wordAlignment', 'sentenceAndPauseBoundaries']}}
        path = tmp_path / 'review.json'; save(path, receipt)
        inputs = {'source': source_path, 'aligned': fixture.segments_path, 'anchor': fixture.manifest_path}
        expected = {'sourceId': source['source']['sourceId'], 'mediaSha256': source['source']['media']['sha256']}
        assert reviews.validate_review('english', path, inputs=inputs, expected_source=expected)['status'] == 'validated'
        with pytest.raises(ValueError, match='active run'):
            reviews.validate_review('english', path, inputs=inputs, expected_source={**expected, 'mediaSha256': 'e' * 64})
    finally:
        fixture.doCleanups()


def test_review_locale_must_match_job(tmp_path):
    path = tmp_path / 'review.json'; save(path, {'targetLocale': 'es'})
    with pytest.raises(ValueError, match='active job'):
        reviews.validate_review('translation', path, inputs={}, expected_locale='ko')

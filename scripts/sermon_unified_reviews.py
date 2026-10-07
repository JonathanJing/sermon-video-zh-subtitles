"""Read-only review ingestion using existing producer validation contracts.

The caller stores the validated receipt unchanged and binds its file hash. These
functions never create an approval or change a candidate's human-review fields.
A machine quality waiver is accepted for translation and audio and is reported
with ``reviewKind = machine_quality_waiver``, never as a human approval.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from scripts import delivery_contract as delivery
from scripts import machine_quality_release_basis as machine_basis
from scripts import study_artifacts

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def schema(value, name):
    Draft202012Validator(read(ROOT / 'schemas' / name), format_checker=FormatChecker()).validate(value)


def validate_review(kind, receipt_path, *, inputs, expected_source=None, expected_locale=None):
    """inputs values are paths except window sunday/sourceUrl.

    window: timeline, sunday, sourceUrl
    english: aligned, anchor
    translation: source, anchor, candidate
    audio: package, screening
    outline/meditation: artifact (independently frozen study output)
    """
    receipt_path = Path(receipt_path)
    receipt = read(receipt_path)
    bound_source = None
    if expected_source is not None and kind != 'window':
        delivery.require('source' in inputs, 'Current source package required for review ingestion')
        bound_source = read(inputs['source'])
        schema(bound_source, 'sermon-english-source-package-v1.schema.json')
        delivery.require(bound_source['source']['media']['sha256'] == expected_source['mediaSha256']
                         and bound_source['source']['sourceId'] == expected_source['sourceId'], 'Review source differs from active run')
        if 'sourceUrlHash' in expected_source:
            delivery.require(bound_source['source']['sourceUrlHash'] == expected_source['sourceUrlHash'], 'Review source URL differs')
        if 'window' in expected_source:
            delivery.require(all(bound_source['source']['approvedWindow'][key] == expected_source['window'][key] for key in ('startSeconds', 'endSeconds')), 'Review source window differs')
    observed_locale = receipt.get('targetLocale', receipt.get('locale'))
    if expected_locale is not None:
        delivery.require(observed_locale == expected_locale, 'Review locale differs from active job')
    if kind == 'window':
        from scripts.sermon_production_supervisor import validate_window_approval
        ok, reason = validate_window_approval(receipt, sunday=inputs['sunday'], live_url=inputs['sourceUrl'], timeline_report=read(inputs['timeline']))
        delivery.require(ok, reason or 'Window review failed')
    elif kind == 'english':
        from scripts.build_english_source_package import _review_payload
        anchor = read(inputs['anchor'])
        schema(receipt, 'sermon-english-source-review-v1.schema.json')
        if bound_source:
            delivery.require(bound_source['anchors']['artifact']['jsonSha256'] == delivery.sha(anchor)
                             and bound_source['transcript']['artifact']['sha256'] == receipt['alignedSegmentsSha256'],
                             'English review does not bind active source artifacts')
        _review_payload(receipt_path, aligned_sha256=hashlib.sha256(Path(inputs['aligned']).read_bytes()).hexdigest(),
                        anchor_json_sha256=delivery.sha(anchor), source_unit_ids=[row['sourceUnitId'] for row in anchor['sourceUnits']])
    elif kind == 'translation':
        from scripts.prepare_target_language_speech_job import validate_text_release_basis
        source, anchor, candidate = (read(inputs[name]) for name in ('source', 'anchor', 'candidate'))
        schema(source, 'sermon-english-source-package-v1.schema.json')
        schema(candidate, 'sermon-target-language-candidate-v2.schema.json')
        validate_text_release_basis(source, anchor, candidate, receipt)
    elif kind == 'audio':
        from scripts.stage_formal_multilingual_dev import validate_audio_screening_review
        package = read(inputs['package'])
        version = receipt.get('schemaVersion')
        delivery.require(version in {'sermon-target-language-audio-human-review-receipt-v' + str(n) for n in range(1, 5)}
                         | {machine_basis.AUDIO_WAIVER_SCHEMA}, 'Unsupported audio review')
        schema(receipt, version + '.schema.json')
        schema(package, 'sermon-target-language-audio-package-v1.schema.json')
        if bound_source:
            delivery.require(package['englishSourcePackageJsonSha256'] == delivery.sha(bound_source), 'Audio review source package differs')
        expected = {'targetLocale': package['targetLocale'], 'englishSourcePackageJsonSha256': package['englishSourcePackageJsonSha256'],
                    'targetLanguageCandidateJsonSha256': package['targetLanguageCandidateJsonSha256'],
                    'targetLanguageAudioPackageJsonSha256': delivery.sha(package), 'trackSha256': package['track']['sha256']}
        delivery.require(all(receipt.get(k) == v for k, v in expected.items()), 'Audio review package/track binding differs')
        delivery.require(receipt['reviewedUnitIds'] == [unit['textGroupId'] for unit in package['units']], 'Audio review coverage differs')
        screening = read(inputs['screening']) if inputs.get('screening') else None
        validate_audio_screening_review(package, receipt, screening)
    elif kind in ('outline', 'meditation'):
        artifact = read(inputs['artifact'])
        delivery.require(artifact['kind'] == kind, 'Study review kind differs')
        if bound_source:
            delivery.require(artifact['sourcePackageSha256'] == delivery.sha(bound_source), 'Study review source package differs')
        study_artifacts.ingest_review(artifact, receipt)
    else:
        raise ValueError('Unsupported review kind')
    return {'status': 'validated', 'kind': kind,
            'reviewKind': receipt.get('reviewKind', 'human_review') if kind in ('translation', 'audio') else 'human_review',
            'receiptPath': str(receipt_path.resolve()),
            'receiptSha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            'receiptJsonSha256': delivery.sha(receipt), 'locale': observed_locale,
            'sourceIdentity': bound_source['source'] if bound_source else None}


def validate_window(manifest, bindings=None, base='.'):
    """Validate the original operator receipt against URL, timeline, media, and exact window."""
    from scripts.sermon_production_supervisor import validate_window_approval, parse_timecode, stable_hash
    bindings = manifest['bindings'] if bindings is None else bindings
    base = Path(base).resolve()
    def bound(name):
        delivery.require(name in bindings, 'window_binding_required:' + name)
        row = bindings[name]
        path = (base / row['path']).resolve()
        delivery.require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'], 'window_binding_changed:' + name)
        return read(path)
    receipt = bound('windowApproval')
    timeline = bound('timelineReport')
    descriptor = bound('sourceDescriptor')
    url = descriptor.get('sourceUrl') or descriptor.get('url')
    source = manifest['source']
    delivery.require(url and hashlib.sha256(url.encode('utf-8')).hexdigest() == source['sourceUrlHash'], 'window_source_url_changed')
    delivery.require(descriptor.get('sourceId') == source['sourceId'] and descriptor.get('mediaSha256') == source['mediaSha256'], 'window_source_descriptor_changed')
    sunday = descriptor.get('sunday') or descriptor.get('serviceDate')
    delivery.require(sunday, 'window_source_date_required')
    ok, reason = validate_window_approval(receipt, sunday=sunday, live_url=url, timeline_report=timeline)
    delivery.require(ok, reason or 'window_review_invalid')
    delivery.require(timeline.get('audioSha256') == source['mediaSha256'], 'window_timeline_media_changed')
    delivery.require(timeline.get('durationSeconds') == source['durationSeconds'], 'window_timeline_duration_changed')
    window = source['window']
    delivery.require(parse_timecode(receipt['startTime']) == window['startSeconds']
                     and parse_timecode(receipt['endTime']) == window['endSeconds'], 'window_bounds_changed')
    delivery.require(window.get('approvalReceiptSha256') == bindings['windowApproval']['sha256'], 'window_approval_hash_changed')
    return {'status': 'validated', 'kind': 'window', 'receiptSha256': bindings['windowApproval']['sha256']}

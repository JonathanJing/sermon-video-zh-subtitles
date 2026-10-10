"""Read-only canonical package adapter using existing producer validators.

Layer 4 supports existing formal-dev candidates, not publication/HTTP acceptance.
No progress-ledger status, model, human approval creation or dispatch is involved.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import canonical_pipeline_definition as pipeline
from scripts import build_english_source_package as english
from scripts import prepare_target_language_speech_job as handoff
from scripts import produce_target_language_candidate as producer
from scripts import inspect_canonical_audio as audio_inspector
from scripts import inspect_canonical_release as release_inspector
from scripts.sermon_release_workflow import _safe_path
from scripts.sermon_workflow_jobs import _digest, _read

SCHEMA = 'sermon-canonical-package-inspection-config-v1'
SCHEMA_V2 = 'sermon-canonical-package-inspection-config-v2'
SCHEMA_V3 = 'sermon-canonical-package-inspection-config-v3'
MAX_JSON_BYTES = 16 * 1024 * 1024


def _read_package(root, reference, hashes, key):
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError('invalid_package_reference')
    path = _safe_path(root / reference)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError('package_exceeds_inspection_budget')
    value = _read(path)
    if not isinstance(value, dict):
        raise ValueError('package_must_be_object')
    # Bind the canonical JSON actually parsed, not a second read.
    hashes[key] = _digest(value)
    return value


def inspect(config_path, *, candidate_mode='production'):
    path = _safe_path(Path(config_path).absolute())
    config = _read_package(path.parent, str(path), {}, 'configuration')
    return inspect_configuration(path.parent, config, candidate_mode=candidate_mode)


def inspect_configuration(root, config, *, candidate_mode='production'):
    """Inspect a trusted backend's effective config through the same gates."""
    root = _safe_path(Path(root).absolute())
    if not isinstance(config, dict) or not root.is_dir():
        raise ValueError('invalid_inspection_configuration')
    version = config.get('schemaVersion')
    fields = {'schemaVersion', 'source', 'anchor', 'locales'} | ({'pageId'} if version == SCHEMA_V3 else set())
    if (set(config) != fields or version not in {SCHEMA, SCHEMA_V2, SCHEMA_V3}
            or not isinstance(config['locales'], dict) or not config['locales']
            or not set(config['locales']) <= set(pipeline.LOCALES)):
        raise ValueError('invalid_inspection_configuration')
    if version == SCHEMA_V3 and (not isinstance(config['pageId'], str)
                                or not release_inspector.stage.PAGE_ID.fullmatch(config['pageId'])):
        raise ValueError('invalid_page_identity')
    for lane in config['locales'].values():
        allowed = {'policy', 'candidate', 'humanReview'} | ({'audio'} if version != SCHEMA else set())
        if version == SCHEMA_V3:
            allowed.add('release')
        if not isinstance(lane, dict) or set(lane) - allowed or 'policy' not in lane:
            raise ValueError('invalid_locale_configuration')
        if 'audio' in lane:
            audio_inspector.validate_configuration(lane['audio'])
        if 'release' in lane:
            release_inspector.validate_configuration(lane['release'])
    spec = pipeline.definition(tuple(config['locales']))
    observations, approvals, hashes, diagnostics = {}, {}, {'configuration': _digest(config)}, {}
    def project():
        result = pipeline.plan(spec, input_identity=hashes.get('source', _digest({'source': 'unavailable'})),
                               observations=observations, approvals=approvals)
        # Local file identity participates even when a validator rejects it.
        result['stateRevision'] = _digest({'planRevision': result['stateRevision'], 'packageIdentities': hashes})
        result['packageIdentities'] = dict(hashes)
        result['inspectionDiagnostics'] = dict(diagnostics)
        result['inspectionCoverage'] = {'source': 'production_source_gate', 'text': 'production_candidate_and_review_gates',
                                        'audio': ('production_artifact_and_review_gates' if version != SCHEMA else 'not_integrated'),
                                        'release': ('formal_dev_candidate_assets_gate' if version == SCHEMA_V3 else 'not_integrated')}
        # Never label an unvalidated/missing policy as ready to invoke a model.
        for node, code in diagnostics.items():
            if node in result['nodes']:
                result['nodes'][node]['status'] = 'blocked'
                result['nodes'][node]['reasonCode'] = code
        return result
    try:
        source = _read_package(root, config['source'], hashes, 'source')
        anchor = _read_package(root, config['anchor'], hashes, 'anchor')
        handoff._validate_schema(source, 'sermon-english-source-package-v1.schema.json', 'source package')
        english.validate_ready_package(source)
        producer.validate_source_for_translation(source, anchor)
        summary_evidence = source['evidence']['pipelineSummary']
        if summary_evidence is None:
            raise ValueError('source_media_summary_missing')
        summary = _read_package(root, summary_evidence['path'], hashes, 'sourceSummary')
        if (english.file_sha256(_safe_path(root / summary_evidence['path'])) != summary_evidence['sha256']
                or hashes['sourceSummary'] != summary_evidence['jsonSha256']
                or english._source_media(summary) != source['source']['media']):
            raise ValueError('source_media_summary_changed')
        window = source['source']['approvedWindow']
        start, end = summary.get('sermonStartSeconds'), summary.get('sermonEndSeconds')
        if not english._finite(start) or start < 0:
            start = min(float(unit['start']) for unit in anchor['sourceUnits'])
        if not english._finite(end) or end <= start:
            end = max(float(unit['end']) for unit in anchor['sourceUnits'])
        if window['startSeconds'] != start or window['endSeconds'] != end:
            raise ValueError('source_window_summary_changed')
        window_evidence = window['evidence']
        window_receipt = _read_package(root, window_evidence['path'], hashes, 'sourceWindowReview')
        if (source['issues'] or window['status'] != 'approved'
                or window_receipt.get('status') != 'approved' or window_receipt.get('humanApproval') is not True
                or english.file_sha256(_safe_path(root / window_evidence['path'])) != window_evidence['sha256']
                or hashes['sourceWindowReview'] != window_evidence['jsonSha256']
                or not english.approval_url_matches(window_receipt, source['source']['sourceUrlHash'],
                                                    source_url=summary.get('sourceUrl'))):
            raise ValueError('source_window_approval_changed')
        # The source's independent human receipt and aligned transcript remain
        # immutable evidence; do not accept a copied approval flag alone.
        aligned = source['transcript']['artifact']
        aligned_path = _safe_path(root / aligned['path'])
        if english.file_sha256(aligned_path) != aligned['sha256']:
            raise ValueError('aligned_transcript_identity_changed')
        reviewed, _ = english._review_payload(
            _safe_path(root / source['review']['evidence']['path']),
            aligned_sha256=aligned['sha256'], anchor_json_sha256=hashes['anchor'],
            source_unit_ids=[unit['sourceUnitId'] for unit in anchor['sourceUnits']])
        if reviewed != source['review']:
            raise ValueError('source_review_receipt_changed')
    except (ValueError, TypeError, KeyError, OSError):
        diagnostics['source'] = 'source_or_anchor_not_validated'
        return project()
    source_id = project()['nodes']['source']['identity']
    approvals['source'] = {'source_review': {'identity': source_id, 'receiptSha256': _digest(source['review'])}}
    observations['source'] = {'identity': source_id, 'status': 'validated', 'outputSha256': hashes['source']}
    for locale, lane in sorted(config['locales'].items()):
        text, audio = 'text.' + locale, 'audio.' + locale
        try:
            policy = _read_package(root, lane['policy'], hashes, 'policy.' + locale)
            request = producer.prepare_request(source, anchor, policy, candidate_mode=candidate_mode)
            if request['targetLocale'] != locale:
                raise ValueError('policy_locale_mismatch')
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics[text] = 'policy_not_validated'
            continue
        if 'candidate' not in lane:
            continue
        try:
            candidate = _read_package(root, lane['candidate'], hashes, 'candidate.' + locale)
            handoff._validate_schema(candidate, 'sermon-target-language-candidate-v2.schema.json', 'candidate')
            handoff.validate_target_candidate(source, anchor, candidate, require_human_approval=False)
            handoff.validate_policy_binding(candidate, policy)
            if candidate['targetLocale'] != locale or candidate['status'] not in {
                    'machine_review_pass_human_review_pending', 'human_translation_approved'}:
                raise ValueError('candidate_not_machine_reviewed')
            text_id = project()['nodes'][text]['identity']
            observations[text] = {'identity': text_id, 'status': 'validated', 'outputSha256': hashes['candidate.' + locale]}
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics[text] = 'candidate_not_validated'
            continue
        if 'humanReview' not in lane:
            continue
        try:
            receipt = _read_package(root, lane['humanReview'], hashes, 'review.' + locale)
            # A human receipt or a machine quality waiver satisfies this gate.
            released = handoff.validate_released_candidate(source, anchor, candidate, receipt)
            audio_id = project()['nodes'][audio]['identity']
            approvals[audio] = {'translation_review': {'identity': audio_id, 'receiptSha256': hashes['review.' + locale]}}
            if released['textPolicy'] == handoff.MACHINE_TEXT_POLICY:
                # Satisfied by policy, but never recorded as a human approval.
                approvals[audio]['translation_review']['kind'] = pipeline.WAIVER_KIND
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics[audio] = 'translation_review_not_validated'
            continue
        if 'audio' not in lane:
            continue
        try:
            upstream = {'source': root / config['source'], 'anchor': root / config['anchor'],
                        'candidate': root / lane['candidate'], 'policy': root / lane['policy'],
                        'human_receipt': root / lane['humanReview']}
            checked = audio_inspector.inspect(root, lane['audio'], upstream, _read_package, hashes, locale)
            expected = {'source': hashes['source'], 'anchor': hashes['anchor'],
                        'candidate': hashes['candidate.' + locale], 'policy': hashes['policy.' + locale],
                        'human_receipt': hashes['review.' + locale]}
            if any(checked['upstreamIdentities'][key] != value for key, value in expected.items()):
                raise ValueError('audio_upstream_identity_changed')
            approvals[audio]['voice_authorization'] = {
                'identity': audio_id, 'receiptSha256': checked['voiceAuthorizationSha256']}
            observations[audio] = {'identity': audio_id, 'status': 'validated', 'outputSha256': checked['outputSha256']}
            if checked['listeningReviewSha256'] is not None:
                page = 'page.' + locale
                page_id = project()['nodes'][page]['identity']
                approvals[page] = {'audio_listening_review': {
                    'identity': page_id, 'receiptSha256': checked['listeningReviewSha256']}}
                if checked.get('listeningReviewKind') == 'machine_quality_waiver':
                    approvals[page]['audio_listening_review']['kind'] = pipeline.WAIVER_KIND
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics[audio] = 'audio_package_or_review_not_validated'
            continue
        if 'release' not in lane or checked['listeningReviewSha256'] is None:
            continue
        try:
            release_sha = release_inspector.inspect(
                root, lane['release'], page_id=config['pageId'], locale=locale,
                source=source, candidate=candidate, audio_path=root / lane['audio']['package'],
                audio_sha256=checked['outputSha256'], read_package=_read_package, hashes=hashes)
            observations[page] = {'identity': page_id, 'status': 'validated', 'outputSha256': release_sha}
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics['page.' + locale] = 'release_candidate_not_validated'
    return project()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.config), sort_keys=True, ensure_ascii=False))


if __name__ == '__main__':
    main()

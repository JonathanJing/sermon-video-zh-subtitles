"""Read-only canonical Source/Text/Audio adapter using existing producer validators.

Layer 4 release inspection remains explicitly unsupported.
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
from scripts.sermon_release_workflow import _safe_path
from scripts.sermon_workflow_jobs import _digest, _read

SCHEMA = 'sermon-canonical-package-inspection-config-v1'
SCHEMA_V2 = 'sermon-canonical-package-inspection-config-v2'
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


def inspect(config_path):
    path = _safe_path(Path(config_path).absolute())
    config = _read_package(path.parent, str(path), {}, 'configuration')
    if (set(config) != {'schemaVersion', 'source', 'anchor', 'locales'} or config['schemaVersion'] not in {SCHEMA, SCHEMA_V2}
            or not isinstance(config['locales'], dict) or not config['locales']
            or not set(config['locales']) <= set(pipeline.LOCALES)):
        raise ValueError('invalid_inspection_configuration')
    for lane in config['locales'].values():
        allowed = {'policy', 'candidate', 'humanReview'} | ({'audio'} if config['schemaVersion'] == SCHEMA_V2 else set())
        if not isinstance(lane, dict) or set(lane) - allowed or 'policy' not in lane:
            raise ValueError('invalid_locale_configuration')
        if 'audio' in lane:
            audio_inspector.validate_configuration(lane['audio'])
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
                                        'audio': ('production_artifact_and_review_gates' if config['schemaVersion'] == SCHEMA_V2
                                                  else 'not_integrated'), 'release': 'not_integrated'}
        # Never label an unvalidated/missing policy as ready to invoke a model.
        for node, code in diagnostics.items():
            if node in result['nodes']:
                result['nodes'][node]['status'] = 'blocked'
                result['nodes'][node]['reasonCode'] = code
        return result
    try:
        source = _read_package(path.parent, config['source'], hashes, 'source')
        anchor = _read_package(path.parent, config['anchor'], hashes, 'anchor')
        handoff._validate_schema(source, 'sermon-english-source-package-v1.schema.json', 'source package')
        producer.validate_source_for_translation(source, anchor)
        window = source['source']['approvedWindow']
        window_evidence = window['evidence']
        window_receipt = _read_package(path.parent, window_evidence['path'], hashes, 'sourceWindowReview')
        if (source['issues'] or window['status'] != 'approved'
                or window_receipt.get('status') != 'approved' or window_receipt.get('humanApproval') is not True
                or english.file_sha256(_safe_path(path.parent / window_evidence['path'])) != window_evidence['sha256']
                or hashes['sourceWindowReview'] != window_evidence['jsonSha256']
                or window_receipt.get('sourceUrlHash') not in (None, source['source']['sourceUrlHash'])):
            raise ValueError('source_window_approval_changed')
        # The source's independent human receipt and aligned transcript remain
        # immutable evidence; do not accept a copied approval flag alone.
        aligned = source['transcript']['artifact']
        aligned_path = _safe_path(path.parent / aligned['path'])
        if english.file_sha256(aligned_path) != aligned['sha256']:
            raise ValueError('aligned_transcript_identity_changed')
        reviewed, _ = english._review_payload(
            _safe_path(path.parent / source['review']['evidence']['path']),
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
            policy = _read_package(path.parent, lane['policy'], hashes, 'policy.' + locale)
            request = producer.prepare_request(source, anchor, policy)
            if request['targetLocale'] != locale:
                raise ValueError('policy_locale_mismatch')
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics[text] = 'policy_not_validated'
            continue
        if 'candidate' not in lane:
            continue
        try:
            candidate = _read_package(path.parent, lane['candidate'], hashes, 'candidate.' + locale)
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
            receipt = _read_package(path.parent, lane['humanReview'], hashes, 'review.' + locale)
            handoff.validate_target_candidate(source, anchor, candidate)
            handoff.validate_human_review_receipt(source, anchor, candidate, receipt)
            audio_id = project()['nodes'][audio]['identity']
            approvals[audio] = {'translation_review': {'identity': audio_id, 'receiptSha256': hashes['review.' + locale]}}
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics[audio] = 'translation_review_not_validated'
            continue
        if 'audio' not in lane:
            continue
        try:
            upstream = {'source': path.parent / config['source'], 'anchor': path.parent / config['anchor'],
                        'candidate': path.parent / lane['candidate'], 'policy': path.parent / lane['policy'],
                        'human_receipt': path.parent / lane['humanReview']}
            checked = audio_inspector.inspect(path.parent, lane['audio'], upstream, _read_package, hashes, locale)
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
        except (ValueError, TypeError, KeyError, OSError):
            diagnostics[audio] = 'audio_package_or_review_not_validated'
    return project()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.config), sort_keys=True, ensure_ascii=False))


if __name__ == '__main__':
    main()

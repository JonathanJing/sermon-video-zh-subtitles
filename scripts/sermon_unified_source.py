"""Fixed formal source preparation: bounded ASR, existing MFA, anchors and judge.

The result is an English Source *candidate*. Full English/source human review
remains pending. Speaker labels remain anonymous and chunk-local; no person
identity is inferred. inspect is read-only; execute never publishes or translates.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import build_english_source_package as english
from scripts import canonical_layer2_controller as code
from scripts import english_source_judge_cache as immutable
from scripts import judge_english_source_for_translation as judge
from scripts import mfa_backend
from scripts import sermon_accounting as accounting
from scripts import sermon_sentence_interpretation as anchors
from scripts import sermon_source_budget as budget
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-unified-source-preparation-v1'
FIELDS = {'schemaVersion', 'productionRunId', 'sourceId', 'sourceUrlHash', 'serviceDate',
          'media', 'mediaSha256', 'sourceDurationSeconds', 'window', 'windowApproval', 'windowApprovalSha256',
          'timelineReport', 'timelineReportSha256', 'sourceDescriptor', 'sourceDescriptorSha256',
          'jobRoot', 'outputDirectory', 'budgetAuthorization', 'mfa', 'anchorPolicy', 'judge'}
LOCAL_MFA_FIELDS = {'mfa_executable', 'dictionary_path', 'acoustic_model', 'g2p_model', 'spoken_forms_path'}
SPARK_MFA_FIELDS = LOCAL_MFA_FIELDS | {'host', 'proxy_jump', 'relay_host', 'relay_host_key_alias', 'python', 'root'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def _load(path):
    path = _safe_path(Path(path).absolute())
    require(path.is_file() and path.stat().st_size <= 32 * 1024 * 1024, 'source_input_size_invalid')
    return jobs._read(path)


def _sha(path):
    return english.file_sha256(_safe_path(Path(path).absolute()))


def _freeze(path, value):
    if path.exists():
        require(_load(path) == value, 'source_immutable_artifact_changed:' + path.name)
    else:
        immutable._atomic(path, value)


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class Configuration:
    path: Path
    value: dict
    media: Path
    output: Path
    job_root: Path
    window_receipt: Path
    identity: str
    code_identity: str
    authority: dict
    budget_root: Path
    approval_hash: str
    authorization_hash: str


def load_configuration(path):
    path = _safe_path(Path(path).absolute())
    value = _load(path)
    require(isinstance(value, dict) and set(value) == FIELDS and value['schemaVersion'] == SCHEMA,
            'invalid_source_preparation_configuration')
    require(all(isinstance(value[k], str) and english.SHA256.fullmatch(value[k]) for k in
                ('productionRunId', 'sourceUrlHash', 'mediaSha256', 'windowApprovalSha256',
                 'timelineReportSha256', 'sourceDescriptorSha256')),
            'invalid_source_identity')
    require(isinstance(value['sourceId'], str) and bool(value['sourceId'].strip()), 'source_id_required')
    english._validate_service_date(value['serviceDate'])
    window = value['window']
    require(isinstance(window, dict) and set(window) == {'startSeconds', 'endSeconds'}
            and all(_positive(v) for v in window.values())
            and 0 < window['endSeconds'] - window['startSeconds'] <= 6 * 3600, 'invalid_source_window')
    def resolve(key):
        require(isinstance(value[key], str) and value[key].strip(), 'invalid_source_path')
        return _safe_path(path.parent / value[key])
    media, output, job_root, receipt_path = (resolve(k) for k in
        ('media', 'outputDirectory', 'jobRoot', 'windowApproval'))
    require(media.is_file() and _sha(media) == value['mediaSha256'], 'source_media_identity_changed')
    require(not any(output == p or output in p.parents for p in (media, path, receipt_path, job_root))
            and not (job_root == output or job_root in output.parents), 'source_paths_overlap')
    from scripts.sermon_unified_reviews import validate_window
    require(_positive(value['sourceDurationSeconds']) and value['sourceDurationSeconds'] > 0,
            'invalid_source_duration')
    bindings = {name: {'path': str(resolve(name)), 'sha256': value[name + 'Sha256']}
                for name in ('windowApproval', 'timelineReport', 'sourceDescriptor')}
    validate_window({'source': {'sourceId': value['sourceId'], 'sourceUrlHash': value['sourceUrlHash'],
        'mediaSha256': value['mediaSha256'], 'durationSeconds': value['sourceDurationSeconds'],
        'window': {**window, 'approvalReceiptSha256': value['windowApprovalSha256']}}, 'bindings': bindings},
        base=path.parent)
    mfa = value['mfa']
    require(isinstance(mfa, dict) and set(mfa) == {'backend', 'allowSparkFallback', 'localOptions', 'sparkOptions'}
            and mfa['backend'] in {'auto', 'spark', 'macbook'} and type(mfa['allowSparkFallback']) is bool
            and isinstance(mfa['localOptions'], dict) and set(mfa['localOptions']) == LOCAL_MFA_FIELDS
            and isinstance(mfa['sparkOptions'], dict) and set(mfa['sparkOptions']) == SPARK_MFA_FIELDS,
            'invalid_source_mfa_configuration')
    require(all(v is None or isinstance(v, str) for v in mfa['localOptions'].values())
            and all(v is None or isinstance(v, str) for v in mfa['sparkOptions'].values()),
            'invalid_source_mfa_option')
    policy = value['anchorPolicy']
    require(isinstance(policy, dict) and set(policy) == {'maxUnitSeconds', 'boundaryOverrides'}
            and type(policy['maxUnitSeconds']) in (int, float) and 1 <= policy['maxUnitSeconds'] <= 120
            and (policy['boundaryOverrides'] is None or isinstance(policy['boundaryOverrides'], dict)),
            'invalid_source_anchor_policy')
    require(isinstance(value['judge'], dict) and set(value['judge']) == {'model', 'reasoningEffort', 'batchSize', 'workers'}
            and value['judge']['model'] in ('gpt-6-astra', 'gpt-6.1-sol')
            and value['judge']['reasoningEffort'] in budget.text_limits.SUPPORTED_REASONING_EFFORTS
            and type(value['judge']['batchSize']) is int and 1 <= value['judge']['batchSize'] <= 15
            and type(value['judge']['workers']) is int and value['judge']['workers'] == 1,
            'invalid_source_judge_configuration')
    identity = jobs._digest({k: v for k, v in value.items() if k != 'budgetAuthorization'})
    code_identity = code.code_identity()
    auth_path = resolve('budgetAuthorization')
    auth = _load(auth_path)
    require(isinstance(auth, dict) and set(auth) == {'schemaVersion', 'binding', 'authority', 'approvalReceipt'}
            and auth['schemaVersion'] == 'sermon-source-budget-authorization-v1', 'source_budget_authorization_required')
    budget_root = job_root.parent / f'.{job_root.name}.source-budget'
    expected = {'productionRunId': value['productionRunId'], 'configurationSha256': identity,
                'codeIdentitySha256': code_identity, 'budgetRoot': str(budget_root)}
    require(auth['binding'] == expected, 'source_budget_execution_binding_changed')
    authority = auth['authority']
    budget.SourceBudget(budget_root, authority, verify=lambda: None)
    approval_path = _safe_path(auth_path.parent / auth['approvalReceipt'])
    approval = _load(approval_path)
    require(_sha(approval_path) == authority['approvalSha256']
            and approval.get('schemaVersion') == 'sermon-source-budget-approval-v1'
            and approval.get('binding') == {**expected, 'globalBounds': authority['globalBounds'],
                                            'requestLimits': authority['requestLimits']}
            and approval.get('humanApproval') is True and approval.get('decision') == 'approved'
            and approval.get('operatorEvidence') and approval.get('reviewedBy') and approval.get('reviewedAt'),
            'source_budget_approval_not_bound')
    return Configuration(path, value, media, output, job_root, receipt_path, identity,
                         code_identity, authority, budget_root, _sha(approval_path), _sha(auth_path))


def inspect(config_path):
    """Pure local configuration/identity inspection; no remote MFA or provider."""
    config = load_configuration(config_path)
    duration = config.value['window']['endSeconds'] - config.value['window']['startSeconds']
    count = math.ceil(duration / 180)
    return {'schemaVersion': 'sermon-unified-source-inspection-v1', 'status': 'ready',
            'configurationSha256': config.identity, 'codeIdentitySha256': config.code_identity,
            'sourceMediaSha256': config.value['mediaSha256'], 'mediaSha256': config.value['mediaSha256'],
            'sourceId': config.value['sourceId'], 'window': config.value['window'],
            'sourceUrlHash': config.value['sourceUrlHash'],
            'sourceIdentity': {key: config.value[key] for key in
                ('productionRunId', 'sourceId', 'sourceUrlHash', 'mediaSha256',
                 'sourceDurationSeconds', 'window', 'windowApprovalSha256')},
            'sourceDurationSeconds': config.value['sourceDurationSeconds'],
            'windowApprovalSha256': config.value['windowApprovalSha256'],
            'policy': {'anchorPolicy': config.value['anchorPolicy'], 'judge': config.value['judge'], 'mfa': config.value['mfa']},
            'inputsSha256': {'configuration': _sha(config.path), 'media': config.value['mediaSha256'],
                'windowApproval': _sha(config.window_receipt),
                'timelineReport': config.value['timelineReportSha256'],
                'sourceDescriptor': config.value['sourceDescriptorSha256'],
                'budgetAuthorization': config.authorization_hash,
                'budgetApproval': config.approval_hash}, 'snapshotBound': True,
            'productionRunId': config.value['productionRunId'],
            'outputDirectory': str(config.output), 'budgetRoot': str(config.budget_root),
            'globalBounds': config.authority['globalBounds'], 'chunkCount': count, 'chunkMaxSeconds': 180,
            'mfaBackend': config.value['mfa']['backend'], 'mfaRuntimeVerified': False,
            'humanSourceReview': 'pending', 'productionTranslationEligible': False}


def _mfa_options(config):
    value = config.value['mfa']
    return {'backend': value['backend'], 'allow_spark_fallback': value['allowSparkFallback'],
            'local_options': value['localOptions'], 'spark_options': value['sparkOptions']}


def _probe(path):
    value = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=60, check=True)
    duration = float(json.loads(value.stdout)['format']['duration'])
    require(math.isfinite(duration) and duration > 0, 'source_media_duration_invalid')
    return duration


def _validate_pcm(path, duration):
    expected_samples = round(duration * 16000)
    with wave.open(str(path), 'rb') as decoded:
        require(decoded.getnchannels() == 1 and decoded.getsampwidth() == 2
                and decoded.getframerate() == 16000 and decoded.getcomptype() == 'NONE',
                'source_extracted_audio_format_changed')
        frames = decoded.getnframes()
        require(abs(frames - expected_samples) <= 1, 'source_extracted_audio_duration_changed')
        remaining = frames
        while remaining:
            count = min(remaining, 65536)
            require(len(decoded.readframes(count)) == count * 2, 'source_extracted_audio_truncated')
            remaining -= count


def _audio(config, path, start, duration):
    identity = {'mediaSha256': config.value['mediaSha256'], 'startSeconds': start,
                'durationSeconds': duration, 'sampleRate': 16000, 'channels': 1, 'sampleWidth': 2}
    receipt = path.with_suffix('.identity.json')
    if path.exists():
        require(receipt.is_file(), 'source_audio_identity_missing')
        saved = _load(receipt)
        require(saved.get('identity') == identity and saved.get('sha256') == _sha(path), 'source_audio_identity_changed')
        _validate_pcm(path, duration)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.wav', dir=path.parent)
    os.close(fd)
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', format(start, '.9f'), '-t', format(duration, '.9f'),
                        '-i', str(config.media), '-vn', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', temporary],
                       check=True, capture_output=True, timeout=max(60, duration * 2))
        _validate_pcm(temporary, duration)
        saved = {'identity': identity, 'sha256': _sha(temporary)}
        # Receipt first: a crash can leave a receipt without audio, which is
        # safely re-extracted and must produce the exact frozen bytes.
        _freeze(receipt, saved)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def _reference_rows(response, index, start, end):
    text = response.get('text')
    require(isinstance(text, str) and bool(text.strip()), 'source_transcript_missing_text')
    base = f'chunk-{index:04d}'
    segments = response.get('segments')
    if isinstance(segments, list) and segments and any('speaker' in row for row in segments if isinstance(row, dict)):
        require(all(isinstance(row, dict) and isinstance(row.get('text'), str)
                    and _positive(row.get('start')) and _positive(row.get('end'))
                    and row['end'] > row['start'] and row['end'] <= end - start + .002 for row in segments),
                'source_speaker_turn_timing_invalid')
        require(' '.join(' '.join(row['text'].split()) for row in segments).split() == text.split(),
                'source_speaker_turn_text_differs')
        names, rows, previous_end = {}, [], 0
        for number, segment in enumerate(segments):
            require(segment['start'] >= previous_end, 'source_speaker_turns_overlap')
            previous_end = segment['end']
            label = segment.get('speaker')
            require(label is None or isinstance(label, (str, int)), 'source_speaker_label_invalid')
            if label is not None:
                names.setdefault(str(label), f'{base}-anonymous-{len(names) + 1:03d}')
            rows.append({'id': f'{base}-turn-{number:04d}', 'start': start + segment['start'],
                         'end': start + segment['end'], 'text': segment['text'],
                         'speakerId': names.get(str(label)) if label is not None else None,
                         'speakerIdentityStatus': 'anonymous_chunk_local' if label is not None else 'unavailable'})
        return rows
    return [{'id': base, 'start': start, 'end': end, 'text': text,
             'speakerId': None, 'speakerIdentityStatus': 'unavailable'}]


def execute(config_path, *, api_key=None, transport=None, aligner=None, mfa_preflight=None):
    """Execute a fixed candidate recipe. Injection seams are offline tests only."""
    config = load_configuration(config_path)
    def fresh():
        current = load_configuration(config.path)
        require((current.identity, current.code_identity, current.approval_hash, current.authorization_hash) ==
                (config.identity, config.code_identity, config.approval_hash, config.authorization_hash),
                'source_execution_binding_changed')
    with work_lock(config.output):
        config.output.mkdir(parents=True, exist_ok=True)
        with accounting.accounting_session(config.output / 'accounting', 'unified_source_preparation',
                {'productionRunId': config.value['productionRunId']}, evidence_directory=config.output):
            return _execute(config, fresh, api_key=api_key, transport=transport,
                            aligner=aligner or mfa_backend.align_reference_chunks,
                            mfa_preflight=mfa_preflight or mfa_backend.preflight)


def _execute(config, fresh, *, api_key, transport, aligner, mfa_preflight):
    out, value = config.output, config.value
    # Reject the incompatible text budget before spending on source ASR.
    require(value['judge']['model'] != 'gpt-6.1-sol', 'codex_cli_provider_output_cap_unsupported')
    _freeze(out / 'source-run.json', {'configurationSha256': config.identity,
                                     'codeIdentitySha256': config.code_identity,
                                     'authorizationSha256': config.authorization_hash})
    total_duration = _probe(config.media)
    window = value['window']
    require(abs(total_duration - value['sourceDurationSeconds']) <= .002, 'source_duration_identity_changed')
    require(window['endSeconds'] <= total_duration + .002, 'source_window_exceeds_media')
    duration = window['endSeconds'] - window['startSeconds']
    aligned_path, manifest_path = out / 'aligned-segments.json', out / 'anchor-manifest.json'
    if not aligned_path.exists():
        require(not (out / 'mfa-started.json').exists(), 'source_mfa_outcome_unknown_reconciliation_required')
        runtime = mfa_preflight(**_mfa_options(config))
        _freeze(out / 'mfa-preflight.json', runtime)
    clip = _audio(config, out / 'source-clip.wav', window['startSeconds'], duration)
    caller = budget.SourceBudget(config.budget_root, config.authority, verify=fresh, transport=transport)
    references, finals = [], []
    for index in range(math.ceil(duration / 180)):
        start, end = index * 180, min((index + 1) * 180, duration)
        audio = _audio(config, out / 'chunks' / f'{index:04d}.wav', window['startSeconds'] + start, end - start)
        if api_key is None:
            api_key = os.environ.get('OPENAI_API_KEY', '')
        # Cached complete chunks remain usable without a key; a production miss
        # cannot reach the network without a nonempty key.
        if transport is None and not api_key:
            ledger_path = config.budget_root / 'source-budget.json'
            ledger = _load(ledger_path) if ledger_path.exists() else {'requests': {}}
            require(ledger['requests'].get(f'asr.{index:04d}', {}).get('status') == 'returned',
                    'OPENAI_API_KEY_is_not_configured')
        response = caller.transcribe(f'asr.{index:04d}', audio.read_bytes(), _sha(audio), api_key or '')
        final = {'schemaVersion': 'sermon-source-asr-final-v1', 'chunkIndex': index,
                 'sourceMediaSha256': value['mediaSha256'], 'sourceWindow': window,
                 'clipStartSeconds': start, 'clipEndSeconds': end, 'audioSha256': _sha(audio),
                 'model': 'gpt-transcribe', 'response': response}
        _freeze(out / 'chunks' / f'{index:04d}.asr-final.json', final)
        finals.append(final)
        references.extend(_reference_rows(response, index, start, end))
    _freeze(out / 'asr_reference_chunks.json', references)
    _freeze(out / 'asr_reference.json', {'text': '\n'.join(row['response']['text'] for row in finals),
                                         'chunksSha256': jobs._digest(finals), 'immutableAsrFinal': True})
    _freeze(out / 'speaker-turns.json', {'schemaVersion': 'sermon-source-anonymous-turns-v1',
        'identityMapping': 'not_performed', 'crossChunkIdentity': 'unknown',
        'turns': [{k: row[k] for k in ('id', 'start', 'end', 'speakerId', 'speakerIdentityStatus')} for row in references]})
    alignment_marker = out / 'mfa-started.json'
    if aligned_path.exists():
        aligned = _load(aligned_path)
        evidence = _load(out / 'alignment-receipt.json')
        require(evidence['alignedSha256'] == _sha(aligned_path)
                and evidence['referenceSha256'] == jobs._digest(references)
                and evidence['clipSha256'] == _sha(clip), 'source_alignment_cache_changed')
    else:
        require(not alignment_marker.exists(), 'source_mfa_outcome_unknown_reconciliation_required')
        _freeze(alignment_marker, {'referenceSha256': jobs._digest(references), 'clipSha256': _sha(clip),
                                   'configurationSha256': config.identity})
        aligned = aligner(references, clip, out / 'mfa', **_mfa_options(config))
        # Preserve evidence-backed anonymous turns separately and on each aligned
        # row. No diarization label is mapped to a real person or across chunks.
        by_chunk = {str(row['id']): row for row in references}
        require(isinstance(aligned, list) and aligned, 'source_alignment_empty')
        for row in aligned:
            reference = by_chunk.get(str(row.get('referenceChunkId')))
            require(reference is not None, 'source_alignment_reference_changed')
            row['speakerId'] = reference['speakerId']
            row['speakerIdentityStatus'] = reference['speakerIdentityStatus']
        fresh()
        _freeze(aligned_path, aligned)
        _freeze(out / 'alignment-receipt.json', {'alignedSha256': _sha(aligned_path),
            'referenceSha256': jobs._digest(references), 'clipSha256': _sha(clip),
            'runtime': _load(out / 'mfa' / 'backend.json')})
    manifest = anchors.build_anchor_manifest(aligned, source_path=aligned_path,
        unit_policy=anchors.UNIT_POLICY_V2, max_unit_seconds=value['anchorPolicy']['maxUnitSeconds'],
        boundary_overrides=value['anchorPolicy']['boundaryOverrides'])
    _freeze(manifest_path, manifest)
    descriptor = _load(config.path.parent / value['sourceDescriptor'])
    summary = {'status': 'english_source_candidate', 'source': str(config.media),
        'sourceUrl': descriptor.get('sourceUrl') or descriptor.get('url'),
        'sourceDurationSeconds': total_duration, 'sourceClip': str(clip), 'clipDurationSeconds': duration,
        'sermonStartSeconds': window['startSeconds'], 'sermonEndSeconds': window['endSeconds'],
        'models': {'referenceAsr': 'gpt-transcribe'}, 'outputMode': 'reading', 'readingAligner': 'mfa',
        'readingAlignmentRuntime': _load(out / 'alignment-receipt.json')['runtime'],
        'timingPrecision': 'mfa_word_aligned',
        'sourceAsrEvidence': english.artifact(out / 'asr_reference.json', value=_load(out / 'asr_reference.json')),
        'sourceChunkEvidence': english.artifact(out / 'asr_reference_chunks.json', value=references),
        'speakerTurnEvidence': english.artifact(out / 'speaker-turns.json', value=_load(out / 'speaker-turns.json')),
        'speakerIdentityMapping': 'not_performed',
        'pipelineInputIdentity': {'sourceAudio': {'sha256': value['mediaSha256'], 'sizeBytes': config.media.stat().st_size},
                                 'readingAligner': 'mfa'}, 'segmentCount': len(aligned)}
    _freeze(out / 'summary.json', summary)
    with budget.judge_limits(config.authority['requestLimits']):
        judged = judge.run(aligned_path=aligned_path, manifest_path=manifest_path, out=out / 'machine-judge.json',
            api_key=api_key or '', caller=caller.judge, cache_root=out / 'judge-requests',
            model=value['judge']['model'], effort=value['judge']['reasoningEffort'],
            batch_size=value['judge']['batchSize'], workers=value['judge']['workers'])
    package = english.build_package(aligned_path, manifest_path, summary_path=out / 'summary.json',
        approval_evidence_path=config.window_receipt, machine_judge_path=out / 'machine-judge.json',
        source_id=value['sourceId'], source_url_hash=value['sourceUrlHash'], service_date=value['serviceDate'])
    require(package['translationEligible'] is False, 'source_preparation_cannot_grant_human_review')
    fresh()
    _freeze(out / 'english-source-candidate.json', package)
    return {'status': 'succeeded' if judged['layer2DevelopmentEligible'] else 'blocked',
            'kind': 'english_source_candidate',
            'reason': ('human_source_review_required' if judged['layer2DevelopmentEligible']
                                           else 'source_machine_judge_rejected'),
            'artifact': 'verified' if judged['layer2DevelopmentEligible'] else 'present_unverified',
            'review': 'human_pending', 'productionEligible': False, 'humanApprovalCreated': False,
            'candidatePath': str(out / 'english-source-candidate.json'), 'candidateSha256': jobs._digest(package),
            'sourceMediaSha256': value['mediaSha256'], 'chunkCount': len(finals),
            'speakerIdentityMapping': 'not_performed', 'speakerReview': 'required',
            'machineJudgeStatus': judged['status']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'execute'))
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    result = inspect(args.config) if args.command == 'inspect' else execute(args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in {'ready', 'succeeded'} else 2


if __name__ == '__main__':
    raise SystemExit(main())

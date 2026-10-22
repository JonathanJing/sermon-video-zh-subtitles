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
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextvars import copy_context

from . import backend as _source
from . import english_source_package as english
from . import english_source_judge_cache as immutable


class _CodeIdentity:
    """Code identity through the Layer 1 port; `code.code_identity` stays a test seam."""
    @staticmethod
    def code_identity():
        return _source.current().code.code_identity()


code = _CodeIdentity()
from . import english_source_judge as judge  # noqa: E402
from . import mfa_backend  # noqa: E402
from . import sentence_interpretation as anchors  # noqa: E402
from . import budget  # noqa: E402


class _Jobs:
    """The host's durable job store, looked up at each call so the package imports without a host."""
    def __getattr__(self, name):
        return getattr(_source.current().core.jobs, name)


jobs = _Jobs()


def _safe_path(path):
    return _source.current().core.safe_path(path)


def work_lock(work):
    return _source.current().workspace.work_lock(work)

SCHEMA = 'sermon-unified-source-preparation-v1'
SCHEMA_V2 = 'sermon-unified-source-preparation-v2'
# v3 = v2 plus an explicit judge backend (2026-10-21 user decision): openai_api runs gpt-6.1-sol,
# claude_cli_opus runs claude-opus-5-5 through the subscription Claude CLI. v1/v2 stay OpenAI.
SCHEMA_V3 = 'sermon-unified-source-preparation-v3'
JUDGE_BACKEND_MODELS = {'openai_api': 'gpt-6.1-sol', 'claude_cli_opus': 'claude-opus-5-5'}
MAX_ASR_WORKERS = 16
# Budget authorization v1 bound the code identity: any commit, even one unrelated to the run,
# invalidated the authorization and a returned request's re-check aborted the judge mid-run
# (2026-10-21 E4b). v2 binds what the human approves, the run, its configuration digest, its budget
# root and bounds; the code identity at approval is kept as evidence, every attempt records the
# code it started with, and drift observed during a run is logged, not fatal. Artifacts keep their
# own code bindings (alignment identity, judge implementation hash, deterministic rebuild).
AUTHORIZATION_V1 = 'sermon-source-budget-authorization-v1'
AUTHORIZATION_V2 = 'sermon-source-budget-authorization-v2'
APPROVAL_V1 = 'sermon-source-budget-approval-v1'
APPROVAL_V2 = 'sermon-source-budget-approval-v2'
PCM_START_SHORTFALL_SAMPLES = 160  # 10 ms at 16 kHz
FIELDS = {'schemaVersion', 'productionRunId', 'sourceId', 'sourceUrlHash', 'serviceDate',
          'media', 'mediaSha256', 'sourceDurationSeconds', 'window', 'windowApproval', 'windowApprovalSha256',
          'timelineReport', 'timelineReportSha256', 'sourceDescriptor', 'sourceDescriptorSha256',
          'jobRoot', 'outputDirectory', 'budgetAuthorization', 'mfa', 'anchorPolicy', 'judge'}
LOCAL_MFA_FIELDS = {'mfa_executable', 'dictionary_path', 'acoustic_model', 'g2p_model', 'spoken_forms_path'}
SPARK_MFA_FIELDS = LOCAL_MFA_FIELDS | {'host', 'proxy_jump', 'relay_host', 'relay_host_key_alias', 'python', 'root'}
# Optional v2 field: the path of a source text review (`source/text_review.py`) applied to the
# ASR reference text before MFA. The review binds this run's own ASR and clip hashes, so it can only be
# written after ASR; its hash is therefore frozen in the run's provenance, not in the configuration.
TEXT_REVIEW_FIELDS = {'sourceTextReview'}
# Optional v2/v3 field: a directory, relative to the configuration, that holds the machine judge's
# content-addressed request cache. Every execute and rebuild of this source that names the same
# directory replays batches whose sentences, units, neighbors and policy are unchanged, so a
# boundary rebuild pays only for the batches it moved. Absent, each output keeps its own cache.
JUDGE_CACHE_FIELDS = {'judgeCacheRoot'}
# Optional v2/v3 field: the MacBook per-chunk MFA raw alignment cache (relative to the configuration).
# Spark keeps its own under its job root, so Spark runs reuse chunks without this field.
MFA_CHUNK_CACHE_FIELDS = {'mfaChunkCacheRoot'}
# Optional v2/v3 field: earlier budget roots of this source (relative to the configuration) whose
# returned ASR this configuration may replay at no cost. The ledger matches a chunk by its
# operation and audio identity, refuses a root whose same operation carries other audio, and
# records every replay as `reused` with its provenance (2026-10-21: three executes of one
# episode each paid the same 14 chunks again because the ledger is per jobRoot).
REUSE_FIELDS = {'reuseBudgetRoots'}
# Only transcription replays across roots; the machine judge always runs under this root's own
# cap, and a chunk no reuse root returned is paid here rather than failing the run.
REUSE_OPERATIONS = ('asr.',)
OPTIONAL_FIELDS = TEXT_REVIEW_FIELDS | JUDGE_CACHE_FIELDS | MFA_CHUNK_CACHE_FIELDS | REUSE_FIELDS


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


def _record_attempt(path, value):
    """Keep the latest observation at `path` and every earlier distinct one in a history file.

    A preflight is a runtime observation, not an input: fixing the Spark environment between
    attempts must not stop the next attempt (2026-10-18 broadcast E26 did, on a frozen
    mfa-preflight.json). The alignment receipt binds the runtime that actually aligned.
    """
    if path.exists():
        previous = _load(path)
        if previous == value:
            return
        with (path.with_name(path.stem + '-history.ndjson')).open('a', encoding='utf-8') as history:
            history.write(json.dumps(previous, ensure_ascii=False, sort_keys=True) + '\n')
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + '\n', encoding='utf-8')


def numeric_references(references, spoken_forms_path):
    """Tokens the frozen ASR text leaves without an exact spoken form, per reference chunk.

    MFA refuses them, so they are reported right after ASR, in the same stop as the text review,
    instead of one attempt later (2026-10-17 Resi v1, 2026-10-18 broadcast E26, 2026-10-21 podcast v1
    each lost an attempt this way).
    """
    import re as _re
    forms = mfa_backend.local._spoken_forms(spoken_forms_path)
    ambiguous = []
    for row in references:
        for token in _re.findall(r'\S+', ' '.join(str(row.get('text', '')).split())):
            if token in forms:
                continue
            if _re.search(r'\d[.,:/-]\d|\d(?:st|nd|rd|th)\b|[$€£%]', token, _re.I) \
                    or any(len(part) > 1 and part.startswith('0')
                           for part in mfa_backend.local.WORD_RE.findall(token) if part.isdecimal()):
                ambiguous.append({'referenceChunkId': row.get('id'), 'token': token})
    return ambiguous


def check_budget_authorization(auth_path, *, production_run_id, configuration_sha256, budget_root, code_identity):
    """Validate a budget authorization and its human approval; return (authority, approval_path, version)."""
    auth = _load(auth_path)
    version = auth.get('schemaVersion') if isinstance(auth, dict) else None
    fields = {'schemaVersion', 'binding', 'authority', 'approvalReceipt'} | ({'evidence'} if version == AUTHORIZATION_V2 else set())
    require(isinstance(auth, dict) and version in (AUTHORIZATION_V1, AUTHORIZATION_V2) and set(auth) == fields,
            'source_budget_authorization_required')
    expected = {'productionRunId': production_run_id, 'configurationSha256': configuration_sha256,
                'budgetRoot': str(budget_root)}
    if version == AUTHORIZATION_V1:
        expected['codeIdentitySha256'] = code_identity
    require(auth['binding'] == expected, 'source_budget_execution_binding_changed')
    if version == AUTHORIZATION_V2:
        evidence = auth['evidence']
        require(isinstance(evidence, dict) and set(evidence) == {'codeIdentitySha256AtApproval'}
                and isinstance(evidence['codeIdentitySha256AtApproval'], str)
                and english.SHA256.fullmatch(evidence['codeIdentitySha256AtApproval']),
                'source_budget_authorization_evidence_invalid')
    authority = auth['authority']
    approval_path = _safe_path(Path(auth_path).parent / auth['approvalReceipt'])
    approval = _load(approval_path)
    require(_sha(approval_path) == authority['approvalSha256']
            and approval.get('schemaVersion') == (APPROVAL_V1 if version == AUTHORIZATION_V1 else APPROVAL_V2)
            and approval.get('binding') == {**expected, 'globalBounds': authority['globalBounds'],
                                            'requestLimits': authority['requestLimits']}
            and approval.get('humanApproval') is True and approval.get('decision') == 'approved'
            and approval.get('operatorEvidence') and approval.get('reviewedBy') and approval.get('reviewedAt'),
            'source_budget_approval_not_bound')
    return authority, approval_path, version


def record_attempt(out, event, **fields):
    """Append one line to the output's attempts log: every start, and code drift seen during a run."""
    import datetime
    out.mkdir(parents=True, exist_ok=True)
    row = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'event': event, **fields}
    with (out / 'source-run-attempts.ndjson').open('a', encoding='utf-8') as log:
        log.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    return row


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def ordered_bounded_map(items, worker, workers):
    """Bound dispatch and preserve input order; a failure stops new admission.

    Already running leaves finish their immutable receipts before returning the
    exception. No automatic retries or loss of successful sibling work.
    """
    require(type(workers) is int and 1 <= workers <= MAX_ASR_WORKERS, 'invalid_source_concurrency')
    items = list(items)
    if workers == 1:
        return [worker(item) for item in items]
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        source = iter(enumerate(items))
        pending = {}
        for _ in range(min(workers, len(items))):
            index, item = next(source)
            pending[pool.submit(copy_context().run, worker, item)] = index
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            count = len(done)
            for future in sorted(done, key=lambda f: pending[f]):
                index = pending.pop(future)
                try:
                    results[index] = future.result()
                except BaseException:
                    for remaining in pending:
                        remaining.cancel()
                    raise
            for _ in range(count):
                item = next(source, None)
                if item is not None:
                    index, value = item
                    pending[pool.submit(copy_context().run, worker, value)] = index
    return [results[index] for index in range(len(items))]


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
    authorization_version: str = AUTHORIZATION_V1


def _validate_judge_backend(value):
    """A v3 judge names its backend, and the backend fixes the model; earlier versions stay OpenAI."""
    if value['schemaVersion'] == SCHEMA_V3:
        require(isinstance(value['judge'], dict) and value['judge'].get('backend') in JUDGE_BACKEND_MODELS,
                'invalid_source_judge_backend')


def judge_backend(value):
    return value['judge'].get('backend', 'openai_api') if value['schemaVersion'] == SCHEMA_V3 else 'openai_api'


def claude_judge_transport(value, receipts_dir, request_limits):
    """The subscription Claude CLI judge transport for a claude_cli_opus configuration, else None."""
    if judge_backend(value) != 'claude_cli_opus':
        return None
    from ..compute.transports.claude_source_judge import ClaudeSourceJudgeTransport
    # The CLI call gets the same per-request wall-time bound the budget reserves.
    return ClaudeSourceJudgeTransport(model=value['judge']['model'], effort=value['judge']['reasoningEffort'],
                                      receipts_dir=receipts_dir,
                                      timeout_seconds=request_limits['wallTimeMs'] / 1000)


def load_configuration(path):
    path = _safe_path(Path(path).absolute())
    value = _load(path)
    require(isinstance(value, dict) and value.get('schemaVersion') in (SCHEMA, SCHEMA_V2, SCHEMA_V3)
            and (set(value) == FIELDS if value['schemaVersion'] == SCHEMA else
                 FIELDS | {'asrWorkers'} <= set(value) <= FIELDS | {'asrWorkers'} | OPTIONAL_FIELDS),
            'invalid_source_preparation_configuration')
    if value['schemaVersion'] in (SCHEMA_V2, SCHEMA_V3):
        # One worker per 180 s chunk lets a 40-minute source transcribe in one round
        # (2026-10-21: 14 chunks at 4 workers took 32 s; the provider has no stated
        # concurrency limit this low, and each request is still ledgered before dispatch).
        require(type(value['asrWorkers']) is int and 1 <= value['asrWorkers'] <= MAX_ASR_WORKERS,
                'invalid_source_asr_concurrency')
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
    if 'sourceTextReview' in value:
        resolve('sourceTextReview')
    if 'judgeCacheRoot' in value:
        resolve('judgeCacheRoot')
    if 'mfaChunkCacheRoot' in value:
        resolve('mfaChunkCacheRoot')
    reuse_roots = reuse_budget_roots(value, path)
    require(media.is_file() and _sha(media) == value['mediaSha256'], 'source_media_identity_changed')
    require(not any(output == p or output in p.parents for p in (media, path, receipt_path, job_root))
            and not (job_root == output or job_root in output.parents), 'source_paths_overlap')
    validate_window = _source.current().review.validate_window
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
    _validate_judge_backend(value)
    judge_fields = {'model', 'reasoningEffort', 'batchSize', 'workers'} | (
        {'backend'} if value['schemaVersion'] == SCHEMA_V3 else set())
    require(isinstance(value['judge'], dict) and set(value['judge']) == judge_fields
            and value['judge']['model'] in (('gpt-6-astra', 'gpt-6.1-sol') if value['schemaVersion'] != SCHEMA_V3
                                            else (JUDGE_BACKEND_MODELS[value['judge']['backend']],))
            and value['judge']['reasoningEffort'] in budget.text_limits.SUPPORTED_REASONING_EFFORTS
            and type(value['judge']['batchSize']) is int and 1 <= value['judge']['batchSize'] <= 15
            and type(value['judge']['workers']) is int
            and 1 <= value['judge']['workers'] <= (1 if value['schemaVersion'] == SCHEMA else 8),
            'invalid_source_judge_configuration')
    identity = jobs._digest({k: v for k, v in value.items() if k != 'budgetAuthorization'})
    code_identity = code.code_identity()
    auth_path = resolve('budgetAuthorization')
    budget_root = job_root.parent / f'.{job_root.name}.source-budget'
    require(budget_root.resolve() not in {root.resolve() for root in reuse_roots}, 'invalid_source_reuse_roots')
    authority, approval_path, version = check_budget_authorization(
        auth_path, production_run_id=value['productionRunId'], configuration_sha256=identity,
        budget_root=budget_root, code_identity=code_identity)
    budget.SourceBudget(budget_root, authority, verify=lambda: None, reuse_roots=reuse_roots,
        reuse_operations=REUSE_OPERATIONS, reuse_miss_pays=True,
        max_concurrent=max(value.get('asrWorkers', 1), value['judge']['workers']))
    return Configuration(path, value, media, output, job_root, receipt_path, identity,
                         code_identity, authority, budget_root, _sha(approval_path), _sha(auth_path), version)


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
            'authorizationVersion': config.authorization_version,
            'reuseBudgetRoots': [str(root) for root in reuse_budget_roots(config.value, config.path)],
            'globalBounds': config.authority['globalBounds'], 'chunkCount': count, 'chunkMaxSeconds': 180,
            'mfaBackend': config.value['mfa']['backend'], 'mfaRuntimeVerified': False,
            'humanSourceReview': 'pending', 'productionTranslationEligible': False}


def reuse_budget_roots(value, config_path):
    """Resolved earlier budget roots this configuration may replay returned ASR from."""
    roots = value.get('reuseBudgetRoots', [])
    require(isinstance(roots, list) and all(isinstance(root, str) and root.strip() for root in roots)
            and len(set(roots)) == len(roots), 'invalid_source_reuse_roots')
    resolved = [_safe_path(Path(config_path).parent / root) for root in roots]
    require(all((root / 'source-budget.json').is_file() for root in resolved), 'source_reuse_root_missing')
    return resolved


def judge_cache_root(value, config_path, out):
    """The shared content-addressed judge cache a configuration names, else this output's own."""
    if 'judgeCacheRoot' in value:
        return _safe_path(Path(config_path).parent / value['judgeCacheRoot'])
    return out / 'judge-requests'


def _mfa_options(config, *, alignment=False):
    value = config.value['mfa']
    options = {'backend': value['backend'], 'allow_spark_fallback': value['allowSparkFallback'],
               'local_options': value['localOptions'], 'spark_options': value['sparkOptions']}
    if alignment and 'mfaChunkCacheRoot' in config.value:
        options['chunk_cache_dir'] = _safe_path(config.path.parent / config.value['mfaChunkCacheRoot'])
    return options


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
        # A stream whose first packet starts a few milliseconds after 0 decodes that many samples
        # short of the window (2026-10-18 broadcast: 64 samples at start 0); that is not truncation.
        # Any overrun, or more than 10 ms missing, still is.
        require(-PCM_START_SHORTFALL_SAMPLES <= frames - expected_samples <= 1,
                'source_extracted_audio_duration_changed')
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


def execute(config_path, *, api_key=None, transport=None, aligner=None, mfa_preflight=None, claude_transport=None):
    """Execute a fixed candidate recipe. Injection seams are offline tests only."""
    config = load_configuration(config_path)
    drift = []
    def fresh():
        current = load_configuration(config.path)
        require((current.identity, current.approval_hash, current.authorization_hash) ==
                (config.identity, config.approval_hash, config.authorization_hash),
                'source_execution_binding_changed')
        if config.authorization_version == AUTHORIZATION_V1:
            require(current.code_identity == config.code_identity, 'source_execution_binding_changed')
        elif current.code_identity != config.code_identity and current.code_identity not in drift:
            # The process keeps running the code it loaded; the files on disk changed underneath it.
            drift.append(current.code_identity)
            record_attempt(config.output, 'code_identity_drift_observed', startedWith=config.code_identity,
                           onDisk=current.code_identity)
    with work_lock(config.output):
        config.output.mkdir(parents=True, exist_ok=True)
        with _source.current().accounting.session(config.output / 'accounting', 'unified_source_preparation',
                {'productionRunId': config.value['productionRunId']}, evidence_directory=config.output):
            return _execute(config, fresh, api_key=api_key, transport=transport, claude_transport=claude_transport,
                            aligner=aligner or mfa_backend.align_reference_chunks,
                            mfa_preflight=mfa_preflight or mfa_backend.preflight)


def _execute(config, fresh, *, api_key, transport, aligner, mfa_preflight, claude_transport=None):
    out, value = config.output, config.value
    run_record = out / 'source-run.json'
    if run_record.exists():
        require(_load(run_record).get('configurationSha256') == config.identity, 'source_run_configuration_changed')
    else:
        _freeze(run_record, {'configurationSha256': config.identity, 'codeIdentitySha256': config.code_identity,
                             'authorizationSha256': config.authorization_hash,
                             'authorizationVersion': config.authorization_version})
    record_attempt(out, 'attempt_started', configurationSha256=config.identity,
                   codeIdentitySha256=config.code_identity, authorizationSha256=config.authorization_hash,
                   authorizationVersion=config.authorization_version)
    total_duration = _probe(config.media)
    window = value['window']
    require(abs(total_duration - value['sourceDurationSeconds']) <= .002, 'source_duration_identity_changed')
    require(window['endSeconds'] <= total_duration + .002, 'source_window_exceeds_media')
    duration = window['endSeconds'] - window['startSeconds']
    aligned_path, manifest_path = out / 'aligned-segments.json', out / 'anchor-manifest.json'
    if not aligned_path.exists():
        require(not (out / 'mfa-started.json').exists(), 'source_mfa_outcome_unknown_reconciliation_required')
        runtime = mfa_preflight(**_mfa_options(config))
        _record_attempt(out / 'mfa-preflight.json', runtime)
    clip = _audio(config, out / 'source-clip.wav', window['startSeconds'], duration)
    if claude_transport is None:
        claude_transport = claude_judge_transport(value, out / 'judge-requests' / 'claude-cli-calls',
                                                  config.authority['requestLimits'])
    caller = budget.SourceBudget(config.budget_root, config.authority, verify=fresh, transport=transport,
        max_concurrent=max(value.get('asrWorkers', 1), value['judge']['workers']), claude_transport=claude_transport,
        reuse_roots=reuse_budget_roots(value, config.path), reuse_operations=REUSE_OPERATIONS, reuse_miss_pays=True)
    if api_key is None:
        api_key = os.environ.get('OPENAI_API_KEY', '')
    def transcribe_chunk(index):
        start, end = index * 180, min((index + 1) * 180, duration)
        audio = _audio(config, out / 'chunks' / f'{index:04d}.wav', window['startSeconds'] + start, end - start)
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
        return final, _reference_rows(response, index, start, end)
    chunks = ordered_bounded_map(range(math.ceil(duration / 180)), transcribe_chunk, value.get('asrWorkers', 1))
    finals = [final for final, _ in chunks]
    references = [reference for _, rows in chunks for reference in rows]
    _freeze(out / 'asr_reference_chunks.json', references)
    _freeze(out / 'asr_reference.json', {'text': '\n'.join(row['response']['text'] for row in finals),
                                         'chunksSha256': jobs._digest(finals), 'immutableAsrFinal': True})
    _freeze(out / 'speaker-turns.json', {'schemaVersion': 'sermon-source-anonymous-turns-v1',
        'identityMapping': 'not_performed', 'crossChunkIdentity': 'unknown',
        'turns': [{k: row[k] for k in ('id', 'start', 'end', 'speakerId', 'speakerIdentityStatus')} for row in references]})
    # Everything the operator must supply before MFA is reported in this one stop: spoken forms
    # for ambiguous numerals and, when configured, the text review of this run's ASR.
    spoken_forms_path = (value['mfa']['localOptions'].get('spoken_forms_path')
                         or value['mfa']['sparkOptions'].get('spoken_forms_path'))
    ambiguous = numeric_references(references, spoken_forms_path)
    _record_attempt(out / 'numeric-references.json', {
        'schemaVersion': 'sermon-source-numeric-references-v1', 'spokenFormsPath': spoken_forms_path,
        'spokenFormsSha256': _sha(spoken_forms_path) if spoken_forms_path else None,
        'ambiguousTokens': ambiguous, 'status': 'ambiguous_tokens_need_spoken_forms' if ambiguous else 'clear'})
    if 'sourceTextReview' in value:
        # Apply the bound review to the reference text only; asr_reference*.json keep the raw ASR.
        from .text_review import apply_review
        review_path = _safe_path(config.path.parent / value['sourceTextReview'])
        # Stop before MFA until the operator's review of this run's ASR exists; ASR replays on resume.
        require(review_path.is_file(), 'source_text_review_required')
        segments = [{'id': index, 'text': row['text']} for index, row in enumerate(references)]
        reviewed, provenance = apply_review(segments, review_path, clip, out / 'asr_reference.json')
        provenance = {k: v for k, v in provenance.items() if k != 'reviewPath'}
        _freeze(out / 'source-text-review-provenance.json', provenance)
        references = [{**row, 'text': segment['text']} for row, segment in zip(references, reviewed)]
    # The review may have rewritten a numeral; check the text MFA will actually see.
    require(not numeric_references(references, spoken_forms_path),
            'source_ambiguous_numeric_reference_configure_spoken_forms')
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
        aligned = aligner(references, clip, out / 'mfa', **_mfa_options(config, alignment=True))
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
        unit_policy=anchors.UNIT_POLICY_V3, max_unit_seconds=value['anchorPolicy']['maxUnitSeconds'],
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
        'sourceChunkEvidence': english.artifact(out / 'asr_reference_chunks.json',
                                                value=json.loads((out / 'asr_reference_chunks.json').read_text())),
        'speakerTurnEvidence': english.artifact(out / 'speaker-turns.json', value=_load(out / 'speaker-turns.json')),
        'speakerIdentityMapping': 'not_performed',
        'pipelineInputIdentity': {'sourceAudio': {'sha256': value['mediaSha256'], 'sizeBytes': config.media.stat().st_size},
                                 'readingAligner': 'mfa'}, 'segmentCount': len(aligned)}
    _freeze(out / 'summary.json', summary)
    with budget.judge_limits(config.authority['requestLimits']):
        judged = judge.run(aligned_path=aligned_path, manifest_path=manifest_path, out=out / 'machine-judge.json',
            api_key=api_key or '', caller=caller.judge, cache_root=judge_cache_root(value, config.path, out),
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


REBUILD_OVERRIDES_SCHEMA = 'sermon-anchor-boundary-overrides-v3'


def rebuild(config_path, base_output, out_dir, overrides_path, authorization_path, *, api_key=None, transport=None,
            operator_acceptance=None, claude_transport=None):
    """Rebuild anchors, judge and candidate from a run's frozen alignment; no ASR or MFA.

    The base run's aligned segments, summary and window approval are reused by hash. Boundary
    overrides (sentence ID -> ordered word IDs to split after) must name the same aligned
    segments. The judge spends only under its own authorization and budget root.
    """
    config_path = _safe_path(Path(config_path).absolute())
    value = _load(config_path)
    require(value.get('schemaVersion') in (SCHEMA, SCHEMA_V2, SCHEMA_V3), 'invalid_source_preparation_configuration')
    _validate_judge_backend(value)
    base_identity = jobs._digest({k: v for k, v in value.items() if k != 'budgetAuthorization'})
    base, out = _safe_path(Path(base_output).absolute()), _safe_path(Path(out_dir).absolute())
    aligned_path = base / 'aligned-segments.json'
    receipt = _load(base / 'alignment-receipt.json')
    require(receipt['alignedSha256'] == _sha(aligned_path), 'source_alignment_cache_changed')
    aligned = _load(aligned_path)
    overrides = _load(_safe_path(Path(overrides_path).absolute()))
    require(set(overrides) == {'schemaVersion', 'alignedSegmentsSha256', 'overrides'}
            and overrides['schemaVersion'] == REBUILD_OVERRIDES_SCHEMA
            and overrides['alignedSegmentsSha256'] == receipt['alignedSha256']
            and isinstance(overrides['overrides'], dict), 'invalid_boundary_overrides')
    acceptance_path = _safe_path(Path(operator_acceptance).absolute()) if operator_acceptance else None
    identity = jobs._digest({'baseConfiguration': base_identity, 'alignedSha256': receipt['alignedSha256'],
                             'boundaryOverrides': overrides, 'judge': value['judge'],
                             'maxUnitSeconds': value['anchorPolicy']['maxUnitSeconds'],
                             **({'operatorAcceptanceSha256': _sha(acceptance_path)} if acceptance_path else {})})
    authorization_path = _safe_path(Path(authorization_path).absolute())
    budget_root = out.parent / f'.{out.name}.judge-budget'
    code_identity = code.code_identity()
    authority, approval_path, version = check_budget_authorization(
        authorization_path, production_run_id=value['productionRunId'], configuration_sha256=identity,
        budget_root=budget_root, code_identity=code_identity)
    out.mkdir(parents=True, exist_ok=True)
    record_attempt(out, 'attempt_started', rebuildIdentity=identity, codeIdentitySha256=code_identity,
                   authorizationSha256=_sha(authorization_path), authorizationVersion=version)
    manifest = anchors.build_anchor_manifest(aligned, source_path=aligned_path,
        unit_policy=anchors.UNIT_POLICY_V3, max_unit_seconds=value['anchorPolicy']['maxUnitSeconds'],
        boundary_overrides=overrides['overrides'])
    manifest_path = out / 'anchor-manifest.json'
    _freeze(manifest_path, manifest)
    _freeze(out / 'summary.json', _load(base / 'summary.json'))
    if claude_transport is None:
        claude_transport = claude_judge_transport(value, out / 'judge-requests' / 'claude-cli-calls',
                                                  authority['requestLimits'])
    caller = budget.SourceBudget(budget_root, authority, verify=lambda: None, transport=transport,
                                 max_concurrent=value['judge']['workers'], claude_transport=claude_transport)
    with budget.judge_limits(authority['requestLimits']):
        judged = judge.run(aligned_path=aligned_path, manifest_path=manifest_path, out=out / 'machine-judge.json',
            api_key=api_key if api_key is not None else os.environ.get('OPENAI_API_KEY', ''),
            caller=caller.judge, cache_root=judge_cache_root(value, config_path, out),
            model=value['judge']['model'], effort=value['judge']['reasoningEffort'],
            batch_size=value['judge']['batchSize'], workers=value['judge']['workers'],
            operator_acceptance=acceptance_path)
    window_receipt = _safe_path(config_path.parent / value['windowApproval'])
    package = english.build_package(aligned_path, manifest_path, summary_path=out / 'summary.json',
        approval_evidence_path=window_receipt, machine_judge_path=out / 'machine-judge.json',
        source_id=value['sourceId'], source_url_hash=value['sourceUrlHash'], service_date=value['serviceDate'])
    require(package['translationEligible'] is False, 'source_preparation_cannot_grant_human_review')
    _freeze(out / 'english-source-candidate.json', package)
    _freeze(out / 'rebuild-receipt.json', {'schemaVersion': 'sermon-source-anchor-rebuild-v1',
        'baseOutput': str(base), 'baseConfigurationSha256': base_identity, 'rebuildIdentity': identity,
        'alignedSha256': receipt['alignedSha256'], 'boundaryOverridesSha256': _sha(_safe_path(Path(overrides_path).absolute())),
        'budgetAuthorizationSha256': _sha(authorization_path), 'asrOrMfaRerun': False,
        'operatorAcceptanceSha256': _sha(acceptance_path) if acceptance_path else None})
    return {'status': 'succeeded' if judged['layer2DevelopmentEligible'] else 'blocked',
            'kind': 'english_source_candidate',
            'reason': 'human_source_review_required' if judged['layer2DevelopmentEligible'] else 'source_machine_judge_rejected',
            'review': 'human_pending', 'productionEligible': False, 'humanApprovalCreated': False,
            'candidatePath': str(out / 'english-source-candidate.json'), 'candidateSha256': jobs._digest(package),
            'machineJudgeStatus': judged['status']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'execute', 'rebuild'))
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--base-output', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--boundary-overrides', type=Path)
    parser.add_argument('--budget-authorization', type=Path)
    parser.add_argument('--operator-acceptance', type=Path)
    args = parser.parse_args()
    if args.command == 'rebuild':
        result = rebuild(args.config, args.base_output, args.out, args.boundary_overrides, args.budget_authorization,
                         operator_acceptance=args.operator_acceptance)
    else:
        result = inspect(args.config) if args.command == 'inspect' else execute(args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in {'ready', 'succeeded'} else 2


if __name__ == '__main__':
    raise SystemExit(main())

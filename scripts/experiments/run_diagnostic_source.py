#!/usr/bin/env python3
"""Explicit source ASR4 -> MFA -> anchors -> CLI judge8 diagnostic producer.

No human approval is minted or inherited. API ASR reservations are enforceable
request/time/cost bounds; CLI token/cost figures are planning estimates only.
The strict formal source producer keeps rejecting unsupported CLI output caps.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import sermon_unified_source as source
from scripts import sermon_source_budget as budget
from scripts import sermon_workflow_jobs as jobs
from scripts import build_english_source_package as english
from scripts import sermon_sentence_interpretation as anchors
from scripts import judge_english_source_for_translation as judge
from scripts import sermon_codex_transport as codex
from scripts import sermon_model_call_observation as observation
from scripts import codex_layer2_resources as cli_resources
from scripts import english_source_judge_cache as judge_cache
from scripts import production_concurrency_profile as profile_tools
from scripts import sermon_accounting as accounting
from scripts import mfa_backend
from scripts.production_concurrency_profile import validate_profile, load_profile
from scripts.sermon_unified import resources
from scripts.sermon_execution_harness import work_lock

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'diagnostic-source-execution-v1'


def _implementations():
    modules = (source, budget, english, anchors, judge, codex, cli_resources, judge_cache, profile_tools)
    return {Path(module.__file__).name: source._sha(Path(module.__file__)) for module in modules} | {
        Path(__file__).name: source._sha(Path(__file__))}


def _cli_identity(path):
    path = Path(path).absolute().resolve()
    binary = path.parent.parent / 'CodexCLI.app/Contents/MacOS/codex'
    return {'cliPath': str(path), 'cliSha256': source._sha(path),
            'binarySha256': source._sha(binary if binary.is_file() else path)}


def prepare(*, provenance_path, out_dir, profile, resource_policy, mfa, cli_path=None, frozen_sample_dir=None):
    """Read source identity, freeze a diagnostic plan; zero model/runtime calls."""
    provenance_path, out = Path(provenance_path).resolve(), Path(out_dir).resolve()
    source.require(out.is_relative_to(ROOT / 'artifacts') and out != ROOT / 'artifacts',
                   'diagnostic_source_requires_ignored_output')
    provenance = source._load(provenance_path)
    source.require(provenance.get('diagnosticOnly') is True and provenance.get('productionEligible') is False
        and provenance.get('humanApprovalCreated') is False, 'diagnostic_source_provenance_required')
    profile = validate_profile(profile)
    resource_policy = resources.validate_policy(resource_policy)
    source.require(resource_policy['capacities']['online_api'] == profile['sourceASRWorkers']
        and resource_policy['capacities']['codex_cli'] == profile['totalCodexSlots'], 'source_shared_resource_capacity_mismatch')
    media = Path(provenance['parentMedia']['path']).resolve()
    source.require(source._sha(media) == provenance['parentMedia']['sha256'], 'source_media_identity_changed')
    window = provenance['actualCompleteSentenceWindow']
    source.require(all(type(window[k]) in (int, float) and math.isfinite(window[k]) for k in ('startSeconds', 'endSeconds'))
        and 0 <= window['startSeconds'] < window['endSeconds'] <= provenance['parentMedia']['durationSeconds'],
        'diagnostic_source_window_invalid')
    source.require(isinstance(mfa, dict) and set(mfa) == {'backend', 'allowSparkFallback', 'localOptions', 'sparkOptions'}
        and mfa['backend'] in ('spark', 'macbook', 'auto') and type(mfa['allowSparkFallback']) is bool
        and isinstance(mfa['localOptions'], dict) and set(mfa['localOptions']) == source.LOCAL_MFA_FIELDS
        and isinstance(mfa['sparkOptions'], dict) and set(mfa['sparkOptions']) == source.SPARK_MFA_FIELDS,
        'invalid_source_mfa_configuration')
    duration = window['endSeconds'] - window['startSeconds']
    chunks = math.ceil(duration / 180)
    # Fixed provider implementation defines the audio worst-case charge. These
    # are reservations, not invoice values, and audio token counts stay unknown.
    authority = {'approvalSha256': jobs._digest({'diagnosticOnly': True, 'provenance': provenance}),
        'globalBounds': {'requests': chunks, 'wallTimeMs': chunks * budget.transcription.WALL_TIME_MS,
            'costMicrousd': sum(math.ceil(min(180, duration - i * 180) / 60) * budget.transcription.MICROUSD_PER_MINUTE
                                 for i in range(chunks))},
        'requestLimits': dict(budget.text_limits.DEFAULT_REQUEST_LIMITS)}
    value = {'schemaVersion': SCHEMA, 'simulationOnly': True, 'diagnosticOnly': True,
        'productionEligible': False, 'humanApproval': False, 'windowApproval': 'pending',
        'provenancePath': str(provenance_path), 'provenanceSha256': source._sha(provenance_path),
        'media': str(media), 'mediaSha256': provenance['parentMedia']['sha256'],
        'sourceDurationSeconds': provenance['parentMedia']['durationSeconds'],
        'window': {key: window[key] for key in ('startSeconds', 'endSeconds')},
        'outDir': str(out), 'profile': profile, 'resourcePolicy': resource_policy, 'mfa': mfa,
        'judge': {'model': 'gpt-6.1-sol', 'reasoningEffort': 'high', 'serviceTier': 'fast', 'batchSize': 15},
        'baselineSampleCounts': {'sourceUnits': provenance['sourceUnitCount'], 'sourceSentences': provenance['sourceSentenceCount']},
        'apiAuthority': authority, 'apiAuthorityKind': 'diagnostic_planning_reservation_not_human_receipt',
        'cliBudgetScope': {'outputTokenCapEnforced': False, 'invoiceCostCapEnforced': False,
            'planningOutputTokensPerRequest': 4096, 'automaticRetry': False, 'unknownOutcomeRetainsSlot': True},
        'cliIdentity': _cli_identity(cli_path or Path.home() / '.local/bin/codex'), 'implementations': _implementations()}
    value['mode'] = 'fresh_source_asr4_mfa_judge8'
    if frozen_sample_dir is not None:
        frozen = Path(frozen_sample_dir).resolve()
        inputs = {name: {'path': str(frozen / filename), 'sha256': source._sha(frozen / filename)}
            for name, filename in (('aligned', 'aligned-segments.json'), ('anchor', 'anchor.json'),
                ('source', 'source.json'), ('summary', 'summary.json'))}
        original = source._load(inputs['source']['path'])
        original_anchor = source._load(inputs['anchor']['path'])
        source.require(original.get('translationEligible') is False and original['review']['humanApproval'] is False
            and original['source']['media']['sha256'] == value['mediaSha256']
            and {key: original['source']['approvedWindow'][key] for key in ('startSeconds', 'endSeconds')} == value['window']
            and original['source']['approvedWindow']['humanApproval'] is False
            and original['anchors']['artifact']['sha256'] == inputs['anchor']['sha256']
            and original['transcript']['artifact']['sha256'] == inputs['aligned']['sha256']
            and original_anchor['input']['mfaSegmentsSha256'] == inputs['aligned']['sha256']
            and len(original_anchor['sourceUnits']) == provenance['sourceUnitCount']
            and len(judge._sentence_inputs(original_anchor)) == provenance['sourceSentenceCount'],
            'diagnostic_frozen_source_binding_changed')
        value.update(mode='frozen_source_judge8', frozenInputs=inputs)
    path = out / 'diagnostic-source-config.json'
    source._freeze(path, value)
    return {'status': 'prepared_diagnostic', 'configPath': str(path), 'sourceASRWorkers': profile['sourceASRWorkers'],
        'sourceJudgeWorkers': profile['sourceJudgeWorkers'], 'sourceChunkCount': chunks, 'modelCalls': 0,
        'productionEligible': False, 'humanApproval': False, 'requiresHumanSourceReview': True,
        'strictFormalSourceBudgetCompatible': False, 'mode': value['mode'],
        'sourceASRCallsPlanned': chunks if frozen_sample_dir is None else 0,
        'criticalFixtureIdentity': {'configurationSha256': jobs._digest(value), 'mediaSha256': value['mediaSha256'],
            'window': value['window'], 'provenanceSha256': value['provenanceSha256'],
            'implementations': value['implementations'], 'frozenInputs': value.get('frozenInputs')}}


def _configuration(path):
    value = source._load(path)
    source.require(value.get('schemaVersion') == SCHEMA and value.get('simulationOnly') is True
        and value.get('productionEligible') is False and value.get('humanApproval') is False, 'diagnostic_source_configuration_required')
    validate_profile(value['profile'])
    resources.validate_policy(value['resourcePolicy'])
    source.require(value['implementations'] == _implementations(), 'diagnostic_source_implementation_changed')
    source.require(source._sha(value['provenancePath']) == value['provenanceSha256']
        and source._sha(value['media']) == value['mediaSha256']
        and _cli_identity(value['cliIdentity']['cliPath']) == value['cliIdentity'], 'diagnostic_source_identity_changed')
    if value.get('frozenInputs') is not None:
        source.require(all(source._sha(row['path']) == row['sha256'] for row in value['frozenInputs'].values()),
                       'diagnostic_frozen_source_binding_changed')
    return value


def _execute_frozen(value, fresh, cli_call):
    """Judge the exact existing anchors; explicitly zero fresh source ASR/MFA."""
    out = Path(value['outDir'])
    aligned_path, anchor_path = out / 'aligned-segments.json', out / 'anchor.json'
    for name, path in (('aligned', aligned_path), ('anchor', anchor_path), ('summary', out / 'summary.json')):
        frozen = value['frozenInputs'][name]
        # Preserve exact bytes: anchors bind the aligned file's byte hash, so
        # loading/dumping an equivalent JSON object would invalidate the input.
        if path.exists():
            source.require(source._sha(path) == frozen['sha256'], 'diagnostic_frozen_input_changed')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = Path(frozen['path']).read_bytes()
            source.require(hashlib.sha256(raw).hexdigest() == frozen['sha256'], 'diagnostic_frozen_input_changed')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            jobs._sync_directory(path.parent)
    judged = judge.run(aligned_path=aligned_path, manifest_path=anchor_path, out=out / 'machine-judge.json',
        api_key='', caller=DiagnosticJudgeCaller(value, cli_call=cli_call), cache_root=out / 'judge-requests',
        model='gpt-6.1-sol', effort='high', batch_size=15, workers=value['profile']['sourceJudgeWorkers'])
    old = source._load(value['frozenInputs']['source']['path'])
    package = english.build_package(aligned_path, anchor_path, summary_path=out / 'summary.json',
        machine_judge_path=out / 'machine-judge.json', source_id=old['source']['sourceId'],
        source_url_hash=old['source']['sourceUrlHash'], service_date=old['source']['serviceDate'])
    source.require(package['translationEligible'] is False and package['review']['humanApproval'] is False,
                   'diagnostic_source_cannot_approve_content')
    source._freeze(out / 'source.json', package)
    result = {'schemaVersion': 'diagnostic-source-result-v1', 'status': 'diagnostic_frozen_source_judged',
        'mode': value['mode'], 'simulationOnly': True, 'productionEligible': False, 'humanApproval': False,
        'requiresHumanSourceReview': True, 'sourcePath': str(out / 'source.json'), 'anchorPath': str(anchor_path),
        'sourceSha256': source._sha(out / 'source.json'), 'anchorSha256': source._sha(anchor_path),
        'sourceASRWorkers': value['profile']['sourceASRWorkers'], 'sourceJudgeWorkers': value['profile']['sourceJudgeWorkers'],
        'sourceASRCalls': 0, 'sourceASR': 'reused_frozen_source', 'mfaCalls': 0, 'alignment': 'reused_frozen_source',
        'baselineSampleCounts': value['baselineSampleCounts'],
        'actualAnchorCounts': {'sourceUnits': judged['counts']['sourceUnits'], 'sourceSentences': judged['counts']['sourceSentences']},
        'machineJudgeStatus': judged['status'], 'cliBudgetScope': value['cliBudgetScope']}
    fresh()
    source._freeze(out / 'result.json', result)
    return result


class DiagnosticJudgeCaller:
    """Known terminal CLI results release business slots; unknowns keep them."""
    def __init__(self, value, *, cli_call=None):
        self.value = value
        self.cli_call = cli_call or codex._call
        self.local = threading.local()

    def admit_resource(self, payload):
        key = jobs._digest(payload)
        if not hasattr(self.local, 'permits'):
            self.local.permits = {}
        previous = self.local.permits.get(key)
        if previous is not None and not previous.consumed:
            return previous
        folder = Path(self.value['outDir']) / 'judge-cli' / key
        # A returned raw response can repair the outer judge cache without a new
        # CLI permit. Exact binding is checked again by __call__ before use.
        if (folder / 'diagnostic-response.json').exists():
            return None
        identity = {'payloadSha256': key, 'configurationSha256': jobs._digest(self.value)}
        admission = cli_resources.Admission(self.value['resourcePolicy'], call_id=jobs._digest(identity),
            identity=identity, receipt_directory=folder, concurrency_profile=self.value['profile'])
        admission.reserve()
        self.local.permits[key] = admission
        return admission

    def __call__(self, api_key, payload):
        source.require(payload['model'] == 'gpt-6.1-sol' and payload['reasoning_effort'] == 'high'
            and 'max_completion_tokens' not in payload, 'diagnostic_judge_configuration_changed')
        identity = {'payloadSha256': jobs._digest(payload), 'configurationSha256': jobs._digest(self.value)}
        folder = Path(self.value['outDir']) / 'judge-cli' / jobs._digest(payload)
        response_path = folder / 'diagnostic-response.json'
        if response_path.exists():
            saved = source._load(response_path)
            source.require(saved.get('identity') == identity and saved.get('responseSha256') == jobs._digest(saved.get('response')),
                'diagnostic_judge_response_changed')
            return saved['response']
        admission = self.admit_resource(payload)
        prompt = '\n\n'.join(message['role'].upper() + ':\n' + message['content'] for message in payload['messages'])
        with admission.dispatch():
            result = self.cli_call(prompt + '\nReturn only valid JSON.', model='gpt-6.1-sol', reasoning='high',
                service_tier='fast', output_schema=judge._response_schema(), output_dir=folder / 'cli',
                timeout_seconds=180, cli_path=self.value['cliIdentity']['cliPath'])
            source.require(result.get('completed') is True and result.get('requestedModel') == 'gpt-6.1-sol'
                and result.get('requestedReasoningEffort') == 'high' and result.get('requestedServiceTier') == 'fast'
                and result.get('toolCalls') == 0, 'diagnostic_judge_terminal_response_invalid')
            usage = observation.normalize_usage(result.get('usage'))
            response = {'id': result['id'], 'model': result['requestedModel'], 'serverModel': None,
                'modelIdentityKind': 'requested', 'codexReceipt': result,
                'choices': [{'finish_reason': 'stop', 'message': {'content': result['content']}}],
                'usage': {'prompt_tokens': usage['inputTokens'], 'completion_tokens': usage['outputTokens'],
                    'total_tokens': usage['totalTokens'], 'prompt_tokens_details': {'cached_tokens': usage['cachedInputTokens']},
                    'completion_tokens_details': {'reasoning_tokens': usage['reasoningTokens']}}}
            source._freeze(response_path, {'identity': identity, 'response': response, 'responseSha256': jobs._digest(response)})
            admission.response_sha256 = jobs._digest(response)
            admission.mark_terminal()
            return response


def execute(config_path, *, api_key=None, api_transport=None, aligner=None, mfa_preflight=None, cli_call=None):
    config_path = Path(config_path).resolve()
    value = _configuration(config_path)
    out, window = Path(value['outDir']), value['window']
    def fresh():
        source.require(_configuration(config_path) == value, 'diagnostic_source_configuration_changed')
    config = SimpleNamespace(media=Path(value['media']), value=value)
    aligner = aligner or mfa_backend.align_reference_chunks
    mfa_preflight = mfa_preflight or mfa_backend.preflight
    with work_lock(out):
        with accounting.accounting_session(out / 'accounting', 'diagnostic_source_asr4_judge8',
                {'simulationOnly': True, 'productionEligible': False}, evidence_directory=out):
            if value.get('mode') == 'frozen_source_judge8':
                return _execute_frozen(value, fresh, cli_call)
            duration = window['endSeconds'] - window['startSeconds']
            source.require(abs(source._probe(config.media) - value['sourceDurationSeconds']) <= .002,
                           'source_duration_identity_changed')
            aligned_path, anchor_path = out / 'aligned-segments.json', out / 'anchor.json'
            if not aligned_path.exists():
                source.require(not (out / 'mfa-started.json').exists(), 'source_mfa_outcome_unknown_reconciliation_required')
                source._freeze(out / 'mfa-preflight.json', mfa_preflight(**source._mfa_options(config)))
            clip = source._audio(config, out / 'source-clip.wav', window['startSeconds'], duration)
            caller = budget.SourceBudget(out / 'api-budget', value['apiAuthority'], verify=fresh,
                transport=api_transport, max_concurrent=value['profile']['sourceASRWorkers'], resource_policy=value['resourcePolicy'])
            if api_key is None:
                import os
                api_key = os.environ.get('OPENAI_API_KEY', '')
            def transcribe(index):
                start, end = index * 180, min((index + 1) * 180, duration)
                audio = source._audio(config, out / 'chunks' / f'{index:04d}.wav', window['startSeconds'] + start, end - start)
                response = caller.transcribe(f'asr.{index:04d}', audio.read_bytes(), source._sha(audio), api_key or '')
                final = {'schemaVersion': 'sermon-source-asr-final-v1', 'chunkIndex': index,
                    'sourceMediaSha256': value['mediaSha256'], 'sourceWindow': window,
                    'clipStartSeconds': start, 'clipEndSeconds': end, 'audioSha256': source._sha(audio),
                    'model': 'gpt-transcribe', 'response': response, 'diagnosticOnly': True}
                source._freeze(out / 'chunks' / f'{index:04d}.asr-final.json', final)
                return final, source._reference_rows(response, index, start, end)
            chunks = source.ordered_bounded_map(range(math.ceil(duration / 180)), transcribe, value['profile']['sourceASRWorkers'])
            finals, references = [f for f, _ in chunks], [r for _, rows in chunks for r in rows]
            source._freeze(out / 'asr_reference_chunks.json', references)
            if aligned_path.exists():
                receipt = source._load(out / 'alignment-receipt.json')
                source.require(receipt['referenceSha256'] == jobs._digest(references)
                    and receipt['alignedSha256'] == source._sha(aligned_path)
                    and receipt['clipSha256'] == source._sha(clip), 'source_alignment_cache_changed')
                aligned = source._load(aligned_path)
            else:
                source._freeze(out / 'mfa-started.json', {'referenceSha256': jobs._digest(references), 'clipSha256': source._sha(clip)})
                aligned = aligner(references, clip, out / 'mfa', **source._mfa_options(config))
                fresh()
                source._freeze(aligned_path, aligned)
                source._freeze(out / 'alignment-receipt.json', {'referenceSha256': jobs._digest(references),
                    'alignedSha256': source._sha(aligned_path), 'clipSha256': source._sha(clip)})
            manifest = anchors.build_anchor_manifest(aligned, source_path=aligned_path, unit_policy=anchors.UNIT_POLICY_V2,
                max_unit_seconds=8, boundary_overrides=None)
            source._freeze(anchor_path, manifest)
            judge_caller = DiagnosticJudgeCaller(value, cli_call=cli_call)
            judged = judge.run(aligned_path=aligned_path, manifest_path=anchor_path, out=out / 'machine-judge.json',
                api_key='', caller=judge_caller, cache_root=out / 'judge-requests', model='gpt-6.1-sol', effort='high',
                batch_size=value['judge']['batchSize'], workers=value['profile']['sourceJudgeWorkers'])
            summary = {'sermonStartSeconds': window['startSeconds'], 'sermonEndSeconds': window['endSeconds'],
                'readingAligner': 'mfa', 'models': {'referenceAsr': 'gpt-transcribe'},
                'pipelineInputIdentity': {'sourceAudio': {'sha256': value['mediaSha256'], 'sizeBytes': config.media.stat().st_size,
                    'durationSeconds': value['sourceDurationSeconds']}}}
            source._freeze(out / 'summary.json', summary)
            package = english.build_package(aligned_path, anchor_path, summary_path=out / 'summary.json',
                machine_judge_path=out / 'machine-judge.json', source_id='diagnostic-source-' + value['mediaSha256'][:16])
            source.require(package['translationEligible'] is False and package['review']['humanApproval'] is False,
                           'diagnostic_source_cannot_approve_content')
            source._freeze(out / 'source.json', package)
            result = {'schemaVersion': 'diagnostic-source-result-v1', 'status': 'diagnostic_source_complete',
                'simulationOnly': True, 'productionEligible': False, 'humanApproval': False, 'requiresHumanSourceReview': True,
                'sourcePath': str(out / 'source.json'), 'anchorPath': str(anchor_path),
                'sourceSha256': source._sha(out / 'source.json'), 'anchorSha256': source._sha(anchor_path),
                'sourceASRWorkers': value['profile']['sourceASRWorkers'], 'sourceJudgeWorkers': value['profile']['sourceJudgeWorkers'],
                'mode': value['mode'], 'chunkCount': len(finals), 'sourceASR': 'fresh_bounded_asr',
                'baselineSampleCounts': value['baselineSampleCounts'],
                'actualAnchorCounts': {'sourceUnits': len(manifest['sourceUnits']), 'sourceSentences': judged['counts']['sourceSentences']},
                'machineJudgeStatus': judged['status'], 'apiAuthority': value['apiAuthority'], 'cliBudgetScope': value['cliBudgetScope']}
            fresh()
            source._freeze(out / 'result.json', result)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'execute'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--provenance', type=Path)
    parser.add_argument('--out-dir', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--resource-policy', type=Path)
    parser.add_argument('--mfa-config', type=Path)
    parser.add_argument('--codex-cli', type=Path)
    parser.add_argument('--frozen-sample-dir', type=Path, help='Exact existing source/anchors: zero new source ASR or MFA')
    args = parser.parse_args()
    if args.command == 'execute':
        source.require(args.config is not None, 'diagnostic_source_config_required')
        result = execute(args.config)
    else:
        source.require(all(p is not None for p in (args.provenance, args.out_dir, args.profile, args.resource_policy, args.mfa_config)),
            'diagnostic_source_prepare_inputs_required')
        result = prepare(provenance_path=args.provenance, out_dir=args.out_dir, profile=load_profile(args.profile),
            resource_policy=source._load(args.resource_policy), mfa=source._load(args.mfa_config), cli_path=args.codex_cli,
            frozen_sample_dir=args.frozen_sample_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

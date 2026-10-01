"""Explicit Source reuse by a distinct diagnostic attempt, never old-budget replay.

The closed parent keeps its real provider receipts and MFA artifacts. The new
attempt gets only hash-bound Source/Anchor copies and its own pending diagnostic
context. No receipt is copied into the new provider ledger or relabeled as a
current model call. This adapter has no credential or model execution path.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat
from types import SimpleNamespace

from scripts import sermon_accounting as accounting
from scripts import sermon_diagnostic_attempts as attempts
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_fresh_diagnostic_source as fresh
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-cached-fresh-diagnostic-source-v1'
SOURCE_MODULES = ('sermon_fresh_diagnostic_source', 'build_english_source_package',
    'sermon_sentence_interpretation', 'sermon_diagnostic_context',
    'sermon_review_contracts', 'sermon_public_snapshot', 'four_layer_measure',
    'mfa_backend', 'mfa_alignment', 'mfa_spark')
SOURCE_SCOPE = ('sourceMediaSha256', 'sourceAudioSha256', 'sourceClipSha256', 'sourceWindowSeconds',
                'credentialReferenceSha256', 'projectId', 'organizationId')


def _ref(path):
    path = _safe_path(path)
    c.require(path.is_file(), 'fresh_source_cache_artifact_required')
    # JSON evidence uses the existing stable aggregate reader. Media/runtime
    # files are hash evidence only and are never parsed or executed here.
    if path.suffix == '.json':
        _, raw = public.read_snapshot(path)
        sha = c.bytes_sha256(raw)
    else:
        fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            before=os.fstat(fd)
            c.require(stat.S_ISREG(before.st_mode) and before.st_size <= 8*1024**3,
                'fresh_source_cache_artifact_invalid')
            digest=hashlib.sha256()
            with os.fdopen(os.dup(fd),'rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
            after=os.fstat(fd); named=os.stat(path,follow_symlinks=False)
            identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
            c.require(identity(before)==identity(after)==identity(named),'fresh_source_cache_artifact_changed')
            sha=digest.hexdigest()
        finally:os.close(fd)
    return {'path':str(path), 'bytesSha256':sha}


def _capture(new_plan, subject, parent_plan_path, authorization):
    c.require(type(subject) is provider.DiagnosticProvider,
        'fresh_source_cache_fixed_provider_required')
    c.require(type(authorization) is dict and authorization.get('productionEligible') is False
        and authorization.get('humanReviewMode') == 'default_pass_for_isolated_test_only',
        'fresh_source_cache_test_authorization_required')
    root = _safe_path(new_plan['runDirectory'])
    c.require(subject.config == new_plan['providerConfig'] and subject.store.root == root/'budget',
        'fresh_source_cache_runtime_binding_changed')
    c.require(new_plan['executionIdentity'].get('trackedWorkingTreeDirty') is False
        and subject.config['codeSha256'] == c.canonical_sha256(new_plan['executionIdentity']),
        'fresh_source_cache_code_binding_changed')
    parent_path = _safe_path(parent_plan_path)
    parent, _ = public.read_snapshot(parent_path)
    oldroot = _safe_path(parent['runDirectory'])
    c.require(parent_path == oldroot/'run-plan.json' and oldroot != root
        and root not in oldroot.parents and oldroot not in root.parents,
        'fresh_source_cache_distinct_parent_required')
    c.require(all(new_plan['providerConfig'][key] == parent['providerConfig'][key] for key in SOURCE_SCOPE)
        and new_plan['providerConfig']['runId'] != parent['providerConfig']['runId'],
        'fresh_source_cache_source_scope_changed')
    c.require(all((oldroot/'budget'/budget.STORE_ID/name).is_file()
                  for name in ('state.json','provider-run/state.json','provider-run/closed.json')),
        'fresh_source_cache_closed_parent_required')
    terminal = attempts.terminal_parent(parent, _legacy_observation=True)
    c.require(not terminal['unsettledBudgetReservations'], 'fresh_source_cache_parent_unsettled')
    closed_path = oldroot/'budget'/budget.STORE_ID/'provider-run/closed.json'
    closed, _ = public.read_snapshot(closed_path)
    attempts._unavailable({**terminal, 'projectedPlan':parent, 'runDirectory':str(oldroot)})
    c.require(closed['budgetStateFileSha256'] == terminal['snapshots'][1]['bytesSha256']
        and closed['closureEvidenceSha256'] == c.canonical_sha256(terminal),
        'fresh_source_cache_parent_close_changed')
    history_path = root/'linked-history.json'
    history, _ = public.read_snapshot(history_path)
    c.require(history.get('schemaVersion') in (attempts.SCHEMA, attempts.SCHEMA_V2)
        and history.get('newPlanSha256') == c.canonical_sha256(new_plan)
        and history.get('authorizationSha256') == new_plan['providerConfig']['approvalSha256'],
        'fresh_source_cache_lineage_changed')
    oldrows = [row for row in history['parentEvidence'] if row['planSha256'] == terminal['planSha256']]
    c.require(len(oldrows) == 1 and all(oldrows[0].get(key) == value for key,value in terminal.items()
        if key not in {'unsettledBudgetReservations','oldReplayAllowed','refundedMicrousd','observationStatus'}),
        'fresh_source_cache_parent_not_in_lineage')
    attempt_auth, _ = public.read_snapshot(root/'authorization.json')
    c.require(c.canonical_sha256(attempt_auth) == history['authorizationSha256'],
        'fresh_source_cache_attempt_authorization_changed')
    source, _ = public.read_snapshot(oldroot/'source.json')
    anchor, _ = public.read_snapshot(oldroot/'anchor-manifest.json')
    old_context, _ = public.read_snapshot(oldroot/'diagnostic-context.json')
    evidence, _ = public.read_snapshot(oldroot/'fresh-source-evidence.json')
    simulation, _ = public.read_snapshot(oldroot/'simulation-authorization.json')
    diagnostic.validate_source(source, anchor, old_context)
    diagnostic.validate_runtime(old_context,run_id=parent['providerConfig']['runId'],store_sha256=closed['storeSha256'])
    c.require(old_context['runConfigSha256'] == c.canonical_sha256(parent['providerConfig'])
        and old_context['continuationCodeCommit'] == parent['executionIdentity']['gitCommit']
        and old_context['simulationAuthorizationRef'] == c.canonical_sha256(simulation)
        and simulation.get('productionEligible') is False and simulation.get('realHumanAcceptance') == 'not_performed'
        and simulation.get('sourceCanonicalSha256') == c.canonical_sha256(source)
        and simulation.get('anchorCanonicalSha256') == c.canonical_sha256(anchor),
        'fresh_source_cache_simulation_changed')
    c.require(evidence.get('schemaVersion') == 'sermon-fresh-diagnostic-source-evidence-v1'
        and evidence.get('sourceCanonicalSha256') == c.canonical_sha256(source)
        and evidence.get('anchorCanonicalSha256') == c.canonical_sha256(anchor)
        and evidence.get('contextSha256') == c.canonical_sha256(old_context)
        and evidence.get('productionEligible') is False and evidence.get('humanAcceptance') == 'pending',
        'fresh_source_cache_source_evidence_changed')
    asr, asr_ref = fresh.returned_receipt(oldroot,parent['providerConfig'],'transcription.initial','gpt-transcribe')
    review, review_ref = fresh.returned_receipt(oldroot,parent['providerConfig'],'source.initial','gpt-6-astra')
    c.require(evidence['asr'] == asr_ref and evidence['sourceCheck'] == review_ref,
        'fresh_source_cache_provider_receipt_changed')
    state_folder = oldroot/'budget'/budget.STORE_ID/'provider-run'
    @contextmanager
    def verified_parent_state():
        yield state_folder, c.read_snapshot(state_folder/'state.json')[0]
    reader = SimpleNamespace(config=parent['providerConfig'],_locked=verified_parent_state)
    expected_payload = provider.DiagnosticProvider.source_check_payload(reader)
    c.require(review['payloadSha256'] == c.canonical_sha256(expected_payload),
        'fresh_source_cache_review_asr_binding_changed')
    content = c.decode_json(review['response']['choices'][0]['message']['content'].encode())
    c.require(c.canonical_sha256(content) == evidence['sourceReviewContentSha256']
        and simulation['sourceReviewReceiptSha256'] == review_ref['receiptSha256'],
        'fresh_source_cache_review_content_changed')
    aligned_path = _safe_path(source['transcript']['artifact']['path'])
    aligned, raw = fresh._read_alignment(aligned_path)
    aligned_bytes_sha=c.bytes_sha256(raw)
    c.require(c.bytes_sha256(raw) == source['transcript']['artifact']['sha256'] == evidence['alignedSegmentsSha256']
        and c.canonical_sha256(aligned) == source['transcript']['artifact']['jsonSha256']
        and fresh.normalized_text(' '.join(row['text'] for row in aligned)) == fresh.normalized_text(asr['response']['text'])
        and source['source']['media']['sha256'] == parent['providerConfig']['sourceMediaSha256']
        and [source['source']['approvedWindow'][key] for key in ('startSeconds','endSeconds')]
            == parent['providerConfig']['sourceWindowSeconds'], 'fresh_source_cache_alignment_binding_changed')
    refs = [parent_path,closed_path,history_path,root/'authorization.json',oldroot/'source.json',oldroot/'anchor-manifest.json',
        oldroot/'diagnostic-context.json',oldroot/'fresh-source-evidence.json',oldroot/'simulation-authorization.json',aligned_path]
    refs += [Path(row['path']) for row in terminal['snapshots']]
    for part in ('anchors',):
        artifact = source[part]['artifact']; value, raw = public.read_snapshot(artifact['path'])
        c.require(c.bytes_sha256(raw) == artifact['sha256'] and c.canonical_sha256(value) == artifact['jsonSha256']
            and value == anchor, 'fresh_source_cache_anchor_artifact_changed')
        refs.append(Path(artifact['path']))
    summary = source['evidence']['pipelineSummary']; value, raw = public.read_snapshot(summary['path'])
    c.require(c.bytes_sha256(raw) == summary['sha256'] and
        (summary.get('jsonSha256') is None or c.canonical_sha256(value) == summary['jsonSha256']),
        'fresh_source_cache_summary_changed')
    refs.append(Path(summary['path']))
    recipe_path=oldroot/'fresh-source-recipe.json';recipe,_=public.read_snapshot(recipe_path)
    c.require(_ref(recipe['files']['audio_path']['path'])['bytesSha256'] ==
        recipe['files']['audio_path']['sha256'] == parent['providerConfig']['sourceAudioSha256'],
        'fresh_source_cache_audio_changed')
    c.require(_ref(parent['sourceClipPath'])['bytesSha256']==parent['providerConfig']['sourceClipSha256'],
        'fresh_source_cache_clip_changed')
    refs += [recipe_path,Path(recipe['files']['audio_path']['path']),Path(parent['sourceClipPath'])]
    if evidence['alignmentMode'] == 'fresh_local_mfa':
        runtime_path = oldroot/'mfa/backend.json'; runtime, _ = public.read_snapshot(runtime_path)
        c.require(runtime['backend'] == 'macbook-local', 'fresh_source_cache_mfa_backend_changed')
        refs.append(runtime_path); runtime = runtime['runtime']
        for item in runtime['files'].values():
            if item:
                c.require(_ref(item['path'])['bytesSha256'] == item['sha256'],'fresh_source_cache_mfa_file_changed')
                refs.append(Path(item['path']))
        for path,sha in runtime.get('nativeKalpy',{}).items():
            c.require(_ref(path)['bytesSha256'] == sha,'fresh_source_cache_mfa_file_changed');refs.append(Path(path))
        env_root = Path(runtime['files']['mfa_executable']['path']).parent.parent
        for name,sha in runtime.get('condaRecords',{}).items():
            c.require(Path(name).name == name, 'fresh_source_cache_mfa_file_changed')
            path = env_root/'conda-meta'/name
            c.require(_ref(path)['bytesSha256'] == sha,'fresh_source_cache_mfa_file_changed');refs.append(path)
        refs += [Path(row['mfaManifest']) for row in aligned if row.get('mfaManifest')]
    else:
        c.require(evidence['alignmentMode'] == 'validated_prior_alignment_cache', 'fresh_source_cache_alignment_mode_invalid')
    repository = Path(__file__).resolve().parents[1]
    from scripts import sermon_source_producer_compatibility as compatibility
    producers = {}; current_producers={}
    for name in SOURCE_MODULES:
        relative='scripts/'+name+'.py';current_producers[relative]=_ref(repository/relative)['bytesSha256']
        producers[relative]=parent['executionIdentity']['loadedProjectCodeSha256'].get(relative)
    c.require(all(new_plan['executionIdentity']['loadedProjectCodeSha256'].get(path)==sha
        for path,sha in current_producers.items()), 'fresh_source_cache_producer_code_changed')
    migration=compatibility.verify(producers,current_producers,
        new_plan['executionIdentity']['loadedProjectCodeSha256'],{
            'parentPlanSha256':c.canonical_sha256(parent),'newPlanSha256':c.canonical_sha256(new_plan),
            'sourceCanonicalSha256':c.canonical_sha256(source),'anchorCanonicalSha256':c.canonical_sha256(anchor),
            'alignmentBytesSha256':aligned_bytes_sha,'asrReceiptSha256':asr_ref['receiptSha256'],
            'sourceCheckReceiptSha256':review_ref['receiptSha256']})
    c.require(source['implementation']['builderSha256'] == producers['scripts/build_english_source_package.py']
        and source['implementation']['anchorGeneratorSha256'] == producers['scripts/sermon_sentence_interpretation.py'],
        'fresh_source_cache_source_implementation_changed')
    proof = {'schemaVersion':SCHEMA,'parentPlanSha256':c.canonical_sha256(parent),'newPlanSha256':c.canonical_sha256(new_plan),
        'parentRunId':parent['providerConfig']['runId'],'runId':new_plan['providerConfig']['runId'],
        'storeSha256':subject.store.store_sha256,'authorizationSha256':c.canonical_sha256(authorization),
        'sourceCanonicalSha256':c.canonical_sha256(source),'anchorCanonicalSha256':c.canonical_sha256(anchor),
        'parentSourceEvidenceSha256':c.canonical_sha256(evidence),'sourceProducerSha256':producers,
        'parentPlanRef':_ref(parent_path),'files':[_ref(path) for path in sorted(set(refs))],
        'historicalSourceProviderCalls':2,'newASRCalls':0,'newSourceCheckCalls':0,'newMFACalls':0,
        'sourceExecution':'historical_receipts_reused_current_deterministic_inspection',
        'productionEligible':False,'humanAcceptance':'pending'}
    if migration is not None:
        proof.update(schemaVersion='sermon-cached-fresh-diagnostic-source-v2',
            sourceProducerCompatibility=migration)
    return source, anchor, proof


def prepare_source(new_plan, subject, *, parent_plan_path, authorization):
    source, anchor, proof = _capture(new_plan,subject,parent_plan_path,authorization)
    root = _safe_path(new_plan['runDirectory'])
    simulation = {'schemaVersion':SCHEMA,'authorizationSha256':c.canonical_sha256(authorization),
        'cacheProofSha256':c.canonical_sha256(proof),'parentSimulationExecution':'retained_not_reapproved',
        'realHumanAcceptance':'not_performed','productionEligible':False}
    context = {'schemaVersion':diagnostic.SCHEMA,'runId':subject.config['runId'],
        'runConfigSha256':c.canonical_sha256(subject.config),'storeSha256':subject.store.store_sha256,
        'sourceCanonicalSha256':c.canonical_sha256(source),'anchorCanonicalSha256':c.canonical_sha256(anchor),
        'simulationAuthorizationRef':c.canonical_sha256(simulation),
        'continuationCodeCommit':new_plan['executionIdentity']['gitCommit'],'humanAcceptance':'pending','productionEligible':False}
    diagnostic.validate_source(source,anchor,context)
    with accounting.stage('diagnostic.source_cache',executor_type='deterministic_program',cache_hit=True,depends_on=[]) as span:
        for name,value in (('source.json',source),('anchor-manifest.json',anchor),('cached-source-proof.json',proof),
            ('cached-source-authorization.json',authorization),('simulation-authorization.json',simulation),('diagnostic-context.json',context)):
            public.save_once(root/name,value)
        accounting.record_workload('diagnostic.source_cache_binding',{'cacheProofSha256':c.canonical_sha256(proof),
            'historicalSourceProviderCalls':2,'newASRCalls':0,'newSourceCheckCalls':0,'newMFACalls':0,
            'productionEligible':False,'realHumanAcceptancePending':True})
    return {'source':source,'anchor':anchor,'context':context,'evidence':proof,'completionSpans':[span]}


def validate_evidence(new_plan, subject, context, evidence):
    root = _safe_path(new_plan['runDirectory'])
    authorization, _ = public.read_snapshot(root/'cached-source-authorization.json')
    source, anchor, current = _capture(new_plan,subject,evidence['parentPlanRef']['path'],authorization)
    c.require(current == evidence == public.read_snapshot(root/'cached-source-proof.json')[0],
        'fresh_source_cache_frozen_evidence_changed')
    simulation, _ = public.read_snapshot(root/'simulation-authorization.json')
    c.require(simulation == {'schemaVersion':SCHEMA,'authorizationSha256':c.canonical_sha256(authorization),
        'cacheProofSha256':c.canonical_sha256(current),'parentSimulationExecution':'retained_not_reapproved',
        'realHumanAcceptance':'not_performed','productionEligible':False}
        and c.canonical_sha256(simulation) == context['simulationAuthorizationRef']
        and context['runConfigSha256'] == c.canonical_sha256(subject.config)
        and context['continuationCodeCommit'] == new_plan['executionIdentity']['gitCommit'],
        'fresh_source_cache_simulation_changed')
    diagnostic.validate_runtime(context,run_id=subject.config['runId'],store_sha256=subject.store.store_sha256)
    diagnostic.validate_source(source,anchor,context)
    c.require(public.read_snapshot(root/'source.json')[0] == source
        and public.read_snapshot(root/'anchor-manifest.json')[0] == anchor,
        'fresh_source_cache_current_source_changed')
    return deepcopy(current)

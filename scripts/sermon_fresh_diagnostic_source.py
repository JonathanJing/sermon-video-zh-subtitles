"""Fresh Layer 1 diagnostic preparation using real returned provider evidence.

No credentials or model transport live here. The fresh runner owns ASR/source
calls; this adapter binds their actual receipts, reuses only verified alignment,
or explicitly invokes the existing local MFA backend. Pending review never
becomes formal approval. All outputs are immutable and remain diagnostic-only.
"""
from copy import deepcopy
from pathlib import Path
import unicodedata
import tempfile

from scripts import sermon_review_contracts as c
from scripts import sermon_review_budget as budget
from scripts import sermon_strict_layer2 as immutable
from scripts import sermon_sentence_interpretation as anchors
from scripts import build_english_source_package as english
from scripts import sermon_diagnostic_context as diagnostic
from scripts import sermon_accounting as accounting
from scripts import sermon_public_snapshot as aggregate
from scripts import mfa_backend
from scripts import sermon_completion as completion
from scripts import sermon_fresh_source_causality as causality
from scripts import sermon_mfa_identity as mfa_identity
from scripts.sermon_release_workflow import _safe_path


def _read(path):
    return c.read_snapshot(_safe_path(Path(path)))


def _sha(path):
    return c.bytes_sha256(_safe_path(Path(path)).read_bytes())


def _read_alignment(path):
    """Alignment is aggregate evidence, not a private per-review receipt."""
    try:
        value, data = aggregate.read_snapshot(_safe_path(Path(path)))
    except c.ContractError as exc:
        # Bind the safe failure to this input domain; never publish paths or
        # parse bodies, and leave the private review contract's cap unchanged.
        if str(exc) in {'invalid_public_snapshot_file', 'public_snapshot_size_limit',
                        'invalid_public_json_bytes', 'public_snapshot_changed_during_read'}:
            raise c.ContractError('fresh_alignment_snapshot_invalid') from exc
        raise
    c.require(type(value) is list and all(type(row) is dict for row in value),
              'fresh_alignment_snapshot_invalid')
    return value, data


def normalized_text(text):
    c.require(type(text) is str and bool(text.strip()), 'fresh_source_asr_text_missing')
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def returned_receipt(root, config, operation, model):
    """Fixed local receipt path; never follow a provider-supplied reference."""
    root = _safe_path(Path(root))
    folder = root/'budget'/budget.STORE_ID/'provider-run'
    state, raw = _read(folder/'state.json')
    c.require(state['config'] == config and all(row['state'] in ('returned','rejected')
        for row in state['requests'].values()), 'fresh_source_provider_outcome_unknown')
    rows = [(call,row) for call,row in state['requests'].items() if row['operationId'] == operation]
    c.require(len(rows)==1 and rows[0][1]['state']=='returned' and rows[0][1]['model']==model,
              'fresh_source_returned_receipt_required')
    call,row = rows[0]; budget._label(call)
    receipt,data = _read(folder/(call+'.json'))
    c.require(c.bytes_sha256(data)==row['receiptSha256'] and receipt['modelCallId']==call
        and receipt['payloadSha256']==row['requestSha256'] and type(receipt['response']) is dict,
        'fresh_source_receipt_binding_changed')
    c.require(_read(folder/'state.json')[1]==raw, 'fresh_source_provider_snapshot_changed')
    return receipt, {'operationId':operation,'model':model,'modelCallId':call,
                     'receiptSha256':c.bytes_sha256(data),'requestSha256':row['requestSha256']}


def preflight_recipe(plan, recipe, authorization):
    """Check consumer/seed compatibility before any fresh provider request."""
    config = plan['providerConfig']
    c.require(type(authorization) is dict and authorization.get('productionEligible') is False
        and authorization.get('humanReviewMode') == 'default_pass_for_isolated_test_only',
        'fresh_source_test_authorization_required')
    c.require(type(recipe.get('run_mfa', False)) is bool
        and (not recipe.get('run_mfa') or recipe.get('local_runtime_path') is not None),
        'fresh_source_recipe_invalid')
    c.require(_sha(recipe['audio_path']) == config['sourceAudioSha256'], 'fresh_source_audio_changed')
    prior, _ = _read(recipe['prior_plan_path'])
    old_config = prior['providerConfig']
    c.require(all(config[key] == old_config[key] for key in
        ('sourceMediaSha256', 'sourceAudioSha256', 'sourceClipSha256', 'sourceWindowSeconds')),
        'fresh_alignment_prior_source_changed')
    old_asr, _ = returned_receipt(prior['runDirectory'], old_config, 'transcription.initial', 'gpt-transcribe')
    source, _ = _read(recipe['prior_source_path'])
    aligned, raw = _read_alignment(recipe['prior_aligned_path'])
    artifact = source['transcript']['artifact']
    c.require(artifact['sha256'] == c.bytes_sha256(raw)
        and artifact['jsonSha256'] == c.canonical_sha256(aligned)
        and Path(artifact['path']) == Path(recipe['prior_aligned_path'])
        and source['source']['media']['sha256'] == config['sourceMediaSha256']
        and [source['source']['approvedWindow'][key] for key in ('startSeconds', 'endSeconds')]
            == config['sourceWindowSeconds'] and aligned
        and normalized_text(' '.join(row['text'] for row in aligned)) == normalized_text(old_asr['response']['text']),
        'fresh_alignment_prior_artifact_changed')
    summary, raw = _read(recipe['prior_summary_path'])
    ref = source['evidence']['pipelineSummary']
    c.require(ref['sha256'] == c.bytes_sha256(raw)
        and (ref.get('jsonSha256') is None or ref['jsonSha256'] == c.canonical_sha256(summary)),
        'fresh_source_prior_summary_changed')
    try:
        # Exercise the actual current builders on the frozen seed before buying
        # requests. Temporary compatibility outputs are not production evidence.
        anchor = anchors.build_anchor_manifest(aligned, source_path=Path(recipe['prior_aligned_path']),
            unit_policy=anchors.UNIT_POLICY_V2)
        future_summary = deepcopy(summary)
        future_summary['pipelineInputIdentity']['sourceAudio']['sha256'] = config['sourceMediaSha256']
        future_summary['sermonStartSeconds'], future_summary['sermonEndSeconds'] = config['sourceWindowSeconds']
        with tempfile.TemporaryDirectory(prefix='source-preflight-', dir=plan['runDirectory']) as directory:
            directory = Path(directory)
            anchor_path, summary_path = directory/'anchor.json', directory/'summary.json'
            anchor_path.write_bytes(c.canonical_bytes(anchor)); summary_path.write_bytes(c.canonical_bytes(future_summary))
            english.build_package(Path(recipe['prior_aligned_path']), anchor_path, summary_path=summary_path,
                source_id=source['source']['sourceId'], source_url_hash=source['source']['sourceUrlHash'],
                service_date=source['source']['serviceDate'])
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise c.ContractError('fresh_source_recipe_consumer_incompatible') from exc
    # These actual fixed builders/consumers must be included before the plan is
    # frozen. No late importer or unknown recipe may buy a request first.
    repository = Path(__file__).resolve().parents[1]
    frozen = plan['executionIdentity']['loadedProjectCodeSha256']
    for module in (__file__, english.__file__, anchors.__file__, diagnostic.__file__,
                   completion.__file__, causality.__file__, mfa_identity.__file__):
        path = Path(module).resolve()
        c.require(frozen.get(str(path.relative_to(repository))) == _sha(path),
            'fresh_source_consumer_not_frozen')


def prepare_source(plan, subject, *, prior_plan_path, prior_source_path, prior_aligned_path,
                   prior_summary_path, audio_path, authorization, run_mfa=False,
                   local_runtime_path=None, depends_on=None, deadline_monotonic=None, source_completions=None):
    """Deterministic/fixed-MFA bridge from fresh ASR to actual English/Anchors.

    Prior references are user-selected local frozen source evidence. No old
    budget, receipt, policy or approval is edited. `run_mfa` authorizes local
    inference only when transcript equality does not allow exact cache reuse.
    """
    config=plan['providerConfig']; root=_safe_path(Path(plan['runDirectory']))
    c.require(root.is_absolute() and subject.config==config and subject.store.root==root/'budget',
              'fresh_source_provider_binding_changed')
    c.require(type(run_mfa) is bool and type(authorization) is dict and
        authorization.get('productionEligible') is False and
        authorization.get('humanReviewMode')=='default_pass_for_isolated_test_only',
        'fresh_source_test_authorization_required')
    with subject._locked() as (_,state):
        subject._remaining(state)
        original_deadline=state['startedMonotonic']+config['totalWallSeconds']
    c.require(deadline_monotonic is None or deadline_monotonic==original_deadline,
              'fresh_mfa_original_deadline_changed')
    deadline_monotonic=original_deadline
    audio_path=_safe_path(Path(audio_path))
    c.require(_sha(audio_path)==config['sourceAudioSha256'], 'fresh_source_audio_changed')
    asr,asr_ref=returned_receipt(root,config,'transcription.initial','gpt-transcribe')
    review,review_ref=returned_receipt(root,config,'source.initial','gpt-6-astra')
    c.require(review['payloadSha256']==c.canonical_sha256(subject.source_check_payload()),
              'fresh_source_check_asr_binding_changed')
    text=asr['response'].get('text'); normalized_text(text)
    c.require(type(review['response'].get('choices')) is list and len(review['response']['choices'])==1
        and review['response']['choices'][0].get('finish_reason')=='stop'
        and review['response']['choices'][0]['message'].get('refusal') is None,
        'fresh_source_check_response_incomplete')
    review_content=c.decode_json(review['response']['choices'][0]['message']['content'].encode())
    c.require(type(review_content) is dict, 'fresh_source_check_response_invalid')
    prior,_=_read(prior_plan_path); old_config=prior['providerConfig']
    c.require(all(config[k]==old_config[k] for k in ('sourceMediaSha256','sourceAudioSha256',
        'sourceClipSha256','sourceWindowSeconds')), 'fresh_alignment_prior_source_changed')
    old_asr,old_ref=returned_receipt(prior['runDirectory'],old_config,'transcription.initial','gpt-transcribe')
    old_source,_=_read(prior_source_path); aligned,aligned_raw=_read_alignment(prior_aligned_path)
    artifact=old_source['transcript']['artifact']
    c.require(artifact['sha256']==c.bytes_sha256(aligned_raw) and
        artifact['jsonSha256']==c.canonical_sha256(aligned) and
        old_source['source']['media']['sha256']==old_config['sourceMediaSha256'] and
        [old_source['source']['approvedWindow'][k] for k in ('startSeconds','endSeconds')]==old_config['sourceWindowSeconds'],
        'fresh_alignment_prior_artifact_changed')
    c.require(type(aligned) is list and aligned and normalized_text(' '.join(x['text'] for x in aligned))==
        normalized_text(old_asr['response']['text']), 'fresh_alignment_prior_asr_changed')
    same=normalized_text(text)==normalized_text(old_asr['response']['text'])
    summary,summary_raw=_read(prior_summary_path)
    ref=old_source['evidence']['pipelineSummary']
    c.require(ref['sha256']==c.bytes_sha256(summary_raw) and
        (ref.get('jsonSha256') is None or ref['jsonSha256']==c.canonical_sha256(summary)),
        'fresh_source_prior_summary_changed')
    preflight = None
    if run_mfa:
        preflight_path = root/'mfa-identity-preflight.json'
        previous = _read(preflight_path)[0] if preflight_path.exists() else None
        preflight = mfa_identity.preflight(plan, local_runtime_path, expected_receipt=previous)
        immutable.save_once(preflight_path, preflight)
        mfa_identity.require_accepted(preflight)
    if source_completions is not None:
        c.require(type(source_completions) is dict and set(source_completions) == {'intake', 'transcription', 'sourceCheck'},
            'fresh_causality_predecessors_required')
        _, events = completion.current_events()
        upstream = source_completions['sourceCheck']
        completion.validate(upstream, events, production_run_id=config['runId'],
            artifact_sha256=review_ref['receiptSha256'], dependencies=[source_completions['transcription']['spanId']])
        c.require(upstream['stage'] in causality.STAGES['sourceCheck'], 'fresh_causality_provider_leaf_required')
        depends_on = [upstream['spanId']]
    chunks=[{'id':'fresh-diagnostic','start':0.,'end':config['sourceWindowSeconds'][1]-config['sourceWindowSeconds'][0],'text':text}]
    immutable.save_once(root/'reference-chunks.json',chunks)
    with accounting.stage('diagnostic.alignment',executor_type='deterministic_program',
                          cache_hit=same,depends_on=depends_on,work_unit_id='source.alignment') as alignment_span:
        if not same:
            c.require(run_mfa and local_runtime_path is not None,'fresh_alignment_required')
            runtime,_=_read(local_runtime_path)
            c.require(runtime['backend']=='macbook-local','fresh_local_mfa_runtime_required')
            files=runtime['runtime']['files']
            for item in files.values():
                if item: c.require(_sha(item['path'])==item['sha256'],'fresh_mfa_runtime_file_changed')
            options={key:item['path'] if item else None for key,item in files.items()}
            try:
                aligned=mfa_backend.align_reference_chunks(chunks,audio_path,root/'mfa',local_options=options,
                    spark_options={},allow_spark_fallback=False,deadline_monotonic=deadline_monotonic)
            except mfa_backend.local.MFADeadlineReached as exc:
                raise c.ContractError('fresh_mfa_original_deadline_reached') from exc
            except mfa_backend.LocalRuntimeUnavailable as exc:
                raise c.ContractError('fresh_mfa_runtime_unavailable') from exc
            except ValueError as exc:
                raise c.ContractError('fresh_mfa_alignment_invalid') from exc
            except (RuntimeError,OSError) as exc:
                raise c.ContractError('fresh_mfa_command_failed') from exc
        comparison = None
        if not same:
            comparison_path = root/'mfa-identity-comparison.json'
            previous = _read(comparison_path)[0] if comparison_path.exists() else None
            comparison = mfa_identity.validate_alignment(plan, local_runtime_path, root/'mfa/backend.json',
                preflight_receipt=preflight, expected_receipt=previous,
                aligned_segments=aligned, reference_chunks=chunks)
            immutable.save_once(comparison_path, comparison)
            mfa_identity.require_accepted(comparison)
        aggregate.save_once(root/'aligned-segments.json',aligned)
        mode='validated_prior_alignment_cache' if same else 'fresh_local_mfa'
        accounting.record_workload('diagnostic.alignment_binding',{'sourceAudioSha256':config['sourceAudioSha256'],
            'newASRReceiptSha256':asr_ref['receiptSha256'],'oldASRReceiptSha256':old_ref['receiptSha256'],
            'oldAlignedSegmentsSha256':c.bytes_sha256(aligned_raw),'alignmentCacheHit':same,
            'backendInferenceObserved':None if not same else False,
            'backendCacheHitObserved':None if not same else False,
            'alignedSegmentsSha256':_sha(root/'aligned-segments.json')})
    alignment_completion = completion.capture(alignment_span, production_run_id=config['runId'],
        artifact_sha256=_sha(root/'aligned-segments.json'), artifact_kind='aligned_segments',
        execution_mode='cache_replay' if same else 'backend_execution_unobserved') if source_completions is not None else None
    with accounting.stage('diagnostic.source_package',depends_on=[alignment_span],executor_type='deterministic_program',
            work_unit_id='source.package') as source_span:
        try:
            anchor=anchors.build_anchor_manifest(aligned,source_path=root/'aligned-segments.json',unit_policy=anchors.UNIT_POLICY_V2)
        except ValueError as exc:
            raise c.ContractError('fresh_anchor_contract_invalid') from exc
        immutable.save_once(root/'anchor-manifest.json',anchor)
        summary=deepcopy(summary)
        summary['pipelineInputIdentity']['sourceAudio']['sha256']=config['sourceMediaSha256']
        summary['sermonStartSeconds'],summary['sermonEndSeconds']=config['sourceWindowSeconds']
        summary['diagnosticASRReceiptSha256']=asr_ref['receiptSha256']
        summary['diagnosticAlignmentMode']=mode
        immutable.save_once(root/'source-summary.json',summary)
        try:
            source=english.build_package(root/'aligned-segments.json',root/'anchor-manifest.json',summary_path=root/'source-summary.json',
                source_id=old_source['source']['sourceId'],source_url_hash=old_source['source']['sourceUrlHash'],
                service_date=old_source['source']['serviceDate'])
        except ValueError as exc:
            raise c.ContractError('fresh_english_source_contract_invalid') from exc
        immutable.save_once(root/'source.json',source)
        simulation={'schemaVersion':'sermon-fresh-diagnostic-simulation-v1',
            'authorizationSha256':c.canonical_sha256(authorization),'sourceCanonicalSha256':c.canonical_sha256(source),
            'anchorCanonicalSha256':c.canonical_sha256(anchor),'sourceReviewReceiptSha256':review_ref['receiptSha256'],
            'sourceReviewContentSha256':c.canonical_sha256(review_content),'sourceReviewStatus':'pending',
            'realHumanAcceptance':'not_performed','productionEligible':False}
        immutable.save_once(root/'simulation-authorization.json',simulation)
        context={'schemaVersion':diagnostic.SCHEMA,'runId':config['runId'],'runConfigSha256':c.canonical_sha256(config),
            'storeSha256':subject.store.store_sha256,'sourceCanonicalSha256':c.canonical_sha256(source),
            'anchorCanonicalSha256':c.canonical_sha256(anchor),'simulationAuthorizationRef':c.canonical_sha256(simulation),
            'continuationCodeCommit':plan['executionIdentity']['gitCommit'],'humanAcceptance':'pending','productionEligible':False}
        diagnostic.validate_source(source,anchor,context)
        immutable.save_once(root/'diagnostic-context.json',context)
        accounting.record_workload('diagnostic.fresh_source_binding',{'sourceCanonicalSha256':context['sourceCanonicalSha256'],
            'anchorCanonicalSha256':context['anchorCanonicalSha256'],'sourceReviewReceiptSha256':review_ref['receiptSha256'],
            'simulatedHumanApproval':True,'realHumanAcceptancePending':True,'productionEligible':False})
    causal = None
    if source_completions is not None:
        source_completion = completion.capture(source_span, production_run_id=config['runId'],
            artifact_sha256=c.canonical_sha256(source), artifact_kind='source_package',
            execution_mode='deterministic_validation')
        identity, events = completion.current_events()
        recipe = _read(root/'fresh-source-recipe.json')[0]
        causal = {'schemaVersion':causality.SCHEMA, 'runId':config['runId'],
            'planSha256':c.canonical_sha256(plan), 'recipeSha256':c.canonical_sha256(recipe),
            'logDirectory':str(identity[0]), 'handles':dict(source_completions,
                alignment=alignment_completion, sourcePackage=source_completion)}
        causality.validate(causal, events, plan=plan, recipe=recipe, asr_ref=asr_ref, review_ref=review_ref,
            aligned_sha256=_sha(root/'aligned-segments.json'), source_sha256=c.canonical_sha256(source))
        immutable.save_once(root/'fresh-source-causality.json', causal)
    evidence={'schemaVersion':'sermon-fresh-diagnostic-source-evidence-v2','asr':asr_ref,'sourceCheck':review_ref,
            'alignmentMode':mode,'sourceCanonicalSha256':c.canonical_sha256(source),'anchorCanonicalSha256':c.canonical_sha256(anchor),
            'alignedSegmentsSha256':_sha(root/'aligned-segments.json'),'sourceReviewStatus':'pending',
            'sourceReviewContentSha256':c.canonical_sha256(review_content),'contextSha256':c.canonical_sha256(context),
            'productionEligible':False,'humanAcceptance':'pending'}
    evidence.update(mfaIdentityPreflightSha256=c.canonical_sha256(preflight) if not same else None,
        mfaIdentityComparisonSha256=c.canonical_sha256(comparison) if comparison else None,
        sourceCausalitySha256=c.canonical_sha256(causal) if causal else None)
    immutable.save_once(root/'fresh-source-evidence.json',evidence)
    return {'source':source,'anchor':anchor,'context':context,'evidence':evidence,'completionSpans':[source_span]}

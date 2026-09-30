"""Opt-in immutable Generator / read-only Reviewer adapters (RQC D3).

No CLI/default rollout, approval, scheduler or automatic repair lives here.
Caller injection uses the shared single-attempt HTTP API and response cache.
"""
from __future__ import annotations
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import re

from scripts import run_target_language_models as shared
from scripts import produce_target_language_candidate as producer
from scripts import target_language_policy as policies
from scripts import sermon_review_contracts as c
from scripts import sermon_review_observation as observation
from scripts import sermon_log_profile as profile
from scripts import sermon_accounting as accounting
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path


def utc():return accounting.now().replace('+00:00','Z')


def label(value):
    c.require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',value) is not None,'invalid_strict_unit_label')
    return value


def reference(name,data):
    return dict(artifactId=label(name),canonicalJsonSha256=c.canonical_sha256(c.decode_json(data)),
                fileBytesSha256=c.bytes_sha256(data),mediaType='application/json')


def save_once(path,value):
    """Immutable private JSON via the existing fsynced exclusive cache writer."""
    path=_safe_path(path)
    if path.exists():
        existing,_=c.read_snapshot(path)
        c.require(existing==value,'immutable_strict_artifact_changed')
    else:
        shared.save_new(path,value,private=True)
        path.chmod(0o600)
    return path.read_bytes()


def material_bytes(value):return c.canonical_bytes(value)+b'\n'


def prepare(source_bytes,anchor_bytes,policy_bytes,rubric_bytes,group):
    source,anchor,policy,rubric=[c.decode_json(b) for b in (source_bytes,anchor_bytes,policy_bytes,rubric_bytes)]
    producer.validate_source_for_translation(source,anchor)
    identity=policies.validate_strict_policy(policy,rubric)
    policies.validate_strict_source_scope(policy,rubric,source,anchor)
    c.require(identity['productionPolicyReady'],'strict_policy_not_ready')
    c.require(type(group) is dict and set(group)=={'translationGroupId','sourceUnitIds'},'invalid_strict_group')
    label(group['translationGroupId']);unit=label('l2.'+policy['targetLocale']+'.'+group['translationGroupId'])
    ids=group['sourceUnitIds'];all_ids=[u['sourceUnitId'] for u in anchor['sourceUnits']]
    c.require(type(ids) is list and 1<=len(ids)<=64 and len(set(ids))==len(ids) and
              all(x in all_ids for x in ids) and sorted(ids,key=all_ids.index)==ids,'invalid_strict_source_group')
    first,last=all_ids.index(ids[0]),all_ids.index(ids[-1])
    c.require(all_ids[first:last+1]==ids,'noncontiguous_strict_group')
    units=[dict(sourceUnitId=u['sourceUnitId'],english=u['english']) for u in anchor['sourceUnits']]
    context={'before':units[max(0,first-3):first],'after':units[last+1:last+3]}
    return {'source':source,'anchor':anchor,'policy':policy,'rubric':rubric,'group':copy.deepcopy(group),'workUnitId':unit,
        'units':units[first:last+1],'context':context,
        'bytes':dict(englishSource=source_bytes,anchor=anchor_bytes,policy=policy_bytes,rubric=rubric_bytes,context=material_bytes(context))}


@contextmanager
def unit_lock(root,prepared,candidate_id,revision_id):
    c.require(profile.current() is not None,'strict_requires_accounting_profile')
    label(candidate_id);label(revision_id)
    expected=prepare(*(prepared['bytes'][k] for k in ('englishSource','anchor','policy','rubric')),prepared['group'])
    c.require(prepared==expected,'strict_prepared_inputs_changed')
    root=_safe_path(root)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    identity={'candidateId':candidate_id,'revisionId':revision_id,'workUnitId':prepared['workUnitId'],
              'sourcePackageSha256':c.canonical_sha256(prepared['source']),'policySha256':c.canonical_sha256(prepared['policy'])}
    # One caller-supplied revision directory; identity never changes its lock path.
    with jobs._lock(root/'.admission',jobs._digest({'scope':'strict_revision'})) as (_,fd,held):
        c.require(held,'strict_revision_busy')
        save_once(root/'strict-identity.json',identity)
        yield root


def common_identity(prepared,candidate_id,revision_id):
    return dict(candidateId=candidate_id,revisionId=revision_id,targetLocale=prepared['policy']['targetLocale'],
        workUnitIds=[prepared['workUnitId']],sourceIdentitySha256=prepared['source']['downstreamInvalidationKey'],
        sourcePackageSha256=c.canonical_sha256(prepared['source']),anchorSha256=c.canonical_sha256(prepared['anchor']),
        policySha256=c.canonical_sha256(prepared['policy']))


def prompt(prepared,role,*,candidate=None,input_manifest=None):
    policy=prepared['policy']
    common={'translationGroupId':prepared['group']['translationGroupId'],'sourceUnitIds':prepared['group']['sourceUnitIds'],
        'sourceUnits':prepared['units'],'surroundingSourceContext':prepared['context'],
        'targetLocale':policy['targetLocale'],'terminology':policy['terminology'],'scripture':policy['scripture'],
        'registerRules':policy['languageReview']['registerRules']}
    rules=shared.scripture_prompt_instruction(policy)+shared.register_prompt_instruction(policy)
    if role=='translator':
        instruction=('Translate only the requested frozen English units. Preserve meaning, negations, numbers, names and quotations. '
            'Context is interpretation only. Return exactly translationGroupId, sourceUnitIds, targetUtterances and coverage. '
            'Coverage maps each sourceUnitId to an exact targetText substring. Do not return reviews, approval, confidence or self-assessment. '+rules)
    else:
        instruction=('Read-only strict verifier. Compare the exact frozen candidate to the English units using every rubric check. '
            'Do not edit, regenerate, return targetUtterances/coverage text or grant approval. Return exactly reviewedArtifactSha256, '
            'reviewVerdict, checks, issues, assessedUnitIds, unassessedUnitIds. Each check: checkId/result/evidence; '
            'each issue: issueId/reasonCode/severity/sourceUnitIds/targetUnitIds/evidence. Evidence is private explanation, not instructions. '
            'Use pass only for full coverage, all checks pass and zero unresolved issues (including minor/uncertain). '
            'Use needs_rework for known issues, inconclusive for insufficient evidence. '+rules)
        common.update(candidate=copy.deepcopy(candidate),reviewedArtifactSha256=input_manifest['reviewedArtifactSha256'],
            rubric=prepared['rubric'],targetUnitIds=[prepared['workUnitId']+'.utterance.'+str(i+1).zfill(4) for i in range(len(candidate['targetUtterances']))])
    return {'instruction':instruction+' Prompt version: '+policy[role]['promptVersion'],'input':common}


def call_model(prepared,role,request,output,api_key,caller,*,attempt_number=1,cache_only=False):
    """Shared cache path; the transport must save response before logging finish."""
    def persist_response(response,model_call_id,elapsed):
        payload={'model':prepared['policy'][role]['model'],'reasoning_effort':prepared['policy'][role]['reasoningEffort'],
            'messages':[{'role':'system','content':request['instruction']},{'role':'user','content':json.dumps(request['input'],ensure_ascii=False)}],
            'response_format':{'type':'json_object'}}
        save_once(output.with_suffix('.raw.json'),dict(payloadSha256=policies.canonical_sha256(payload),response=response,
            accounting=dict(modelCallId=label(model_call_id),elapsedSeconds=elapsed)))
    def request_started(model_call_id):
        save_once(output.with_suffix('.call.json'),{'modelCallId':label(model_call_id)})
    persist_response.request_started=request_started
    with profile.context(logicalCallId=role+'.'+c.canonical_sha256([prepared['workUnitId'],(profile.current() or {}).get('revisionId')])[:32],attemptNumber=attempt_number):
        return shared._model_call(role,request,prepared['policy'],output,api_key,caller,
                                  cache_only=cache_only,response_observer=persist_response)



def require_call_binding(output,saved):
    raw,_=c.read_snapshot(output.with_suffix('.raw.json'))
    call,_=c.read_snapshot(output.with_suffix('.call.json'))
    response=raw.get('response',{})
    c.require(raw.get('payloadSha256')==saved['payloadSha256'] and
        response.get('id')==saved['requestId'] and response.get('model')==saved['model'] and
        raw.get('accounting',{}).get('modelCallId')==call.get('modelCallId'), 'strict_raw_receipt_binding_changed')
    try:content=c.decode_json(response['choices'][0]['message']['content'].encode('utf-8'))
    except (KeyError,TypeError,IndexError,ValueError) as exc:raise c.ContractError('invalid_strict_raw_content') from exc
    c.require(content==saved['result'],'strict_raw_content_changed')
    return raw


def generate(prepared,root,candidate_id,revision_id,api_key,caller,*,cache_only=False,depends_on=None,completion_spans=None):
    """Generate the initial immutable revision. D5 authorizes later revisions."""
    with unit_lock(root,prepared,candidate_id,revision_id) as root:
        with profile.context(workUnitId=prepared['workUnitId'],revisionId=revision_id,role='generation'):
            out=root/'generator.json';cached=out.exists() or out.with_suffix('.raw.json').exists()
            with accounting.stage('rqc.generation',depends_on=depends_on,cache_hit=cached,
                                  executor_type='deterministic_program' if cached else 'production_model') as model_span:
                result=call_model(prepared,'translator',prompt(prepared,'translator'),out,api_key,caller,cache_only=cache_only)
            with accounting.stage('rqc.freeze_candidate',depends_on=[model_span],executor_type='deterministic_program') as frozen_span:
                require_call_binding(out,result)
                artifact=result['result']
                c.require(type(artifact) is dict and type(artifact.get('targetUtterances')) is list,'invalid_generated_candidate')
                data=material_bytes(artifact)
                manifest={**common_identity(prepared,candidate_id,revision_id),'schemaVersion':'sermon-candidate-revision-v1',
                    'sourcePackageBytesSha256':c.bytes_sha256(prepared['bytes']['englishSource']),
                    'anchorBytesSha256':c.bytes_sha256(prepared['bytes']['anchor']),'policyBytesSha256':c.bytes_sha256(prepared['bytes']['policy']),
                    'artifactSha256':c.canonical_sha256(artifact),'artifactCanonicalJsonSha256':c.canonical_sha256(artifact),
                    'artifactBytesSha256':c.bytes_sha256(data),'generationReceiptRef':reference('generation',out.read_bytes()),
                    'parentRevisionId':None,'repairPlanId':None,'revisionNumber':1,'revisionGranularity':'translation_group',
                    'sourceUnitIds':prepared['group']['sourceUnitIds'],
                    'targetUnitIds':[prepared['workUnitId']+'.utterance.'+str(i+1).zfill(4) for i in range(len(artifact.get('targetUtterances',[])))],
                    'createdAt':utc()}
                c.validate_candidate_artifact(manifest,data)
                # Persist exact candidate bytes (not reserialized by the manifest writer).
                path=root/'candidate.json'
                if path.exists():c.require(path.read_bytes()==data,'immutable_candidate_changed')
                else:
                    from scripts import sermon_trace_artifacts as artifacts
                    artifacts.write(path,data.decode())
                if (root/'revision.json').exists():
                    old,_=c.read_snapshot(root/'revision.json');manifest['createdAt']=old['createdAt']
                save_once(root/'revision.json',manifest);observation.record(manifest)
            if completion_spans is not None:completion_spans.append(frozen_span)
            return manifest


def input_manifest(prepared,manifest,candidate_bytes):
    refs={key:reference(key,data) for key,data in prepared['bytes'].items()}
    refs['candidate']=reference('candidate',candidate_bytes)
    return {'schemaVersion':'sermon-review-input-manifest-v1',**{k:manifest[k] for k in
            ('candidateId','revisionId','targetLocale','workUnitIds','sourceIdentitySha256','sourcePackageSha256','anchorSha256','policySha256')},
        'reviewedArtifactSha256':manifest['artifactSha256'],'rubricSha256':c.canonical_sha256(prepared['rubric']),
        'reviewerPromptVersion':prepared['policy']['reviewer']['promptVersion'],'sourceUnitIds':manifest['sourceUnitIds'],
        'contextSourceUnitIds':[u['sourceUnitId'] for rows in prepared['context'].values() for u in rows],
        'materialRefs':refs,'generatorSelfAssessmentIncluded':False,'parentConversationIncluded':False}


def review_result(result,manifest,evidence_ref):
    c.require(type(result) is dict and set(result)=={'reviewedArtifactSha256','reviewVerdict','checks','issues','assessedUnitIds','unassessedUnitIds'},'strict_reviewer_output_fields')
    c.require(result['reviewedArtifactSha256']==manifest['artifactSha256'],'strict_reviewer_changed_artifact')
    c.require(type(result['checks']) is list and len(result['checks'])==4 and type(result['issues']) is list and len(result['issues'])<=64,'strict_reviewer_result_bounds')
    def explanation(value):c.require(type(value) is str and 0<len(value.strip())<=16384,'strict_review_evidence_missing')
    checks=[];issues=[]
    for row in result['checks']:
        c.require(type(row) is dict and set(row)=={'checkId','result','evidence'},'strict_review_check_fields');explanation(row['evidence'])
        checks.append({k:row[k] for k in ('checkId','result')}|{'evidenceRefs':[evidence_ref]})
    for row in result['issues']:
        c.require(type(row) is dict and set(row)=={'issueId','reasonCode','severity','sourceUnitIds','targetUnitIds','evidence'},'strict_review_issue_fields');explanation(row['evidence'])
        issues.append({k:v for k,v in row.items() if k!='evidence'}|{'evidenceRefs':[evidence_ref]})
    return dict(reviewVerdict=result['reviewVerdict'],checks=checks,issues=issues,
        coverage=dict(expectedUnitIds=manifest['sourceUnitIds'],assessedUnitIds=result['assessedUnitIds'],unassessedUnitIds=result['unassessedUnitIds']))


def _review_receipt_base(prepared,manifest,inputs,attempt_number):
    identity=c.canonical_sha256([manifest['candidateId'],manifest['revisionId'],prepared['workUnitId'],attempt_number])[:32]
    return {**common_identity(prepared,manifest['candidateId'],manifest['revisionId']),
        'schemaVersion':'sermon-review-receipt-v1','reviewId':'review-'+identity,'reviewAttemptId':'review-attempt-'+identity,
        'reviewedArtifactSha256':manifest['artifactSha256'],'rubricSha256':c.canonical_sha256(prepared['rubric']),
        'reviewerInputManifestSha256':c.canonical_sha256(inputs),'reviewMode':'strict_verifier',
        'reviewerModelRequested':prepared['policy']['reviewer']['model'],
        'reviewerPromptVersion':prepared['policy']['reviewer']['promptVersion'],'createdAt':utc()}


def _failed_review(prepared,manifest,inputs,output,attempt_number,error):
    # No observed transport identity means no model receipt can be manufactured.
    call,_=c.read_snapshot(output.with_suffix('.call.json'))
    raw=None
    try:
        raw,_=c.read_snapshot(output.with_suffix('.raw.json'))
    except (OSError,ValueError):pass
    returned=isinstance(raw,dict) and isinstance(raw.get('response'),dict)
    response=raw['response'] if returned else {}
    model=accounting._label(response.get('model'),None);provider_id=accounting._label(response.get('id'),None)
    failure={'schemaVersion':'sermon-strict-review-execution-failure-v1',
        'reasonCode':'invalid_review_response' if returned else 'transport_outcome_unknown',
        'errorType':accounting._label(type(error).__name__)}
    evidence_path=output.with_suffix('.failure.json');save_once(evidence_path,failure)
    accounting.record_log('rqc_review_execution',fields={'status':'failed' if returned else 'outcome_unknown','reasonCode':failure['reasonCode']})
    return {**_review_receipt_base(prepared,manifest,inputs,attempt_number),
        'modelCallId':label(call['modelCallId']),'reviewerModelActual':model,'providerResponseId':provider_id,
        'executionStatus':'failed' if returned else 'outcome_unknown','reviewVerdict':'not_assessed',
        'checks':[],'issues':[],
        'coverage':dict(expectedUnitIds=manifest['sourceUnitIds'],assessedUnitIds=[],unassessedUnitIds=manifest['sourceUnitIds']),
        'evidenceRefs':[reference('review-execution-failure',evidence_path.read_bytes())],
        'missingReasons':{k:'not_observed' if returned else 'outcome_unknown' for k,v in
            [('reviewerModelActual',model),('providerResponseId',provider_id)] if v is None}}


def review(prepared,root,candidate_id,revision_id,api_key,caller,*,cache_only=False,attempt_number=1,depends_on=None,completion_spans=None):
    """Read-only review. A second execution requires D5 reservation by the caller.

    No automatic retry or generator invocation occurs, including on invalid output.
    """
    c.require(type(attempt_number) is int and 1<=attempt_number<=2,'invalid_review_attempt_number')
    with unit_lock(root,prepared,candidate_id,revision_id) as root:
        manifest,manifest_bytes=c.read_snapshot(root/'revision.json');artifact,data=c.read_snapshot(root/'candidate.json')
        c.validate_candidate_artifact(manifest,data)
        generation,generation_bytes=c.read_snapshot(root/'generator.json')
        c.require(reference('generation',generation_bytes)==manifest['generationReceiptRef'] and
            generation.get('result')==artifact and generation.get('model')==prepared['policy']['translator']['model'],
            'review_generation_binding_changed')
        for key,value in common_identity(prepared,candidate_id,revision_id).items():c.require(manifest[key]==value,'review_current_identity_changed')
        for kind,key in [('englishSource','sourcePackageBytesSha256'),('anchor','anchorBytesSha256'),('policy','policyBytesSha256')]:
            c.require(c.bytes_sha256(prepared['bytes'][kind])==manifest[key],'review_source_bytes_changed')
        inputs=input_manifest(prepared,manifest,data);c.validate_contract(inputs);save_once(root/'review-input.json',inputs)
        suffix='' if attempt_number==1 else '-'+str(attempt_number)
        receipt_path=root/('review-receipt'+suffix+'.json')
        with profile.context(workUnitId=prepared['workUnitId'],revisionId=revision_id,role='quality_review'):
            if receipt_path.exists():
                with accounting.stage('rqc.review_receipt_cache',depends_on=depends_on,cache_hit=True,executor_type='deterministic_program') as cached_span:
                    receipt,_=c.read_snapshot(receipt_path);c.validate_review_binding(receipt,manifest,prepared['rubric'],inputs)
                    observation.record(receipt)
                if completion_spans is not None:completion_spans.append(cached_span)
                return receipt
            output=root/('reviewer'+suffix+'.json');cached=output.exists() or output.with_suffix('.raw.json').exists()
            error=None;result=None
            try:
                with accounting.stage('rqc.review',depends_on=depends_on,cache_hit=cached,
                                      executor_type='deterministic_program' if cached else 'production_model') as review_span:
                    result=call_model(prepared,'reviewer',prompt(prepared,'reviewer',candidate=artifact,input_manifest=inputs),
                        output,api_key,caller,cache_only=cache_only,attempt_number=attempt_number)
            except accounting.AccountingWriteError:raise
            except Exception as exc:
                if getattr(exc,'sermon_logging_failed',False):raise
                error=exc
            with accounting.stage('rqc.review_receipt',depends_on=[review_span],executor_type='deterministic_program') as receipt_span:
                c.require(c.read_snapshot(root/'candidate.json')[1]==data and c.read_snapshot(root/'revision.json')[1]==manifest_bytes,'candidate_changed_during_review')
                receipt=None
                if error is None:
                    try:
                        raw=require_call_binding(output,result)
                        model_call=raw.get('accounting',{}).get('modelCallId')
                        c.require(model_call is not None,'strict_review_call_identity_missing')
                        c.require(result['requestId']!=generation.get('requestId'),'review_reuses_generator_response_identity')
                        receipt={**_review_receipt_base(prepared,manifest,inputs,attempt_number),
                            'reviewerModelActual':result['model'],'modelCallId':model_call,
                            'providerResponseId':result['requestId'],'executionStatus':'succeeded',
                            'evidenceRefs':[reference('review-result',output.read_bytes())],'missingReasons':{},
                            **review_result(result['result'],manifest,reference('review-result',output.read_bytes()))}
                        receipt['receiptSha256']=c.receipt_sha256(receipt)
                        c.validate_review_binding(receipt,manifest,prepared['rubric'],inputs)
                    except (ValueError,TypeError,KeyError) as exc:error=exc
                if error is not None:
                    receipt=_failed_review(prepared,manifest,inputs,output,attempt_number,error)
                    receipt['receiptSha256']=c.receipt_sha256(receipt)
                    c.validate_review_binding(receipt,manifest,prepared['rubric'],inputs)
                save_once(receipt_path,receipt);observation.record(receipt)
            if completion_spans is not None:completion_spans.append(receipt_span)
            return receipt

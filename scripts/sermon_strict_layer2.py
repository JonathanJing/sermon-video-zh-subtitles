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


def prepare(source_bytes,anchor_bytes,policy_bytes,rubric_bytes,group,*,request_limits=None,diagnostic_context=None):
    source,anchor,policy,rubric=[c.decode_json(b) for b in (source_bytes,anchor_bytes,policy_bytes,rubric_bytes)]
    if diagnostic_context is None:
        producer.validate_source_for_translation(source,anchor)
    else:
        from scripts.sermon_diagnostic_context import validate_source
        validate_source(source,anchor,diagnostic_context)
    identity=policies.validate_strict_policy(policy,rubric)
    policies.validate_strict_source_scope(policy,rubric,source,anchor)
    if diagnostic_context is None:
        c.require(identity['productionPolicyReady'],'strict_policy_not_ready')
    else:
        from scripts.sermon_diagnostic_context import require_policy_ready
        require_policy_ready(identity,diagnostic_context)
    c.require(type(group) is dict and set(group)=={'translationGroupId','sourceUnitIds'},'invalid_strict_group')
    label(group['translationGroupId']);unit=label('l2.'+policy['targetLocale']+'.'+group['translationGroupId'])
    # Every supported candidate has at most 64 utterances, hence a four-digit
    # suffix. Reject an impossible D1 target ID before any model work is started.
    c.require(len(unit+'.utterance.0001')<=100,'invalid_strict_target_unit_label')
    ids=group['sourceUnitIds'];all_ids=[u['sourceUnitId'] for u in anchor['sourceUnits']]
    c.require(type(ids) is list and 1<=len(ids)<=64 and len(set(ids))==len(ids) and
              all(x in all_ids for x in ids) and sorted(ids,key=all_ids.index)==ids,'invalid_strict_source_group')
    first,last=all_ids.index(ids[0]),all_ids.index(ids[-1])
    c.require(all_ids[first:last+1]==ids,'noncontiguous_strict_group')
    units=[dict(sourceUnitId=u['sourceUnitId'],english=u['english']) for u in anchor['sourceUnits']]
    context={'before':units[max(0,first-3):first],'after':units[last+1:last+3]}
    result = {'source':source,'anchor':anchor,'policy':policy,'rubric':rubric,'group':copy.deepcopy(group),'workUnitId':unit,
        'units':units[first:last+1],'context':context,
        'bytes':dict(englishSource=source_bytes,anchor=anchor_bytes,policy=policy_bytes,rubric=rubric_bytes,context=material_bytes(context))}
    if request_limits is not None:
        from scripts.sermon_provider_limits import validate_request_limits
        result['requestLimits'] = validate_request_limits(request_limits)
    if diagnostic_context is not None:
        from scripts.sermon_diagnostic_context import validate_context
        result['diagnosticContext'] = validate_context(diagnostic_context)
    return result


@contextmanager
def unit_lock(root,prepared,candidate_id,revision_id):
    c.require(profile.current() is not None,'strict_requires_accounting_profile')
    label(candidate_id);label(revision_id)
    expected=prepare(*(prepared['bytes'][k] for k in ('englishSource','anchor','policy','rubric')),prepared['group'],request_limits=prepared.get('requestLimits'),diagnostic_context=prepared.get('diagnosticContext'))
    c.require(prepared==expected,'strict_prepared_inputs_changed')
    root=_safe_path(root)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    identity={'candidateId':candidate_id,'revisionId':revision_id,'workUnitId':prepared['workUnitId'],
              'sourcePackageSha256':c.canonical_sha256(prepared['source']),'policySha256':c.canonical_sha256(prepared['policy'])}
    # One caller-supplied revision directory; identity never changes its lock path.
    with jobs._lock(root/'.admission',jobs._digest({'scope':'strict_revision'})) as (_,fd,held):
        c.require(held,'strict_revision_busy')
        save_once(root/'strict-identity.json',identity)
        if 'requestLimits' in prepared:
            save_once(root/'request-limits.json',prepared['requestLimits'])
        else:
            c.require(not (root/'request-limits.json').exists(),'strict_request_limits_changed')
        if 'diagnosticContext' in prepared:
            save_once(root/'diagnostic-context.json',prepared['diagnosticContext'])
        else:
            c.require(not (root/'diagnostic-context.json').exists(),'strict_diagnostic_context_changed')
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


def validate_repair(prepared,candidate_id,revision_id,repair):
    """Validate a fixed one-group content revision before any transport.

    This proves evidence/lineage, never budget or execution authority. D5 must
    reserve against the pinned shared ledger before invoking this adapter.
    """
    from scripts.sermon_repair_planning import CONTENT_FAILURES
    c.require(type(repair) is dict and set(repair)=={'parentRevision','parentCandidateBytes','plan',
        'triggerReview','inputManifest','sidecars','priorRevisions','priorRepairs'},'invalid_strict_repair_inputs')
    parent,plan,review,inputs=[repair[k] for k in ('parentRevision','plan','triggerReview','inputManifest')]
    c.validate_candidate_artifact(parent,repair['parentCandidateBytes'])
    c.validate_review_binding(review,parent,prepared['rubric'],inputs)
    c.validate_repair_binding(plan,review,parent)
    c.require(set(plan['affectedWorkUnitIds'])==set(parent['workUnitIds']),'strict_repair_scope_changed')
    for name,key in [('englishSource','sourcePackageBytesSha256'),('anchor','anchorBytesSha256'),('policy','policyBytesSha256')]:
        c.require(c.bytes_sha256(prepared['bytes'][name])==parent[key],'strict_repair_source_bytes_changed')
    c.require(plan['repairAction']=='repair_translation' and plan['toRevisionId']==revision_id and
        parent['candidateId']==candidate_id and parent['revisionNumber']<3,'strict_repair_revision_limit_or_identity')
    c.require({i['reasonCode'] for i in review['issues']}<=CONTENT_FAILURES,'strict_repair_requires_content_findings')
    c.require(inputs==input_manifest(prepared,parent,repair['parentCandidateBytes']),'strict_repair_input_changed')
    for key,value in common_identity(prepared,candidate_id,parent['revisionId']).items():
        c.require(parent[key]==value,'strict_repair_current_identity_changed')
    history,plans=repair['priorRevisions'],repair['priorRepairs']
    c.require(type(history) is list and type(plans) is list and len(history)==len(plans)==parent['revisionNumber']-1,
        'strict_repair_history_missing')
    chain=history+[parent]
    for i,revision in enumerate(chain):
        c.validate_revision_lineage(revision,chain[i-1] if i else None,plans[i-1] if i else None)
    refs=[plan[k] for k in ('constraintsRef','budgetRef','dependencyClosureRef')]
    c.require(type(repair['sidecars']) is dict and set(repair['sidecars'])=={r['artifactId'] for r in refs},'strict_repair_sidecars_missing')
    for ref in refs:
        data=repair['sidecars'][ref['artifactId']]
        c.require(reference(ref['artifactId'],data)==ref and c.canonical_bytes(c.decode_json(data))==data,
            'strict_repair_sidecar_changed')
    return repair


def generation_prompt(prepared,repair=None):
    request=prompt(prepared,'translator')
    if repair is not None:
        request['instruction']+=' Repair only this group using the bound failure findings. Preserve the frozen source and policy; never approve your output.'
        request['input'].update(parentCandidate=c.decode_json(repair['parentCandidateBytes']),
            repairPlanId=repair['plan']['repairPlanId'],reasonCodes=repair['plan']['reasonCodes'],
            failedChecks=repair['triggerReview']['checks'],issues=repair['triggerReview']['issues'])
    return request


def save_repair(root,repair):
    from scripts import sermon_trace_artifacts as artifacts
    for key,name in [('parentRevision','parent-revision'),('plan','repair-plan'),
                     ('triggerReview','trigger-review'),('inputManifest','repair-input')]:
        save_once(root/(name+'.json'),repair[key])
    save_once(root/'repair-sidecars.json',{key:c.decode_json(data) for key,data in repair['sidecars'].items()})
    save_once(root/'repair-history.json',{key:repair[key] for key in ('priorRevisions','priorRepairs')})
    path=root/'parent-candidate.json';data=repair['parentCandidateBytes']
    if path.exists():c.require(c.read_snapshot(path)[1]==data,'strict_repair_parent_bytes_changed')
    else:artifacts.write(path,data.decode('utf-8'))


def load_repair(root):
    root=Path(root)
    if not (root/'repair-plan.json').exists():return None
    result={key:c.read_snapshot(root/(name+'.json'))[0] for key,name in
        [('parentRevision','parent-revision'),('plan','repair-plan'),('triggerReview','trigger-review'),('inputManifest','repair-input')]}
    result['parentCandidateBytes']=c.read_snapshot(root/'parent-candidate.json')[1]
    result['sidecars']={key:c.canonical_bytes(value) for key,value in c.read_snapshot(root/'repair-sidecars.json')[0].items()}
    result.update(c.read_snapshot(root/'repair-history.json')[0])
    return result


def _payload(prepared,role,request):
    return shared.model_payload(role,request,prepared['policy'],prepared.get('requestLimits'))


def _transport_rejection(output,payload_sha256):
    path=output.with_suffix('.rejection.json')
    if not path.exists():return None
    from scripts.sermon_pipeline import KNOWN_REQUEST_REJECTIONS
    evidence,_=c.read_snapshot(path)
    call,_=c.read_snapshot(output.with_suffix('.call.json'))
    started,_=c.read_snapshot(output.with_suffix('.started.json'))
    c.require(type(evidence) is dict and set(evidence)=={'schemaVersion','modelCallId','payloadSha256',
        'httpStatus','executionStatus','reasonCode'},'invalid_strict_transport_rejection')
    c.require(evidence['schemaVersion']=='sermon-strict-transport-rejection-v1' and
        type(evidence['httpStatus']) is int and evidence['httpStatus'] in KNOWN_REQUEST_REJECTIONS and
        evidence['executionStatus']=='failed' and evidence['reasonCode']=='http_request_rejected',
        'invalid_strict_transport_rejection')
    c.require(evidence['modelCallId']==label(call['modelCallId']) and
        evidence['payloadSha256']==payload_sha256==started.get('payloadSha256') and
        started.get('status')=='started_response_unconfirmed','strict_transport_rejection_binding_changed')
    c.require(not output.exists() and not output.with_suffix('.raw.json').exists(),
        'conflicting_strict_transport_evidence')
    return evidence


def call_model(prepared,role,request,output,api_key,caller,*,attempt_number=1,cache_only=False):
    """Shared cache path; the transport must save response before logging finish."""
    payload_sha256=policies.canonical_sha256(_payload(prepared,role,request))
    rejection=_transport_rejection(output,payload_sha256)
    if rejection is not None:
        from scripts.sermon_pipeline import TransportRejection
        raise TransportRejection(rejection['httpStatus'])
    def persist_response(response,model_call_id,elapsed):
        save_once(output.with_suffix('.raw.json'),dict(payloadSha256=payload_sha256,response=response,
            accounting=dict(modelCallId=label(model_call_id),elapsedSeconds=elapsed)))
    def request_started(model_call_id):
        save_once(output.with_suffix('.call.json'),{'modelCallId':label(model_call_id)})
    def request_rejected(error,model_call_id):
        from scripts.sermon_pipeline import TransportRejection
        c.require(type(error) is TransportRejection,'invalid_strict_transport_rejection')
        try:
            save_once(output.with_suffix('.rejection.json'),{
                'schemaVersion':'sermon-strict-transport-rejection-v1','modelCallId':label(model_call_id),
                'payloadSha256':payload_sha256,'httpStatus':error.http_status,
                'executionStatus':'failed','reasonCode':'http_request_rejected'})
            _transport_rejection(output,payload_sha256)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            raise accounting.AccountingWriteError('strict_transport_rejection_evidence_failed') from exc
    persist_response.request_started=request_started
    persist_response.request_rejected=request_rejected
    with profile.context(logicalCallId=role+'.'+c.canonical_sha256([prepared['workUnitId'],(profile.current() or {}).get('revisionId')])[:32],attemptNumber=attempt_number):
        return shared._model_call(role,request,prepared['policy'],output,api_key,caller,
                                  cache_only=cache_only,response_observer=persist_response,
                                  request_limits=prepared.get('requestLimits'))



def require_call_binding(output,saved):
    raw,_=c.read_snapshot(output.with_suffix('.raw.json'))
    call,_=c.read_snapshot(output.with_suffix('.call.json'))
    response=raw.get('response',{})
    c.require(raw.get('payloadSha256')==saved['payloadSha256'] and
        response.get('id')==saved['requestId'] and response.get('model')==saved['model'] and
        raw.get('accounting',{}).get('modelCallId')==call.get('modelCallId'), 'strict_raw_receipt_binding_changed')
    try:content=c.decode_json(shared.completed_response_content(response,saved['model'],'strict cached').encode('utf-8'))
    except (KeyError,TypeError,IndexError,ValueError) as exc:raise c.ContractError('invalid_strict_raw_content') from exc
    c.require(content==saved['result'],'strict_raw_content_changed')
    return raw


def generate(prepared,root,candidate_id,revision_id,api_key,caller,*,cache_only=False,depends_on=None,completion_spans=None,repair=None):
    """Freeze one immutable revision; D5 separately reserves every new call."""
    with unit_lock(root,prepared,candidate_id,revision_id) as root:
        if repair is not None:
            validate_repair(prepared,candidate_id,revision_id,repair);save_repair(root,repair)
        else:c.require(load_repair(root) is None,'strict_repair_context_required')
        with profile.context(workUnitId=prepared['workUnitId'],revisionId=revision_id,role='generation'):
            out=root/'generator.json';cached=out.exists() or out.with_suffix('.raw.json').exists() or out.with_suffix('.rejection.json').exists()
            with accounting.stage('rqc.generation',depends_on=depends_on,cache_hit=cached,
                                  executor_type='deterministic_program' if cached else 'production_model') as model_span:
                result=call_model(prepared,'translator',generation_prompt(prepared,repair),out,api_key,caller,cache_only=cache_only)
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
                if repair is not None:
                    manifest.update(parentRevisionId=repair['parentRevision']['revisionId'],repairPlanId=repair['plan']['repairPlanId'],
                        revisionNumber=repair['parentRevision']['revisionNumber']+1)
                    c.validate_revision_lineage(manifest,repair['parentRevision'],repair['plan'])
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


def review_failure_evidence_id(kind, attempt_number):
    """Keep both bounded executions' different immutable evidence addressable."""
    c.require(kind in {'review-execution-failure', 'review-transport-rejection'} and
        type(attempt_number) is int and 1 <= attempt_number <= 2, 'invalid_review_evidence_identity')
    return kind + ('' if attempt_number == 1 else '-2')


def _failed_review(prepared,manifest,inputs,output,attempt_number,error):
    # No observed transport identity means no model receipt can be manufactured.
    call,_=c.read_snapshot(output.with_suffix('.call.json'))
    candidate,_=c.read_snapshot(output.parent/'candidate.json')
    payload_sha256=policies.canonical_sha256(_payload(prepared,'reviewer',
        prompt(prepared,'reviewer',candidate=candidate,input_manifest=inputs)))
    rejection=_transport_rejection(output,payload_sha256)
    raw=None
    try:
        raw,_=c.read_snapshot(output.with_suffix('.raw.json'))
    except (OSError,ValueError):pass
    returned=isinstance(raw,dict) and isinstance(raw.get('response'),dict)
    response=raw['response'] if returned else {}
    model=accounting._label(response.get('model'),None);provider_id=accounting._label(response.get('id'),None)
    known=returned or rejection is not None
    failure={'schemaVersion':'sermon-strict-review-execution-failure-v1',
        'reasonCode':'http_request_rejected' if rejection is not None else
                     'invalid_review_response' if returned else 'transport_outcome_unknown',
        'errorType':accounting._label(type(error).__name__)}
    evidence_path=output.with_suffix('.failure.json');save_once(evidence_path,failure)
    accounting.record_log('rqc_review_execution',fields={'status':'failed' if known else 'outcome_unknown','reasonCode':failure['reasonCode']})
    return {**_review_receipt_base(prepared,manifest,inputs,attempt_number),
        'modelCallId':label(call['modelCallId']),'reviewerModelActual':model,'providerResponseId':provider_id,
        'executionStatus':'failed' if known else 'outcome_unknown','reviewVerdict':'not_assessed',
        'checks':[],'issues':[],
        'coverage':dict(expectedUnitIds=manifest['sourceUnitIds'],assessedUnitIds=[],unassessedUnitIds=manifest['sourceUnitIds']),
        'evidenceRefs':[reference(review_failure_evidence_id('review-execution-failure',attempt_number),evidence_path.read_bytes())]+
            ([reference(review_failure_evidence_id('review-transport-rejection',attempt_number),output.with_suffix('.rejection.json').read_bytes())] if rejection else []),
        'missingReasons':{k:'not_observed' if known else 'outcome_unknown' for k,v in
            [('reviewerModelActual',model),('providerResponseId',provider_id)] if v is None}}


def _validate_cached_review_evidence(receipt,manifest,output):
    """Reopen the immutable reviewer evidence before trusting a cached receipt."""
    c.require(output.stem in {'reviewer','reviewer-2'},'invalid_review_evidence_identity')
    attempt_number=1 if output.stem=='reviewer' else 2
    call,_=c.read_snapshot(output.with_suffix('.call.json'))
    c.require(call.get('modelCallId')==receipt['modelCallId'],'strict_review_call_identity_changed')
    if receipt['executionStatus']=='succeeded':
        result,_=c.read_snapshot(output)
        raw=require_call_binding(output,result)
        model_call=raw.get('accounting',{}).get('modelCallId')
        evidence=reference('review-result',output.read_bytes())
        c.require(receipt['evidenceRefs']==[evidence] and
            receipt['modelCallId']==model_call and
            receipt['providerResponseId']==result.get('requestId') and
            receipt['reviewerModelActual']==result.get('model'),
            'strict_review_evidence_binding_changed')
        expected=review_result(result['result'],manifest,evidence)
        for key,value in expected.items():
            c.require(receipt[key]==value,'strict_review_result_binding_changed')
    else:
        failure_path=output.with_suffix('.failure.json')
        failure_bytes=failure_path.read_bytes()
        expected=[reference(review_failure_evidence_id('review-execution-failure',attempt_number),failure_bytes)]
        rejection_path=output.with_suffix('.rejection.json')
        if rejection_path.exists():
            expected.append(reference(review_failure_evidence_id('review-transport-rejection',attempt_number),rejection_path.read_bytes()))
        c.require(receipt['evidenceRefs']==expected,'strict_review_failure_evidence_changed')


def review(prepared,root,candidate_id,revision_id,api_key,caller,*,cache_only=False,attempt_number=1,depends_on=None,completion_spans=None):
    """Read-only review. A second execution requires D5 reservation by the caller.

    No automatic retry or generator invocation occurs, including on invalid output.
    """
    c.require(type(attempt_number) is int and 1<=attempt_number<=2,'invalid_review_attempt_number')
    with unit_lock(root,prepared,candidate_id,revision_id) as root:
        manifest,manifest_bytes=c.read_snapshot(root/'revision.json');artifact,data=c.read_snapshot(root/'candidate.json')
        c.validate_candidate_artifact(manifest,data)
        repair=load_repair(root)
        if repair is not None:validate_repair(prepared,candidate_id,revision_id,repair)
        c.validate_revision_lineage(manifest,repair['parentRevision'] if repair else None,repair['plan'] if repair else None)
        generation,generation_bytes=c.read_snapshot(root/'generator.json')
        c.require(reference('generation',generation_bytes)==manifest['generationReceiptRef'] and
            generation.get('result')==artifact and generation.get('model')==prepared['policy']['translator']['model'],
            'review_generation_binding_changed')
        c.require(generation['payloadSha256']==c.canonical_sha256(_payload(prepared,'translator',generation_prompt(prepared,repair))),
            'review_generation_payload_changed')
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
                    _validate_cached_review_evidence(receipt,manifest,root/('reviewer'+suffix+'.json'))
                    observation.record(receipt)
                if completion_spans is not None:completion_spans.append(cached_span)
                return receipt
            output=root/('reviewer'+suffix+'.json');cached=output.exists() or output.with_suffix('.raw.json').exists() or output.with_suffix('.rejection.json').exists()
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

"""CAS state and a single pump using sermon_workflow_jobs durable primitives.

A process exit never grants package validity. Dispatch intents survive worker
loss, and only a recorded response can reconcile them without another call.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_unified import contracts as c
from scripts.sermon_unified import adapters

_OWNER_TOKEN = object()

DEFAULT_ROOT = c.ROOT / 'artifacts' / 'unified-production'


def now():
    return datetime.now(timezone.utc).isoformat()


def run_key(m):
    return c.digest({'jobRoot':m['jobRoot'],'productionRunId':m['productionRunId']})


def folder(root, key):
    return jobs._paths(Path(root), key)[1]


def load(root, key):
    # Read-only. Do not use inspect_job, which can reconcile process state.
    p = folder(root,key) / 'unified-state.json'
    if not p.is_file():
        raise c.ContractError('run_not_found',9)
    value = c.read(p)
    if value.get('runKey') != key:
        raise c.ContractError('state_identity_changed',7)
    return value


@contextmanager
def locked(root, key):
    deadline=time.monotonic()+10
    while True:
        with jobs._lock(Path(root), c.digest({'unifiedStateLock':key})) as (_, _, held):
            if held:
                yield
                return
        if time.monotonic()>=deadline:
            raise c.ContractError('state_busy',7)
        time.sleep(0.02)


def save(root, key, state, expected=None):
    with locked(root,key):
        path=folder(root,key)
        path.mkdir(parents=True,exist_ok=True)
        previous=load(root,key) if (path/'unified-state.json').exists() else None
        if previous is not None and previous['stateRevision'] != expected:
            raise c.ContractError('state_revision_conflict',7)
        state['stateRevision']=(previous['stateRevision']+1 if previous else 1)
        state['updatedAt']=now()
        jobs._persist(path/'unified-state.json',state)
    return state


def event(m,state,step,event_type, *, predecessor=None):
    eid='evt-'+uuid.uuid4().hex
    value={'schemaVersion':'sermon-unified-production-event-v1','eventId':eid,
           'eventType':event_type,'time':now(),'productionRunId':m['productionRunId'],
           'runRevision':m['runRevision'],'traceId':state['traceId'],
           'attemptId':state['attemptId'],'locale':step.get('locale'),
           'layer':c.layer(step['stageId'],step.get('reviewKind')),'stageId':step['stageId'],
           'jobId':c.digest(c.job_identity(m,step)),'operationId':step['id'],
           'parentEventId':None,'causedBy':predecessor,'artifactId':None,'receiptId':None,
           'codeHash':m['executionAdmission']['closureSha256'],
           'hostId':c.digest({'host':os.uname().nodename})}
    c.validate(value,'sermon-unified-production-event-v1')
    state['events'].append(value)
    return eid


def submit(m,base,root,expected_hash,expected_revision=None,*,_owner_token=None,_continuation_receipt=None):
    blockers=c.admit(m,base)
    if blockers:
        raise c.ContractError(blockers[0])
    if expected_hash != c.plan_hash(m):
        raise c.ContractError('plan_hash_conflict',7)
    for step in m['steps']:
        adapters.inspect_step(m,base,step,ready=False)
    key=run_key(m)
    with locked(root,key):
        target=folder(root,key)
        current=None
        if (target/'unified-state.json').exists():
            current=load(root,key)
            if current['planHash'] == expected_hash:
                return current
            if expected_revision!=current['stateRevision'] or m['runRevision']!=current['manifest']['runRevision']+1:
                raise c.ContractError('revision_cas_required',7)
            if (current['admission']!='closed' and _owner_token is not _OWNER_TOKEN) or any(x['process'] in ('running','waiting_reconciliation') for x in current['steps'].values()):
                raise c.ContractError('drain_and_reconcile_required',6)
            if _owner_token is not _OWNER_TOKEN and current.get('ownerJobId') and jobs.peek_job(Path(root)/'owners',current['ownerJobId'])['status'] in jobs.ACTIVE:
                raise c.ContractError('durable_owner_still_active',7)
        target.mkdir(parents=True,exist_ok=True)
        # Freeze absolute locators, while planHash excludes local paths.
        frozen=json.loads(json.dumps(m))
        for ref in frozen['bindings'].values():
            ref['path']=str((Path(base)/ref['path']).absolute())
        state={'schemaVersion':'sermon-unified-state-v1','runKey':key,'manifest':frozen,
               'planHash':expected_hash,'manifestSha256':c.digest(frozen),'stateRevision':1,
               'traceId':'trace-'+uuid.uuid4().hex,'attemptId':'attempt-'+uuid.uuid4().hex,
               'admission':'open','scheduler':'canonical','cancelRequested':False,'ownerEpoch':0,'createdAt':now(),
               'updatedAt':now(),'steps':{},'events':[],'reviews':{},'owner':None}
        for step in m['steps']:
            state['steps'][step['id']]={'process':'not_started','artifact':'not_started',
                                      'review':'not_required','publication':'not_started','device':'not_checked'}
        if current is not None:
            old=current['manifest'];old_steps={x['id']:x for x in old['steps']}
            state['stateRevision']=current['stateRevision']+1
            state['revisionHistory']=current.get('revisionHistory',[])+[{
                'runRevision':old['runRevision'],'planHash':current['planHash'],
                'stateSha256':c.digest(current),'attemptId':current['attemptId']}]
            jobs._persist(target/('revision-'+str(old['runRevision'])+'.json'),current)
            # Each reused row keeps its original receipt/event identity. A
            # changed dependency invalidates its entire downstream closure.
            reused=[]
            state['events']=current['events'][:]
            for step in m['steps']:
                sid=step['id'];prior=old_steps.get(sid)
                reuse_started=now();reuse_clock=time.monotonic()
                if (prior is not None and current['steps'][sid]['process']=='succeeded'
                    and reuse_identity(old,prior)==reuse_identity(frozen,step)
                    and all(dep in reused for dep in step['dependsOn'])
                    and reusable_evidence(root,key,current,prior)):
                    state['steps'][sid]=dict(current['steps'][sid],reusedFromRevision=current['steps'][sid].get('reusedFromRevision',old['runRevision']))
                    row=state['steps'][sid]
                    row['originComputeSeconds']=row.get('originComputeSeconds',row.get('computeSeconds'))
                    row.update(readyAt=reuse_started,enqueuedAt=reuse_started,startedAt=reuse_started,
                               completedAt=now(),computeSeconds=time.monotonic()-reuse_clock,cacheValidation=True)
                    row['completionEventId']=event(m,state,step,'cache.reused',predecessor=row.get('completionEventId'))
                    reused.append(sid)
            state['reviews']={k:v for k,v in current['reviews'].items() if k in reused}
            state['historicalReservedMicroUsd']=current.get('historicalReservedMicroUsd',0)+sum(row.get('reservedMicroUsd',0) for sid,row in current['steps'].items() if sid not in reused)
            state['historicalBudgetAuthorities']=sorted(set(current.get('historicalBudgetAuthorities',[])) | {row['budgetAuthoritySha256'] for row in current['steps'].values() if row.get('budgetAuthoritySha256')})
            state['continuationEvidence']=current.get('continuationEvidence',{})
            if _owner_token is _OWNER_TOKEN:
                state['ownerJobId']=current.get('ownerJobId');state['ownerEpoch']=current['ownerEpoch']
            state['revisionReuse']={'reused':reused,'changed':[s['id'] for s in m['steps'] if s['id'] not in reused]}
        if _owner_token is _OWNER_TOKEN:
            state['continuationReceipt']=_continuation_receipt
        jobs._persist(target/'unified-state.json',state)
        return state


def reusable_evidence(root,key,state,step):
    row=state['steps'][step['id']];m=state['manifest']
    try:
        if step['adapter']=='review.gate' and step.get('reviewKind')!='window':
            receipt=state['reviews'][step['id']]
            path=folder(root,key)/('review-'+receipt['originalSha256']+'.json')
            if c.file_sha(path)!=receipt['storedSha256']:
                return False
            from scripts.sermon_unified_reviews import validate_review
            config=c.read(adapters.config_path(m,'/',step))
            inputs={name:c.binding(m,'/',reference) for name,reference in config['inputs'].items()}
            adapters.inspect_step(m,'/',step)
            validate_review('meditation' if step['reviewKind']=='reflection' else step['reviewKind'],path,
                inputs=inputs,expected_source=m['source'],expected_locale=step.get('locale'))
        else:
            # A reused row may originate more than one revision ago.
            origin=m
            if row.get('reusedFromRevision'):
                origin=c.read(folder(root,key)/('revision-'+str(row['reusedFromRevision'])+'.json'))['manifest']
            original_step=next(s for s in origin['steps'] if s['id']==step['id'])
            path=folder(root,key)/('response-'+c.digest(c.job_identity(origin,original_step))+'.json')
            if c.file_sha(path)!=row['responseSha256']:
                return False
            document=c.read(path)
            if document['identity']!=c.job_identity(origin,original_step) or not valid_success(step,document['result'],m):
                return False
            adapters.verify_result(m,'/',step,document['result'])
            if step['adapter']=='app.delivery' and document['result'].get('validatedEndpoints'):
                return False
        return True
    except (OSError,ValueError,KeyError,TypeError,StopIteration):
        return False


def reuse_identity(m,step):
    names={step[k] for k in ('configuration','artifact','budgetAuthorization') if k in step}
    # Bind precisely the review targets. Adding an unrelated locale must not
    # invalidate an unchanged human approval. Window evidence is in source.
    if step['adapter']=='review.gate' and step.get('reviewKind')!='window':
        config=c.read(c.binding(m,'/',step['configuration']))
        names.update(config['inputs'].values())
    return c.digest({'source':m['source'],'step':step,'transport':m['transport'],
        'code':m['executionAdmission'],'content':m['content'],
        'policy':[p for p in m['policies'] if p['locale']==step.get('locale')],
        'bindings':{k:m['bindings'][k]['sha256'] for k in names}})


def valid_success(step,result,m):
    if step['adapter']=='media.verify':
        return result.get('kind')=='media_identity' and result.get('artifact')=='verified' and result.get('mediaSha256')==m['source']['mediaSha256']
    if step['adapter']=='fixture.replay':
        return m['transport']=='fixture' and result.get('fixtureOnly') is True and result.get('productionEligible') is False and result.get('fixtureSetId')==m['fixtureSetId']
    if step['adapter']=='review.gate' and step.get('reviewKind')=='window':
        return result.get('kind')=='window_review' and result.get('receiptSha256')==m['source']['window'].get('approvalReceiptSha256') and result.get('review')=='approved'
    if step['adapter']=='study.produce':
        return result.get('kind')=='study_candidate' and result.get('artifact')=='verified' and result.get('review')=='human_pending' and result.get('productionEligible') is False
    if step['adapter']=='source.prepare':
        return (result.get('kind')=='english_source_candidate' and result.get('artifact')=='verified'
                and result.get('review')=='human_pending' and result.get('productionEligible') is False)
    if step['adapter']=='canonical.audio':
        return result.get('artifact')=='verified' and result.get('review')=='human_pending' and result.get('productionEligible') is False
    if step['adapter']=='canonical.layer2':
        return result.get('kind')=='target_language_candidate' and result.get('artifact')=='verified' and result.get('review')=='human_pending'
    if step['adapter']=='app.delivery':
        return result.get('kind')=='app_delivery' and result.get('artifact')=='verified' and result.get('fourProducts')=='validated'
    if step['adapter']=='canonical.inspect':
        return result.get('artifact')=='verified' and step['stageId'] in ('english_source','layer2_admit','layer3_screen')
    return False


RELEASE_REVIEWS=frozenset({'approved','waived'})


def scope_satisfied(state):
    m=state['manifest'];scope=m['activeScope']
    def verified(stage,locale=None,review=False):
        matches=[s for s in m['steps'] if s['stageId']==stage and (locale is None or s.get('locale')==locale)]
        return bool(matches) and all(state['steps'][s['id']]['process']=='succeeded'
            and state['steps'][s['id']].get('artifact')=='verified'
            and (not review or state['steps'][s['id']].get('review') in review) for s in matches)
    if not verified('media_verify'):
        return False
    if scope=='media_verified':
        return True
    if m.get('transport')=='fixture':
        # A fixture result is a software test, never content eligibility.
        return False
    if not any(s['stageId']=='english_source' and s['adapter']=='canonical.inspect'
               and state['steps'][s['id']]['process']=='succeeded'
               and state['steps'][s['id']].get('artifact')=='verified' for s in m['steps']):
        return False
    if scope=='english_ready_for_translation':
        return True
    if not all(verified('layer2_group',locale) for locale in m.get('locales',[])) or not m.get('locales'):
        return False
    if scope=='layer2_machine_candidate':
        return True
    # Translation and listening gates accept a machine quality waiver (Jony,
    # 2026-10-06); study products still require their human approvals.
    if not all(verified('translation_review',loc,RELEASE_REVIEWS) for loc in m['locales']):
        return False
    if scope=='translation_approved':
        return True
    if not all(verified('layer3_screen',loc) for loc in m['locales']):
        return False
    if scope=='audio_screened':
        return True
    if not all(verified('listen_review',loc,RELEASE_REVIEWS) for loc in m['locales']):
        return False
    if scope=='listen_approved':
        return True
    for loc in m['locales']:
        kinds={s.get('reviewKind') for s in m['steps'] if s['stageId']=='study_product' and s.get('locale')==loc
               and state['steps'][s['id']].get('review')=='approved'}
        if kinds!={'outline','reflection'}:
            return False
    if scope=='study_approved':
        return True
    # Endpoint validation receipts are promoted only by the registered delivery
    # adapter, not by a caller's scope label or uploaded pass observation.
    targets={'dev_reader_verified':{'firebase_dev'},'dual_test_end_approved':{'ios_beta','firebase_dev'},
             'dual_production_verified':{'ios_beta','firebase_dev','ios_prod','firebase_prod'}}[scope]
    accepted={(endpoint,locale) for step in m['steps'] if step['adapter']=='app.delivery'
              for endpoint in state['steps'][step['id']].get('validatedEndpoints',[])
              for locale in state['steps'][step['id']].get('validatedLocales',[])}
    return {(endpoint,locale) for endpoint in targets for locale in m['locales']}<=accepted


def active_steps(m):
    limit=c.SCOPES.index(m['activeScope'])
    return [step for step in m['steps'] if c.SCOPES.index(step['scope'])<=limit]


def _project(state):
    m=state['manifest']; rows=[state['steps'][s['id']] for s in active_steps(m)]
    blockers=[]
    if any(x['process']=='waiting_reconciliation' for x in rows):
        outcome='unknown'
    elif state['cancelRequested']:
        outcome='cancelled' if not any(x['process']=='running' for x in rows) else 'running'
    elif any(x['process']=='failed' for x in rows):
        outcome='failed'
    elif any(x['process']=='blocked' for x in rows):
        outcome='blocked'
    elif all(x['process']=='succeeded' for x in rows):
        # A fixture proves machinery, never dual-end publication or human gates.
        if scope_satisfied(state):
            outcome='succeeded'
        else:
            outcome='blocked';blockers.append({'code':'completion_scope_not_verified'})
    elif any(x['process']=='running' for x in rows):
        outcome='running'
    else:
        outcome='pending'
    for step in active_steps(m):
        sid=step['id'];row=state['steps'][sid]
        if row['process'] in ('blocked','waiting_reconciliation','failed') or row.get('reason')=='resource_capacity_busy':
            blockers.append({'code':row.get('reason','stage_incomplete'),'artifactId':sid})
    return outcome,blockers


def continue_owner(root,key):
    state=load(root,key)
    if state.get('scheduler','canonical')=='canonical':
        return start_owner(root,key)
    # The SDK runtime is isolated from the project interpreter. Wake its
    # existing workflow; the same pump/ledger revalidates every resumed step.
    import subprocess
    sdk=c.ROOT/'artifacts/temporal/runtime/venv/bin/python'
    if sdk.is_file():
        try:
            subprocess.run([str(sdk),'-m','scripts.sermon_temporal','client','unified-submit',
                '--state-root',str(Path(root).absolute()),'--run-key',key,'--plan-hash',state['planHash']],
                cwd=c.ROOT,capture_output=True,timeout=20,check=True)
        except (OSError,subprocess.SubprocessError):
            pass  # Accepted evidence remains stored; job.resume can wake later.
    return load(root,key)


def start_owner(root,key):
    state=load(root,key)
    if state.get('scheduler','canonical')!='canonical':
        raise c.ContractError('temporal_owns_run',7)
    outcome,_=_project(state)
    if outcome in ('unknown','succeeded','cancelled'):
        return state
    with locked(root,key):
        state=load(root,key)
        # An existing live owner can continue; never launch a second pump.
        if state.get('ownerJobId'):
            prior=jobs.peek_job(Path(root)/'owners',state['ownerJobId'])
            if prior['status'] in jobs.ACTIVE:
                return state
        if any(row['process']=='running' for row in state['steps'].values()):
            for row in state['steps'].values():
                if row['process']=='running':
                    row.update(process='waiting_reconciliation',reason='owner_lost_after_dispatch')
            state['stateRevision']+=1
            jobs._persist(folder(root,key)/'unified-state.json',state)
            return state
        state['ownerEpoch']+=1
        ident={'unifiedOwner':key,'epoch':state['ownerEpoch'],'planHash':state['planHash']}
        command=[os.sys.executable,str(c.ROOT/'scripts/sermon.py'),'worker','run',
                 '--state-root',str(Path(root).absolute()),'--run-id',key]
        result=jobs.start_job(Path(root)/'owners',ident,command,timeout_seconds=86400)
        state['ownerJobId']=result['jobId'];state['stateRevision']+=1
        jobs._persist(folder(root,key)/'unified-state.json',state)
        return state


def run_owner(root,key):
    """One owner lease covers dispatch and all recipe-driven revisions."""
    with jobs._lock(Path(root), c.digest({'unifiedOwnerLease':key})) as (_, _, held):
        if not held:
            raise c.ContractError('owner_lease_busy',7)
        return _run_owner(root,key)


def _advance_continuation(root,key,state):
    if 'continuationRecipe' not in state['manifest']['bindings']:
        return state,False
    from scripts import sermon_unified_continuation as continuation
    recipe=c.binding(state['manifest'],'/','continuationRecipe')
    prepared=continuation.prepare_next_revision(state,recipe,root)
    if prepared['status']=='ready':
        # Re-materialization rechecks retained upstream receipts and frozen bytes.
        # submit takes the state lock and checks this exact revision again.
        next_state=submit(prepared['manifest'],'/',root,prepared['planHash'],
                          prepared['expectedStateRevision'],_owner_token=_OWNER_TOKEN,
                          _continuation_receipt={'path':prepared['receiptPath'],'sha256':prepared['receiptSha256']})
        return next_state,True
    if prepared['reason']=='no_continuation_stage':
        return state,False
    view={k:v for k,v in prepared.items() if k!='manifest'}
    if state.get('continuation')!=view:
        state['continuation']=view
        state=save(root,key,state,state['stateRevision'])
    return state,True


def _run_owner(root,key):
    """Keep the detached program alive across review waits, without chat polling."""
    while True:
        try:
            state=pump(root,key)
        except c.ContractError as exc:
            if exc.code not in ('state_revision_conflict','state_busy'):
                raise
            time.sleep(.05)
            continue
        prior_plan=state['planHash']
        has_continuation=False
        if not state.get('cancelRequested') and not any(row['process'] in ('running','waiting_reconciliation','failed') for row in state['steps'].values()):
            try:
                state,has_continuation=_advance_continuation(root,key,state)
            except c.ContractError as exc:
                if exc.code not in ('state_revision_conflict','state_busy','revision_cas_required'):
                    raise
                time.sleep(.05)
                continue
            if state['planHash']!=prior_plan:
                continue
        outcome,_=_project(state)
        if ((outcome=='succeeded' and not has_continuation) or outcome in ('cancelled','failed','unknown') or state['admission']=='closed'
            or state.get('scheduler','canonical')!='canonical'
            or (not has_continuation and all(state['steps'][step['id']]['process']=='succeeded' for step in active_steps(state['manifest'])))):
            return state
        revision=state['stateRevision']
        deadline=datetime.fromisoformat(state['manifest']['executionWindow']['deadlineAt'])
        resource_retry=time.monotonic()+1
        while True:
            if datetime.now(timezone.utc)>=deadline:
                return state
            time.sleep(.2)
            state=load(root,key)
            if state['stateRevision']!=revision:
                break
            if time.monotonic()>=resource_retry and any(
                    row.get('reason')=='resource_capacity_busy' and row['process']=='not_started'
                    for row in state['steps'].values()):
                # Other runs release shared capacity without mutating this run.
                break


def resource_policy(manifest):
    if 'resourcePolicy' not in manifest['bindings']:
        return None
    from scripts.sermon_unified import resources
    return resources.validate_policy(c.read(c.binding(manifest,'/','resourcePolicy')))


def resource_claim(policy, step):
    """Conservative whole-adapter leases until model leaf slots are connected."""
    adapter=step['adapter']
    if adapter in ('source.prepare','canonical.layer2','study.produce'):
        resource='online_api'
        # A Layer 2 adapter can issue many simultaneous requests internally.
        # Reserve the whole lane, never pretend one adapter is one API call.
        units=policy['capacities'][resource]
    elif adapter=='canonical.audio':
        resource,units='spark_tts',1
    elif adapter=='app.delivery':
        resource,units='publisher',1
    else:
        resource,units='cpu',1
    return resource,max(1,units)


def release_completed_resources(state):
    from scripts.sermon_unified import resources
    for sid,row in state['steps'].items():
        claim=row.get('resourceReservation')
        if not claim or row['process'] not in ('succeeded','blocked','failed') or not row.get('responseSha256'):
            continue
        # Reused successful rows retain their origin broker, even if a later
        # revision changes/removes the resource policy for new work.
        policy=resources.validate_policy(claim['policy'])
        if c.digest(policy)!=claim['policySha256']:
            raise c.ContractError('resource_reservation_policy_changed',7)
        identity=claim['identity']
        if claim['operationId']!=c.digest(identity) or claim['owner']['runKey']!=state['runKey']:
            raise c.ContractError('resource_reservation_identity_changed',7)
        path=folder(claim['stateRoot'],state['runKey'])/('response-'+c.digest(identity)+'.json')
        response=c.read(path)
        if (c.file_sha(path)!=row['responseSha256'] or response.get('identity')!=identity
                or response.get('result',{}).get('status')!=row['process']):
            raise c.ContractError('resource_terminal_receipt_changed',7)
        resources.release(policy,operation_id=claim['operationId'],owner=claim['owner'])


def _prepare_dispatch(root,key,state,step):
    m=state['manifest']
    sid=step['id'];row=state['steps'][sid]
    try:
        adapters.inspect_step(m,'/',step)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        row.update(process='blocked',reason=exc.code if isinstance(exc,c.ContractError) else 'adapter_preflight_failed')
        return save(root,key,state,state['stateRevision']),None
    row['readyAt']=max((state['steps'][d].get('completedAt',state['createdAt']) for d in step['dependsOn']),default=state['createdAt'])
    row.setdefault('enqueuedAt',now())
    # Intent and conservative bound survive any crash before the result.
    reserved=state.get('historicalReservedMicroUsd',0)+sum(r.get('reservedMicroUsd',0) for r in state['steps'].values())
    bound=step.get('maxCostMicroUsd',0)
    authority=step.get('budgetAuthorization')
    if authority:
        authority_sha=m['bindings'][authority]['sha256']
        if authority_sha in state.get('historicalBudgetAuthorities',[]) or any(x.get('budgetAuthoritySha256')==authority_sha for x in state['steps'].values()):
            bound=0
        row['budgetAuthoritySha256']=authority_sha
    if reserved+bound>m['budget']['limitMicroUsd']:
        row.pop('intentSha256',None)
        row.update(process='blocked',reason='budget_exhausted')
        return save(root,key,state,state['stateRevision']),None
    if step['adapter']=='canonical.layer2' and step.get('maxCostMicroUsd',0)<=0:
        row.pop('intentSha256',None)
        row.update(process='blocked',reason='paid_request_bound_required')
        return save(root,key,state,state['stateRevision']),None
    row['reservedMicroUsd']=bound
    policy=resource_policy(m)
    if policy is not None:
        from scripts.sermon_unified import resources
        operation=c.digest(c.job_identity(m,step))
        owner={'runKey':key,'attemptId':state['attemptId']}
        resource,units=resource_claim(policy,step)
        claim={'operationId':operation,'owner':owner,'resource':resource,
               'units':units,'identity':c.job_identity(m,step),
               'policy':policy,'policySha256':c.digest(policy),
               'stateRoot':str(Path(root).absolute())}
        try:
            admitted=resources.reserve(policy,operation_id=operation,owner=owner,
                                       resource=resource,units=units)
        except c.ContractError:
            # A durable reservation can precede our state intent in a
            # crash. Never interpret its existence as permission to retry.
            row.update(process='waiting_reconciliation',reason='resource_reservation_unknown',
                       resourceReservation=claim)
            return save(root,key,state,state['stateRevision']),None
        if not admitted:
            # No dispatch or budget consumption has occurred.
            row.pop('reservedMicroUsd',None)
            row.pop('budgetAuthoritySha256',None)
            if row.get('reason')!='resource_capacity_busy':
                row['reason']='resource_capacity_busy'
                return save(root,key,state,state['stateRevision']),None
            return state,None
        row['resourceReservation']=claim
    row.pop('reason',None)
    row.update(process='running',startedAt=now(),monotonicStart=time.monotonic(),processId=os.getpid(),
               intentSha256=c.digest(c.job_identity(m,step)))
    deps=[state['steps'][d].get('completionEventId') for d in step['dependsOn']]
    row['dependsOnEvents']=deps
    row['dispatchEventId']=event(m,state,step,'dispatch.started',predecessor=deps[-1] if deps else None)
    state=save(root,key,state,state['stateRevision'])
    output=folder(root,key)/('response-'+c.digest(c.job_identity(m,step))+'.json')
    return state,output


def _execute_dispatch(executor,m,step,output,state,row):
    if m['transport']=='provider' and step['adapter'] in ('source.prepare','canonical.layer2','canonical.audio','app.delivery','study.produce'):
        from scripts.sermon_unified_accounting import execute as execute_observed
        result=execute_observed(executor,m,step,output,state,row)
    else:
        result=executor(m,'/',step,output)
    if not isinstance(result,dict) or result.get('status') not in ('succeeded','blocked','failed'):
        raise c.ContractError('invalid_adapter_result')
    jobs._persist(output,{'identity':c.job_identity(m,step),'result':result})
    return output


def pump(root,key, *, executor=None, scheduler="canonical"):
    executor=executor or adapters.execute
    with jobs._lock(Path(root),c.digest({'unifiedPump':key})) as (_,_,held):
        if not held:
            raise c.ContractError('owner_busy',7)
        recovered=load(root,key)
        if 'concurrencyProfile' in recovered['manifest']['bindings']:
            from scripts.sermon_unified_parallel import pump_locked
            return pump_locked(root,key,executor=executor,scheduler=scheduler)
        release_completed_resources(recovered)
        abandoned=[sid for sid,row in recovered['steps'].items() if row['process']=='running']
        if abandoned:
            for sid in abandoned:
                recovered['steps'][sid].update(process='waiting_reconciliation',reason='owner_lost_after_dispatch')
            save(root,key,recovered,recovered['stateRevision'])
            return recovered
        while True:
            state=load(root,key);m=state['manifest']
            if state.get('scheduler','canonical')!=scheduler:
                raise c.ContractError('scheduler_ownership_changed',7)
            if state['cancelRequested'] or state['admission']=='closed':
                return state
            errors=c.admit(m,'/')
            window=m['executionWindow']
            current_time=datetime.now(timezone.utc)
            if current_time < datetime.fromisoformat(window['startsAt']):
                errors.append('execution_window_not_started')
            if current_time >= datetime.fromisoformat(window['deadlineAt']):
                errors.append('execution_window_expired')
            if errors:
                return block(root,key,state,errors[0])
            outcome,_=_project(state)
            if outcome in ('unknown','failed','succeeded','cancelled'):
                return state
            step=next((s for s in active_steps(m) if state['steps'][s['id']]['process']=='not_started'
                       and all(state['steps'][d]['process']=='succeeded' for d in s['dependsOn'])),None)
            if step is None:
                return state
            state,output=_prepare_dispatch(root,key,state,step)
            if output is None:
                return state
            sid=step['id'];row=state['steps'][sid]
            try:
                _execute_dispatch(executor,m,step,output,state,row)
            except BaseException as exc:
                # Known validation rejection is a block. Other outcomes may have
                # dispatched; keep the reservation and never automatically retry.
                current=load(root,key)
                current['steps'][sid].update(process='waiting_reconciliation',
                    reason=(exc.code if isinstance(exc,c.ContractError) else 'adapter_outcome_unknown'))
                save(root,key,current,current['stateRevision'])
                return current
            finish(root,key,sid,output)


def finish(root,key,sid,response_path,expected_revision=None):
    for attempt in range(100):
        try:
            return _finish_once(root,key,sid,response_path,expected_revision)
        except c.ContractError as exc:
            if expected_revision is not None or exc.code not in ('state_revision_conflict','state_busy') or attempt==99:
                raise
            time.sleep(.02)


def _finish_once(root,key,sid,response_path,expected_revision=None):
    state=load(root,key);m=state['manifest'];step=next(s for s in m['steps'] if s['id']==sid)
    if expected_revision is not None and state['stateRevision']!=expected_revision:
        raise c.ContractError('state_revision_conflict',7)
    doc=c.read(response_path)
    if doc.get('identity')!=c.job_identity(m,step):
        raise c.ContractError('response_identity_changed',7)
    result=doc['result'];row=state['steps'][sid]
    if row['process']=='succeeded':
        if row.get('responseSha256') != c.file_sha(response_path):
            raise c.ContractError('completed_response_changed',7)
        release_completed_resources(state)
        return state
    if row['process'] not in ('running','waiting_reconciliation') or not row.get('intentSha256'):
        raise c.ContractError('dispatch_intent_required',7)
    if not isinstance(result,dict) or result.get('status') not in ('succeeded','blocked','failed'):
        raise c.ContractError('invalid_adapter_result',7)
    if result['status']=='succeeded' and c.admit(m,'/'):
        raise c.ContractError('response_admission_changed',7)
    if result['status']=='succeeded':
        adapters.verify_result(m,'/',step,result)
    if result['status']=='succeeded' and not valid_success(step,result,m):
        raise c.ContractError('unverified_adapter_success',7)
    row.update(process=result['status'],artifact=result.get('artifact','not_started'),
               review=result.get('review','not_required'),reason=result.get('reason','stage_complete'),
               completedAt=now(),responseSha256=c.file_sha(response_path),
               computeSeconds=(max(0,time.monotonic()-row['monotonicStart']) if row.get('processId')==os.getpid() and row.get('monotonicStart') is not None else None))
    if result.get('accountingEvidence'):
        row['accountingEvidence']=result['accountingEvidence']
    if step['adapter']=='app.delivery':
        row['validatedEndpoints']=result.get('validatedEndpoints',[])
        row['validatedLocales']=result.get('locales',[])
        row['publication']=result.get('publication','not_started')
    row['completionEventId']=event(m,state,step,'dispatch.'+result['status'],predecessor=row.get('dispatchEventId'))
    saved=save(root,key,state,state['stateRevision'])
    release_completed_resources(saved)
    return saved


def block(root,key,state,reason):
    for row in state['steps'].values():
        if row['process']=='not_started':
            row.update(process='blocked',reason=reason)
            break
    return save(root,key,state,state['stateRevision'])


def ingest_review(root,key,job_id,receipt_path,expected):
    state=load(root,key);m=state['manifest']
    if expected!=state['stateRevision']:
        raise c.ContractError('state_revision_conflict',7)
    step=next((s for s in m['steps'] if c.digest(c.job_identity(m,s))==job_id),None)
    if step is None or step['adapter']!='review.gate':
        raise c.ContractError('review_job_required')
    if any(state['steps'][d]['process']!='succeeded' for d in step['dependsOn']):
        raise c.ContractError('review_upstream_incomplete')
    if m['transport']=='fixture':
        raise c.ContractError('fixture_cannot_grant_human_approval')
    from scripts.sermon_unified_reviews import validate_review,validate_window
    adapters.inspect_step(m,'/',step)
    original_sha=c.file_sha(receipt_path)
    config=c.read(adapters.config_path(m,'/',step))
    if set(config)!={'schemaVersion','inputs'} or config['schemaVersion']!='sermon-unified-review-inputs-v1':
        raise c.ContractError('review_configuration_invalid',2)
    inputs={name:c.binding(m,'/',reference) for name,reference in config['inputs'].items()}
    kind=step.get('reviewKind')
    if kind=='reflection':kind='meditation'
    if kind=='window':
        validated=validate_window(m,base='/')
        if original_sha!=validated['receiptSha256']:
            raise c.ContractError('window_approval_changed',7)
    else:
        validated=validate_review(kind,receipt_path,inputs=inputs,expected_source=m['source'],expected_locale=step.get('locale'))
    if c.file_sha(receipt_path)!=original_sha:
        raise c.ContractError('review_changed_during_validation',7)
    doc=c.read(receipt_path)
    dst=folder(root,key)/('review-'+original_sha+'.json')
    jobs._persist(dst,doc)
    # This is a new review observation; it cannot alter prior machine evidence.
    # A machine quality waiver satisfies the gate as 'waived', never 'approved'.
    waived=validated.get('reviewKind')=='machine_quality_waiver'
    state['reviews'][step['id']]={'originalSha256':original_sha,'originalPath':str(Path(receipt_path).resolve()),'storedSha256':c.file_sha(dst),
                                  'kind':kind,'reviewKind':validated.get('reviewKind','human_review'),'validatedAt':now()}
    if waived:
        state['steps'][step['id']].update(process='succeeded',artifact='verified',review='waived',
                                        completedAt=now(),reason='machine_quality_waiver_accepted')
    else:
        state['steps'][step['id']].update(process='succeeded',artifact='verified',review='approved',
                                        completedAt=now(),approvedAt=now(),reason='bound_review_accepted')
    state['steps'][step['id']]['completionEventId']=event(m,state,step,'review.waived' if waived else 'review.approved')
    return save(root,key,state,expected),original_sha


def mutate(root,key,operation,expected):
    state=load(root,key)
    if expected is None or expected!=state['stateRevision']:
        raise c.ContractError('state_revision_conflict',7)
    if operation=='cancel':
        state['cancelRequested']=True;state['admission']='closed'
    elif operation=='drain':
        state['admission']='closed'
    elif operation=='resume':
        if any(r['process'] in ('running','waiting_reconciliation') for r in state['steps'].values()):
            raise c.ContractError('reconciliation_required',6)
        state['admission']='open'
        # Completed effects are immutable. Only pre-dispatch blocks can retry.
        for row in state['steps'].values():
            if row['process']=='blocked' and not row.get('intentSha256'):
                row.update(process='not_started')
    return save(root,key,state,expected)


def ingest_continuation_evidence(root,key,binding_name,path,expected):
    state=load(root,key)
    if expected!=state['stateRevision']:
        raise c.ContractError('state_revision_conflict',7)
    if state['manifest']['transport']=='fixture':
        raise c.ContractError('fixture_cannot_grant_human_approval')
    from scripts import sermon_unified_continuation as continuation
    recipe=c.binding(state['manifest'],'/','continuationRecipe')
    ref=continuation.validate_evidence(state,recipe,root,binding_name,path)
    prior=state.get('continuationEvidence',{}).get(binding_name)
    if prior and prior!=ref:
        raise c.ContractError('continuation_evidence_overwrite_forbidden',7)
    state.setdefault('continuationEvidence',{})[binding_name]=ref
    state.pop('continuation',None)
    return save(root,key,state,expected),ref['sha256']

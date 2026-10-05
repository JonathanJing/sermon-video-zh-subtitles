#!/usr/bin/env python3
"""Unified CLI. Run with .venv/bin/python scripts/sermon.py --help."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
import uuid

sys.dont_write_bytecode=True

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.sermon_unified import contracts as c
from scripts.sermon_unified import runtime as r

CODES={'succeeded':0,'pending':3,'running':3,'blocked':4,'partial':4,'failed':5,'unknown':6,'cancelled':10}


def envelope(command,m=None,key=None):
    m=m or {}
    return {'schemaVersion':'sermon-cli-result-v2','command':command,'requestId':'req-'+uuid.uuid4().hex,
            'subject':{'kind':'run','id':key or m.get('productionRunId','unresolved')},
            'runId':m.get('productionRunId','unresolved'),'runRevision':m.get('runRevision',0),
            'outcome':'blocked','completionScope':m.get('activeScope','media_verified'),
            'nextActions':[],'error':None}


def state_result(command,state,job_id=None):
    m=state['manifest'];result=envelope(command,m,state['runKey']);outcome,blockers=r._project(state)
    rows=[(s['id'],state['steps'][s['id']]) for s in r.active_steps(m)];chosen=None
    if job_id:
        chosen=next(((s['id'],state['steps'][s['id']]) for s in m['steps']
                     if c.digest(c.job_identity(m,s))==job_id),None)
        if chosen is None:
            raise c.ContractError('job_not_found',9)
    if chosen is None:
        chosen=next(((k,v) for k,v in rows if v['process']!='succeeded'),rows[-1])
    sid,row=chosen
    result.update(outcome=outcome,stage=next(s['stageId'] for s in m['steps'] if s['id']==sid),
        jobState={k:row[k] for k in ('process','artifact','review','publication','device')},
        runSummary={'outcome':outcome,'completionScope':m['activeScope'],'blockers':blockers},
        cost={'currency':'USD','actualMicroUsd':None,
              'reservedMicroUsd':state.get('historicalReservedMicroUsd',0)+sum(x.get('reservedMicroUsd',0) for x in state['steps'].values())})
    if job_id:
        result['subject']={'kind':'job','id':job_id}
        result['outcome']={'not_started':'pending','waiting_reconciliation':'unknown',
                           'cancel_requested':'running'}.get(row['process'],row['process'])
    result['stateRevision']=state['stateRevision']
    current=r.datetime.now(r.timezone.utc)
    w=m['executionWindow']
    ds='not_started' if current<r.datetime.fromisoformat(w['startsAt']) else 'expired' if current>=r.datetime.fromisoformat(w['deadlineAt']) else 'within_window'
    if outcome=='succeeded':
        ended=max((x.get('completedAt',state['updatedAt']) for x in state['steps'].values()))
        ds='completed_in_window' if r.datetime.fromisoformat(ended)<=r.datetime.fromisoformat(w['deadlineAt']) else 'completed_late'
    result['execution']={'transport':m['transport'],'productionEligible':outcome=='succeeded' and m['transport']=='provider' and m['activeScope']=='dual_production_verified','deadlineStatus':ds,'remainingSteps':sum(state['steps'][s['id']]['process']!='succeeded' for s in r.active_steps(m)),'runtimeCodexTurns':0}
    result['nextActions']=['job.reconcile'] if outcome=='unknown' else ['review.ingest'] if row['review']=='human_pending' else []
    return result


def run(args):
    command=args.group+'.'+args.action.replace('-','_')
    if command in ('run.plan','run.submit'):
        path=Path(args.manifest).absolute();m=c.read(path);res=envelope(command,m)
        blockers=c.admit(m,path.parent)
        if not blockers:
            from scripts.sermon_unified import adapters
            for step in m.get('steps',[]):
                try:adapters.inspect_step(m,path.parent,step,ready=False)
                except (c.ContractError,ValueError,OSError) as exc:
                    blockers.append(exc.code if isinstance(exc,c.ContractError) else 'adapter_preflight_failed')
        res['plan']={'planHash':None if blockers else c.plan_hash(m),'newPaidRequests':0,
                     'blockers':[{'code':x} for x in sorted(set(blockers))]}
        res['outcome']='blocked' if blockers else 'succeeded'
        if command=='run.submit':
            res['submit']={'frozen':False,'manifestSha256':None,'jobId':None}
            if not blockers:
                state=r.submit(m,path.parent,args.state_root,args.plan_hash,args.expected_revision)
                state=r.continue_owner(args.state_root,state['runKey'])
                res['subject']['id']=state['runKey']
                res['submit'].update(frozen=True,manifestSha256=state['manifestSha256'],jobId=state.get('ownerJobId'))
        return res,4 if blockers else 0
    if command=='worker.run':
        r.run_owner(args.state_root,args.run_id)
        return None,0
    state=r.load(args.state_root,args.run_id)
    if command=='run.events':
        from scripts.sermon_unified_observability import events,project
        result=envelope(command,state['manifest'],state['runKey']);result['outcome']='succeeded'
        result['events']=events(state,after=args.after_event,trace_id=args.trace_id,attempt_id=args.attempt_id)
        result['progress']=project(state);result['stateRevision']=state['stateRevision']
        return result,0
    if command=='worker.transfer':
        from scripts.sermon_temporal.unified import transfer
        state=transfer(args.state_root,args.run_id,args.expected_revision,scheduler=args.scheduler)
        result=envelope(command,state['manifest'],state['runKey']);result['outcome']='succeeded';result['stateRevision']=state['stateRevision']
        return result,0
    if command in ('job.status','job.result','job.wait'):
        deadline=time.monotonic()+args.timeout
        while True:
            result=state_result(command,state,args.job_id)
            if command!='job.wait' or result['outcome'] not in ('running','pending'):
                return result,0 if command=='job.status' else CODES[result['outcome']]
            if time.monotonic()>=deadline:
                return result,3
            time.sleep(min(.2,max(0,deadline-time.monotonic())))
            state=r.load(args.state_root,args.run_id)
    if command=='layer.submit':
        if args.locale and args.locale not in state['manifest']['locales']:
            raise c.ContractError('locale_not_in_manifest',2)
        # The fixed DAG decides what is runnable; a layer request cannot force
        # a jump past upstream gates.
        stage=next((s for s in state['manifest']['steps'] if c.layer(s['stageId'])=='layer'+str(args.layer)
                    and (not args.locale or s.get('locale')==args.locale)),None)
        if stage is None:
            raise c.ContractError('layer_not_in_manifest',4)
        if any(state['steps'][d]['process']!='succeeded' for d in stage['dependsOn']):
            result=state_result(command,state);result['outcome']='blocked'
            result['error']={'code':'upstream_gate_pending','message':'upstream_gate_pending'}
            return result,4
        r.continue_owner(args.state_root,args.run_id)
        return state_result(command,r.load(args.state_root,args.run_id)),0
    if command in ('job.resume','job.cancel','worker.drain'):
        state=r.mutate(args.state_root,args.run_id,args.action,args.expected_revision)
        if command=='job.resume':
            state=r.continue_owner(args.state_root,args.run_id)
        if command=='worker.drain':
            result=envelope(command,state['manifest'],state['runKey']);result['outcome']='succeeded'
            result['drain']={'ownerId':state.get('ownerJobId') or state['runKey'],'admission':'closed',
                'inFlight':sum(x['process']=='running' for x in state['steps'].values()),
                'waitingReconciliation':sum(x['process']=='waiting_reconciliation' for x in state['steps'].values())}
            return result,0
        return state_result(command,state),0
    if command in ('job.reconcile','job.cache_recover'):
        if args.expected_revision!=state['stateRevision']:
            raise c.ContractError('state_revision_conflict',7)
        step=next((s for s in state['manifest']['steps'] if c.digest(c.job_identity(state['manifest'],s))==args.job_id),None)
        if step is None:raise c.ContractError('job_not_found',9)
        path=r.folder(args.state_root,args.run_id)/('response-'+args.job_id+'.json')
        if not path.is_file():raise c.ContractError('response_evidence_required',6)
        state=r.finish(args.state_root,args.run_id,step['id'],path,args.expected_revision)
        state=r.continue_owner(args.state_root,args.run_id)
        return state_result(command,state,args.job_id),0
    if command=='review.ingest' and args.binding:
        state,sha=r.ingest_continuation_evidence(args.state_root,args.run_id,args.binding,args.receipt,args.expected_revision)
        r.continue_owner(args.state_root,args.run_id)
        result=state_result(command,r.load(args.state_root,args.run_id))
        result['reviewIngest']={'decision':'accepted','receiptSha256':sha,'reason':None}
        return result,0
    if command=='review.ingest':
        result=envelope(command,state['manifest'],state['runKey'])
        result['reviewIngest']={'decision':'rejected','receiptSha256':None,'reason':'bound_review_validator_required'}
        receipt=c.read(args.receipt)
        if not receipt.get('schemaVersion') or set(receipt)=={'approved'}:
            result['reviewIngest']['reason']='unbound_review_receipt'
            return result,2
        state,sha=r.ingest_review(args.state_root,args.run_id,args.job_id,args.receipt,args.expected_revision)
        result['outcome']='succeeded';result['stateRevision']=state['stateRevision']
        result['reviewIngest']={'decision':'accepted','receiptSha256':sha,'reason':None}
        r.continue_owner(args.state_root,args.run_id)
        return result,0
    raise c.ContractError('unsupported_command',2)


def parser():
    p=argparse.ArgumentParser(description=__doc__);groups=p.add_subparsers(dest='group',required=True)
    commands={'run':('plan','submit','events'),'job':('status','result','wait','resume','reconcile','cache-recover','cancel'),
              'layer':('submit',),'review':('ingest',),'worker':('run','drain','transfer')}
    for group,actions in commands.items():
        sub=groups.add_parser(group).add_subparsers(dest='action',required=True)
        for action in actions:
            q=sub.add_parser(action);q.add_argument('--json',action='store_true')
            q.add_argument('--state-root',type=Path,default=r.DEFAULT_ROOT)
            if group=='run' and action!='events':
                q.add_argument('--manifest',required=True)
                if action=='submit':
                    q.add_argument('--plan-hash',required=True)
                    q.add_argument('--expected-revision',type=int)
            else:
                q.add_argument('--run-id',required=True)
                q.add_argument('--job-id')
                q.add_argument('--expected-revision',type=int)
                q.add_argument('--timeout',type=float,default=30)
            if group=='run' and action=='events':
                q.add_argument('--after-event');q.add_argument('--trace-id');q.add_argument('--attempt-id')
            if group=='layer':q.add_argument('--layer',type=int,choices=[1,2,3,4],required=True);q.add_argument('--locale')
            if group=='review':
                q.add_argument('--receipt',required=True)
                q.add_argument('--binding',help='已冻结续跑配方中的证据槽位')
            if group=='worker' and action=='transfer':q.add_argument('--scheduler',choices=['canonical','temporal'],required=True)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        result,code=run(args)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        command=args.group+'.'+args.action.replace('-','_')
        code=exc.exit_code if isinstance(exc,c.ContractError) else 8
        result=envelope(command)
        result['error']={'code':exc.code if isinstance(exc,c.ContractError) else 'infrastructure_or_input_error',
                         'message':exc.code if isinstance(exc,c.ContractError) else 'See local bound evidence.'}
        if command in ('run.plan','run.submit'):
            result['plan']={'planHash':None,'newPaidRequests':0,'blockers':[{'code':result['error']['code']}]}
        if command=='run.submit':result['submit']={'frozen':False,'manifestSha256':None,'jobId':None}
        if command.startswith('job.') or command=='layer.submit':
            result['jobState']={'process':'blocked','artifact':'not_started','review':'not_required','publication':'not_started','device':'not_checked'}
        if command=='review.ingest':result['reviewIngest']={'decision':'rejected','receiptSha256':None,'reason':result['error']['code']}
        if command=='worker.drain':result['drain']={'ownerId':'unresolved','admission':'closed','inFlight':0,'waitingReconciliation':0}
    if args.group=='worker' and args.action=='run':
        if code:
            print('unified_owner_stopped',file=sys.stderr)
        return code
    if result is not None:
        c.validate(result,'sermon-cli-result-v2')
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return code

if __name__=='__main__':
    raise SystemExit(main())

"""Opt-in Temporal activity adapter over the same unified durable store.

Migration must drain the canonical pump and explicitly transfer its scheduler
identity first. No alternative ledger, provider retry or approval path exists.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UnifiedRequest:
    state_root: str
    run_key: str
    plan_hash: str

    def validate(self):
        from scripts.sermon_unified import runtime as r, contracts as c
        if not Path(self.state_root).is_absolute():
            raise c.ContractError('absolute_state_root_required',2)
        state=r.load(self.state_root,self.run_key)
        if state['planHash']!=self.plan_hash or state.get('scheduler','canonical')!='temporal':
            raise c.ContractError('scheduler_or_plan_changed',7)
        return state


def inspect(request):
    from scripts.sermon_unified import runtime as r
    state=request.validate()
    return {'outcome':r._project(state)[0],'stateRevision':state['stateRevision'],
            'planHash':state['planHash'],'productionRunId':state['manifest']['productionRunId'],
            'runRevision':state['manifest']['runRevision']}


def execute(request):
    from scripts.sermon_unified import runtime as r
    request.validate()
    r.pump(request.state_root,request.run_key,scheduler='temporal')
    return inspect(request)


def transfer(root,key,expected_revision, *, scheduler):
    from scripts.sermon_unified import runtime as r, contracts as c
    from scripts import sermon_workflow_jobs as jobs
    if scheduler not in ('canonical','temporal'):
        raise c.ContractError('scheduler_invalid',2)
    with jobs._lock(Path(root),c.digest({'unifiedPump':key})) as (_,_,held):
        if not held:
            raise c.ContractError('owner_busy',7)
        state=r.load(root,key)
        if state['stateRevision']!=expected_revision:
            raise c.ContractError('state_revision_conflict',7)
        if state['admission']!='closed' or any(x['process'] in ('running','waiting_reconciliation') for x in state['steps'].values()):
            raise c.ContractError('drain_and_reconcile_required',6)
        if state.get('ownerJobId') and jobs.peek_job(Path(root)/'owners',state['ownerJobId'])['status'] in jobs.ACTIVE:
            raise c.ContractError('durable_owner_still_active',7)
        state['scheduler']=scheduler;state['admission']='open'
        state['schedulerTransfer']={'from':r.load(root,key).get('scheduler','canonical'),'to':scheduler,
                                    'at':r.now(),'expectedRevision':expected_revision}
        return r.save(root,key,state,expected_revision)


def sdk_types():
    """Import module-level SDK definitions only in the dedicated runtime."""
    from .unified_sdk import UnifiedWorkflow, execute_activity
    return UnifiedWorkflow, execute_activity


def project_call(operation, request):
    """SDK runtime invokes the pinned project interpreter, like legacy activities."""
    import json
    import subprocess
    from .local_io import PROJECT_PYTHON, ROOT
    result=subprocess.run([str(PROJECT_PYTHON),'-m','scripts.sermon_temporal.unified',operation,
                           request.state_root,request.run_key,request.plan_hash],
                          cwd=ROOT,capture_output=True,text=True,timeout=86500)
    if result.returncode:
        raise RuntimeError('Unified project activity failed; inspect durable state before retry')
    return json.loads(result.stdout)


def main():
    import argparse
    import json
    from scripts.sermon_unified import runtime as r
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['inspect','execute','cancel'])
    parser.add_argument('state_root');parser.add_argument('run_key');parser.add_argument('plan_hash')
    args=parser.parse_args()
    request=UnifiedRequest(args.state_root,args.run_key,args.plan_hash)
    if args.operation=='cancel':
        from scripts.sermon_unified.contracts import ContractError
        import time
        for attempt in range(100):
            state=request.validate()
            try:
                r.mutate(request.state_root,request.run_key,'cancel',state['stateRevision'])
                break
            except ContractError as exc:
                if exc.code not in ('state_revision_conflict','state_busy') or attempt==99:
                    raise
                time.sleep(.02)
        result=inspect(request)
    else:
        result=(execute if args.operation=='execute' else inspect)(request)
    print(json.dumps(result))


if __name__=='__main__':
    main()

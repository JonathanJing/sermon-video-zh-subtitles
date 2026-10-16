"""Opt-in bounded branch execution under the existing single durable owner.

Workers persist responses only. The owner alone admits dependencies, updates
state and commits verified results. Owner loss never permits redispatch.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from datetime import datetime, timezone
import copy
import time

from scripts.sermon_unified import contracts as c, runtime as r
from scripts.production_concurrency_profile import load_profile


def profile(manifest):
    value=load_profile(c.binding(manifest,'/','concurrencyProfile'))
    policy=r.resource_policy(manifest)
    if policy is None or policy['capacities']['codex_cli']!=value['totalCodexSlots']:
        raise c.ContractError('parallel_resource_policy_required')
    if policy['capacities']['cpu']<value['cpuWorkers']:
        raise c.ContractError('parallel_cpu_capacity_insufficient')
    return value


def _unknown(root,key,sid,exc):
    # Concurrent review/cancel writes use the same CAS boundary as finish.
    for attempt in range(100):
        state=r.load(root,key)
        row=state['steps'][sid]
        if row['process'] not in ('running','waiting_reconciliation'):
            return state
        row.update(process='waiting_reconciliation',
                   reason=exc.code if isinstance(exc,c.ContractError) else 'adapter_outcome_unknown')
        try:
            return r.save(root,key,state,state['stateRevision'])
        except c.ContractError as conflict:
            if conflict.code not in ('state_revision_conflict','state_busy') or attempt==99:
                raise
            time.sleep(.02)


def pump_locked(root,key,*,executor,scheduler):
    state=r.load(root,key)
    settings=profile(state['manifest'])
    r.release_completed_resources(state)
    abandoned=[sid for sid,row in state['steps'].items() if row['process']=='running']
    if abandoned:
        for sid in abandoned:
            state['steps'][sid].update(process='waiting_reconciliation',reason='owner_lost_after_dispatch')
        return r.save(root,key,state,state['stateRevision'])
    futures={}
    # The pump lock is held through draining; no second owner can claim live work.
    with ThreadPoolExecutor(max_workers=settings['maxBranches']) as pool:
        while True:
            for future in list(futures):
                if not future.done():
                    continue
                sid=futures.pop(future)
                try:
                    r.finish(root,key,sid,future.result())
                except BaseException as exc:
                    _unknown(root,key,sid,exc)
            state=r.load(root,key);m=state['manifest']
            if state.get('scheduler','canonical')!=scheduler:
                if futures:
                    wait(futures,timeout=.1,return_when=FIRST_COMPLETED)
                    continue
                raise c.ContractError('scheduler_ownership_changed',7)
            outcome,_=r._project(state)
            stopped=state['cancelRequested'] or state['admission']=='closed' or outcome in (
                'unknown','failed','succeeded','cancelled')
            errors=c.admit(m,'/')
            current=datetime.now(timezone.utc)
            if current<datetime.fromisoformat(m['executionWindow']['startsAt']):
                errors.append('execution_window_not_started')
            if current>=datetime.fromisoformat(m['executionWindow']['deadlineAt']):
                errors.append('execution_window_expired')
            if errors:
                stopped=True
                # Do not replace in-flight intents with a broad run block.
                if not futures:
                    return r.block(root,key,state,errors[0])
            dispatched=False
            if not stopped:
                for step in r.active_steps(m):
                    if len(futures)>=settings['maxBranches']:
                        break
                    state=r.load(root,key)
                    if state['cancelRequested'] or state['admission']=='closed':
                        break
                    row=state['steps'][step['id']]
                    if row['process']!='not_started' or not all(
                            state['steps'][dep]['process']=='succeeded' for dep in step['dependsOn']):
                        continue
                    if step['adapter']=='study.produce' and sum(
                            next(s for s in m['steps'] if s['id']==sid)['adapter']=='study.produce'
                            for sid in futures.values())>=settings['studyBranches']:
                        continue
                    state,output=r._prepare_dispatch(root,key,state,step)
                    if output is None:
                        # Busy capacity does not hide other ready resource lanes.
                        if state['steps'][step['id']]['process'] not in ('not_started',):
                            break
                        continue
                    # Each worker receives an immutable dispatch snapshot/context.
                    snapshot=copy.deepcopy(state)
                    future=pool.submit(copy_context().run,r._execute_dispatch,executor,m,step,
                                       output,snapshot,snapshot['steps'][step['id']])
                    futures[future]=step['id'];dispatched=True
            if futures:
                wait(futures,timeout=.1,return_when=FIRST_COMPLETED)
                continue
            if not dispatched:
                return r.load(root,key)

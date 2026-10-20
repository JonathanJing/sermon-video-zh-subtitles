"""Read-only incremental events and honest timing/cost projections."""
from __future__ import annotations
from datetime import datetime,timezone
from scripts.sermon_unified import runtime as r


def events(state, *, after=None, trace_id=None, attempt_id=None):
    rows=state['events'];start=0
    if after:
        indices=[i for i,x in enumerate(rows) if x['eventId']==after]
        if len(indices)!=1:
            raise ValueError('event_cursor_not_found')
        start=indices[0]+1
    return [x for x in rows[start:] if (trace_id is None or x['traceId']==trace_id)
            and (attempt_id is None or x['attemptId']==attempt_id)]


def project(state):
    m=state['manifest'];by_id={s['id']:s for s in m['steps']}
    critical={};missing=[];handoffs=[];rows=[]
    for step in r.active_steps(m):
        sid=step['id'];row=state['steps'][sid];elapsed=row.get('computeSeconds')
        deps=step['dependsOn']
        if elapsed is None or any(dep not in critical for dep in deps):
            missing.append(sid)
        else:
            critical[sid]=elapsed+max((critical[d] for d in deps),default=0)
        if row.get('startedAt') and deps and all(state['steps'][d].get('completedAt') for d in deps):
            ready=max(datetime.fromisoformat(state['steps'][d]['completedAt']) for d in deps)
            handoff=(datetime.fromisoformat(row['startedAt'])-ready).total_seconds()
            if handoff>=0:handoffs.append(handoff)
        rows.append({'id':sid,'locale':step.get('locale'),'stage':step['stageId'],
                     'process':row['process'],'computeSeconds':elapsed,
                     'dependsOnEvents':row.get('dependsOnEvents',[]),
                     'timestamps':{k:row.get(k) for k in ('readyAt','approvedAt','enqueuedAt','startedAt','completedAt')},
                     'reservedMicroUsd':row.get('reservedMicroUsd',0),
                     'actualMicroUsd':None,'accountingEvidence':row.get('accountingEvidence'),
                     'reason':row.get('reason')})
    ordered=sorted(handoffs)
    return {'schemaVersion':'sermon-unified-progress-v1','productionRunId':m['productionRunId'],
            'runRevision':m['runRevision'],'stateRevision':state['stateRevision'],
            'plannedSteps':len(rows),'completedSteps':sum(x['process']=='succeeded' for x in rows),
            'outcome':r._project(state)[0],'steps':rows,
            'criticalPath':{'status':'incomplete' if missing else 'complete',
                            'computeSeconds':None if missing else max(critical.values(),default=0),
                            'missingSteps':missing,'scope':'compute_only_not_total_wall'},
            'handoff':{'count':len(ordered),'p95Seconds':ordered[max(0,(95*len(ordered)+99)//100-1)] if ordered else None},
            'deadlineAt':m['executionWindow']['deadlineAt'],
            'deadlineMarginSeconds':(datetime.fromisoformat(m['executionWindow']['deadlineAt'])-datetime.now(timezone.utc)).total_seconds(),
            'remainingSteps':[x['id'] for x in rows if x['process']!='succeeded'],
            'etaSeconds':None,'etaReason':'no_same_workload_resource_calibration',
            'humanListeningSeconds':None,'actualCostMicroUsd':None,'runtimeCodexTurns':0}


def compare(a,b):
    """Cost/performance A/B only after equality of actual quality/input evidence."""
    identity=('sourceSha256','policySha256','qualityReceiptSha256','scope','workload','cacheMode')
    if any(a.get(k) is None or a[k]!=b.get(k) for k in identity):
        raise ValueError('comparison_identity_or_quality_mismatch')
    fields=('wallSeconds','freshApiAttempts','uncachedInputTokens','cachedInputTokens','outputTokens','gpuSeconds')
    return {'schemaVersion':'sermon-unified-comparison-v1',
            'identity':{k:a[k] for k in identity},
            'deltas':{k:None if a.get(k) is None or b.get(k) is None else b[k]-a[k] for k in fields},
            'billedCostDeltaMicroUsd':None if a.get('billedMicroUsd') is None or b.get('billedMicroUsd') is None else b['billedMicroUsd']-a['billedMicroUsd']}


def bounded_packet(state, *, max_bytes=16384):
    """Minimal diagnostic context with an explicit byte cap and omitted counts."""
    import json
    if type(max_bytes) is not int or not 1024<=max_bytes<=65536:
        raise ValueError('invalid_context_packet_limit')
    m=state['manifest'];steps=r.active_steps(m)
    pending=[{'id':step['id'],'stage':step['stageId'],'locale':step.get('locale'),
              'process':state['steps'][step['id']]['process'],
              'reason':state['steps'][step['id']].get('reason')} for step in steps
             if state['steps'][step['id']]['process']!='succeeded']
    value={'schemaVersion':'sermon-unified-context-packet-v1','productionRunId':m['productionRunId'],
           'runRevision':m['runRevision'],'stateRevision':state['stateRevision'],'planHash':state['planHash'],
           'activeScope':m['activeScope'],'outcome':r._project(state)[0],'pendingCount':len(pending),
           'pending':pending[:8],'events':[{'eventId':x['eventId'],'eventType':x['eventType'],
               'stageId':x['stageId'],'time':x['time']} for x in state['events'][-8:]],
           'omittedPending':max(0,len(pending)-8),'omittedEvents':max(0,len(state['events'])-8),
           'evidenceRequiredForAction':True,'approvalGranted':False}
    while len(json.dumps(value,ensure_ascii=False).encode())>max_bytes:
        field='events' if value['events'] else 'pending'
        if not value[field]:
            raise ValueError('context_packet_identity_exceeds_limit')
        value[field].pop(0 if field=='events' else -1)
        value['omittedEvents' if field=='events' else 'omittedPending']+=1
    return value

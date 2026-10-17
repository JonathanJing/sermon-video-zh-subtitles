"""Explicit opt-in envelope/context adapter for the existing accounting writer."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import os
import re

from scripts import sermon_log_contract as contract
from scripts import sermon_log_outbox as outbox

_context = ContextVar('sermon_log_profile',default=None)
PROFILE_ENV = 'SERMON_ACCOUNTING_CONTRACT_VERSION'
CONTEXT_ENV = 'SERMON_ACCOUNTING_CONTRACT_CONTEXT'
CONTEXT_KEYS = frozenset({'workUnitId','attemptId','decisionId','productionRunId','engineeringRunId',
    'workKind','evidenceMode','executorType','logicalCallId','providerScopeKey','attemptNumber','role',
    'revisionId','dispatchSpanId','jobId','parentSpanId'})


def current():
    result=_context.get()
    if result is not None:return dict(result)
    version=os.environ.get(PROFILE_ENV)
    if version is None:return None
    if version!=contract.VERSION:raise ValueError('unsupported_contract_version')
    encoded=os.environ.get(CONTEXT_ENV,'{}')
    if len(encoded.encode())>4096:raise ValueError('profile_context_size_limit')
    value=json.loads(encoded)
    _validate_context(value)
    return value


def _validate_context(value):
    if not isinstance(value,dict) or set(value)-CONTEXT_KEYS:raise ValueError('invalid_profile_context')
    # Validate supplied fields through a complete fixture-free envelope below;
    # here ensure bounded primitives so environment context is never arbitrary.
    for key,item in value.items():
        if item is None:continue
        if key=='attemptNumber':
            if type(item) is not int or not 1<=item<=2**53-1:raise ValueError('invalid_attempt_number')
        elif not isinstance(item,str) or len(item)>100 or not re.fullmatch(r'[A-Za-z0-9_.:-]+',item):
            raise ValueError('invalid_profile_context_label')
    if value.get('workKind') not in {'production','control','engineering'}:raise ValueError('profile_work_kind_required')
    if value.get('evidenceMode') not in {'current_execution','cache_replay','synthetic'}:raise ValueError('profile_evidence_mode_required')


@contextmanager
def context(**fields):
    merged={**(current() or {}),**fields};_validate_context(merged)
    token=_context.set(merged)
    try:yield merged
    finally:_context.reset(token)


def child_environment(env):
    value=current()
    if value is not None:
        env[PROFILE_ENV]=contract.VERSION
        env[CONTEXT_ENV]=json.dumps(value,sort_keys=True,separators=(',',':'))
    return env


def _utc(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat().replace('+00:00','Z') if value is not None else None


def _build(event,base,context,event_id,producer_id,sequence):
    from scripts import sermon_accounting as accounting
    row={**base,**event}
    row.pop('pid',None);row.pop('threadId',None)
    row.update(traceId=hashlib.sha256(('sermon-trace-v1:'+row['runId']).encode()).hexdigest()[:32],contractVersion=contract.VERSION,eventId=event_id,producerId=producer_id,sequence=sequence)
    for key in ('recordedAt','startedAt','completedAt','dependencyReadyAt','queuedAt'):
        if key in row:row[key]=_utc(row[key])
    for key in ('parentSpanId','workUnitId','attemptId','decisionId','productionRunId','engineeringRunId','executorType','workKind','evidenceMode'):
        if row.get(key) is None:row[key]=context.get(key)
    for key in ('role','revisionId','dispatchSpanId','jobId'):
        if context.get(key) is not None:row[key]=context[key]
    kind=row['event']
    # The operation's endpoint is a fact, independent of delayed persistence.
    if kind=='stage_finished' and 'completedAt' not in row:row['completedAt']=row['recordedAt']
    if kind.startswith('api_attempt'):
        row.update(provider='openai',requestedModel=row.get('requestedModel') or row.get('model'),
            modelCallId=row['attemptId'],logicalCallId=context.get('logicalCallId'),
            stageAttemptId=context.get('attemptId'),providerScopeKey=context.get('providerScopeKey'),
            attemptNumber=context.get('attemptNumber',1),usageScope='direct_response',usageSemanticsVersion='openai_usage_v1')
        if kind=='api_attempt_started':row['model']=None
        else:
            row.update(providerResponseId=row.get('responseId'),billingReceiptId=None,
                usageStatus='not_reported' if all(v is None for v in row['usage'].values()) else
                    'partial' if any(v is None for v in row['usage'].values()) else 'reported')
    if kind.startswith('sdk_call_'):
        row.update(usageScope='sdk_aggregate',coverageStatus='unknown',coveredResponseIds=None)
    if 'executionIdentity' in row:row['executionIdentity']=accounting.safe_execution_identity(row['executionIdentity'])
    if 'resources' in row:row['resources']={**row['resources'],'scope':'process_lifetime_counters_not_stage_allocation'}
    if 'evidence' in row:
        evidence=row['evidence']
        if evidence.get('schemaVersion')!='sermon-workflow-evidence-v1':raise ValueError('profile_evidence_collection_failed')
        row['evidence']={k:evidence[k] for k in ('schemaVersion','evidenceScope','currentRunExecutionProven','missingCategories')}
        row['evidence']['artifacts']=[{k:a[k] for k in ('category','sha256','bytes')} for a in evidence['artifacts']]
    reasons={}
    reason_keys=contract.validator().schema['$defs']['missingReasons']['properties']
    for key in reason_keys:
        if key in row and row[key] is None:
            reasons[key]='not_applicable' if (key in {'parentSpanId','decisionId'} or
                key=='engineeringRunId' and row['workKind']!='engineering' or
                key=='productionRunId' and row['workKind']!='production') else 'not_observed'
    for key,value in row.get('usage',{}).items():
        if value is None and key in reason_keys:reasons[key]='provider_not_reported'
    if row.get('cost',{}).get('estimatedUsd','absent') is None:reasons['cost']='not_observed'
    if kind.startswith('sdk_call_'):reasons['coverage']='not_observed'
    row['missingReasons']=reasons
    return row


def write(directory,event,base):
    ctx=current()
    if ctx is None:raise ValueError('profile_context_required')
    prepared=outbox.prepare(directory,lambda event_id,producer_id,sequence:_build(event,base,ctx,event_id,producer_id,sequence))
    return outbox.deliver(directory,prepared)


@contextmanager
def session(directory,workflow,metadata=None,*,work_kind,evidence_mode,production_run_id=None,**kwargs):
    from scripts import sermon_accounting as accounting
    if current() is not None:raise ValueError('use_existing_profile_session_for_nested_work')
    with context(workKind=work_kind,evidenceMode=evidence_mode,productionRunId=production_run_id):
        with accounting.accounting_session(directory,workflow,metadata,**kwargs) as run:yield run


def reject_downgrade(directory,run_id):
    marker=Path(directory)/'.run-profiles'/(hashlib.sha256(run_id.encode()).hexdigest()+'.json')
    if marker.exists() or marker.is_symlink():raise ValueError('profile_run_requires_propagated_context')


def job_context(job_id):
    """Persist only the explicit accounting environment, never the whole env."""
    from scripts import sermon_accounting as accounting
    if current() is None:return None
    with context(jobId=job_id,dispatchSpanId=accounting._span.get() or os.environ.get(accounting.ENV_KEYS[3]),parentSpanId=None,attemptId=None):
        env=accounting.subprocess_environment()
    # Detached execution has a causal dispatch link, not synchronous containment.
    env.pop(accounting.ENV_KEYS[3],None)
    env.pop(accounting.ENV_KEYS[2],None)
    keys=(*accounting.ENV_KEYS,accounting.WORKFLOW_ENV,PROFILE_ENV,CONTEXT_ENV)
    selected={k:env[k] for k in keys if k in env}
    return {'schemaVersion':'sermon-job-accounting-context-v1','jobId':job_id,'environment':selected}


def restore_job_environment(value,job_id):
    from scripts import sermon_accounting as accounting
    if not isinstance(value,dict) or set(value)!={'schemaVersion','jobId','environment'} or value['schemaVersion']!='sermon-job-accounting-context-v1' or value['jobId']!=job_id:
        raise ValueError('invalid_job_accounting_context')
    env=value['environment'];allowed={*accounting.ENV_KEYS,accounting.WORKFLOW_ENV,PROFILE_ENV,CONTEXT_ENV}
    if (not isinstance(env,dict) or set(env)-allowed or env.get(PROFILE_ENV)!=contract.VERSION or
        any(not isinstance(v,str) or '\0' in v or len(v)>4096 for v in env.values()) or
        not all(env.get(k) for k in (*accounting.ENV_KEYS[:2],accounting.WORKFLOW_ENV,CONTEXT_ENV))):
        raise ValueError('invalid_job_accounting_environment')
    ctx=json.loads(env[CONTEXT_ENV]);_validate_context(ctx)
    if ctx.get('jobId')!=job_id:raise ValueError('job_accounting_identity_conflict')
    return {**{k:v for k,v in os.environ.items() if k not in allowed},**env}

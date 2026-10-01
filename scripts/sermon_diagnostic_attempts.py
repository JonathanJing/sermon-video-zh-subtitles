"""Explicit new attempts from terminal parent evidence; never renew old clocks.

The trusted operator supplies authorization and frozen identities. Hash fields
are evidence bindings, not authority discovery. No credential, model, provider
clock, refund, old-ledger mutation or approval upgrade occurs in this module.
"""
from copy import deepcopy
import math
from pathlib import Path
import time

from scripts import sermon_review_contracts as c, sermon_review_budget as budget
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_execution_extensions as extensions
from scripts import sermon_public_snapshot as public
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_release_workflow import _safe_path

SCHEMA = 'sermon-diagnostic-linked-attempt-v1'
AUTH_SCHEMA = 'sermon-diagnostic-new-attempt-authorization-v1'


def terminal_parent(plan, *, _legacy_observation=False):
    """Read actual terminal ledgers and receipts without checking/resetting time."""
    c.require(type(plan) is dict and set(plan) == {'schemaVersion', 'runDirectory',
        'providerConfig', 'authority', 'executionIdentity', 'sourceClipPath'} and
        plan['schemaVersion'] == 'sermon-bounded-diagnostic-plan-v1', 'invalid_diagnostic_plan')
    config = provider.validate_config(plan['providerConfig'])
    c.require(c.canonical_sha256(plan['executionIdentity']) == config['codeSha256'],
              'attempt_parent_code_binding_changed')
    root = _safe_path(Path(plan['runDirectory']))
    c.require(root.is_absolute(), 'attempt_absolute_directory_required')
    store = budget.BudgetStore(root/'budget', plan['authority'])
    folder = store.root / budget.STORE_ID
    state, state_bytes = c.read_snapshot(folder/'provider-run/state.json')
    ledger, ledger_bytes = c.read_snapshot(folder/'state.json')
    c.require(set(state)=={'schemaVersion','config','authoritySha256','clockDomain','startedMonotonic','requests'}
              and state.get('schemaVersion') == provider.SCHEMA and state.get('config') == config
              and state.get('authoritySha256') == store.authority_sha256
              and type(state.get('requests')) is dict, 'attempt_parent_provider_changed')
    budget._hash(state['clockDomain'])
    c.require(type(state['startedMonotonic']) in (int,float) and math.isfinite(state['startedMonotonic'])
              and state['startedMonotonic']>=0, 'attempt_parent_clock_changed')
    c.require(ledger == {'schemaVersion': budget.SCHEMA, 'authority': store.authority,
        'storeSha256': store.store_sha256, 'reservations': ledger.get('reservations')}
        and type(ledger['reservations']) is dict, 'attempt_parent_budget_changed')
    snapshots = [{'path':str(folder/'provider-run/state.json'),'bytesSha256':c.bytes_sha256(state_bytes)},
                 {'path':str(folder/'state.json'),'bytesSha256':c.bytes_sha256(ledger_bytes)}]
    for call_id,row in state['requests'].items():
        budget._label(call_id)
        c.require(type(row) is dict and set(row)=={'requestSha256','bounds','model','state','receiptSha256','operationId'}
                  and row['model'] in ('gpt-transcribe','gpt-6-astra','gpt-6-sol'), 'attempt_parent_request_changed')
        budget._hash(row['requestSha256']);budget._hash(row['receiptSha256']) if row['state'] in ('returned','rejected') else None
        c.require(row.get('state') in ('returned','rejected'), 'attempt_parent_reconciliation_required')
        path=folder/'provider-run'/(call_id+'.json');receipt,raw=c.read_snapshot(path)
        c.require(c.bytes_sha256(raw)==row['receiptSha256'] and receipt.get('modelCallId')==call_id
                  and receipt.get('payloadSha256')==row['requestSha256'], 'attempt_parent_receipt_changed')
        if row['state']=='rejected':
            c.require(type(receipt.get('httpStatus')) is int and 300<=receipt['httpStatus']<=599,
                      'attempt_parent_rejection_unproven')
        else:c.require(type(receipt.get('response')) is dict, 'attempt_parent_return_unproven')
        if row['operationId'] is not None: budget._label(row['operationId'])
        if row['model']=='gpt-transcribe':
            c.require(type(row['bounds']) is dict and set(row['bounds'])=={'requests','wallTimeMs','costMicrousd'}
                and all(type(v) is int and 0<v<=10**15 for v in row['bounds'].values()),
                'attempt_parent_bounds_changed')
        else: budget._amounts(row['bounds'],positive=True)
        c.require(row['bounds']['requests']==1, 'attempt_parent_bounds_changed')
        snapshots.append({'path':str(path),'bytesSha256':c.bytes_sha256(raw)})
    for key,row in ledger['reservations'].items():
        store._validate_row(key,row)
        c.require(_legacy_observation or (row['phase']=='result' and row['result']['executionStatus']!='outcome_unknown'),
                  'attempt_parent_reconciliation_required')
    provider_cost=sum(row['bounds']['costMicrousd'] for row in state['requests'].values())
    c.require(len(state['requests'])<=config['maxRequests'] and provider_cost<=config['hardLimitMicrousd'],
              'attempt_parent_authority_exceeded')
    budget_charge=budget._sum(list(ledger['reservations'].values()))
    result = {'planSha256':c.canonical_sha256(plan),'snapshots':snapshots,
        'requestCount':max(len(state['requests']),budget_charge['requests']),
        'reservedMicrousd':max(provider_cost,budget_charge['costMicrousd']),
        'clockDomain':state['clockDomain'],'startedMonotonic':state['startedMonotonic'],
        'totalWallSeconds':config['totalWallSeconds']}
    if _legacy_observation:
        unsettled = [key for key,row in ledger['reservations'].items() if row['phase'] != 'result'
                     or row['result']['executionStatus']=='outcome_unknown']
        result.update(unsettledBudgetReservations=unsettled, oldReplayAllowed=False, refundedMicrousd=0,
            observationStatus='legacy_unsettled_retained' if unsettled else 'terminal_known')
        if unsettled:
            # Conservative full authorization, never infer settlement or refund.
            result['requestCount']=max(result['requestCount'], config['maxRequests'],store.authority['globalBounds']['requests'])
            result['reservedMicrousd']=max(result['reservedMicrousd'],config['hardLimitMicrousd'],store.authority['globalBounds']['costMicrousd'])
    return result


def prepare_new_attempt(parent_plan, *, new_root, authorization, execution_identity, ancestor_plans=()):
    parents=[terminal_parent(plan) for plan in (parent_plan,*ancestor_plans)]
    c.require(len({row['planSha256'] for row in parents})==len(parents), 'attempt_duplicate_parent')
    keys={'schemaVersion','parentPlanSha256','parentSnapshotsSha256','instructionReferenceSha256',
          'newMaxRequests','newHardLimitMicrousd','newTotalWallSeconds',
          'cumulativeMaxRequests','cumulativeHardLimitMicrousd'}
    c.require(type(authorization) is dict and set(authorization)==keys
              and authorization['schemaVersion']==AUTH_SCHEMA, 'invalid_new_attempt_authorization')
    c.require(authorization['parentPlanSha256']==parents[0]['planSha256'] and
              authorization['parentSnapshotsSha256']==c.canonical_sha256(parents),
              'attempt_authorization_parent_changed')
    budget._hash(authorization['instructionReferenceSha256'])
    for key in keys-{'schemaVersion','parentPlanSha256','parentSnapshotsSha256','instructionReferenceSha256'}:
        c.require(type(authorization[key]) is int and 0<authorization[key]<=10**15,
                  'invalid_new_attempt_authorization')
    identity=extensions._identity(execution_identity)
    root=_safe_path(Path(new_root))
    c.require(root.is_absolute(), 'attempt_absolute_directory_required')
    for old in (parent_plan,*ancestor_plans):
        oldroot=_safe_path(Path(old['runDirectory']))
        c.require(root!=oldroot and root not in oldroot.parents and oldroot not in root.parents,
                  'attempt_roots_overlap')
    count=sum(row['requestCount'] for row in parents);cost=sum(row['reservedMicrousd'] for row in parents)
    c.require(count+authorization['newMaxRequests']<=authorization['cumulativeMaxRequests'] and
              cost+authorization['newHardLimitMicrousd']<=authorization['cumulativeHardLimitMicrousd'],
              'attempt_cumulative_authority_exceeded')
    approval=c.canonical_sha256(authorization);config=deepcopy(parent_plan['providerConfig'])
    config.update(runId=c.canonical_sha256({'parents':parents,'authorizationSha256':approval,
                                          'executionIdentity':identity,'newRoot':str(root)}),
        approvalSha256=approval,codeSha256=c.canonical_sha256(identity),
        maxRequests=authorization['newMaxRequests'],hardLimitMicrousd=authorization['newHardLimitMicrousd'],
        targetMicrousd=min(config['targetMicrousd'],authorization['newHardLimitMicrousd']),
        totalWallSeconds=authorization['newTotalWallSeconds'])
    provider.validate_config(config)
    authority=deepcopy(parent_plan['authority']);authority['approvalSha256']=approval
    for scope in ('globalBounds','unitBounds'):
        authority[scope].update(requests=config['maxRequests'],costMicrousd=config['hardLimitMicrousd'])
    budget._authority(authority)
    plan={'schemaVersion':parent_plan['schemaVersion'],'runDirectory':str(root),'providerConfig':config,
          'authority':authority,'executionIdentity':identity,'sourceClipPath':parent_plan['sourceClipPath']}
    linkage={'schemaVersion':SCHEMA,'parentEvidence':parents,'authorizationSha256':approval,
        'newPlanSha256':c.canonical_sha256(plan),'priorRequestCount':count,'priorReservedMicrousd':cost,
        'oldLedgerAndDeadlineModified':False,'newProviderClock':'starts_on_first_new_provider_access',
        'successfulParentEvidence':'retained_revalidate_current_input_hashes_before_reuse',
        'productionEligible':False}
    return plan,linkage


def persist_new_attempt(plan, linkage, authorization):
    c.require(linkage['newPlanSha256']==c.canonical_sha256(plan) and
              linkage['authorizationSha256']==c.canonical_sha256(authorization), 'attempt_linkage_changed')
    for parent in linkage['parentEvidence']:
        for ref in parent['snapshots']:
            c.require(c.bytes_sha256(c.read_snapshot(Path(ref['path']))[1])==ref['bytesSha256'],
                      'attempt_parent_changed_before_persist')
    root=_safe_path(Path(plan['runDirectory']));root.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,value in [('run-plan.json',plan),('linked-history.json',linkage),('authorization.json',authorization)]:
        public.save_once(root/name,value)
    jobs._sync_directory_ancestry(root)
    return root

# v1 above remains readable for historical evidence. New execution uses v2.
SCHEMA_V2 = 'sermon-diagnostic-linked-attempt-v2'
AUTH_SCHEMA_V2 = 'sermon-diagnostic-new-attempt-authorization-v2'
BASELINE_SCHEMA = 'sermon-diagnostic-legacy-observation-v1'
CLOSED_SCHEMA = 'sermon-diagnostic-provider-closed-v1'
PRIVATE_KEYS = {'executionIdentity','providerConfig','authority','sourceClipPath','driverSha256',
                'parentLedgers','sourceParentRef','anchorParentRef'}


def _ref(path):
    path=_safe_path(Path(path));c.require(path.is_absolute() and path.is_file(),'attempt_snapshot_required')
    return {'path':str(path),'bytesSha256':c.bytes_sha256(path.read_bytes())}


def _verify_refs(refs):
    for ref in refs:
        c.require(_ref(ref['path']) == {'path':ref['path'],'bytesSha256':ref['bytesSha256']},'attempt_snapshot_changed')


def _project(path):
    path=_safe_path(Path(path));value,_=public.read_snapshot(path)
    if set(value)==PRIVATE_KEYS:
        root=path.parent
        value={**{key:value[key] for key in ('executionIdentity','providerConfig','authority','sourceClipPath')},
               'schemaVersion':'sermon-bounded-diagnostic-plan-v1','runDirectory':str(root)}
    else:
        root=_safe_path(Path(value['runDirectory']))
    if path != root/'run-plan.json':
        saved,_=public.read_snapshot(root/'run-plan.json')
        c.require(saved==value,'attempt_original_plan_path_required')
    return value,root


def _dependencies(path, original):
    _,root=_project(path);dependencies=[];refs=[]
    if set(original)==PRIVATE_KEYS:
        refs=[*original['parentLedgers'],original['sourceParentRef'],original['anchorParentRef']]
        _verify_refs(refs)
        dependencies += [Path(row['path']).parents[3]/'run-plan.json' for row in original['parentLedgers']]
    history=root/'linked-history.json'
    if history.exists():
        h,_=public.read_snapshot(history);refs.append(_ref(history))
        if h.get('schemaVersion')=='sermon-linked-diagnostic-history-v1':
            _verify_refs(h['parentArtifacts']);refs += h['parentArtifacts']
            dependencies += [Path(row['path']) for row in h['parentArtifacts']
                if row.get('purpose') in {'original_plan','immediate_parent_plan','original_ancestor_original_plan'}]
        elif h.get('schemaVersion') in {SCHEMA,SCHEMA_V2}:
            for row in h['parentEvidence']:
                _verify_refs(row['snapshots']);refs += row['snapshots']
                state=next(ref for ref in row['snapshots'] if ref['path'].endswith('/provider-run/state.json'))
                dependencies.append(Path(state['path']).parents[3]/'run-plan.json')
        else:raise c.ContractError('attempt_unknown_lineage_schema')
    return dependencies,refs


def observe_legacy_lineage(parent_plan_path, *, additional_plan_paths=(), excluded_empty_plan_paths=()):
    """Immutable provenance baseline, not recovery/settlement of an old D5 run."""
    queue=[Path(parent_plan_path),*map(Path,additional_plan_paths)];rows=[];seen={};allrefs={}
    while queue:
        path=_safe_path(queue.pop());original,_=public.read_snapshot(path)
        plan,root=_project(path)
        allrefs[str(path)]=_ref(path)
        if str(root) in seen:
            c.require(seen[str(root)]==c.canonical_sha256(plan),'attempt_duplicate_root_changed')
            allrefs[str(path)]=_ref(path)
            continue
        seen[str(root)]=c.canonical_sha256(plan)
        dependencies,refs=_dependencies(path,original);queue += dependencies
        observed=terminal_parent(plan,_legacy_observation=True)
        observed.update(originalPlan=_ref(root/'run-plan.json'),projectedPlan=plan,runDirectory=str(root),lineageRefs=refs)
        rows.append(observed)
        for ref in [observed['originalPlan'],*observed['snapshots'],*refs]:
            allrefs[ref['path']]={'path':ref['path'],'bytesSha256':ref['bytesSha256']}
    rows.sort(key=lambda row:row['runDirectory'])
    c.require(rows and len({row['projectedPlan']['providerConfig']['runId'] for row in rows})==len(rows),'attempt_duplicate_run_identity')
    scope={k:rows[0]['projectedPlan']['providerConfig'][k] for k in ('sourceMediaSha256','sourceClipSha256','sourceAudioSha256','sourceWindowSeconds')}
    c.require(all(all(row['projectedPlan']['providerConfig'][k]==v for k,v in scope.items()) for row in rows),'attempt_lineage_source_changed')
    exclusions=[]
    for path in excluded_empty_plan_paths:
        plan,root=_project(Path(path));c.require(str(root) not in seen and not (root/'budget').exists(),'attempt_exclusion_not_empty')
        c.require(all(plan['providerConfig'][k]==v for k,v in scope.items()),'attempt_lineage_source_changed')
        ref=_ref(path);exclusions.append({'originalPlan':ref,'runDirectory':str(root),'reason':'no_budget_or_provider_initialized','calls':0})
        allrefs[ref['path']]=ref
    return {'schemaVersion':BASELINE_SCHEMA,'parentPlan':_ref(parent_plan_path),'observations':rows,
        'excludedEmptyAttempts':exclusions,'snapshots':sorted(allrefs.values(),key=lambda row:row['path']),
        'priorRequestCount':sum(row['requestCount'] for row in rows),'priorReservedMicrousd':sum(row['reservedMicrousd'] for row in rows),
        'unknownProviderOutcomesAllowed':False,'oldReplayAllowed':False,'oldLedgersModified':False,
        'refundedMicrousd':0,'productionEligible':False}


def validate_baseline(baseline):
    c.require(type(baseline) is dict and baseline.get('schemaVersion')==BASELINE_SCHEMA,'attempt_legacy_baseline_required')
    _verify_refs(baseline['snapshots'])
    expected=observe_legacy_lineage(baseline['parentPlan']['path'],
        additional_plan_paths=[r['originalPlan']['path'] for r in baseline['observations']],
        excluded_empty_plan_paths=[r['originalPlan']['path'] for r in baseline['excludedEmptyAttempts']])
    c.require(expected==baseline,'attempt_legacy_baseline_changed')
    return baseline


def close_parent(plan_path, *, instruction_reference_sha256):
    """Permanently stop new requests under the same provider lock; no old rewrite."""
    budget._hash(instruction_reference_sha256)
    plan,root=_project(plan_path);store=budget.BudgetStore(root/'budget',plan['authority'])
    evidence=terminal_parent(plan,_legacy_observation=True)  # provider MUST be known, D5 remains labelled unsettled.
    path=root/'budget'/budget.STORE_ID/'provider-run/closed.json'
    receipt={'schemaVersion':CLOSED_SCHEMA,'runId':plan['providerConfig']['runId'],
        'runConfigSha256':c.canonical_sha256(plan['providerConfig']),'storeSha256':store.store_sha256,
        'providerStateFileSha256':evidence['snapshots'][0]['bytesSha256'],
        'budgetStateFileSha256':evidence['snapshots'][1]['bytesSha256'],
        'closureEvidenceSha256':c.canonical_sha256(evidence),'instructionReferenceSha256':instruction_reference_sha256,
        'productionEligible':False,'newDispatchAllowed':False}
    with store._locked():
        _verify_refs(evidence['snapshots'])
        public.save_once(path,receipt)
    return path


def _unavailable(row):
    plan=row['projectedPlan'];root=Path(row['runDirectory']);config=plan['providerConfig']
    closed=root/'budget'/budget.STORE_ID/'provider-run/closed.json'
    if closed.exists():
        receipt,_=public.read_snapshot(closed)
        store=budget.BudgetStore(root/'budget',plan['authority'])
        c.require(set(receipt)=={'schemaVersion','runId','runConfigSha256','storeSha256','providerStateFileSha256',
            'budgetStateFileSha256','closureEvidenceSha256','instructionReferenceSha256','productionEligible','newDispatchAllowed'}
            and receipt['schemaVersion']==CLOSED_SCHEMA and receipt['newDispatchAllowed'] is False
            and receipt['productionEligible'] is False and receipt['runId']==config['runId']
            and receipt['runConfigSha256']==c.canonical_sha256(config) and receipt['storeSha256']==store.store_sha256
            and receipt['providerStateFileSha256']==row['snapshots'][0]['bytesSha256'], 'attempt_parent_close_changed')
        return _ref(closed)
    c.require(provider.boot_identity()==row['clockDomain'] and
        time.monotonic() >= row['startedMonotonic']+row['totalWallSeconds'], 'attempt_parent_still_dispatchable')
    return None


def prepare_new_attempt_v2(parent_plan_path, *, new_root, authorization, execution_identity, baseline):
    baseline=validate_baseline(baseline);root=_safe_path(Path(new_root));identity=extensions._identity(execution_identity)
    keys={'schemaVersion','parentPlanSha256','legacyBaselineSha256','instructionReferenceSha256','newRoot','newRunId',
        'newMaxRequests','newHardLimitMicrousd','newTotalWallSeconds','cumulativeMaxRequests','cumulativeHardLimitMicrousd',
        'scope'}
    c.require(type(authorization) is dict and set(authorization)==keys and authorization['schemaVersion']==AUTH_SCHEMA_V2
        and authorization['scope']=='fresh_distinct_stage_no_old_replay','invalid_new_attempt_authorization_v2')
    c.require(_ref(parent_plan_path)==baseline['parentPlan'] and authorization['parentPlanSha256']==
        c.canonical_sha256(public.read_snapshot(parent_plan_path)[0]) and authorization['legacyBaselineSha256']==c.canonical_sha256(baseline),
        'attempt_authorization_parent_changed')
    c.require(root.is_absolute() and str(root)==authorization['newRoot'],'attempt_authorization_target_changed')
    budget._hash(authorization['newRunId']);budget._hash(authorization['instructionReferenceSha256'])
    for key in ('newMaxRequests','newHardLimitMicrousd','newTotalWallSeconds','cumulativeMaxRequests','cumulativeHardLimitMicrousd'):
        c.require(type(authorization[key]) is int and 0<authorization[key]<=10**15,'invalid_new_attempt_authorization')
    closes=[]
    for row in baseline['observations']:
        oldroot=Path(row['runDirectory']);c.require(root!=oldroot and root not in oldroot.parents and oldroot not in root.parents,'attempt_roots_overlap')
        c.require(authorization['newRunId'] != row['projectedPlan']['providerConfig']['runId'],'attempt_new_run_identity_required')
        ref=_unavailable(row)
        if ref:closes.append(ref)
    count=baseline['priorRequestCount'];cost=baseline['priorReservedMicrousd']
    c.require(count+authorization['newMaxRequests']<=authorization['cumulativeMaxRequests'] and
        cost+authorization['newHardLimitMicrousd']<=authorization['cumulativeHardLimitMicrousd'],'attempt_cumulative_authority_exceeded')
    parent,_=_project(parent_plan_path);config=deepcopy(parent['providerConfig']);approval=c.canonical_sha256(authorization)
    config.update(runId=authorization['newRunId'],approvalSha256=approval,codeSha256=c.canonical_sha256(identity),
        maxRequests=authorization['newMaxRequests'],hardLimitMicrousd=authorization['newHardLimitMicrousd'],
        targetMicrousd=min(config['targetMicrousd'],authorization['newHardLimitMicrousd']),totalWallSeconds=authorization['newTotalWallSeconds'])
    provider.validate_config(config);authority=deepcopy(parent['authority']);authority['approvalSha256']=approval
    for scope in ('globalBounds','unitBounds'):authority[scope].update(requests=config['maxRequests'],costMicrousd=config['hardLimitMicrousd'])
    budget._authority(authority)
    plan=dict(schemaVersion='sermon-bounded-diagnostic-plan-v1',runDirectory=str(root),providerConfig=config,
        authority=authority,executionIdentity=identity,sourceClipPath=parent['sourceClipPath'])
    linkage=dict(schemaVersion=SCHEMA_V2,parentEvidence=baseline['observations'],legacyObservationBaseline=baseline,
        authorizationSha256=approval,newPlanSha256=c.canonical_sha256(plan),priorRequestCount=count,priorReservedMicrousd=cost,
        parentClosureSnapshots=closes,newProviderClock='starts_on_first_new_provider_access',oldLedgerAndDeadlineModified=False,
        successfulParentEvidence='retain_only_explicit_current_input_bindings',oldReplayAllowed=False,productionEligible=False)
    successor,binding=_successor_binding(plan,baseline,authorization)
    if successor.exists():
        c.require(public.read_snapshot(successor)[0]==binding,'attempt_parent_successor_already_reserved')
    return plan,linkage


def _successor_binding(plan,baseline,authorization):
    parent,parentroot=_project(baseline['parentPlan']['path'])
    row=next(row for row in baseline['observations'] if row['runDirectory']==str(parentroot))
    key=c.canonical_sha256({'parentRunId':parent['providerConfig']['runId'],
        'providerStateFileSha256':row['snapshots'][0]['bytesSha256']})
    path=parentroot/'new-attempt-successors'/(key+'.json')
    binding={'parentSnapshotSha256':key,'legacyBaselineSha256':c.canonical_sha256(baseline),
        'authorizationSha256':c.canonical_sha256(authorization),'newRoot':plan['runDirectory'],
        'newRunId':plan['providerConfig']['runId'],'newPlanSha256':c.canonical_sha256(plan)}
    return path,binding


def persist_new_attempt_v2(plan,linkage,authorization):
    c.require(linkage['schemaVersion']==SCHEMA_V2 and linkage['newPlanSha256']==c.canonical_sha256(plan)
        and linkage['authorizationSha256']==c.canonical_sha256(authorization) and plan['runDirectory']==authorization['newRoot']
        and plan['providerConfig']['runId']==authorization['newRunId'],'attempt_linkage_changed')
    baseline=validate_baseline(linkage['legacyObservationBaseline']);_verify_refs(linkage['parentClosureSnapshots'])
    expected_plan,expected_linkage=prepare_new_attempt_v2(baseline['parentPlan']['path'],
        new_root=plan['runDirectory'],authorization=authorization,execution_identity=plan['executionIdentity'],baseline=baseline)
    c.require(plan==expected_plan and linkage==expected_linkage,'attempt_linkage_changed')
    closes=[]
    for row in baseline['observations']:
        ref=_unavailable(row)
        if ref:closes.append(ref)
    c.require(closes==linkage['parentClosureSnapshots'],'attempt_parent_close_changed')
    # One target in the authorization plus one immutable use record under its
    # parent prevents alternate-root reuse and crash acknowledgement ambiguity.
    parentplan,parent=_project(baseline['parentPlan']['path'])
    use=parent/'new-attempt-authorizations'/(c.canonical_sha256(authorization)+'.json')
    binding={'authorizationSha256':c.canonical_sha256(authorization),'newRoot':plan['runDirectory'],
        'newRunId':plan['providerConfig']['runId'],'newPlanSha256':c.canonical_sha256(plan)}
    successor,successor_binding=_successor_binding(plan,baseline,authorization)
    store=budget.BudgetStore(parent/'budget',parentplan['authority'])
    with store._locked():
        _verify_refs(baseline['snapshots']);_verify_refs(linkage['parentClosureSnapshots'])
        successor.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        public.save_once(successor,successor_binding)
        jobs._sync_directory_ancestry(successor.parent)
        use.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        public.save_once(use,binding)
        root=Path(plan['runDirectory']);root.mkdir(parents=True,exist_ok=True,mode=0o700)
        for name,value in [('run-plan.json',plan),('linked-history.json',linkage),('authorization.json',authorization),('legacy-observation.json',baseline)]:
            public.save_once(root/name,value)
        jobs._sync_directory_ancestry(root)
    return root

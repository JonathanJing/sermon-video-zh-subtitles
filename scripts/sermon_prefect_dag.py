"""Local, mock-only Prefect adapter around canonical nodes and durable jobs.

No producer, provider, human approval or publication adapter exists here. Prefect
is scheduling/visibility only: validated immutable receipts are the DAG inputs.
The existing job store owns process lifetime, single dispatch and uncertainty.
"""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import math
import re
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

from scripts import sermon_accounting as accounting
from scripts import sermon_dag_contract as contract
from scripts import sermon_log_profile as profile
from scripts import sermon_model_resources as resources
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock, utc_now

REPO = Path(__file__).resolve().parents[1]
CLOSURE = ('sermon_dag_contract.py', 'sermon_prefect_dag.py', 'run_sermon_prefect_dag.py',
           'canonical_pipeline_definition.py', 'sermon_workflow_jobs.py',
           'sermon_execution_harness.py', 'sermon_review_budget.py', 'sermon_model_resources.py',
           'sermon_accounting.py','sermon_log_profile.py','sermon_review_contracts.py')


def code_identity():
    return c.canonical_sha256({name: hashlib.sha256((REPO/'scripts'/name).read_bytes()).hexdigest()
                               for name in CLOSURE})


def read(path):
    return c.read_snapshot(Path(path))[0]


def save_once(path, value):
    path = Path(path)
    jobs._reject_link(path.parent, directory=True)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        c.require(read(path) == value, 'pilot_immutable_evidence_changed')
    else:
        jobs._persist(path, value)
        jobs._sync_directory_ancestry(path.parent)


def initialize(root, plan):
    """Caller owns work_lock. Never adopt an existing diagnostic/output folder."""
    root = Path(root)
    jobs._reject_link(root, directory=True)
    plan = contract.validate_plan(plan)
    if root.exists() and not (root/'plan.json').exists():
        c.require(not any(root.iterdir()), 'pilot_requires_empty_dedicated_root')
    save_once(root/'plan.json', plan)
    save_once(root/'runtime.json', {'codeSha256': code_identity(), 'mode': 'mock_only'})
    return root.resolve()


def load(root):
    root = Path(root)
    jobs._reject_link(root, directory=True)
    plan = contract.validate_plan(read(root/'plan.json'))
    c.require(read(root/'runtime.json') == {'codeSha256': code_identity(), 'mode': 'mock_only'},
              'pilot_code_changed_requires_explicit_migration')
    return plan


def amounts(n=1):
    # Synthetic quota dimensions; never exported as real provider tokens/spend.
    return dict(requests=n, inputTokens=n, outputTokens=n, wallTimeMs=30000*n, costMicrousd=n)


def mock_store(root, plan):
    authority = {'approvalSha256': plan['planSha256'], 'globalBounds': amounts(plan['mockRequestLimit']),
                 'unitBounds': amounts(), 'limits': dict(budget.DEFAULT_LIMITS)}
    return budget.BudgetStore(Path(root)/'mock-budget', authority)


def chain(plan, node):
    return dict(zip(budget.IDENTITY_FIELDS, [plan['inputIdentitySha256'], plan['planSha256'],
        plan['planSha256'], plan['planSha256'], plan['planSha256'], node['locale'],
        'l2.'+node['locale']+'.mock']))


def busy_retry(callback, deadline):
    """Only non-mutating lock contention is retryable, within this live invocation."""
    while True:
        try:
            return callback()
        except c.ContractError as exc:
            if str(exc) != 'budget_store_busy' or time.monotonic() >= deadline:
                raise
            time.sleep(.01)


def node_dir(root, node):
    return Path(root)/'nodes'/node['id']


def _core(plan, node, dependencies):
    identity = contract.node_identity(plan, node, dependencies)
    return {'schemaVersion': contract.RECEIPT_SCHEMA, 'runId': plan['runId'],
            'planSha256': plan['planSha256'], 'workUnitId': node['id'], 'identitySha256': identity,
            'attemptId': 'mock-1', 'revisionId': 'r1', 'dependencies': dependencies,
            'evidenceMode': 'synthetic', 'productionEligible': False,
            'realHumanStatus': 'pending' if node['humanGates'] else 'not_applicable',
            'simulatedHumanStatus': 'simulated' if node['humanGates'] and plan['simulatedHuman'] else 'not_applicable',
            'mockScenario': node['mockScenario']}


def valid_receipt(root, plan, node, dependencies):
    """Validate business result independently of Prefect/exit-code completion."""
    value = read(node_dir(root, node)/'receipt.json')
    core = _core(plan, node, dependencies)
    c.require(c.canonical_sha256({k:value.get(k) for k in core}) == c.canonical_sha256(core),
              'pilot_receipt_binding_changed')
    c.require(set(value) == set(core)|{'outputSha256','spanId','startedAt','completedAt','elapsedSeconds',
        'executionStatus','reviewVerdict','admissionStatus','reservationId'}, 'invalid_pilot_receipt')
    expected = {'identitySha256': core['identitySha256'], 'syntheticOutput': True,
                'audioDisposition': 'audio_unavailable' if node['layer']==3 and
                node['locale'] in plan['definition']['textOnlyLocales'] else 'mock_artifact'}
    output = read(node_dir(root, node)/'output.json')
    c.require(c.canonical_sha256(output) == c.canonical_sha256(expected) == value['outputSha256'], 'pilot_output_changed')
    c.require(type(value['spanId']) is str and re.fullmatch('[a-f0-9]{32}',value['spanId']) is not None
              and type(value['elapsedSeconds']) in (int,float) and math.isfinite(value['elapsedSeconds'])
              and value['elapsedSeconds'] >= 0, 'invalid_pilot_measurement')
    for key in ('startedAt','completedAt'):
        c.require(type(value[key]) is str and datetime.fromisoformat(value[key]).tzinfo is not None,
                  'invalid_pilot_timestamp')
    c.require(value['executionStatus'] == 'succeeded' and value['reviewVerdict'] == 'synthetic_pass'
              and value['admissionStatus'] == 'mock_only' and node['mockScenario'] == 'pass',
              'pilot_result_not_successful')
    # The receipt's exact bytes/facts must have been observed inside a completed
    # worker stage. Scheduler success or a free-form span ID is insufficient.
    events,damaged=accounting.read_events(Path(root)/'accounting')
    c.require(not damaged,'pilot_accounting_damaged')
    integrity=accounting.profile_integrity(events)
    selected=[r for r in events if id(r) in integrity['_selected'] and id(r) not in integrity['_excluded']]
    expected_job=jobs._digest({'pilotPlanSha256':plan['planSha256'],'nodeIdentitySha256':core['identitySha256']})
    matching=[r for r in selected if r.get('spanId')==value['spanId'] and r.get('jobId')==expected_job
              and r.get('workUnitId')==node['id'] and r.get('evidenceMode')=='synthetic']
    ends=[r for r in matching if r['event']=='stage_finished' and r.get('status')=='completed']
    proofs=[r for r in matching if r['event']=='workload' and
            r.get('metrics',{}).get('receiptSha256')==c.canonical_sha256(value)]
    c.require(len(ends)==1 and len(proofs)==1 and value['elapsedSeconds']<=ends[0]['elapsedSeconds']+.01,
              'pilot_receipt_trace_binding_missing')
    if node['layer'] == 2:
        store = mock_store(root, plan)
        ledger = read(store.root/budget.STORE_ID/'state.json')
        c.require(ledger.get('authority') == store.authority and ledger.get('storeSha256') == store.store_sha256
                  and ledger.get('schemaVersion') == budget.SCHEMA, 'pilot_budget_identity_changed')
        row = ledger['reservations'].get(value['reservationId'])
        if row is not None: store._validate_row(value['reservationId'],row)
        c.require(row is not None and row['request']['identity'] == chain(plan,node)
                  and row['request']['inputSha256'] == core['identitySha256'] and row['phase']=='result'
                  and row['result'] == {'executionStatus':'succeeded','contentStatus':'pass',
                      'receiptSha256':c.canonical_sha256(value),'usage':amounts()}, 'pilot_budget_not_settled')
    else:
        c.require(value['reservationId'] is None, 'unexpected_pilot_reservation')
    return value


def dependency_receipts(root, plan, node):
    by_id = {n['id']:n for n in plan['nodes']}
    receipts = {}
    for key in node['dependsOn']:
        parent = by_id[key]
        ancestors = dependency_receipts(root, plan, parent)
        receipts[key] = valid_receipt(root, plan, parent, {k:v['outputSha256'] for k,v in ancestors.items()})
    return receipts


def worker(root, node_id, request_sha):
    """Fixed trusted subprocess entry; absolutely no networking, even loopback."""
    def denied(*args, **kwargs):
        raise RuntimeError('mock_pilot_network_forbidden')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    plan = load(root)
    node = next(n for n in plan['nodes'] if n['id'] == node_id)
    folder = node_dir(root,node)
    request = read(folder/'request.json')
    c.require(c.canonical_sha256(request) == request_sha, 'pilot_request_changed')
    deps = dependency_receipts(root,plan,node)
    dependencies = {k:v['outputSha256'] for k,v in deps.items()}
    core = _core(plan,node,dependencies)
    c.require(request['identitySha256'] == core['identitySha256'], 'pilot_worker_identity_changed')
    c.require(not node['humanGates'] or plan['simulatedHuman'], 'pilot_real_human_gate_pending')
    lease = resources.local_model_slot(timeout=20) if node['resourcePool']=='local_model' else nullcontext()
    with lease:
        with accounting.stage('pilot.mock.'+node_id, executor_type='deterministic_program',
                depends_on=[v['spanId'] for v in deps.values()], work_unit_id=node_id,
                attempt_id='mock-1', dependency_ready_at=request['dependencyReadyAt'], queued_at=request['queuedAt']) as span:
            started, tick = utc_now(), time.monotonic()
            rid, store = None, None
            if node['layer']==2:
                store = mock_store(root,plan)
                deadline = tick+20
                try:
                    reservation = busy_retry(lambda: store.reserve(chain(plan,node), operation_id='mock.initial',
                        kind='initial_generation', revision_id='r1', revision_number=1,
                        input_sha256=core['identitySha256'], bounds=amounts()),deadline)
                except c.ContractError as exc:
                    if str(exc) in {'budget_exhausted','budget_store_busy','budget_reconciliation_required'}:
                        save_once(folder/'failure.json',{**core,'executionStatus':'blocked','reason':str(exc)})
                    raise
                c.require(reservation['created'], 'pilot_budget_reconciliation_required')
                rid = reservation['reservationId']
                busy_retry(lambda: store.mark_request(rid),deadline)
            time.sleep(plan['mockDelaySeconds'])
            scenario = node['mockScenario']
            if scenario != 'pass':
                status = 'outcome_unknown' if scenario=='outcome_unknown' else 'failed'
                evidence = {**core, 'executionStatus':status, 'reason':'controlled_'+scenario}
                save_once(folder/'failure.json',evidence)
                if store is not None:
                    busy_retry(lambda: store.record_result(rid, {'executionStatus':status,
                        'contentStatus':'not_assessed','receiptSha256':c.canonical_sha256(evidence),
                        'usage':None if status=='outcome_unknown' else amounts()}),time.monotonic()+5)
                raise RuntimeError('controlled_'+scenario)
            output = {'identitySha256':core['identitySha256'],'syntheticOutput':True,
                'audioDisposition':'audio_unavailable' if node['layer']==3 and
                node['locale'] in plan['definition']['textOnlyLocales'] else 'mock_artifact'}
            receipt = {**core, 'outputSha256':c.canonical_sha256(output), 'spanId':span,
                'startedAt':started, 'completedAt':utc_now(), 'elapsedSeconds':time.monotonic()-tick,
                'executionStatus':'succeeded','reviewVerdict':'synthetic_pass','admissionStatus':'mock_only',
                'reservationId':rid}
            save_once(folder/'output.json',output)
            save_once(folder/'receipt.json',receipt)
            accounting.record_workload('pilot.mock.receipt',{'receiptSha256':c.canonical_sha256(receipt),
                'planSha256':plan['planSha256'],'nodeIdentitySha256':core['identitySha256'],'synthetic':True})
            if store is not None:
                busy_retry(lambda: store.record_result(rid, {'executionStatus':'succeeded',
                    'contentStatus':'pass','receiptSha256':c.canonical_sha256(receipt),'usage':amounts()}),time.monotonic()+5)
    return 0


class Runner:
    """Trusted scheduling adapter; derivative observations never grant dispatch."""
    def __init__(self,root,plan):
        self.root, self.plan = Path(root), plan
        self.pools = {k:threading.BoundedSemaphore(n) for k,n in plan['resourceLimits'].items()}
        self.observations = {}
        self.lock = threading.Lock()
        # A restarted scheduler cannot assume its fresh semaphores own the
        # slots of surviving processes. Read-only inspection never resets them.
        self.dispatch_closed = False
        prior_root=self.root/'jobs'
        if prior_root.exists():
            for folder in prior_root.iterdir():
                if re.fullmatch('[a-f0-9]{64}',folder.name):
                    state=jobs.peek_job(prior_root,folder.name)
                    if state['status'] in jobs.ACTIVE|{'uncertain'}:
                        self.dispatch_closed=True

    def observe(self,node,status,reason=None,**extra):
        value = {'runId':self.plan['runId'],'planSha256':self.plan['planSha256'],'workUnitId':node['id'],
            'executionStatus':status,'reason':reason,'observedAt':utc_now(), 'evidenceMode':'synthetic',
            'productionEligible':False, **extra}
        with self.lock:
            self.observations[node['id']] = value
            snapshot = {'schemaVersion':contract.SNAPSHOT_SCHEMA,'runId':self.plan['runId'],
                'planSha256':self.plan['planSha256'],'productionEligible':False,
                'nodes':dict(self.observations),'observedAt':utc_now()}
            jobs._persist(self.root/'snapshot.json',snapshot)
        return value

    def execute(self,node,upstream=(),*,flow_run_id=None,task_run_id=None):
        metadata = dict(flowRunId=flow_run_id,taskRunId=task_run_id)
        if self.dispatch_closed:
            return self.observe(node,'blocked','prior_worker_lifetime_unresolved',**metadata)
        if any(v['executionStatus']!='completed' for v in upstream):
            return self.observe(node,'blocked','upstream_not_admitted',**metadata)
        if node['humanGates'] and not self.plan['simulatedHuman']:
            return self.observe(node,'blocked','real_human_review_pending',**metadata)
        try:
            deps = dependency_receipts(self.root,self.plan,node)
            dependencies = {k:v['outputSha256'] for k,v in deps.items()}
            ident = contract.node_identity(self.plan,node,dependencies)
            folder = node_dir(self.root,node)
            request_path = folder/'request.json'
            request = {'identitySha256':ident,'dependencyReadyAt':utc_now(),'queuedAt':utc_now()}
            if request_path.exists():
                request = read(request_path)
                c.require(request['identitySha256']==ident,'pilot_request_identity_changed')
            save_once(request_path,request)
            job_identity = {'pilotPlanSha256':self.plan['planSha256'],'nodeIdentitySha256':ident}
            job_id = jobs._digest(job_identity)
            metadata.update(jobId=job_id,identitySha256=ident,attemptId='mock-1')
            self.observe(node,'queued','resource_admission',**metadata)
            with self.pools[node['resourcePool']]:
                if self.dispatch_closed:
                    return self.observe(node,'blocked','prior_worker_lifetime_unresolved',**metadata)
                argv = [sys.executable,str(REPO/'scripts/run_sermon_prefect_dag.py'),'worker',
                        '--root',str(self.root),'--node',node['id'],'--request-sha',c.canonical_sha256(request)]
                with profile.context(workKind='control',evidenceMode='synthetic',workUnitId=node['id'],attemptId='mock-1'):
                    state = jobs.start_job(self.root/'jobs',job_identity,argv,node['timeoutSeconds'])
                poll_deadline = time.monotonic()+node['timeoutSeconds']+5
                while state['status'] in jobs.ACTIVE and time.monotonic()<poll_deadline:
                    self.observe(node,'running' if state['status']=='running' else 'queued',**metadata)
                    time.sleep(.1)
                    state = jobs.inspect_job(self.root/'jobs',job_id)
                if state['status']!='succeeded':
                    if state['status'] in jobs.ACTIVE|{'uncertain'}:
                        # Latch BEFORE leaving the semaphore. No waiting/new
                        # branch may consume a permit whose old process may live.
                        self.dispatch_closed=True
                    status = 'outcome_unknown' if state['status'] in jobs.ACTIVE|{'uncertain'} else 'failed'
                    failure_path = folder/'failure.json'
                    reason='durable_job_'+state['status']
                    ledger_path=self.root/'mock-budget'/budget.STORE_ID/'state.json'
                    if node['layer']==2 and ledger_path.exists():
                        ledger=read(ledger_path)
                        if any(row['request']['identity']==chain(self.plan,node) and
                               (row['phase']!='result' or row['result']['executionStatus']=='outcome_unknown')
                               for row in ledger['reservations'].values()):
                            status,reason='outcome_unknown','budget_reconciliation_required'
                    if failure_path.exists():
                        failure=read(failure_path)
                        c.require(all(failure.get(k)==v for k,v in _core(self.plan,node,dependencies).items()),
                                  'pilot_failure_binding_changed')
                        if failure.get('executionStatus') in {'outcome_unknown','blocked'}:
                            status=failure['executionStatus']
                        reason=failure['reason']
                    return self.observe(node,status,reason,**metadata)
                receipt = valid_receipt(self.root,self.plan,node,dependencies)
                return self.observe(node,'completed',receiptSha256=c.canonical_sha256(receipt),
                    outputSha256=receipt['outputSha256'],spanId=receipt['spanId'],
                    reviewVerdict=receipt['reviewVerdict'],realHumanStatus=receipt['realHumanStatus'],
                    simulatedHumanStatus=receipt['simulatedHumanStatus'],admissionStatus='mock_only',**metadata)
        except (ValueError,OSError) as exc:
            # No raw exception message/body enters projection. The immutable job
            # files retain local evidence; uncertain/missing proof never retries.
            return self.observe(node,'blocked','evidence_or_admission_failed',errorType=type(exc).__name__,**metadata)


def isolated_prefect_environment(root):
    """Fresh CLI process only; reject ambient settings without printing values."""
    c.require('prefect' not in sys.modules, 'pilot_requires_fresh_prefect_process')
    c.require(not any(key.upper().startswith('PREFECT_') for key in os.environ),
              'pilot_rejects_ambient_prefect_settings')
    home=Path(root)/'prefect'
    jobs._reject_link(home,directory=True)
    jobs._reject_link(home/'prefect.db',directory=False)
    jobs._reject_link(home/'profiles.toml',directory=False)
    database='sqlite+aiosqlite:///'+str(home/'prefect.db')
    os.environ.update(PREFECT_HOME=str(home),PREFECT_PROFILES_PATH=str(home/'profiles.toml'),
        PREFECT_SERVER_DATABASE_CONNECTION_URL=database,PREFECT_LOCAL_STORAGE_PATH=str(home/'storage'),
        PREFECT_SERVER_ALLOW_EPHEMERAL_MODE='true',PREFECT_SERVER_ANALYTICS_ENABLED='false',
        PREFECT_LOGGING_TO_API_ENABLED='false',PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY='false')
    return home,database


def run(root,plan):
    """Run one local Prefect flow. No deployment/cloud profile or automatic retry."""
    root = Path(root).absolute()
    with work_lock(root):
        root = initialize(root,plan)
        home,database=isolated_prefect_environment(root)
        from prefect import flow, task
        from prefect.cache_policies import NO_CACHE
        from prefect.context import get_run_context
        from prefect.task_runners import ThreadPoolTaskRunner
        from prefect.settings import get_current_settings
        settings=get_current_settings()
        c.require(settings.api.url is None and settings.api.key is None and settings.home==home
                  and settings.server.database.connection_url.get_secret_value()==database
                  and settings.results.local_storage_path==home/'storage'
                  and not settings.server.analytics_enabled and not settings.cloud.enable_orchestration_telemetry,
                  'pilot_prefect_settings_not_isolated')
        runner = Runner(root,plan)
        @task(retries=0,cache_policy=NO_CACHE,persist_result=False)
        def dispatch(node,upstream):
            ctx = get_run_context()
            return runner.execute(node,upstream,flow_run_id=str(ctx.task_run.flow_run_id),task_run_id=str(ctx.task_run.id))
        @flow(name='sermon-local-mock-dag',retries=0,persist_result=False,
              task_runner=ThreadPoolTaskRunner(max_workers=10))
        def orchestrate():
            futures = {}
            for node in plan['nodes']:
                futures[node['id']] = dispatch.submit(node,[futures[d] for d in node['dependsOn']])
            return {key:value.result() for key,value in futures.items()}
        with profile.session(root/'accounting','canonical_prefect_mock',
                {'evidenceMode':'synthetic','planSha256':plan['planSha256']},work_kind='control',evidence_mode='synthetic') as session:
            save_once(root/'accounting-sessions'/(session['runId']+'.json'),
                {'runId':plan['runId'],'planSha256':plan['planSha256'],
                 'accountingRunId':session['runId'],'codeSha256':code_identity(),
                 'mode':'mock_only','productionEligible':False})
            return orchestrate()

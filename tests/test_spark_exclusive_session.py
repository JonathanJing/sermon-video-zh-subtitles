import copy
import json
import os
from pathlib import Path
from unittest.mock import patch
import pytest
from scripts.spark_exclusive_session import Engine, Client, SessionError, UNITS, RESTORE_ORDER, LinuxBackend, dispatch, RESOURCE_TRACKER_HELPER, RESOURCE_TRACKER_ARGUMENT

class FakeBackend:
    def __init__(self):
        self.calls = []
        self.value = {'host': 'spark', 'bootId': 'boot-1', 'units': {}, 'containers': [], 'gpu': [], 'processes': [],
                      'queue': {'pending': 0, 'claimed': 0, 'outstanding': 0}, 'memAvailableBytes': 100 * 1024**3,
                      'modelHealth': {'healthy': True, 'modelIds': ['original-model'], 'processingSlots': 0}}
        for index, name in enumerate(UNITS, 10):
            self.value['units'][name] = {'name': name, 'active': 'active', 'sub': 'running', 'mainPid': index,
                                         'identity': name + '-hash', 'controlGroup': '/user/' + name, 'killMode': 'control-group'}
            self.value['processes'].append({'pid': index, 'ppid': 1, 'startTicks': index * 100, 'executable': 'service',
                                             'role': 'model' if name == 'llama-server.service' else None, 'cgroup': '/user/' + name})
        self.value['gpu'] = [{'pid': 13, 'executable': 'llama-server', 'usedMiB': None}]
        self.fail_after_stop = None
        self.fail_start = None
        self.health_failure = False

    def inventory(self): return copy.deepcopy(self.value)
    def stable_memory(self, minimum):
        if self.value['memAvailableBytes'] < minimum: raise SessionError('insufficient_available_memory')
        return [self.value['memAvailableBytes']] * 3
    def stop_unit(self, name, *, preempt=False):
        self.calls.append(('stop', name, preempt))
        pid = self.value['units'][name]['mainPid']
        self.value['units'][name]['active'] = 'inactive'; self.value['units'][name]['mainPid'] = 0
        removed = Engine.descendants(self.value['processes'], [(pid, pid * 100)])
        self.value['processes'] = [p for p in self.value['processes'] if p['pid'] not in removed]
        self.value['gpu'] = [p for p in self.value['gpu'] if p['pid'] not in removed]
        if name == self.fail_after_stop: raise SessionError('timeout_unknown')
    def start_unit(self, name):
        self.calls.append(('start', name))
        if name == self.fail_start: raise SessionError('start_unknown')
        self.value['units'][name]['active'] = 'active'
    def stop_container(self, cid):
        self.calls.append(('stop-container', cid)); next(c for c in self.value['containers'] if c['id'] == cid)['running'] = False
        self.value['processes'] = [p for p in self.value['processes'] if p['pid'] != 200]
    def start_container(self, cid): self.calls.append(('start-container', cid)); next(c for c in self.value['containers'] if c['id'] == cid)['running'] = True
    def wait_model_health(self, original):
        if self.health_failure: raise SessionError('model_health_not_restored')
        return original
    def backup_state(self, path):
        self.calls.append(('backup', str(path)))
        return {'path': str(path), 'sha256': {'enqueue.sqlite': 'abc'}}

@pytest.fixture
def engine(tmp_path):
    backend = FakeBackend()
    return Engine(tmp_path, backend)

def begin(engine, **kwargs): return engine.begin('session', 'owner', 90, **kwargs)

def test_closed_ledger_ignores_migration_snapshot_and_rejects_new_work(engine):
    begin(engine)
    assert engine.finish('session', 'owner')['status'] == 'closed'
    (engine.root / 'session.before-controller-migration-stale.json').write_text(
        json.dumps({'status': 'reconcile_required', 'sessionId': 'stale'}), encoding='utf-8')
    assert engine.load()['status'] == 'closed'
    assert engine.load()['sessionId'] == 'session'
    with pytest.raises(SessionError, match='session_not_ready'):
        engine.job_start('session', 'owner', 'next-run')


def test_full_lifecycle_restores_original_only(engine):
    inactive = 'llama-performance-collector.service'
    engine.backend.value['units'][inactive].update(active='inactive', mainPid=0)
    state = begin(engine)
    assert state['status'] == 'exclusive_ready'
    assert engine.require('session', 'owner')['status'] == 'exclusive_ready'
    first = engine.job_start('session', 'owner', 'first', {'host': 'mac', 'pid': 42})
    with pytest.raises(SessionError, match='jobs_prevent_restore'): engine.finish('session', 'owner')
    engine.job_end('session', 'owner', first['jobId'], 'known_terminal', True)
    second = engine.job_start('session', 'owner', 'second')
    engine.job_end('session', 'owner', second['jobId'], 'known_terminal', True)
    assert not any(call[0] == 'start' for call in engine.backend.calls)
    result = engine.finish('session', 'owner')
    assert result['status'] == 'closed'
    assert [('start', name) for name in RESTORE_ORDER if name != inactive] == [call for call in engine.backend.calls if call[0] == 'start']
    count = len(engine.backend.calls)
    engine.finish('session', 'owner')
    assert len(engine.backend.calls) == count
    assert all(event['revision'] == i + 1 for i, event in enumerate(result['events']))

def test_double_owner_and_configuration_binding(engine):
    begin(engine)
    with pytest.raises(SessionError, match='owner_mismatch'): engine.begin('session', 'different', 90)
    with pytest.raises(SessionError, match='configuration_changed'): engine.begin('session', 'owner', 91)
    assert begin(engine)['status'] == 'exclusive_ready'

@pytest.mark.parametrize('case', ['queue', 'child', 'gpu', 'container', 'memory', 'model_slots'])
def test_begin_fail_closed(engine, case):
    v = engine.backend.value
    if case == 'queue': v['queue']['claimed'] = 1
    if case == 'child': v['processes'].append({'pid': 500, 'ppid': 11, 'startTicks': 900, 'cgroup': '/user/spark-agent.service'})
    if case == 'gpu': v['gpu'].append({'pid': 500, 'usedMiB': None})
    if case == 'container': v['containers'].append({'id': 'f'*64, 'running': True})
    if case == 'memory': v['memAvailableBytes'] = 1
    if case == 'model_slots': v['modelHealth']['processingSlots'] = 1
    with pytest.raises(SessionError): begin(engine)
    assert not any(call[0] == 'start' for call in engine.backend.calls)

def test_unknown_stop_never_implicitly_restore_and_reconcile(engine):
    engine.backend.fail_after_stop = 'llama-server.service'
    with pytest.raises(SessionError, match='reconciliation'): begin(engine)
    assert engine.load()['status'] == 'reconcile_required'
    assert not any(call[0] == 'start' for call in engine.backend.calls)
    with pytest.raises(SessionError, match='reconciliation'): engine.finish('session', 'owner')
    engine.backend.fail_after_stop = None
    assert engine.reconcile('session', 'owner')['status'] == 'planning'
    assert engine.resume_begin('session', 'owner')['status'] == 'exclusive_ready'
    assert engine.finish('session', 'owner')['status'] == 'closed'

def test_unknown_job_and_exact_exit_reconciliation(engine):
    begin(engine)
    job = engine.job_start('session', 'owner', 'tts')
    engine.backend.value['processes'].append({'pid': 501, 'ppid': 1, 'startTicks': 998, 'role': None})
    engine.job_bind('session', 'owner', job['jobId'], 501)
    with pytest.raises(SessionError, match='still_alive'): engine.job_end('session', 'owner', job['jobId'], 'known_terminal', True)
    with pytest.raises(SessionError, match='reconciliation'): engine.job_end('session', 'owner', job['jobId'], 'unknown', False)
    with pytest.raises(SessionError, match='not_ready'): engine.require('session', 'owner')
    engine.backend.value['processes'] = []
    state = engine.reconcile('session', 'owner', job_id=job['jobId'])
    assert state['jobs'][job['jobId']]['status'] == 'terminal'
    assert engine.resume_begin('session', 'owner')['status'] == 'exclusive_ready'


def test_boot_identity_and_external_restart_hold(engine):
    begin(engine)
    engine.backend.value['bootId'] = 'boot-2'
    with pytest.raises(SessionError, match='boot_identity'): engine.require('session', 'owner')
    with pytest.raises(SessionError, match='boot_identity'): engine.finish('session', 'owner')
    assert engine.load()['status'] == 'reconcile_required'


def test_external_service_or_unit_identity_changes_block(engine):
    begin(engine)
    engine.backend.value['units']['llama-server.service']['active'] = 'active'
    with pytest.raises(SessionError, match='competing_service'): engine.require('session', 'owner')
    engine.backend.value['units']['llama-server.service']['active'] = 'inactive'
    engine.backend.value['units']['llama-server.service']['identity'] = 'changed'
    with pytest.raises(SessionError, match='identity_changed'): engine.finish('session', 'owner')


def test_restore_unknown_is_not_retried_without_readback(engine):
    begin(engine); engine.backend.fail_start = 'llama-server.service'
    with pytest.raises(SessionError, match='reconciliation'): engine.finish('session', 'owner')
    assert engine.load()['status'] == 'restoring_failed'
    with pytest.raises(SessionError, match='reconciliation'): engine.finish('session', 'owner')
    with pytest.raises(SessionError, match='not_proven'): engine.reconcile('session', 'owner')
    # Operator readback proves original unit already started, then continuation
    # performs no duplicate start and finishes collector/admission restoration.
    engine.backend.value['units']['llama-server.service']['active'] = 'active'
    engine.backend.fail_start = None
    engine.reconcile('session', 'owner')
    assert engine.finish('session', 'owner')['status'] == 'closed'
    assert sum(call == ('start', 'llama-server.service') for call in engine.backend.calls) == 1


def test_model_health_failure_retry_does_not_respawn(engine):
    begin(engine); engine.backend.health_failure = True
    with pytest.raises(SessionError, match='health_not_restored'): engine.finish('session', 'owner')
    assert engine.load()['status'] == 'restoring_failed'
    engine.backend.health_failure = False
    assert engine.finish('session', 'owner')['status'] == 'closed'
    assert engine.backend.calls.count(('start', 'llama-server.service')) == 1


def test_own_bound_descendants_allowed_unknown_gpu_blocks(engine):
    begin(engine); job = engine.job_start('session', 'owner', 'tts')
    engine.backend.value['processes'] += [{'pid': 500, 'ppid': 1, 'startTicks': 100}, {'pid': 501, 'ppid': 500, 'startTicks': 200, 'role': 'worker'}]
    engine.job_bind('session', 'owner', job['jobId'], 500)
    engine.backend.value['gpu'] = [{'pid': 501, 'usedMiB': None}]
    assert engine.require('session', 'owner')['status'] == 'running'
    engine.backend.value['gpu'].append({'pid': 502})
    with pytest.raises(SessionError, match='unmanaged_gpu'): engine.require('session', 'owner')


def test_auto_remove_and_container_identity(engine):
    cid = 'f'*64
    engine.backend.value['containers'] = [{'id': cid, 'image': 'image', 'running': False, 'autoRemove': True, 'identity': 'cid'}]
    with pytest.raises(SessionError, match='auto_remove'): begin(engine, container_ids=[cid])
    engine.backend.value['containers'][0]['autoRemove'] = False
    begin(engine, container_ids=[cid]); engine.backend.value['containers'][0]['identity'] = 'changed'
    with pytest.raises(SessionError, match='identity_changed'): engine.finish('session', 'owner')


def test_snapshot_no_environment_values_and_private_permissions(engine):
    begin(engine)
    serialized = engine.path.read_text()
    assert 'Environment=' not in serialized
    assert engine.path.stat().st_mode & 0o777 == 0o600


def test_preemption_private_snapshot_before_stop_and_unknown_calls_barrier(engine):
    engine.backend.value['queue']['claimed'] = 1
    engine.backend.value['queue']['outstanding'] = 1
    with pytest.raises(SessionError, match='authorization_required'): begin(engine, preempt=True)
    state = begin(engine, preempt=True, allow_interrupted_restart=True)
    assert state['status'] == 'exclusive_ready'
    assert engine.backend.calls[0][0] == 'backup'
    assert all(call[2] for call in engine.backend.calls if call[0] == 'stop')
    assert engine.require('session', 'owner')['status'] == 'exclusive_ready'
    with pytest.raises(SessionError, match='foreign_dispatch'): engine.finish('session', 'owner')
    engine.backend.value['queue']['claimed'] = 0; engine.backend.value['queue']['outstanding'] = 0
    assert engine.finish('session', 'owner')['status'] == 'closed'


def test_client_contract_env_and_read_only_gateway(engine):
    begin(engine)
    requests = []
    def runner(request): requests.append(request); return dispatch(request, engine)
    client = Client('session', 'owner', runner=runner)
    assert client.environment['SPARK_EXCLUSIVE_SESSION_ID'] == 'session'
    client.require_ready(); hold = client.start_job('cli', pid=42)
    client.end_job(hold, process_exited=True, outcome='known_terminal')
    assert hold['dispatcher']['pid'] == 42
    with patch.dict(os.environ, {'SPARK_EXCLUSIVE_SOCKET': '/no-socket'}):
        with pytest.raises(SessionError, match='read_only'): Client('session', 'owner').start_job('cli')


def test_explicit_memory_required(engine):
    for value in (0, -1, float('nan'), float('inf')):
        with pytest.raises(SessionError, match='memory_minimum'): engine.begin('session', 'owner', value)


def test_preempt_native_request_records_interruption_without_replay(engine):
    engine.backend.value['modelHealth']['processingSlots'] = 2
    state = begin(engine, preempt=True, allow_interrupted_restart=True)
    assert state['interruptedWork']['interruptedNativeInference'] == 2
    assert state['interruptedWork']['nativeCallerResubmitRequired'] is True
    assert not state['interruptedWork']['requiresDispatchReconciliation']
    assert engine.finish('session', 'owner')['status'] == 'closed'
    assert all(call[0] != 'inference' for call in engine.backend.calls)


def test_unknown_unbound_dispatcher_hold_cannot_release_on_flag(engine):
    begin(engine); job = engine.job_start('session', 'owner', 'mac-cli')
    with pytest.raises(SessionError, match='reconciliation'): engine.job_end('session', 'owner', job['jobId'], 'unknown', False)
    with pytest.raises(SessionError, match='dispatcher_terminal_receipt'): engine.job_end('session', 'owner', job['jobId'], 'known_terminal', True)
    with pytest.raises(SessionError, match='dispatcher_terminal_receipt'): engine.reconcile('session', 'owner', job_id=job['jobId'])
    assert engine.load()['jobs'][job['jobId']]['status'] == 'unknown'


def test_unknown_unbound_dispatcher_hold_accepts_bound_terminal_observation(engine):
    begin(engine); job = engine.job_start('session', 'owner', 'production-model-call',
        dispatcher={'host': 'MacBookPro.localdomain', 'pid': 9363})
    with pytest.raises(SessionError, match='reconciliation'):
        engine.job_end('session', 'owner', job['jobId'], 'unknown', False)
    receipt = {'schemaVersion':'spark-dispatcher-terminal-observation-v1',
        'jobId':job['jobId'],'dispatcher':job['dispatcher'],
        'dispatcherProcessExited':True,'modelChildProcessesExited':True,
        'evidenceScope':'local_process_census','observedAt':'2026-10-05T00:00:00Z',
        'processCensusSha256':'a'*64}
    result=engine.reconcile('session','owner',job_id=job['jobId'],dispatcher_terminal_receipt=receipt)
    assert result['jobs'][job['jobId']]['status']=='terminal'
    assert result['jobs'][job['jobId']]['dispatcherTerminalReceipt']==receipt


def test_reconciling_unknown_job_keeps_other_active_job_running(engine):
    begin(engine)
    unknown = engine.job_start('session', 'owner', 'production-model-call',
        dispatcher={'host': 'mac', 'pid': 12345})
    engine.job_start('session', 'owner', 'diagnostic-dag')
    with pytest.raises(SessionError, match='reconciliation'):
        engine.job_end('session', 'owner', unknown['jobId'], 'unknown', False)
    receipt = {'schemaVersion': 'spark-dispatcher-terminal-observation-v1',
        'jobId': unknown['jobId'], 'dispatcher': unknown['dispatcher'],
        'dispatcherProcessExited': True, 'modelChildProcessesExited': True,
        'evidenceScope': 'local_process_census', 'observedAt': '2026-10-05T00:00:00Z',
        'processCensusSha256': 'a' * 64}
    state = engine.reconcile('session', 'owner', job_id=unknown['jobId'],
                             dispatcher_terminal_receipt=receipt)
    assert state['status'] == 'running'


def test_pid_reuse_does_not_claim_new_worker(engine):
    begin(engine); job = engine.job_start('session', 'owner', 'tts')
    engine.backend.value['processes'].append({'pid': 500, 'ppid': 1, 'startTicks': 100})
    engine.job_bind('session', 'owner', job['jobId'], 500)
    engine.backend.value['processes'][0]['startTicks'] = 200
    engine.backend.value['gpu'] = [{'pid': 500}]
    with pytest.raises(SessionError, match='unmanaged_gpu'): engine.require('session', 'owner')


def test_priority_container_pause_restore_exact_identity(engine):
    cid = 'e' * 64
    engine.backend.value['containers'] = [{'id': cid, 'image': 'image', 'running': True, 'pid': 200,
                                         'autoRemove': False, 'identity': 'config-hash'}]
    engine.backend.value['processes'].append({'pid': 200, 'ppid': 1, 'startTicks': 20000})
    begin(engine, preempt=True, allow_interrupted_restart=True, container_ids=[cid])
    assert engine.backend.value['containers'][0]['running'] is False
    a = engine.job_start('session', 'owner', 'probe-one')
    engine.job_end('session', 'owner', a['jobId'], 'known_terminal', True)
    b = engine.job_start('session', 'owner', 'probe-two')
    engine.job_end('session', 'owner', b['jobId'], 'known_terminal', True)
    assert engine.backend.calls.count(('start-container', cid)) == 0
    assert engine.finish('session', 'owner')['status'] == 'closed'
    assert engine.backend.calls.count(('start-container', cid)) == 1


def test_private_queue_backup_and_snapshot_metadata(tmp_path):
    import sqlite3
    root = tmp_path / 'state'; root.mkdir()
    source = root / 'enqueue.sqlite'
    with sqlite3.connect(source) as database:
        database.execute('create table private_parameters(value text)')
        database.execute('insert into private_parameters values(?)', ('private-text',))
    (root / 'queue.json').write_text('{"running":null,"queue":[],"queue_length":0}')
    backend = LinuxBackend(queue_path=source)
    with patch.object(backend, 'model_health', return_value={'healthy': False}):
        receipt = backend.backup_state(tmp_path / 'backup')
    assert set(receipt['sha256']) == {'enqueue.sqlite', 'queue.json'}
    assert 'private-text' not in json.dumps(receipt)
    assert (tmp_path / 'backup').stat().st_mode & 0o777 == 0o700
    assert (tmp_path / 'backup/enqueue.sqlite').stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(tmp_path / 'backup/enqueue.sqlite') as database:
        assert database.execute('select value from private_parameters').fetchone()[0] == 'private-text'


def test_closed_session_does_not_poll_deleted_original_containers(tmp_path):
    backend = FakeBackend(); backend.container_ids = set()
    cid = 'd' * 64
    backend.value['containers'] = [{'id': cid, 'running': False, 'autoRemove': False, 'identity': 'old-config'}]
    original = Engine(tmp_path, backend)
    original.begin('old-session', 'owner', 90, container_ids=[cid])
    original.finish('old-session', 'owner')
    backend.value['containers'] = []
    restored = FakeBackend().value
    for key in ('units', 'processes', 'gpu'): backend.value[key] = restored[key]
    assert cid in backend.container_ids
    later = Engine(tmp_path, backend)
    assert backend.container_ids == set()
    assert later.inspect()['session']['status'] == 'closed'
    assert later.begin('new-session', 'owner', 90)['status'] == 'exclusive_ready'


def test_preemption_freezes_all_running_container_ids_by_default(engine):
    cid = 'c' * 64
    engine.backend.value['containers'] = [{'id': cid, 'image': 'image', 'running': True, 'pid': 200,
                                         'autoRemove': False, 'identity': 'config-hash'}]
    engine.backend.value['processes'].append({'pid': 200, 'ppid': 1, 'startTicks': 20000})
    state = begin(engine, preempt=True, allow_interrupted_restart=True)
    assert state['containerIds'] == [cid]
    assert ('stop-container', cid) in engine.backend.calls
    assert begin(engine, preempt=True, allow_interrupted_restart=True)['containerIds'] == [cid]
    assert engine.finish('session', 'owner')['status'] == 'closed'
    assert ('start-container', cid) in engine.backend.calls


def test_implicit_all_preemption_rejects_auto_remove_before_any_stop(engine):
    cid = 'b' * 64
    engine.backend.value['containers'] = [{'id': cid, 'running': True, 'pid': 200, 'autoRemove': True}]
    with pytest.raises(SessionError, match='auto_remove'): begin(engine, preempt=True, allow_interrupted_restart=True)
    assert not engine.backend.calls


def test_original_durable_queued_jobs_do_not_block_restore(engine):
    engine.backend.value['queue'].update(outstanding=4, activeDispatches=0, queuedJobs=3, inputRequiredJobs=1)
    state = begin(engine, preempt=True, allow_interrupted_restart=True)
    assert state['interruptedWork']['requiresDispatchReconciliation'] is False
    assert engine.finish('session', 'owner')['status'] == 'closed'


def test_actual_dispatches_cannot_silently_requeue_and_restore(engine):
    engine.backend.value['queue'].update(outstanding=4, activeDispatches=1, queuedJobs=3)
    state = begin(engine, preempt=True, allow_interrupted_restart=True)
    assert state['interruptedWork']['requiresDispatchReconciliation'] is True
    engine.backend.value['queue'].update(outstanding=4, activeDispatches=0, queuedJobs=4)
    with pytest.raises(SessionError, match='foreign_dispatch'): engine.finish('session', 'owner')


def test_linux_queue_separates_dispatches_pending_and_unknown_states(tmp_path):
    import sqlite3
    path = tmp_path / 'enqueue.sqlite'
    with sqlite3.connect(path) as database:
        database.execute('create table jobs(state text)')
        database.execute('create table enqueue_requests(status text)')
        database.executemany('insert into jobs values(?)', [('queued',), ('input_required',), ('running',), ('cancel_requested',), ('succeeded',)])
        database.execute("insert into enqueue_requests values('pending')")
    (tmp_path / 'queue.json').write_text('{"running":null,"queue":[],"queue_length":0}')
    queue = LinuxBackend(queue_path=path).queue()
    assert queue['outstanding'] == 4 and queue['activeDispatches'] == 2
    assert queue['queuedJobs'] == 1 and queue['inputRequiredJobs'] == 1
    with sqlite3.connect(path) as database: database.execute("insert into jobs values('unknown')")
    with pytest.raises(SessionError, match='job_state_unknown'): LinuxBackend(queue_path=path).queue()


def launcher_inventory(extra=(), gpu=()):
    processes = [
        {'pid': 10, 'ppid': 1, 'startTicks': 100, 'executable': 'python3', 'role': None, 'cgroup': 'api-cg', 'helper': None},
        {'pid': 20, 'ppid': 1, 'startTicks': 200, 'executable': 'python3', 'role': None, 'cgroup': 'agent-cg', 'helper': None},
    ] + list(extra)
    return {'queue': {'claimed': 0, 'outstanding': 0, 'pending': 0, 'legacyRunning': False, 'legacyQueued': 0},
            'processes': processes, 'gpu': list(gpu),
            'units': {'spark-api.service': {'active': 'active', 'mainPid': 10, 'controlGroup': 'api-cg'},
                      'spark-agent.service': {'active': 'active', 'mainPid': 20, 'controlGroup': 'agent-cg'}}}


def tracker(pid=21, ppid=20):
    return {'pid': pid, 'ppid': ppid, 'startTicks': 210, 'executable': 'python3', 'role': None,
            'cgroup': 'agent-cg', 'helper': RESOURCE_TRACKER_HELPER}


def test_resource_tracker_helper_child_is_allowed(engine):
    engine.idle_launcher(launcher_inventory([tracker()]), begin=True)


def test_other_launcher_child_still_blocks(engine):
    unknown = {'pid': 22, 'ppid': 20, 'startTicks': 220, 'executable': 'python3', 'role': None, 'cgroup': 'agent-cg', 'helper': None}
    with pytest.raises(SessionError, match='launcher_workers_active'): engine.idle_launcher(launcher_inventory([unknown]), begin=True)


def test_helper_with_its_own_child_blocks(engine):
    grandchild = {'pid': 23, 'ppid': 21, 'startTicks': 230, 'executable': 'python3', 'role': None, 'cgroup': 'agent-cg', 'helper': None}
    with pytest.raises(SessionError, match='launcher_workers_active'): engine.idle_launcher(launcher_inventory([tracker(), grandchild]), begin=True)


def test_helper_on_gpu_blocks(engine):
    with pytest.raises(SessionError, match='launcher_workers_active'):
        engine.idle_launcher(launcher_inventory([tracker()], gpu=[{'pid': 21, 'executable': 'python3', 'usedMiB': 1}]), begin=True)


def test_helper_argument_pattern_is_exact():
    assert RESOURCE_TRACKER_ARGUMENT.match('from multiprocessing.resource_tracker import main;main(11)')
    for bad in ('from multiprocessing.resource_tracker import main;main(11); rm -rf ~',
                'import os; os.system("x")', 'from multiprocessing.resource_tracker import main;main(x)'):
        assert not RESOURCE_TRACKER_ARGUMENT.match(bad)

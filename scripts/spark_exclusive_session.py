#!/usr/bin/env python3
"""Recoverable Spark maintenance session with explicit priority interruption; no inference or timeout release.

The managed launcher is stopped while idle. Manual SSH/admin processes are detected
at each admission, not prevented by a kernel isolation boundary. This standalone
stdlib module is staged by content hash over SSH; no repository/runtime install.
"""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import socket
import signal
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid

SCHEMA = 'tongxing-spark-exclusive-v1'
DEFAULT_HOST = 'achillesjing@192.168.1.152'
# Python multiprocessing helper that the spark-agent scheduler starts for itself. It is the only
# launcher child the admission check accepts, and only when it is a direct child with no children.
RESOURCE_TRACKER_HELPER = 'multiprocessing_resource_tracker'
RESOURCE_TRACKER_ARGUMENT = re.compile(r'^from multiprocessing\.resource_tracker import main;main\(\d+\)$')
UNITS = ('spark-api.service', 'spark-agent.service', 'llama-performance-collector.service', 'llama-server.service')
LAUNCHERS = ('spark-api.service', 'spark-agent.service')
STOP_ORDER = UNITS
RESTORE_ORDER = ('llama-server.service', 'llama-performance-collector.service', 'spark-agent.service', 'spark-api.service')
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')

class SessionError(RuntimeError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def check_id(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise SessionError('invalid_identifier')
    return value

def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        if temporary.exists(): temporary.unlink()

class LinuxBackend:
    """Read-only inventory and fixed allowlist mutations, all subprocesses bounded."""
    def __init__(self, *, queue_path=None, samples=3, interval=0.25):
        self.queue_path = Path(queue_path or Path.home() / 'spark-agent/state/enqueue.sqlite')
        self.samples, self.interval = samples, interval
        self.container_ids = set()

    def command(self, arguments, *, timeout=20):
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SessionError('remote_command_outcome_unknown') from exc
        if result.returncode:
            # Do not persist arbitrary stderr/argv: they can contain secrets.
            raise SessionError('remote_command_failed')
        return result.stdout

    def unit(self, name):
        if name not in UNITS + ('spark-api.service',): raise SessionError('unit_not_allowlisted')
        properties = ('Id', 'LoadState', 'ActiveState', 'SubState', 'MainPID', 'ControlGroup', 'FragmentPath', 'DropInPaths', 'KillMode')
        output = self.command(['systemctl', '--user', 'show', name] + [f'--property={p}' for p in properties])
        raw = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        if raw.get('LoadState') != 'loaded': raise SessionError('unit_not_loaded:' + name)
        files = [raw.get('FragmentPath', '')] + shlex.split(raw.get('DropInPaths', ''))
        hashes = []
        for filename in files:
            if not filename: raise SessionError('unit_identity_missing')
            hashes.append({'path': filename, 'sha256': hashlib.sha256(Path(filename).read_bytes()).hexdigest()})
        return {'name': name, 'active': raw.get('ActiveState'), 'sub': raw.get('SubState'),
                'mainPid': int(raw.get('MainPID', '0')), 'controlGroup': raw.get('ControlGroup'),
                'identity': digest(hashes), 'killMode': raw.get('KillMode')}

    def processes(self):
        values = []
        for path in Path('/proc').iterdir():
            if not path.name.isdigit(): continue
            try:
                stat = (path / 'stat').read_text().rsplit(')', 1)[1].split()
                pid, ppid, ticks = int(path.name), int(stat[1]), int(stat[19])
                cmd = (path / 'cmdline').read_bytes().split(b'\0')
                arguments = [part.decode(errors='replace') for part in cmd if part]
                executable = Path(os.readlink(path / 'exe')).name
                cgroup = (path / 'cgroup').read_text()
                role = None
                names = {Path(arg).name for arg in arguments}
                if executable in {'llama-server', 'vllm', 'sglang'} or names & {'llama-server', 'vllm', 'sglang', 'vllm.entrypoints.openai.api_server'}:
                    role = 'model'
                if names & {'task_worker.py', 'job_runtime.py', 'replay_fixed_clip_local_models.py', 'render_formal_target_language_speech.py'}:
                    role = 'worker'
                helper = None
                if len(arguments) == 3 and arguments[1] == '-c' and Path(arguments[0]).name.startswith('python') and RESOURCE_TRACKER_ARGUMENT.match(arguments[2]):
                    helper = RESOURCE_TRACKER_HELPER
                values.append({'pid': pid, 'ppid': ppid, 'startTicks': ticks, 'executable': executable,
                               'role': role, 'cgroup': cgroup.strip(), 'helper': helper})
            except (FileNotFoundError, ProcessLookupError): continue
            except PermissionError:
                # GPU and launcher checks cannot prove an unreadable process identity.
                values.append({'pid': int(path.name), 'unreadable': True})
        return values

    def containers(self):
        ids = sorted(set(self.command(['docker', 'ps', '-q', '--no-trunc']).split()) | self.container_ids)
        values = []
        if not ids: return values
        for data in json.loads(self.command(['docker', 'inspect', *ids])):
            labels = data.get('Config', {}).get('Labels') or {}
            values.append({'id': data['Id'], 'image': data['Image'],
                           'running': bool(data['State']['Running']), 'pid': int(data['State'].get('Pid', 0)),
                           'autoRemove': bool(data['HostConfig']['AutoRemove']),
                           'restartPolicy': data['HostConfig']['RestartPolicy'],
                           'identity': digest({'id': data['Id'], 'image': data['Image'],
                                               'config': data['Config'], 'host': data['HostConfig']}),
                           'session': labels.get('tongxing.spark.session'), 'owner': labels.get('tongxing.spark.owner'),
                           'job': labels.get('tongxing.spark.job')})
        return values

    def queue(self):
        if not self.queue_path.is_file(): raise SessionError('scheduler_queue_missing')
        try:
            with sqlite3.connect(self.queue_path.as_uri() + '?mode=ro', uri=True, timeout=5) as database:
                ingress = dict(database.execute('SELECT status,count(*) FROM enqueue_requests GROUP BY status'))
                jobs = dict(database.execute('SELECT state,count(*) FROM jobs GROUP BY state'))
                tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'enqueue_requests', 'jobs'} <= tables: raise SessionError('scheduler_queue_schema_unknown')
            if not set(ingress) <= {'pending', 'claimed', 'done', 'failed'}: raise SessionError('scheduler_queue_state_unknown')
            outstanding = sum(v for k, v in jobs.items() if k not in {'succeeded', 'failed', 'timed_out', 'canceled'})
            active_dispatches = sum(v for k, v in jobs.items() if k in {'running', 'cancel_requested'})
            if not set(jobs) <= {'queued', 'input_required', 'running', 'cancel_requested', 'succeeded', 'failed', 'timed_out', 'canceled'}:
                raise SessionError('scheduler_job_state_unknown')
            legacy = json.loads((self.queue_path.parent / 'queue.json').read_text())
            if not isinstance(legacy.get('queue'), list) or not isinstance(legacy.get('queue_length'), int): raise SessionError('legacy_queue_state_unknown')
            if len(legacy['queue']) != legacy['queue_length']: raise SessionError('legacy_queue_count_mismatch')
            return {'pending': ingress.get('pending', 0), 'claimed': ingress.get('claimed', 0), 'outstanding': outstanding, 'activeDispatches': active_dispatches,
                    'queuedJobs': jobs.get('queued', 0), 'inputRequiredJobs': jobs.get('input_required', 0),
                    'legacyRunning': legacy.get('running') is not None, 'legacyQueued': len(legacy['queue'])}
        except (sqlite3.Error, OSError, ValueError) as exc: raise SessionError('scheduler_queue_unreadable') from exc

    def gpu(self):
        lines = self.command(['nvidia-smi', '--query-compute-apps=pid,process_name,used_gpu_memory', '--format=csv,noheader,nounits']).splitlines()
        rows = []
        for line in lines:
            fields = [part.strip() for part in line.split(',')]
            if len(fields) != 3 or not fields[0].isdigit(): raise SessionError('gpu_inventory_unknown')
            rows.append({'pid': int(fields[0]), 'executable': Path(fields[1]).name,
                         'usedMiB': int(fields[2]) if fields[2].isdigit() else None})
        return rows

    def memory(self):
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'): return int(line.split()[1]) * 1024
        raise SessionError('memory_inventory_unknown')

    def model_health(self):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3) as response:
                health = json.load(response)
            with urllib.request.urlopen('http://127.0.0.1:8000/v1/models', timeout=3) as response:
                models = json.load(response)
            ids = sorted(item['id'] for item in models['data'] if isinstance(item.get('id'), str))
            with urllib.request.urlopen('http://127.0.0.1:8000/slots', timeout=3) as response:
                slots = json.load(response)
            if not isinstance(slots, list) or not slots or any(not isinstance(slot.get('is_processing'), bool) for slot in slots): raise ValueError('slots_unknown')
            if health.get('status') != 'ok' or not ids: raise ValueError('not_ready')
            return {'healthy': True, 'modelIds': ids, 'processingSlots': sum(slot['is_processing'] for slot in slots)}
        except Exception:
            return {'healthy': False, 'modelIds': [], 'processingSlots': None}

    def inventory(self):
        return {'host': socket.gethostname(), 'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'units': {name: self.unit(name) for name in UNITS},
                'containers': self.containers(), 'processes': self.processes(), 'gpu': self.gpu(),
                'queue': self.queue(), 'memAvailableBytes': self.memory(), 'modelHealth': self.model_health()}

    def stable_memory(self, minimum):
        values = []
        for index in range(self.samples):
            values.append(self.memory())
            if index + 1 < self.samples: time.sleep(self.interval)
        if min(values) < minimum: raise SessionError('insufficient_available_memory')
        return values

    def backup_state(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / 'enqueue.sqlite'
        with sqlite3.connect(self.queue_path.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(target) as destination: source.backup(destination)
        target.chmod(0o600)
        queue_json = self.queue_path.parent / 'queue.json'
        files = [target]
        health = self.model_health()
        if health.get('healthy'):
            with urllib.request.urlopen('http://127.0.0.1:8000/slots', timeout=3) as response: slots = json.load(response)
            snapshot = directory / 'native-slots.json'
            atomic_json(snapshot, slots); files.append(snapshot)
        if queue_json.is_file():
            copy = directory / 'queue.json'
            shutil.copyfile(queue_json, copy); copy.chmod(0o600); files.append(copy)
        hashes = {}
        for path in files:
            with path.open('rb') as handle: os.fsync(handle.fileno())
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return {'path': str(directory), 'sha256': hashes}

    def stop_unit(self, name, *, preempt=False):
        if name not in UNITS: raise SessionError('unit_not_allowlisted')
        if name not in LAUNCHERS:
            self.command(['systemctl', '--user', 'stop', name], timeout=90)
            return
        unit = self.unit(name)
        if unit['active'] == 'inactive': return
        if unit.get('killMode') != 'control-group': raise SessionError('launcher_kill_mode_unknown')
        main = next((p for p in self.processes() if p['pid'] == unit['mainPid']), None)
        if not main or main.get('unreadable'): raise SessionError('launcher_process_unknown')
        os.kill(main['pid'], signal.SIGSTOP)
        # Intent was fsynced by Engine before SIGSTOP. If SSH is lost here,
        # explicit reconciliation can SIGCONT this exact frozen process.
        processes = self.processes()
        helpers = self.launcher_helpers(processes, main['pid'], self.gpu())
        children = Engine.descendants(processes, [(main['pid'], main['startTicks'])]) - {main['pid']} - helpers
        queue = self.queue()
        if not preempt and (children or queue['pending'] or queue['claimed'] or queue['outstanding'] or queue.get('legacyRunning') or queue.get('legacyQueued')):
            os.kill(main['pid'], signal.SIGCONT)
            raise SessionError('launcher_became_busy_before_stop')
        self.command(['systemctl', '--user', 'stop', '--no-block', name])
        try: os.kill(main['pid'], signal.SIGCONT)
        except ProcessLookupError: pass
        deadline = time.monotonic() + 20
        while self.unit(name)['active'] != 'inactive':
            if time.monotonic() >= deadline: raise SessionError('launcher_stop_outcome_unknown')
            time.sleep(0.1)

    def resume_frozen(self, name, original):
        if name not in LAUNCHERS: raise SessionError('launcher_not_allowlisted')
        current = self.unit(name)
        if current['identity'] != original['identity'] or current['mainPid'] != original['mainPid']: raise SessionError('frozen_launcher_identity_changed')
        if current['active'] != 'active': raise SessionError('frozen_launcher_not_active')
        os.kill(current['mainPid'], signal.SIGCONT)


    def start_unit(self, name):
        if name not in UNITS: raise SessionError('unit_not_allowlisted')
        self.command(['systemctl', '--user', 'start', name], timeout=90)

    def stop_container(self, container_id): self.command(['docker', 'stop', '--time', '30', container_id], timeout=60)
    def start_container(self, container_id): self.command(['docker', 'start', container_id], timeout=60)

    def wait_model_health(self, original, timeout=90):
        deadline = time.monotonic() + timeout
        while True:
            health = self.model_health()
            if health['healthy'] and health['modelIds'] == original['modelIds']: return health
            if time.monotonic() >= deadline: raise SessionError('model_health_not_restored')
            time.sleep(1)

class Engine:
    def __init__(self, root, backend):
        self.root, self.backend = Path(root), backend
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'session.json'
        if self.path.exists() and hasattr(backend, 'container_ids'):
            old = self.load()
            if old['status'] != 'closed':
                backend.container_ids.update(old.get('containerIds', []))
                backend.container_ids.update(cid for job in old.get('jobs', {}).values() for cid in job.get('containerIds', []))
            else: backend.container_ids.clear()

    @contextmanager
    def locked(self):
        descriptor = os.open(self.root / 'owner.lock', os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def load(self):
        if not self.path.exists(): return None
        value = json.loads(self.path.read_text())
        if value.get('schemaVersion') != SCHEMA: raise SessionError('session_schema_unknown')
        return value

    def save(self, state, event, **fields):
        state['revision'] += 1
        state['updatedAt'] = now()
        state['events'].append({'revision': state['revision'], 'at': state['updatedAt'], 'event': event, **fields})
        atomic_json(self.path, state)

    def authenticate(self, state, session_id, owner, inventory):
        if not state or state['sessionId'] != session_id or state['owner'] != owner: raise SessionError('session_owner_mismatch')
        if state.get('controllerSha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest(): raise SessionError('session_controller_implementation_changed')
        if inventory['host'] != state['snapshot']['host'] or inventory['bootId'] != state['snapshot']['bootId']:
            if state['status'] != 'closed':
                state['status'] = 'reconcile_required'
                self.save(state, 'boot_identity_changed')
            raise SessionError('boot_identity_changed_manual_reconciliation_required')

    @staticmethod
    def descendants(processes, roots):
        live = {item['pid']: item for item in processes}
        known = {pid for pid, ticks in roots if pid in live and live[pid].get('startTicks') == ticks}
        changed = True
        while changed:
            changed = False
            for item in processes:
                if item.get('ppid') in known and item['pid'] not in known:
                    known.add(item['pid']); changed = True
        return known

    @staticmethod
    def launcher_helpers(processes, launcher_pid, gpu):
        gpu_pids = {row.get('pid') for row in gpu}
        parents = {item.get('ppid') for item in processes}
        return {item['pid'] for item in processes
                if item.get('helper') == RESOURCE_TRACKER_HELPER and item.get('ppid') == launcher_pid
                and item['pid'] not in parents and item['pid'] not in gpu_pids}

    def idle_launcher(self, inventory, *, begin=False):
        queue = inventory['queue']
        if queue['claimed'] or queue['outstanding'] or queue.get('legacyRunning') or (begin and (queue['pending'] or queue.get('legacyQueued'))): raise SessionError('scheduler_work_outstanding')
        processes = inventory['processes']
        for name in LAUNCHERS:
            launcher = inventory['units'][name]
            roots = [p for p in processes if p['pid'] == launcher['mainPid']]
            if launcher['active'] == 'active':
                if len(roots) != 1 or roots[0].get('unreadable'): raise SessionError('launcher_process_unknown')
                helpers = self.launcher_helpers(processes, launcher['mainPid'], inventory.get('gpu', []))
                descendants = self.descendants(processes, [(roots[0]['pid'], roots[0]['startTicks'])]) - helpers
                cgroup = launcher['controlGroup']
                if not cgroup or descendants != {launcher['mainPid']} or any(cgroup in p.get('cgroup', '') and p['pid'] not in helpers | {launcher['mainPid']} for p in processes):
                    raise SessionError('launcher_workers_active')
            elif launcher['active'] != 'inactive': raise SessionError('launcher_state_unknown')

    def resource_check(self, state, inventory, *, before=False, require_idle=False, allow_busy=False):
        if not allow_busy:
            if not before and state.get('preempt'):
                original = state['snapshot']['queue']
                if inventory['queue']['claimed'] > original['claimed'] or inventory['queue']['outstanding'] > original['outstanding']: raise SessionError('new_scheduler_work_detected')
                # Original interrupted requests remain durable foreign reservations.
                for name in LAUNCHERS:
                    if inventory['units'][name]['active'] != 'inactive': raise SessionError('competing_launcher_active')
            else: self.idle_launcher(inventory, begin=before)
        roots = []
        if before:
            for unit in inventory['units'].values():
                if unit['active'] not in {'active', 'inactive'}: raise SessionError('unit_state_unknown')
                main = next((p for p in inventory['processes'] if p['pid'] == unit['mainPid']), None)
                if unit['active'] == 'active':
                    if not main or main.get('unreadable'): raise SessionError('unit_process_unknown')
                    roots.append((main['pid'], main['startTicks']))
        else:
            for name, unit in inventory['units'].items():
                if unit['identity'] != state['snapshot']['units'][name]['identity']: raise SessionError('unit_identity_changed')
                if unit['active'] != 'inactive' or unit['mainPid']: raise SessionError('competing_service_active:' + name)
            if not require_idle:
                for job in state['jobs'].values():
                    if job['status'] in {'active', 'unknown'}:
                        roots.extend((p['pid'], p['startTicks']) for p in job['processes'])
        owned = self.descendants(inventory['processes'], roots)
        original_ids = set(state.get('containerIds', []))
        for container in inventory['containers']:
            if not container['running']: continue
            if before and container['id'] in original_ids:
                if container['autoRemove']: raise SessionError('container_auto_remove_not_recoverable')
                pid = container['pid']
                process = next((p for p in inventory['processes'] if p['pid'] == pid), None)
                if not process or process.get('unreadable'): raise SessionError('container_process_unknown')
                owned |= self.descendants(inventory['processes'], [(pid, process['startTicks'])])
            elif not before and not require_idle and container.get('session') == state['sessionId'] and container.get('owner') == state['owner'] and container.get('job') in state['jobs'] and state['jobs'][container['job']]['status'] == 'active':
                # Label alone is not process ownership: exact runner/container binding required.
                job = state['jobs'][container['job']]
                if not job['processes'] and container['id'] not in job['containerIds']: raise SessionError('container_worker_unbound')
                process = next((p for p in inventory['processes'] if p['pid'] == container['pid']), None)
                if not process or process.get('unreadable'): raise SessionError('container_process_unknown')
                owned |= self.descendants(inventory['processes'], [(process['pid'], process['startTicks'])])
            else: raise SessionError('unmanaged_running_container')
        if any(p['pid'] not in owned for p in inventory['gpu']): raise SessionError('unmanaged_gpu_process')
        if any(p.get('role') in {'model', 'worker'} and p['pid'] not in owned for p in inventory['processes']): raise SessionError('unmanaged_model_or_worker_process')
        return owned

    def inspect(self):
        with self.locked():
            state = self.load()
            if state and state['status'] == 'closed' and hasattr(self.backend, 'container_ids'): self.backend.container_ids.clear()
            return {'inventory': self.backend.inventory(), 'session': state, 'scope': 'idle_api_and_scheduler_paused;manual_admin_bypass_detected_at_admission'}

    def operation(self, state, kind, target, action, verify):
        key = kind + ':' + target
        prior = state['operations'].get(key)
        if prior and prior['status'] == 'verified': return
        if prior and prior['status'] in {'intent', 'unknown'}: raise SessionError('effect_requires_reconciliation:' + key)
        state['operations'][key] = {'status': 'intent', 'at': now()}
        self.save(state, 'intent', operation=key)
        try:
            action()
            readback = self.backend.inventory()
            if not verify(readback): raise SessionError('effect_readback_mismatch')
            state['operations'][key] = {'status': 'verified', 'at': now()}
            self.save(state, 'readback', operation=key)
        except Exception as exc:
            state['operations'][key]['status'] = 'unknown'
            state['status'] = 'restoring_failed' if kind.startswith('start') else 'reconcile_required'
            self.save(state, 'effect_unknown', operation=key, errorCode=str(exc) if isinstance(exc, SessionError) else type(exc).__name__)
            raise SessionError('effect_requires_reconciliation:' + key) from exc

    def begin(self, session_id, owner, minimum_available_gib, container_ids=(), preempt=False, allow_interrupted_restart=False):
        check_id(session_id); check_id(owner)
        if not isinstance(minimum_available_gib, (int, float)) or not math.isfinite(minimum_available_gib) or minimum_available_gib <= 0: raise SessionError('explicit_positive_memory_minimum_required')
        with self.locked():
            old = self.load()
            if old and old['status'] == 'closed' and hasattr(self.backend, 'container_ids'): self.backend.container_ids.clear()
            if old and old['status'] != 'closed' and preempt and not container_ids: container_ids = old['containerIds']
            if hasattr(self.backend, 'container_ids'): self.backend.container_ids.update(container_ids)
            if old and old['status'] != 'closed':
                inventory = self.backend.inventory()
                self.authenticate(old, session_id, owner, inventory)
                if old['minimumAvailableBytes'] != math.ceil(minimum_available_gib * 1024**3) or set(old['containerIds']) != set(container_ids): raise SessionError('session_configuration_changed')
                if old['status'] in {'exclusive_ready', 'running'}:
                    self.resource_check(old, inventory)
                    return old
                raise SessionError('active_session_requires_reconciliation')
            inventory = self.backend.inventory()
            containers = {item['id']: item for item in inventory['containers']}
            if preempt and not container_ids:
                container_ids = sorted(item['id'] for item in inventory['containers'] if item['running'])
                if hasattr(self.backend, 'container_ids'): self.backend.container_ids.update(container_ids)
            if not all(re.fullmatch(r'[0-9a-f]{64}', cid) and cid in containers for cid in container_ids): raise SessionError('exact_container_identity_required')
            if any(containers[cid]['autoRemove'] for cid in container_ids): raise SessionError('container_auto_remove_not_recoverable')
            state = {'schemaVersion': SCHEMA, 'sessionId': session_id, 'owner': owner, 'revision': 0, 'status': 'planning',
                     'createdAt': now(), 'controllerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'snapshot': inventory, 'minimumAvailableBytes': math.ceil(minimum_available_gib * 1024**3),
                     'containerIds': list(container_ids), 'preempt': bool(preempt), 'allowInterruptedRestart': bool(allow_interrupted_restart), 'jobs': {}, 'operations': {}, 'events': [], 'runIds': []}
            if preempt:
                if not allow_interrupted_restart: raise SessionError('interrupted_restart_authorization_required')
                # Freeze ownership independently of queue emptiness; known allowlist
                # cgroups and explicitly selected containers are recoverable scopes.
                self.resource_check(state, inventory, before=True, allow_busy=True)
            else: self.resource_check(state, inventory, before=True)
            if inventory['units']['llama-server.service']['active'] == 'active':
                if not inventory['modelHealth']['healthy']: raise SessionError('original_model_health_unknown')
                if inventory['modelHealth'].get('processingSlots') != 0 and not preempt: raise SessionError('original_model_processing_request')
            if old: atomic_json(self.root / ('closed-' + old['sessionId'] + '-' + str(old['revision']) + '.json'), old)
            self.save(state, 'snapshot_frozen')
            if preempt:
                state['stateBackup'] = self.backend.backup_state(self.root / ('backup-' + session_id))
                state['interruptedWork'] = {'queue': inventory['queue'], 'processes': [p for p in inventory['processes'] if p.get('role') == 'worker'],
                                            'interruptedNativeInference': inventory['modelHealth'].get('processingSlots') or 0,
                                            'nativeCallerResubmitRequired': bool(inventory['modelHealth'].get('processingSlots')),
                                            'requiresDispatchReconciliation': bool(inventory['queue']['claimed'] or inventory['queue'].get('activeDispatches', inventory['queue']['outstanding']) or inventory['queue'].get('legacyRunning') or inventory['queue'].get('legacyQueued'))}
                self.save(state, 'restart_state_saved')
            return self._begin(state)

    def _begin(self, state):
        state['status'] = 'draining'; self.save(state, 'admission_closing')
        # Immediate read-only repeat narrows the queue/worker race; stop launcher only while idle.
        inventory = self.backend.inventory()
        if not state.get('preempt'): self.idle_launcher(inventory, begin=True)
        for name in STOP_ORDER:
            if state['snapshot']['units'][name]['active'] == 'active':
                current = self.backend.inventory()
                if current['units'][name]['identity'] != state['snapshot']['units'][name]['identity']: raise SessionError('unit_identity_changed')
                if name in LAUNCHERS and not state.get('preempt'): self.idle_launcher(current, begin=True)
                self.operation(state, 'stop-unit', name, lambda name=name: self.backend.stop_unit(name, preempt=state.get('preempt', False)),
                               lambda readback, name=name: readback['units'][name]['active'] == 'inactive' and readback['units'][name]['mainPid'] == 0)
        for container_id in state['containerIds']:
            original = next(c for c in state['snapshot']['containers'] if c['id'] == container_id)
            if original['running']:
                current = next((c for c in self.backend.inventory()['containers'] if c['id'] == container_id), None)
                if not current or current['identity'] != original['identity']: raise SessionError('container_identity_changed')
                self.operation(state, 'stop-container', container_id, lambda cid=container_id: self.backend.stop_container(cid),
                               lambda readback, cid=container_id: any(c['id'] == cid and not c['running'] for c in readback['containers']))
        inventory = self.backend.inventory(); self.resource_check(state, inventory, require_idle=True)
        state['memorySamples'] = self.backend.stable_memory(state['minimumAvailableBytes'])
        state['status'] = 'exclusive_ready'; self.save(state, 'exclusive_ready')
        return state

    def status(self, session_id, owner):
        with self.locked():
            state = self.load()
            if state and state['status'] == 'closed' and hasattr(self.backend, 'container_ids'): self.backend.container_ids.clear()
            inventory = self.backend.inventory()
            self.authenticate(state, session_id, owner, inventory)
            return {'session': state, 'inventory': inventory}

    def require(self, session_id, owner):
        with self.locked():
            state = self.load(); inventory = self.backend.inventory()
            self.authenticate(state, session_id, owner, inventory)
            if state['status'] not in {'exclusive_ready', 'running'} or any(j['status'] == 'unknown' for j in state['jobs'].values()): raise SessionError('session_not_ready')
            self.resource_check(state, inventory)
            if state['status'] == 'exclusive_ready': self.backend.stable_memory(state['minimumAvailableBytes'])
            return {'schemaVersion': SCHEMA, 'sessionId': session_id, 'owner': owner, 'revision': state['revision'],
                    'status': state['status'], 'bootId': state['snapshot']['bootId'], 'memAvailableBytes': inventory['memAvailableBytes'],
                    'scope': 'managed_api_and_scheduler_paused;manual_admin_bypass_not_prevented'}

    def job_start(self, session_id, owner, purpose, dispatcher=None, job_id=None):
        check_id(purpose)
        with self.locked():
            state = self.load(); inventory = self.backend.inventory(); self.authenticate(state, session_id, owner, inventory)
            if state['status'] not in {'exclusive_ready', 'running'} or any(j['status'] == 'unknown' for j in state['jobs'].values()): raise SessionError('session_not_ready')
            self.resource_check(state, inventory)
            if state['status'] == 'exclusive_ready': self.backend.stable_memory(state['minimumAvailableBytes'])
            key = check_id(job_id or uuid.uuid4().hex)
            if key in state['jobs']: raise SessionError('job_identity_already_reserved')
            job = {'jobId': key, 'sessionId': session_id, 'owner': owner, 'purpose': purpose, 'status': 'active',
                   'startedAt': now(), 'dispatcher': dispatcher or {}, 'processes': [], 'containerIds': []}
            state['jobs'][key] = job; state['status'] = 'running'; self.save(state, 'job_reserved', jobId=key)
            return job

    def job_bind(self, session_id, owner, job_id, pid=None, container_id=None):
        with self.locked():
            state = self.load(); inventory = self.backend.inventory(); self.authenticate(state, session_id, owner, inventory)
            job = state['jobs'].get(job_id)
            if not job or job['status'] != 'active': raise SessionError('job_not_active')
            if pid:
                process = next((p for p in inventory['processes'] if p['pid'] == pid), None)
                if not process or process.get('unreadable'): raise SessionError('worker_pid_unknown')
                if any(p['pid'] == pid for other in state['jobs'].values() if other is not job for p in other['processes']): raise SessionError('worker_owned_by_another_job')
                record = {'pid': pid, 'startTicks': process['startTicks']}
                if record not in job['processes']: job['processes'].append(record)
            if container_id:
                if hasattr(self.backend, 'container_ids'): self.backend.container_ids.add(container_id)
                inventory = self.backend.inventory()
                container = next((c for c in inventory['containers'] if c['id'] == container_id), None)
                if not container or container.get('session') != session_id or container.get('owner') != owner or container.get('job') != job_id: raise SessionError('job_container_identity_mismatch')
                if container_id not in job['containerIds']: job['containerIds'].append(container_id)
            if not pid and not container_id: raise SessionError('binding_required')
            self.save(state, 'job_bound', jobId=job_id)
            return job

    def job_end(self, session_id, owner, job_id, outcome, process_exited):
        with self.locked():
            state = self.load(); inventory = self.backend.inventory(); self.authenticate(state, session_id, owner, inventory)
            job = state['jobs'].get(job_id)
            if not job: raise SessionError('job_unknown')
            if job['status'] == 'terminal': return job
            if job['status'] == 'unknown' and not job['processes'] and not job['containerIds']: raise SessionError('unbound_unknown_job_requires_dispatcher_terminal_receipt')
            if outcome != 'known_terminal' or process_exited is not True:
                job['status'] = 'unknown'; state['status'] = 'reconcile_required'; self.save(state, 'job_outcome_unknown', jobId=job_id)
                raise SessionError('job_requires_reconciliation')
            if self.descendants(inventory['processes'], [(p['pid'], p['startTicks']) for p in job['processes']]): raise SessionError('job_process_still_alive')
            if any(c['running'] and (c['id'] in job['containerIds'] or c.get('job') == job_id) for c in inventory['containers']): raise SessionError('job_container_still_alive')
            # No remote binding means dispatcher attests its children exited; unknown GPUs still block.
            self.resource_check(state, inventory)
            job['status'] = 'terminal'; job['endedAt'] = now(); self.save(state, 'job_terminal', jobId=job_id)
            if all(j['status'] == 'terminal' for j in state['jobs'].values()):
                self.resource_check(state, inventory, require_idle=True)
                state['status'] = 'exclusive_ready'; self.save(state, 'jobs_idle')
            return job

    def finish(self, session_id, owner):
        with self.locked():
            state = self.load()
            if state and state['status'] == 'closed' and hasattr(self.backend, 'container_ids'): self.backend.container_ids.clear()
            inventory = self.backend.inventory(); self.authenticate(state, session_id, owner, inventory)
            if state['status'] == 'closed': return state
            if any(j['status'] != 'terminal' for j in state['jobs'].values()): raise SessionError('active_or_unknown_jobs_prevent_restore')
            if state.get('interruptedWork', {}).get('requiresDispatchReconciliation') and (inventory['queue']['claimed'] or inventory['queue']['outstanding'] or inventory['queue'].get('legacyRunning') or inventory['queue'].get('legacyQueued')): raise SessionError('interrupted_foreign_dispatch_requires_terminal_reconciliation')
            if any(v['status'] in {'unknown', 'intent'} for v in state['operations'].values()): raise SessionError('effects_require_reconciliation')
            if state['status'] not in {'restoring', 'restoring_failed'}:
                self.resource_check(state, inventory, require_idle=True)
            state['status'] = 'restoring'; self.save(state, 'restore_started')
            for container_id in state['containerIds']:
                original = next(c for c in state['snapshot']['containers'] if c['id'] == container_id)
                current = next((c for c in inventory['containers'] if c['id'] == container_id), None)
                if not current or current['identity'] != original['identity']: raise SessionError('container_identity_changed')
                if original['running']:
                    self.operation(state, 'start-container', container_id, lambda cid=container_id: self.backend.start_container(cid),
                                   lambda readback, cid=container_id: any(c['id'] == cid and c['running'] for c in readback['containers']))
            for name in RESTORE_ORDER:
                current = self.backend.inventory()['units'][name]
                if current['identity'] != state['snapshot']['units'][name]['identity']: raise SessionError('unit_identity_changed')
                if state['snapshot']['units'][name]['active'] == 'active':
                    self.operation(state, 'start-unit', name, lambda name=name: self.backend.start_unit(name),
                                   lambda readback, name=name: readback['units'][name]['active'] == 'active')
                    if name == 'llama-server.service':
                        try:
                            state['restoredModelHealth'] = self.backend.wait_model_health(state['snapshot']['modelHealth'])
                        except Exception as exc:
                            state['status'] = 'restoring_failed'; self.save(state, 'model_health_unconfirmed')
                            raise SessionError('model_health_not_restored') from exc
                        self.save(state, 'model_health_restored')
                elif current['active'] != 'inactive': raise SessionError('originally_inactive_unit_changed')
            state['status'] = 'closed'; self.save(state, 'closed')
            return state

    def reconcile(self, session_id, owner, *, job_id=None, resume_frozen_launcher=None,
                  dispatcher_terminal_receipt=None):
        """Readback only; never arbitrary release, never issue start/stop commands."""
        with self.locked():
            state = self.load(); inventory = self.backend.inventory(); self.authenticate(state, session_id, owner, inventory)
            if resume_frozen_launcher:
                key = 'stop-unit:' + resume_frozen_launcher
                if key not in state['operations'] or state['operations'][key]['status'] not in {'intent', 'unknown'}: raise SessionError('frozen_intent_missing')
                self.backend.resume_frozen(resume_frozen_launcher, state['snapshot']['units'][resume_frozen_launcher])
                state['operations'][key]['status'] = 'not_started'
                self.save(state, 'frozen_launcher_resumed', operation=key)
                inventory = self.backend.inventory()
            for key, operation in state['operations'].items():
                if operation['status'] not in {'intent', 'unknown'}: continue
                kind, target = key.split(':', 1)
                if kind.endswith('unit'):
                    original = state['snapshot']['units'][target]
                    current = inventory['units'][target]
                    if current['identity'] != original['identity']: raise SessionError('unit_identity_changed')
                    expected = 'inactive' if kind == 'stop-unit' else 'active'
                    if current['active'] != expected: raise SessionError('unknown_effect_not_proven')
                else:
                    current = next((c for c in inventory['containers'] if c['id'] == target), None)
                    original = next(c for c in state['snapshot']['containers'] if c['id'] == target)
                    if not current or current['identity'] != original['identity']: raise SessionError('container_identity_changed')
                    if current['running'] != (kind == 'start-container'): raise SessionError('unknown_effect_not_proven')
                operation['status'] = 'verified'; self.save(state, 'effect_reconciled', operation=key)
            if job_id:
                job = state['jobs'].get(job_id)
                if not job: raise SessionError('job_unknown')
                if not job['processes'] and not job['containerIds']:
                    receipt = dispatcher_terminal_receipt
                    if (not isinstance(receipt, dict)
                            or receipt.get('schemaVersion') != 'spark-dispatcher-terminal-observation-v1'
                            or receipt.get('jobId') != job_id
                            or receipt.get('dispatcher') != job['dispatcher']
                            or receipt.get('dispatcherProcessExited') is not True
                            or receipt.get('modelChildProcessesExited') is not True
                            or receipt.get('evidenceScope') != 'local_process_census'
                            or not isinstance(receipt.get('observedAt'), str)
                            or not isinstance(receipt.get('processCensusSha256'), str)
                            or not re.fullmatch('[0-9a-f]{64}', receipt['processCensusSha256'])):
                        raise SessionError('unbound_job_needs_dispatcher_terminal_receipt')
                if self.descendants(inventory['processes'], [(p['pid'], p['startTicks']) for p in job['processes']]): raise SessionError('job_process_still_alive')
                if any(c['running'] and (c['id'] in job['containerIds'] or c.get('job') == job_id) for c in inventory['containers']): raise SessionError('job_container_still_alive')
                self.resource_check(state, inventory)
                job['status'] = 'terminal'; job['endedAt'] = now()
                if dispatcher_terminal_receipt is not None: job['dispatcherTerminalReceipt'] = dispatcher_terminal_receipt
                self.save(state, 'job_exit_reconciled', jobId=job_id)
            if any(j['status'] == 'unknown' for j in state['jobs'].values()): return state
            if any(j['status'] == 'active' for j in state['jobs'].values()):
                if state['status'] != 'running':
                    state['status'] = 'running'; self.save(state, 'active_jobs_restored_after_reconciliation')
                return state
            if state['status'] in {'restoring', 'restoring_failed'}: return state
            if state['status'] in {'draining', 'reconcile_required', 'planning'}:
                # begin continuation is explicit after effects confirmed, with fresh idle/resource checks.
                self.resource_check(state, inventory, before=True, allow_busy=state.get('preempt', False))
                state['status'] = 'planning'; self.save(state, 'begin_reconciled')
            return state

    def resume_begin(self, session_id, owner):
        with self.locked():
            state = self.load(); inventory = self.backend.inventory(); self.authenticate(state, session_id, owner, inventory)
            if state['status'] != 'planning': raise SessionError('reconcile_before_resume')
            if any(j['status'] != 'terminal' for j in state['jobs'].values()): raise SessionError('jobs_prevent_begin_resume')
            return self._begin(state)

class Client:
    def __init__(self, session_id, owner, host=DEFAULT_HOST, *, runner=None):
        self.session_id, self.owner, self.host = check_id(session_id), check_id(owner), host
        self.runner = runner
        if not re.fullmatch(r'[A-Za-z0-9_.@:-]+', host) or host.startswith('-'): raise SessionError('invalid_ssh_host')

    @classmethod
    def from_environment(cls, session_id=None, owner=None):
        session_id = session_id or os.environ.get('SPARK_EXCLUSIVE_SESSION_ID')
        owner = owner or os.environ.get('SPARK_EXCLUSIVE_SESSION_OWNER')
        if not session_id or not owner: raise SessionError('spark_exclusive_session_required')
        return cls(session_id, owner, os.environ.get('SPARK_EXCLUSIVE_HOST', DEFAULT_HOST))

    @property
    def environment(self):
        return {'SPARK_EXCLUSIVE_SESSION_ID': self.session_id, 'SPARK_EXCLUSIVE_SESSION_OWNER': self.owner, 'SPARK_EXCLUSIVE_HOST': self.host}

    def request(self, action, **arguments):
        request = {'action': action, 'session_id': self.session_id, 'owner': self.owner, **arguments}
        if self.runner: return self.runner(request)
        socket_path = os.environ.get('SPARK_EXCLUSIVE_SOCKET')
        if socket_path:
            if action != 'require': raise SessionError('socket_gateway_read_only')
            encoded = json.dumps(request).encode() + b'\n'
            if len(encoded) > 16384: raise SessionError('socket_request_too_large')
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                    stream.settimeout(10); stream.connect(socket_path); stream.sendall(encoded)
                    payload = b''
                    while b'\n' not in payload:
                        chunk = stream.recv(4096)
                        if not chunk: raise SessionError('socket_gateway_unknown')
                        payload += chunk
                        if len(payload) > 65536: raise SessionError('socket_response_too_large')
                response = json.loads(payload.split(b'\n', 1)[0])
            except (OSError, ValueError) as exc: raise SessionError('socket_gateway_unknown') from exc
            if response.get('error'): raise SessionError(response['error'])
            return response['result']
        if sys.platform.startswith('linux') and os.environ.get('SPARK_EXCLUSIVE_REMOTE_LOCAL') == '1':
            return dispatch(request)
        source = Path(__file__).read_bytes()
        payload = json.dumps({'source': base64.b64encode(source).decode(), 'sha256': hashlib.sha256(source).hexdigest(), 'request': request})
        bootstrap = """import sys,json,base64,hashlib,pathlib,importlib.util,os,tempfile
p=json.load(sys.stdin)
s=base64.b64decode(p['source'])
assert hashlib.sha256(s).hexdigest()==p['sha256']
r=pathlib.Path.home()/'.local/state/tongxing-spark-exclusive/modules'
r.mkdir(parents=True,exist_ok=True,mode=0o700)
f=r/(p['sha256']+'.py')
if not f.exists():
 fd,tmp=tempfile.mkstemp(dir=r)
 with os.fdopen(fd,'wb') as h:
  h.write(s);h.flush();os.fsync(h.fileno())
 os.replace(tmp,f)
 fd=os.open(r,os.O_RDONLY);os.fsync(fd);os.close(fd)
assert hashlib.sha256(f.read_bytes()).hexdigest()==p['sha256']
q=importlib.util.spec_from_file_location('spark_exclusive_session',f)
m=importlib.util.module_from_spec(q);q.loader.exec_module(m)
m.remote_response(p['request'])
"""
        try:
            completed = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', self.host,
                                        'python3 -c ' + shlex.quote(bootstrap)], input=payload, text=True,
                                       capture_output=True, timeout=240, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc: raise SessionError('ssh_outcome_unknown_reconcile_before_retry') from exc
        try: response = json.loads(completed.stdout)
        except ValueError as exc: raise SessionError('ssh_outcome_unknown_reconcile_before_retry') from exc
        if completed.returncode or response.get('error'): raise SessionError(response.get('error', 'ssh_failed_unknown'))
        return response['result']

    def require_ready(self): return self.request('require')
    def start_job(self, purpose, pid=None):
        return self.request('job-start', purpose=purpose, dispatcher={'host': socket.gethostname(), 'pid': pid or os.getpid()})
    def bind_job(self, hold, *, pid=None, container_id=None):
        return self.request('job-bind', job_id=hold['jobId'], pid=pid, container_id=container_id)
    def end_job(self, hold, *, process_exited, outcome):
        return self.request('job-end', job_id=hold['jobId'], process_exited=process_exited, outcome=outcome)


def dispatch(request, engine=None):
    request = dict(request); action = request.pop('action')
    engine = engine or Engine(Path.home() / '.local/state/tongxing-spark-exclusive', LinuxBackend())
    if action == 'inspect': return engine.inspect()
    methods = {'begin': engine.begin, 'status': engine.status, 'require': engine.require, 'finish': engine.finish,
               'reconcile': engine.reconcile, 'resume-begin': engine.resume_begin, 'job-start': engine.job_start,
               'job-bind': engine.job_bind, 'job-end': engine.job_end}
    if action not in methods: raise SessionError('unknown_action')
    return methods[action](**request)

def remote_response(request):
    try: print(json.dumps({'result': dispatch(request)}, sort_keys=True))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, SessionError) else type(exc).__name__}))
        raise SystemExit(2)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--local', action='store_true', help='Run on Spark Linux; fixed host state path')
    sub = parser.add_subparsers(dest='action')
    sub.add_parser('inspect')
    for action in ('begin', 'status', 'require', 'finish', 'reconcile', 'resume-begin', 'job-start', 'job-bind', 'job-end'):
        command = sub.add_parser(action)
        command.add_argument('--session-id', required=True)
        command.add_argument('--owner', required=True)
        if action == 'begin':
            command.add_argument('--minimum-available-gib', type=float, required=True)
            command.add_argument('--container-id', action='append', dest='container_ids', default=[])
            command.add_argument('--preempt', action='store_true')
            command.add_argument('--allow-interrupted-restart', action='store_true')
        if action == 'job-start': command.add_argument('--purpose', required=True)
        if action in {'job-bind', 'job-end'}: command.add_argument('--job-id', required=True)
        if action == 'reconcile':
            command.add_argument('--job-id')
            command.add_argument('--resume-frozen-launcher', choices=LAUNCHERS)
            command.add_argument('--confirm-dispatcher-terminal', action='store_true')
        if action == 'job-bind':
            command.add_argument('--pid', type=int); command.add_argument('--container-id')
        if action == 'job-end':
            command.add_argument('--outcome', choices=['known_terminal', 'unknown'], required=True)
            command.add_argument('--process-exited', action='store_true')
    args = vars(parser.parse_args()); host, local = args.pop('host'), args.pop('local')
    action = args.pop('action') or 'inspect'
    try:
        if local:
            if not sys.platform.startswith('linux'): raise SessionError('local_backend_requires_linux')
            result = dispatch({'action': action, **args})
        else:
            session_id, owner = args.pop('session_id', 'inspection'), args.pop('owner', 'inspection')
            client = Client(session_id, owner, host)
            if action == 'inspect': result = client.request('inspect')
            else:
                confirm = args.pop('confirm_dispatcher_terminal', False)
                if confirm:
                    if action != 'reconcile' or not args.get('job_id'): raise SessionError('dispatcher_terminal_job_id_required')
                    current = client.request('status')['session']['jobs'].get(args['job_id'])
                    if not current or current['status'] != 'unknown' or current['purpose'] != 'production-model-call':
                        raise SessionError('dispatcher_terminal_job_not_eligible')
                    dispatcher = current['dispatcher']
                    if dispatcher.get('host') != socket.gethostname() or type(dispatcher.get('pid')) is not int:
                        raise SessionError('dispatcher_host_identity_mismatch')
                    try: os.kill(dispatcher['pid'], 0)
                    except ProcessLookupError: pass
                    else: raise SessionError('dispatcher_process_still_alive')
                    census = subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True, check=True).stdout
                    if any('codex exec' in row and 'codex exec-server' not in row for row in census.splitlines()):
                        raise SessionError('model_child_process_still_alive')
                    args['dispatcher_terminal_receipt'] = {
                        'schemaVersion': 'spark-dispatcher-terminal-observation-v1',
                        'jobId': args['job_id'], 'dispatcher': dispatcher,
                        'dispatcherProcessExited': True, 'modelChildProcessesExited': True,
                        'evidenceScope': 'local_process_census', 'observedAt': now(),
                        'processCensusSha256': hashlib.sha256(census.encode()).hexdigest()}
                result = client.request(action, **args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except SessionError as exc:
        print(json.dumps({'error': str(exc)})); return 2

if __name__ == '__main__': raise SystemExit(main())

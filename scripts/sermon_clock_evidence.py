"""Process-local monotonic evidence. UTC is correlation, not a duration clock."""
import os
import re
import threading
import uuid
import hashlib
import json
import sys
import time
from functools import lru_cache

_lock = threading.Lock()
_pid = None
_domain = None


def _after_fork():
    global _lock, _pid, _domain
    _lock, _pid, _domain = threading.Lock(), None, None


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def clock_domain():
    global _pid, _domain
    with _lock:
        if _pid != os.getpid():
            _pid, _domain = os.getpid(), uuid.uuid4().hex
        return _domain


def monotonic_interval(start, end):
    keys = ('clockDomainId', 'monotonicStartNs', 'monotonicEndNs')
    if not any(k in e for e in (start,end) for k in keys):
        return None
    domain = start.get('clockDomainId')
    if not isinstance(domain,str) or not re.fullmatch(r'[0-9a-f]{32}',domain) or end.get('clockDomainId') != domain:
        raise ValueError('untrusted_clock_domain')
    begin, finish = start.get('monotonicStartNs'), end.get('monotonicEndNs')
    if any(not isinstance(n,str) or not re.fullmatch(r'[0-9]{1,20}',n) for n in (begin,finish)):
        raise ValueError('invalid_monotonic_timestamp')
    if end.get('monotonicStartNs') != begin or int(finish)<int(begin):
        raise ValueError('invalid_monotonic_interval')
    elapsed = (int(finish)-int(begin))/1_000_000_000
    if abs(elapsed-end['elapsedSeconds'])>0.000001:
        raise ValueError('monotonic_elapsed_mismatch')
    return {'clockDomainId':domain,'monotonicStartNs':begin,'monotonicEndNs':finish,
            'elapsedSeconds':end['elapsedSeconds'],'durationBasis':'same_process_monotonic'}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def host_clock_identity():
    """Independently observed same-boot monotonic implementation; never shell.

    The process-local clock domain remains distinct. A caller-supplied identity
    cannot establish comparability; each process must read its own kernel boot.
    """
    if sys.platform == 'darwin':
        import ctypes
        class Timeval(ctypes.Structure):
            _fields_ = [('seconds', ctypes.c_long), ('microseconds', ctypes.c_int)]
        result = Timeval(); size = ctypes.c_size_t(ctypes.sizeof(result))
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.sysctlbyname(b'kern.boottime', ctypes.byref(result), ctypes.byref(size), None, 0) != 0:
            raise ValueError('clock_host_identity_unavailable')
        boot = [result.seconds, result.microseconds]
    elif sys.platform.startswith('linux'):
        from pathlib import Path
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if not re.fullmatch(r'[a-f0-9-]{36}', boot):
            raise ValueError('clock_host_identity_unavailable')
    else:
        raise ValueError('clock_host_identity_unavailable')
    info = time.get_clock_info('monotonic')
    if not info.monotonic or info.adjustable:
        raise ValueError('clock_host_identity_unavailable')
    return _hash([sys.platform, boot, info.implementation, info.resolution])


def _proof(value, phase):
    keys = {'clockLaunchSha256', 'clockIdentitySha256', 'clockParentDomainSha256',
            'clockParentSpanSha256', 'clockRunSha256', 'clockParentStartNs'}
    if phase in ('started', 'finished', 'joined'):
        keys |= {'clockChildDomainSha256', 'clockChildStartNs'}
    if phase in ('finished', 'joined'):
        keys.add('clockChildEndNs')
    if phase == 'joined':
        keys.add('clockParentEndNs')
    if type(value) is not dict or set(value) != keys:
        raise ValueError('invalid_clock_handshake')
    for key, item in value.items():
        if key.endswith('Sha256'):
            if type(item) is not str or re.fullmatch(r'[a-f0-9]{64}', item) is None:
                raise ValueError('invalid_clock_handshake')
        elif type(item) is not int or not 0 <= item <= 2**63-1:
            raise ValueError('invalid_clock_handshake')
    timeline = [value[key] for key in ('clockParentStartNs', 'clockChildStartNs',
        'clockChildEndNs', 'clockParentEndNs') if key in value]
    if timeline != sorted(timeline):
        raise ValueError('invalid_clock_handshake')
    return value


def _record(phase, value):
    from scripts import sermon_accounting as accounting
    accounting.record_workload('clock.worker_' + phase + '_v1', value)
    return dict(value)


def worker_launch(parent_span_id=None):
    """Call inside the synchronous launcher span; persist in its bound request."""
    from scripts import sermon_accounting as accounting
    identity = accounting._identity.get() or tuple(os.environ.get(k) for k in accounting.ENV_KEYS[:2])
    parent = parent_span_id or accounting._span.get() or os.environ.get(accounting.ENV_KEYS[3])
    if not identity[1] or accounting._label(parent, None) is None:
        raise ValueError('clock_accounting_required')
    return _record('launch', _proof({
        'clockLaunchSha256': _hash(uuid.uuid4().hex), 'clockIdentitySha256': host_clock_identity(),
        'clockParentDomainSha256': _hash(clock_domain()), 'clockParentSpanSha256': _hash(parent),
        'clockRunSha256': _hash(identity[1]), 'clockParentStartNs': time.monotonic_ns()}, 'launch'))


def worker_started(launch):
    """Call inside child's accounting session before any measured child work."""
    from scripts import sermon_accounting as accounting
    launch = _proof(launch, 'launch')
    identity = accounting._identity.get() or tuple(os.environ.get(k) for k in accounting.ENV_KEYS[:2])
    if launch['clockIdentitySha256'] != host_clock_identity() or launch['clockRunSha256'] != _hash(identity[1]):
        raise ValueError('clock_worker_scope_changed')
    return _record('started', _proof({**launch, 'clockChildDomainSha256': _hash(clock_domain()),
        'clockChildStartNs': time.monotonic_ns()}, 'started'))


def worker_finished(started):
    started = _proof(started, 'started')
    if started['clockIdentitySha256'] != host_clock_identity() or started['clockChildDomainSha256'] != _hash(clock_domain()):
        raise ValueError('clock_worker_scope_changed')
    return _record('finished', _proof({**started, 'clockChildEndNs': time.monotonic_ns()}, 'finished'))


def worker_joined(launch, finished):
    """After wait/reap, verify the actual saved child result before recording join."""
    launch, finished = _proof(launch, 'launch'), _proof(finished, 'finished')
    if any(finished[key] != item for key, item in launch.items()) or (
        launch['clockIdentitySha256'] != host_clock_identity() or
        launch['clockParentDomainSha256'] != _hash(clock_domain())):
        raise ValueError('clock_worker_scope_changed')
    return _record('joined', _proof({**finished, 'clockParentEndNs': time.monotonic_ns()}, 'joined'))


def validate_worker_handshake(launch, finished, joined):
    """Pure replay of frozen facts; no clock reads, writes or fresh permission."""
    launch, finished, joined = (_proof(launch, 'launch'), _proof(finished, 'finished'),
                               _proof(joined, 'joined'))
    if any(finished[key] != value for key, value in launch.items()) or any(
            joined[key] != value for key, value in finished.items()):
        raise ValueError('clock_worker_scope_changed')
    return dict(joined)


def handshake_windows(events, run_id):
    """Read-only four-fact proof; absent/conflicting facts confer no timing trust."""
    groups, invalid = {}, set()
    for row in events:
        if row.get('event') != 'workload' or row.get('runId') != run_id:
            continue
        phase = {f'clock.worker_{name}_v1': name for name in ('launch', 'started', 'finished', 'joined')}.get(row.get('stage'))
        if phase:
            try:
                value = _proof(row.get('metrics'), phase)
            except ValueError:
                metrics = row.get('metrics')
                if type(metrics) is dict and type(metrics.get('clockLaunchSha256')) is str:
                    invalid.add(metrics['clockLaunchSha256'])
                continue
            groups.setdefault(value['clockLaunchSha256'], {}).setdefault(phase, []).append(value)
    windows = []
    for launch_hash, phases in groups.items():
        if launch_hash in invalid:
            continue
        if set(phases) != {'launch', 'started', 'finished', 'joined'}:
            continue
        unique = {key: {_hash(value): value for value in rows} for key, rows in phases.items()}
        if any(len(rows) != 1 for rows in unique.values()):
            continue
        proofs = {key: next(iter(rows.values())) for key, rows in unique.items()}
        joined = proofs['joined']
        if joined['clockRunSha256'] == _hash(run_id) and all(
            all(joined[key] == value for key, value in proof.items()) for proof in proofs.values()):
            windows.append(joined)
    return windows

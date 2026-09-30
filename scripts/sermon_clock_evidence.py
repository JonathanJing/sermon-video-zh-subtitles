"""Process-local monotonic evidence. UTC is correlation, not a duration clock."""
import os
import re
import threading
import uuid

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

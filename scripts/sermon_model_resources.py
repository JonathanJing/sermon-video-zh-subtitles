"""Bounded cross-process local model admission; queuing is not model failure."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time

from scripts.sermon_execution_harness import ExecutionTerminated, _LOCK_FDS


def memory_snapshot():
    if platform.system() != 'Darwin':
        return {'totalBytes': None, 'availableBytes': None}
    total = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], timeout=3))
    output = subprocess.check_output(['vm_stat'], text=True, timeout=3)
    page = int(re.search(r'page size of (\d+) bytes', output).group(1))
    pages = {key: int(value) for key, value in re.findall(r'^([^:\n]+):\s+(\d+)\.', output, re.M)}
    available = sum(pages.get(key, 0) for key in ('Pages free', 'Pages inactive', 'Pages speculative')) * page
    return {'totalBytes': total, 'availableBytes': available}


def model_policy(snapshot=None):
    snapshot = memory_snapshot() if snapshot is None else snapshot
    default = 2 if (snapshot['totalBytes'] or 0) >= 48 * 1024**3 else 1
    slots = int(os.environ.get('SERMON_LOCAL_MODEL_SLOTS', str(default)))
    if slots not in (1, 2):
        raise ValueError('SERMON_LOCAL_MODEL_SLOTS must be 1 or 2')
    reserve = float(os.environ.get('SERMON_LOCAL_MODEL_RESERVE_GIB', '12'))
    if not 4 <= reserve <= 64:
        raise ValueError('Local model reserve must be 4..64 GiB')
    return {'slots': slots, 'reserveBytes': int(reserve * 1024**3), **snapshot}


@contextmanager
def local_model_slot(*, cancel_event=None, timeout=3600):
    if timeout <= 0:
        raise ValueError('Positive model admission timeout required')
    policy = model_policy()
    root = Path(os.environ.get('SERMON_LOCAL_MODEL_LOCK_ROOT', str(Path(tempfile.gettempdir()) / f'sermon-model-slots-{os.getuid()}')))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + timeout
    fd = None
    token = None
    started = time.monotonic()
    next_memory_check = 0
    try:
        while fd is None:
            if cancel_event is not None and cancel_event.is_set():
                raise ExecutionTerminated('Cancelled while waiting for local model capacity')
            if time.monotonic() >= deadline:
                raise ExecutionTerminated('Local model capacity deadline exceeded; no automatic Spark dispatch')
            now = time.monotonic()
            if now >= next_memory_check:
                snapshot = memory_snapshot()
                next_memory_check = now + 1
            memory_ok = snapshot['availableBytes'] is None or snapshot['availableBytes'] >= policy['reserveBytes']
            if memory_ok:
                for slot in range(policy['slots']):
                    candidate = os.open(root / f'slot-{slot}.lock', os.O_CREAT | os.O_RDWR, 0o600)
                    try:
                        fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        os.close(candidate)
                    else:
                        fd = candidate
                        break
            if fd is None:
                if cancel_event is not None:
                    cancel_event.wait(.1)
                else:
                    time.sleep(.1)
        # bounded_process inherits this FD: a surviving child keeps its permit.
        token = _LOCK_FDS.set((*_LOCK_FDS.get(), fd))
        yield {**policy, 'slot': slot, 'admissionMemory': snapshot, 'waitSeconds': time.monotonic() - started}
    finally:
        if token is not None:
            _LOCK_FDS.reset(token)
        if fd is not None:
            os.close(fd)

"""Host-local shared semaphore for paid Layer 2 API requests.

Each slot is held only while one request is in flight. ``flock`` releases it if a
worker exits or the host reboots, so abandoned lock files do not consume capacity.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import time

MAX_IN_FLIGHT_API_CALLS = 24
MAX_GROUP_WORKERS_PER_LOCALE = 16


@contextmanager
def request_slot(job_root: Path):
    slots = Path(job_root) / '.layer2-api-slots'
    slots.mkdir(parents=True, exist_ok=True)
    while True:
        for index in range(MAX_IN_FLIGHT_API_CALLS):
            path = slots / f'{index:02d}.lock'
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                continue
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            return
        time.sleep(0.05)

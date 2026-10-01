"""Bounded CPU work queue; model calls remain on the producer thread."""
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
import threading
import time


class BoundedCpuPipeline:
    def __init__(self, *, workers=1, max_pending=8):
        if type(workers) is not int or workers not in (0, 1, 2):
            raise ValueError("CPU workers must be 0, 1 or 2")
        if type(max_pending) is not int or not 1 <= max_pending <= 16:
            raise ValueError("CPU pending limit must be 1..16")
        self.pool = ThreadPoolExecutor(max_workers=workers) if workers else None
        self.pending = deque()
        self.lock = threading.Lock()
        self.closed = False
        self.stats = {"workers": workers, "maxPending": max_pending,
                      "submitted": 0, "peakPending": 0,
                      "backpressureSeconds": 0.0, "cpuTaskSeconds": 0.0}

    def __enter__(self):
        return self

    def check(self):
        # Any failed completed task stops admission, even if it is not oldest.
        for future in self.pending:
            if future.done():
                future.result()
        while self.pending and self.pending[0].done():
            self.pending.popleft()

    def submit(self, function, *args, **kwargs):
        if self.closed:
            raise RuntimeError("CPU pipeline already closed")
        self.check()
        if len(self.pending) >= self.stats["maxPending"]:
            started = time.monotonic()
            self.pending[0].result()
            self.stats["backpressureSeconds"] += time.monotonic() - started
            self.check()

        def task():
            started = time.monotonic()
            try:
                return function(*args, **kwargs)
            finally:
                with self.lock:
                    self.stats["cpuTaskSeconds"] += time.monotonic() - started

        if self.pool:
            future = self.pool.submit(copy_context().run, task)
        else:
            future = Future()
            try:
                future.set_result(task())
            except BaseException as exc:
                future.set_exception(exc)
            future.result()
        self.pending.append(future)
        self.stats["submitted"] += 1
        self.stats["peakPending"] = max(self.stats["peakPending"], len(self.pending))
        return future

    def __exit__(self, kind, value, traceback):
        self.closed = True
        try:
            if kind is None:
                for future in self.pending:
                    future.result()
            else:
                for future in self.pending:
                    future.cancel()
        finally:
            # A running write must finish before return; no detached side effects.
            if self.pool:
                self.pool.shutdown(wait=True, cancel_futures=True)
        return False

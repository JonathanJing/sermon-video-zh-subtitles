"""Bounded CPU-only audio preparation; callers retain ordered durable commits.

Model outputs must be detached from GPU by the calling thread before submit.
No model, approval, receipt, or resource-owner state is changed here.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from collections import deque
from contextvars import copy_context
import threading
import time


class BoundedAudioCPU:
    def __init__(self, workers=0, max_pending=16):
        if type(workers) is not int or workers not in (0, 1, 2, 4):
            raise ValueError("Audio CPU workers must be 0, 1, 2 or 4")
        if type(max_pending) is not int or not 1 <= max_pending <= 16:
            raise ValueError("Audio CPU queue must be 1..16 units")
        self.workers, self.max_pending = workers, max_pending
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="audio-cpu") if workers else None
        self.pending = deque()
        self.lock = threading.Lock()
        self.active = self.peak_active = self.peak_pending = self.submitted = self.completed = 0
        self.failed = False
        self.task_wall_seconds = 0.0
        self.started = time.perf_counter()

    def _run(self, function, args, kwargs):
        started = time.perf_counter()
        with self.lock:
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
        try:
            return function(*args, **kwargs)
        except BaseException:
            with self.lock:
                self.failed = True
            raise
        finally:
            with self.lock:
                self.active -= 1
                self.completed += 1
                self.task_wall_seconds += time.perf_counter() - started

    def submit(self, function, *args, **kwargs):
        # Observe all completed errors before dispatching more CPU writes.
        for pending in self.pending:
            if pending.done():
                pending.result()
        while self.pending and self.pending[0].done():
            self.pending.popleft().result()
        if len(self.pending) >= self.max_pending:
            self.pending.popleft().result()
        self.submitted += 1
        if self.pool is None:
            future = Future()
            try:
                future.set_result(self._run(function, args, kwargs))
            except BaseException as error:
                future.set_exception(error)
        else:
            future = self.pool.submit(copy_context().run, self._run, function, args, kwargs)
        self.pending.append(future)
        self.peak_pending = max(self.peak_pending, len(self.pending))
        return future

    def close(self):
        # Running writes always finish before the parent releases its file lock.
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)

    def report(self):
        return {"schemaVersion": "sermon-audio-cpu-runtime-v1", "workers": self.workers,
                "maxPendingUnits": self.max_pending, "peakPendingUnits": self.peak_pending,
                "peakActiveWorkers": self.peak_active, "submittedUnits": self.submitted,
                "completedUnits": self.completed, "failed": self.failed,
                "wallSeconds": time.perf_counter() - self.started,
                "wallScope": "this_producer_invocation_including_model_wait_and_parent_commits",
                "sumTaskWallSeconds": self.task_wall_seconds,
                "taskTimingScope": "encode_full_decode_and_hash_wall_time_summed_across_workers",
                "commitPolicy": "parent_ordered_after_full_decode_and_hash",
                "modelCallsInWorkers": 0}

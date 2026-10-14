"""Owned, bounded spawn workers for admitted immutable TTS batch windows.

    Workers only return model outputs. The caller validates and commits files, in
window order, and replenishes a slot only after consuming its result.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
import copy
import multiprocessing as mp
from multiprocessing.connection import wait
import math
import os
from pathlib import Path
import time
from typing import Callable


class ReplicaPoolError(RuntimeError):
    pass


def linux_mem_available() -> int:
    """Return host MemAvailable bytes, failing closed if measurement is absent."""
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ReplicaPoolError("Linux MemAvailable measurement is unavailable")


def _worker(connection, checkpoint, factory, engine_kwargs, worker_id):
    index = None
    try:
        started = time.monotonic()
        engine = factory(checkpoint, **engine_kwargs)
        connection.send({"kind": "ready", "worker": worker_id, "pid": os.getpid(),
                         "timestamp": time.time(), "loadSeconds": time.monotonic() - started})
        while True:
            command = connection.recv()
            if command is None:
                break
            index, requests, seed = command
            started = time.monotonic()
            rows = engine.batch(requests, seed=seed)
            connection.send({"kind": "result", "worker": worker_id, "pid": os.getpid(),
                             "index": index, "rows": rows, "timestamp": time.time(),
                             "generationSeconds": time.monotonic() - started})
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:
        try:
            connection.send({"kind": "error", "worker": worker_id, "pid": os.getpid(),
                             "index": index, "timestamp": time.time(),
                             "errorType": type(exc).__name__})
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


class SparkTTSReplicaPool(AbstractContextManager):
    """A single-use pool whose outstanding windows never exceed its replicas.

    ``factory`` must be importable at module scope for multiprocessing spawn.
    No process or model is created before ``start``; call it only after admission.
    A telemetry callback runs exclusively in the parent and receives metadata,
    never model outputs or sermon text. Memory is checked between wait/receive
    operations; deserializing one batch result can exceed the polling interval.
    """

    def __init__(self, checkpoint, factory: Callable, engine_kwargs: dict, *,
                 replicas: int = 8, min_available_gib: float = 24,
                 memory_reader: Callable[[], int] = linux_mem_available,
                 telemetry: Callable[[dict], None] | None = None,
                 startup_timeout: float = 600, generation_timeout: float = 600,
                 poll_interval: float = 0.2):
        if type(replicas) is not int or not 1 <= replicas <= 32:
            raise ValueError("Replica count must be 1..32")
        if (not all(math.isfinite(value) for value in
                    (min_available_gib, startup_timeout, generation_timeout, poll_interval))
                or not 0 <= min_available_gib <= 1024
                or min(startup_timeout, generation_timeout, poll_interval) <= 0):
            raise ValueError("Invalid replica pool resource limits")
        self.checkpoint, self.factory = checkpoint, factory
        self.engine_kwargs = copy.deepcopy(engine_kwargs)
        self.replicas = replicas
        self.reserve_bytes = int(min_available_gib * 1024**3)
        self.memory_reader, self.telemetry = memory_reader, telemetry
        self.startup_timeout, self.generation_timeout = startup_timeout, generation_timeout
        self.poll_interval = poll_interval
        self.processes, self.connections = [], []
        self._ready, self._busy, self._pending, self._outputs = set(), {}, {}, {}
        # Worker-side generation seconds per window; the parent's wait is not this.
        self._generation = {}
        self._seen = set()
        self._started = self._closed = False
        self.min_available_bytes = None

    @property
    def outstanding(self):
        return len(self._pending)

    def _event(self, event):
        if self.telemetry is not None:
            self.telemetry(event)

    def _resource_snapshot(self, available):
        workers = []
        for process in self.processes:
            rss = None
            try:
                for line in Path(f"/proc/{process.pid}/status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1]) * 1024
            except (OSError, ValueError):
                pass
            workers.append({"pid": process.pid, "rssBytes": rss})
        sizes = []
        for rows in self._outputs.values():
            for row in rows:
                wave = row.get("wave") if isinstance(row, dict) else None
                size = getattr(wave, "nbytes", None)
                if size is None and hasattr(wave, "numel") and hasattr(wave, "element_size"):
                    size = wave.numel() * wave.element_size()
                sizes.append(size)
        return {"kind": "reserve_failure", "timestamp": time.time(),
                "memAvailableBytes": available if type(available) is int else None,
                "reserveBytes": self.reserve_bytes, "workers": workers,
                "receivedUnconsumedWaveBytes": sum(sizes) if all(type(n) is int for n in sizes) else None,
                "pendingWindows": sorted(self._pending), "receivedWindows": sorted(self._outputs),
                "busyWorkers": dict(self._busy), "gpuPeakBytes": None,
                "gpuPeakStatus": "unknown", "inFlightWaveBytes": None}

    def _guard(self):
        try:
            available = self.memory_reader()
        except Exception as exc:
            self._event(self._resource_snapshot(None) | {"memoryReadError": type(exc).__name__})
            raise
        if type(available) is int:
            self.min_available_bytes = (available if self.min_available_bytes is None
                                        else min(available, self.min_available_bytes))
        if type(available) is not int or available < self.reserve_bytes:
            self._event(self._resource_snapshot(available))
            raise ReplicaPoolError("MemAvailable is below the TTS replica reserve")
        return available

    def _health(self):
        self._guard()
        for worker, process in enumerate(self.processes):
            if process.exitcode is not None:
                self._event({"kind": "worker_exit", "timestamp": time.time(),
                             "worker": worker, "pid": process.pid,
                             "exitCode": process.exitcode})
                raise ReplicaPoolError(f"TTS replica {worker} exited ({process.exitcode})")
        now = time.monotonic()
        for index, submitted in self._pending.items():
            if index not in self._outputs and now - submitted > self.generation_timeout:
                raise ReplicaPoolError(f"TTS window {index} exceeded generation timeout")

    def _receive(self, timeout):
        self._health()
        for connection in wait(self.connections, timeout=timeout):
            worker = self.connections.index(connection)
            try:
                event = connection.recv()
            except (EOFError, OSError) as exc:
                raise ReplicaPoolError(f"TTS replica {worker} closed its channel") from exc
            if not isinstance(event, dict) or event.get("worker") != worker:
                raise ReplicaPoolError("TTS replica event identity differs")
            kind = event.get("kind")
            if kind == "ready":
                if worker in self._ready or worker in self._busy:
                    raise ReplicaPoolError("Duplicate TTS replica readiness")
                self._ready.add(worker)
            elif kind == "result":
                index = event.get("index")
                if self._busy.get(worker) != index or index not in self._pending or index in self._outputs:
                    raise ReplicaPoolError("TTS replica result window differs")
                seconds = event.get("generationSeconds")
                if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
                    raise ReplicaPoolError("TTS replica generation timing invalid")
                self._generation[index] = float(seconds)
                self._outputs[index] = event["rows"]
                del self._busy[worker]
            elif kind == "error":
                self._event(event)
                raise ReplicaPoolError(f"TTS replica {worker} failed ({event.get('errorType')})")
            else:
                raise ReplicaPoolError("Unknown TTS replica event")
            self._event({key: value for key, value in event.items() if key != "rows"})
        self._health()

    def start(self):
        if self._closed or self._started:
            raise ReplicaPoolError("TTS replica pool cannot be restarted")
        self._started = True
        deadline = time.monotonic() + self.startup_timeout
        try:
            context = mp.get_context("spawn")
            for worker in range(self.replicas):
                self._guard()
                parent, child = context.Pipe(duplex=True)
                process = context.Process(target=_worker, args=(child, self.checkpoint,
                    self.factory, self.engine_kwargs, worker), name=f"sermon-tts-{worker}")
                self.connections.append(parent)
                try:
                    process.start()
                finally:
                    child.close()
                self.processes.append(process)
            while len(self._ready) != self.replicas:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReplicaPoolError("TTS replicas exceeded model load timeout")
                self._receive(min(self.poll_interval, remaining))
            self._event({"kind": "pool_ready", "timestamp": time.time(),
                         "replicas": self.replicas, "memAvailableBytes": self._guard()})
            return self
        except BaseException:
            self.close()
            raise

    def submit(self, index: int, requests: list[dict], *, seed: int):
        if not self._started or self._closed:
            raise ReplicaPoolError("TTS replica pool is not running")
        if type(index) is not int or index < 0 or index in self._seen:
            raise ValueError("TTS window index must be unique and nonnegative")
        if not requests or type(seed) is not int:
            raise ValueError("TTS window needs requests and an integer seed")
        if self.outstanding >= self.replicas:
            raise ValueError("Consume a TTS window before replenishing the pool")
        try:
            self._receive(0)
            idle = sorted(self._ready - self._busy.keys())
            if not idle:
                raise ReplicaPoolError("TTS replica capacity accounting differs")
            worker = idle[0]
            self.connections[worker].send((index, copy.deepcopy(requests), seed))
            self._seen.add(index)
            self._pending[index] = time.monotonic()
            self._busy[worker] = index
            self._event({"kind": "submitted", "timestamp": time.time(),
                         "worker": worker, "index": index})
        except BaseException:
            self.close()
            raise

    def result(self, index: int):
        if self._closed or index not in self._pending:
            raise ValueError("TTS window was not submitted or already consumed")
        try:
            while index not in self._outputs:
                self._receive(self.poll_interval)
            self._health()
            rows = self._outputs.pop(index)
            del self._pending[index]
            return rows
        except BaseException:
            self.close()
            raise

    def generation_seconds(self, index: int) -> float:
        """Worker-side generation time of a window that result() has returned."""
        if index not in self._generation:
            raise ValueError("TTS window generation timing is unavailable")
        return self._generation.pop(index)

    def close(self):
        if self._closed:
            return
        self._closed = True
        # Never send a shutdown message into a worker blocked on a large result.
        # Termination applies only to the process objects created by this pool.
        for process in self.processes:
            if process.is_alive():
                process.terminate()
        for process in self.processes:
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        for connection in self.connections:
            connection.close()
        self._outputs.clear()
        self._generation.clear()
        self._pending.clear()
        try:
            self._event({"kind": "pool_closed", "timestamp": time.time(),
                         "minAvailableBytes": self.min_available_bytes})
        except Exception:
            # A telemetry failure must not mask the original producer failure.
            pass

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


# Short alias for callers that already identify the Spark backend.
ReplicaPool = SparkTTSReplicaPool

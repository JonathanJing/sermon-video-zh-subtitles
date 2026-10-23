"""Owned, bounded spawn workers for admitted immutable TTS batch windows.

    Workers only return model outputs. The caller validates and commits files, in
window order, and replenishes a slot only after consuming its result.

Telemetry carries memory metadata only: host MemAvailable and parent RSS at each
event, and each worker's RSS and CUDA caching-allocator counters after load and
after every window. ``release_cuda_cache`` makes a worker return its cached, unused
allocator blocks after each window; it is off unless the caller asks for it.
``cuda_alloc_conf`` is exported as PYTORCH_CUDA_ALLOC_CONF before any worker spawns,
and ``admission_gib_per_replica`` makes ``start`` require reserve plus that budget per
replica before the first process exists, so a run that cannot fit never loads a model.
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


def _rss_bytes(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def _cuda_memory():
    """This process's CUDA caching-allocator counters, or None without torch/CUDA."""
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    return {"allocatedBytes": torch.cuda.memory_allocated(),
            "reservedBytes": torch.cuda.memory_reserved(),
            "maxAllocatedBytes": torch.cuda.max_memory_allocated(),
            "maxReservedBytes": torch.cuda.max_memory_reserved()}


def _worker_memory():
    return {"rssBytes": _rss_bytes(os.getpid()), "cuda": _cuda_memory()}


def _release_cuda_cache():
    """Return cached, unused allocator blocks to the device; None without CUDA."""
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    started = time.monotonic()
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    return time.monotonic() - started


def _worker(connection, checkpoint, factory, engine_kwargs, worker_id, release_cuda_cache=False):
    index = None
    try:
        started = time.monotonic()
        engine = factory(checkpoint, **engine_kwargs)
        connection.send({"kind": "ready", "worker": worker_id, "pid": os.getpid(),
                         "timestamp": time.time(), "loadSeconds": time.monotonic() - started,
                         "memory": _worker_memory()})
        while True:
            command = connection.recv()
            if command is None:
                break
            index, requests, seed = command
            started = time.monotonic()
            rows = engine.batch(requests, seed=seed)
            generation = time.monotonic() - started
            released = _release_cuda_cache() if release_cuda_cache else None
            connection.send({"kind": "result", "worker": worker_id, "pid": os.getpid(),
                             "index": index, "rows": rows, "timestamp": time.time(),
                             "generationSeconds": generation, "releaseSeconds": released,
                             "memory": _worker_memory()})
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
                 poll_interval: float = 0.2, release_cuda_cache: bool = False,
                 cuda_alloc_conf: str | None = None, admission_gib_per_replica: float = 0):
        if type(replicas) is not int or not 1 <= replicas <= 32:
            raise ValueError("Replica count must be 1..32")
        if type(release_cuda_cache) is not bool:
            raise ValueError("release_cuda_cache must be a bool")
        if cuda_alloc_conf is not None and (type(cuda_alloc_conf) is not str or not cuda_alloc_conf
                                            or cuda_alloc_conf != cuda_alloc_conf.strip()):
            raise ValueError("cuda_alloc_conf must be None or a non-empty setting string")
        if (type(admission_gib_per_replica) not in (int, float) or isinstance(admission_gib_per_replica, bool)
                or not math.isfinite(admission_gib_per_replica) or not 0 <= admission_gib_per_replica <= 1024):
            raise ValueError("admission_gib_per_replica must be a finite GiB value in 0..1024")
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
        self.release_cuda_cache = release_cuda_cache
        self.cuda_alloc_conf = cuda_alloc_conf
        self.admission_bytes_per_replica = int(admission_gib_per_replica * 1024**3)
        self.processes, self.connections = [], []
        self._ready, self._busy, self._pending, self._outputs = set(), {}, {}, {}
        # Latest memory metadata each worker reported, for the reserve-failure snapshot.
        self._worker_memory = {}
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
        workers = [{"pid": process.pid, "rssBytes": _rss_bytes(process.pid),
                    "lastReported": self._worker_memory.get(worker)}
                   for worker, process in enumerate(self.processes)]
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
                "parentRssBytes": _rss_bytes(os.getpid()),
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
        available = self._guard()
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
        return available

    def _receive(self, timeout):
        """Receive worker events; return host MemAvailable sampled after them."""
        self._health()
        forwarded = []
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
                self._worker_memory[worker] = event.get("memory")
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
                self._worker_memory[worker] = event.get("memory")
            elif kind == "error":
                self._event(event)
                raise ReplicaPoolError(f"TTS replica {worker} failed ({event.get('errorType')})")
            else:
                raise ReplicaPoolError("Unknown TTS replica event")
            forwarded.append({key: value for key, value in event.items() if key != "rows"})
        available = self._health()
        parent_rss = _rss_bytes(os.getpid())
        for event in forwarded:
            self._event(event | {"memAvailableBytes": available, "parentRssBytes": parent_rss})
        return available

    def _configure_allocator(self):
        """Workers inherit the allocator setting through the spawn environment."""
        if self.cuda_alloc_conf is None:
            return
        present = os.environ.get("PYTORCH_CUDA_ALLOC_CONF")
        if present not in (None, self.cuda_alloc_conf):
            self._event({"kind": "allocator_conflict", "timestamp": time.time(),
                         "required": self.cuda_alloc_conf, "present": present})
            raise ReplicaPoolError("PYTORCH_CUDA_ALLOC_CONF differs from the pool's allocator setting")
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = self.cuda_alloc_conf

    def _admit(self):
        """Whole-pool budget before any process exists: the reserve plus each replica's peak."""
        available = self._guard()
        required = self.reserve_bytes + self.replicas * self.admission_bytes_per_replica
        event = {"kind": "admission", "timestamp": time.time(), "memAvailableBytes": available,
                 "requiredBytes": required, "reserveBytes": self.reserve_bytes,
                 "admissionBytesPerReplica": self.admission_bytes_per_replica, "replicas": self.replicas}
        if self.admission_bytes_per_replica and available < required:
            self._event(event | {"status": "rejected"})
            raise ReplicaPoolError("MemAvailable is below the TTS replica admission budget")
        self._event(event | {"status": "admitted"})

    def start(self):
        if self._closed or self._started:
            raise ReplicaPoolError("TTS replica pool cannot be restarted")
        self._started = True
        deadline = time.monotonic() + self.startup_timeout
        try:
            self._configure_allocator()
            self._admit()
            context = mp.get_context("spawn")
            for worker in range(self.replicas):
                self._guard()
                parent, child = context.Pipe(duplex=True)
                process = context.Process(target=_worker, args=(child, self.checkpoint,
                    self.factory, self.engine_kwargs, worker, self.release_cuda_cache),
                    name=f"sermon-tts-{worker}")
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
                         "replicas": self.replicas, "memAvailableBytes": self._guard(),
                         "parentRssBytes": _rss_bytes(os.getpid()),
                         "releaseCudaCache": self.release_cuda_cache,
                         "cudaAllocConf": os.environ.get("PYTORCH_CUDA_ALLOC_CONF")})
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
            available = self._receive(0)
            idle = sorted(self._ready - self._busy.keys())
            if not idle:
                raise ReplicaPoolError("TTS replica capacity accounting differs")
            worker = idle[0]
            self.connections[worker].send((index, copy.deepcopy(requests), seed))
            self._seen.add(index)
            self._pending[index] = time.monotonic()
            self._busy[worker] = index
            self._event({"kind": "submitted", "timestamp": time.time(),
                         "worker": worker, "index": index, "memAvailableBytes": available})
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

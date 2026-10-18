"""What the durable job store still takes from its host.

``bounded_process`` and ``ExecutionTerminated`` stay in the harness and job liveness in
the checkout until their orchestration batch; the worker the store spawns keeps running
``scripts/sermon_workflow_jobs.py`` (infrastructure design, closure window row).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from .. import ports


@dataclass(frozen=True)
class JobsHost:
    repo_root: Path                                   # workers run with this cwd
    worker_command: Callable[[Path, str, int], list]  # (root, job_id, lock_fd) -> argv of the job worker
    bounded_process: Callable[..., Any]               # sermon_execution_harness.bounded_process
    execution_terminated: Callable[[], type]          # sermon_execution_harness.ExecutionTerminated
    liveness: Callable[[], ModuleType]                # sermon_job_liveness


_current: JobsHost | None = None


def configure(host: JobsHost) -> None:
    global _current
    if not isinstance(host, JobsHost):
        raise TypeError('JobsHost required')
    _current = host


def current() -> JobsHost:
    if _current is None:
        raise ports.Unbound('tongxing_production.orchestration.jobs needs a configured JobsHost')
    return _current

"""The collaborators shared compute receives from its host.

What compute still reaches in the host: the accounting session record, the
resource ledger that stays in orchestration, the artifact root and the job store's
private file primitives (until the closure window W).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import ports


@dataclass(frozen=True)
class ComputeBackend:
    accounting: ports.Accounting               # subprocess_environment locates the outcome receipts
    resources: ports.Resources                 # the unified run's resource ledger (Codex CLI capacity)
    artifact_root: Callable[[], Path]          # default Codex call directories live under it
    job_files: Callable[[], ports.JobFiles]    # the job store's private file primitives, until W


_current: ComputeBackend | None = None


def configure(backend: ComputeBackend) -> None:
    global _current
    if not isinstance(backend, ComputeBackend):
        raise TypeError('ComputeBackend required')
    _current = backend


def current() -> ComputeBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.compute needs a configured ComputeBackend')
    return _current

"""What storage still reaches in the host checkout until the closure window W.

The job store's private file primitives stay in scripts/sermon_workflow_jobs.py, a
waiver closure member that may not change bytes before W (infrastructure design
section 8 item 1): the host lends them through ``ports.JobFiles``.
"""
from __future__ import annotations

from dataclasses import dataclass
from .. import ports


@dataclass(frozen=True)
class StorageBackend:
    job_files: ports.JobFiles


_current: StorageBackend | None = None


def configure(backend: StorageBackend) -> None:
    global _current
    if not isinstance(backend, StorageBackend):
        raise TypeError('StorageBackend required')
    _current = backend


def current() -> StorageBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.storage needs a configured StorageBackend')
    return _current

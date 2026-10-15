"""The collaborators Layer 1 receives from its host."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .. import ports


@dataclass(frozen=True)
class Unmoved:
    """Layer 1 functions whose modules have not moved into the package yet.

    Each entry disappears when its module moves (``sermon_source_budget`` in S3,
    ``sermon_unified_source`` in S4) and its callers import it directly.
    """
    bound_judge_payload: Callable[[dict], dict]
    ordered_bounded_map: Callable[..., list]   # (items, worker, workers)


@dataclass(frozen=True)
class SourceBackend:
    core: ports.Core
    provider: ports.Provider
    code: ports.Code
    mfa: ports.Mfa
    contracts: ports.Contracts
    snapshot: ports.Snapshot
    compute: ports.Compute
    terminology: ports.Terminology
    measure: ports.Measure
    unmoved: Unmoved


_current: SourceBackend | None = None


def configure(backend: SourceBackend) -> None:
    global _current
    if not isinstance(backend, SourceBackend):
        raise TypeError('SourceBackend required')
    _current = backend


def current() -> SourceBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.source needs a configured SourceBackend')
    return _current

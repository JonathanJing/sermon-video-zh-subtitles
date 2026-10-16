"""The collaborators Layer 1 receives from its host."""
from __future__ import annotations

from dataclasses import dataclass

from .. import ports


@dataclass(frozen=True)
class SourceBackend:
    core: ports.Core
    provider: ports.Provider
    code: ports.Code
    mfa: ports.Mfa
    snapshot: ports.Snapshot
    compute: ports.Compute
    resources: ports.Resources
    adjudication: ports.Adjudication
    terminology: ports.Terminology
    measure: ports.Measure
    workspace: ports.Workspace
    accounting: ports.Accounting
    review: ports.Review


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

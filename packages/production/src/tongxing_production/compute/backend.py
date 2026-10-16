"""The collaborators shared compute receives from its host.

Only what compute still reaches in the checkout: the accounting session lives in
observability, which has not moved yet (infrastructure I3).
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import ports


@dataclass(frozen=True)
class ComputeBackend:
    accounting: ports.Accounting               # subprocess_environment locates the outcome receipts


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

"""The collaborators Layer 4 receives from its host."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import ports


@dataclass(frozen=True)
class DeliveryBackend:
    core: ports.Core
    contracts: ports.Contracts
    code: ports.Code
    schemas: ports.Schemas
    workspace: ports.Workspace
    review: ports.Review
    runtime_web: ports.RuntimeWeb
    hosting: ports.Hosting
    waivers: ports.Waivers
    worker_command: Callable[..., list]          # (*arguments) -> [python, scripts/sermon_app_delivery_workflow.py, *arguments]


_current: DeliveryBackend | None = None


def configure(backend: DeliveryBackend) -> None:
    global _current
    if not isinstance(backend, DeliveryBackend):
        raise TypeError('DeliveryBackend required')
    _current = backend


def current() -> DeliveryBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.delivery needs a configured DeliveryBackend')
    return _current

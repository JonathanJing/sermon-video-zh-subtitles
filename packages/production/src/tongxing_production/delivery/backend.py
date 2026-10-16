"""The collaborators Layer 4 receives from its host."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable

from .. import ports


@dataclass(frozen=True)
class Legacy:
    """Host pieces only the legacy v2/v3 adapters (adapters/legacy) use; never four-product delivery."""
    weekly_release: Callable[[], ModuleType]   # experiments/sermon-dubbing-poc/weekly_release: the v1 weekly catalog
    voice_demo: Callable[[], ModuleType]       # scripts.stage_voice_demo_dev: the Dev voice-demo overlay
    firebase_config: Callable[[str], Path]     # firebase/<name>: checked-in Hosting overlay templates


@dataclass(frozen=True)
class DeliveryBackend:
    core: ports.Core
    code: ports.Code
    schemas: ports.Schemas
    workspace: ports.Workspace
    review: ports.Review
    runtime_web: ports.RuntimeWeb
    hosting: ports.Hosting
    waivers: ports.Waivers
    worker_command: Callable[..., list]          # (*arguments) -> [python, scripts/sermon_app_delivery_workflow.py, *arguments]
    legacy: Legacy


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

"""Collaborators the unified orchestration receives from its host.

Orchestration decides what runs next and records it; it does not own the
durable job store, the filesystem helpers, the repository checkout or the
stage implementations. The host (today the ``scripts/sermon_unified`` facade)
builds one ``Backend`` and calls ``configure``; nothing here imports it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

STAGE_NAMES = frozenset({
    'accounting', 'app_delivery', 'audio', 'canonical_binding', 'capabilities',
    'continuation', 'delivery', 'layer2_binding', 'layer2_budget', 'layer2_controller',
    'parallel', 'reviews', 'runtime_identity', 'source', 'study',
})


class BackendUnbound(RuntimeError):
    """Raised when orchestration is used before a host configured it."""


@dataclass(frozen=True)
class Backend:
    # Repository checkout the manifests bind to: ``schemas/`` and closure names
    # are read relative to it. Artifacts default under ``artifact_root``.
    repo_root: Path
    artifact_root: Path
    # Durable job store: ``paths``, ``lock``, ``persist``, ``sync_directory``,
    # ``peek_job``, ``start_job`` and the ``ACTIVE`` status set.
    jobs: Any
    safe_path: Callable[[Path], Path]
    atomic_json: Callable[[Path, Any], None]
    utc_now: Callable[[], str]
    # Repository-wide execution closure: every module a run must bind.
    required_modules: Callable[[], list[str]]
    # argv that runs the detached owner pump for ``(state_root, run_key)``.
    worker_command: Callable[[Path, str], list[str]]
    # Wake an external scheduler for ``(state_root, run_key, plan_hash)``;
    # must swallow its own failures, stored evidence stays authoritative.
    temporal_wake: Callable[[Path, str, str], None]
    # Lazy stage lookup by logical name (see ``STAGE_NAMES``).
    stage: Callable[[str], ModuleType]
    # The run's accounting session (``ports.Accounting``): owner dispatch joins the
    # v4 provider/job ledger through ``profile_session``, ``profile_context`` and
    # ``stage_outcome``.
    accounting: Any


_current: Backend | None = None


def configure(backend: Backend) -> None:
    global _current
    if not isinstance(backend, Backend):
        raise TypeError('Backend required')
    _current = backend


def current() -> Backend:
    if _current is None:
        raise BackendUnbound('tongxing_production.orchestration.unified needs a configured Backend')
    return _current


def stage(name: str) -> ModuleType:
    if name not in STAGE_NAMES:
        raise KeyError(f'unknown stage module: {name}')
    return current().stage(name)

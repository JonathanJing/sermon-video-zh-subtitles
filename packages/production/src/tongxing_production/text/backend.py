"""The collaborators Layer 2 receives from its host."""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable

from .. import ports


@dataclass(frozen=True)
class Unmoved:
    """Cross-layer modules Layer 2 still reaches through its host.

    Each accessor returns the host's module at call time; it disappears when
    that module moves into the package and its callers import it directly.
    """
    durable_jobs: Callable[[], ModuleType]       # canonical_durable_jobs: identity, pipeline, project, reopen
    package_inspection: Callable[[], ModuleType]  # inspect_canonical_packages
    pipeline_definition: Callable[[], ModuleType]  # canonical_pipeline_definition: LOCALES, _sha
    liveness: Callable[[], ModuleType]           # sermon_job_liveness
    review_budget: Callable[[], ModuleType]      # sermon_review_budget (review/)
    speech_handoff: Callable[[], ModuleType]     # audio.speech_job (Layer 3 hand-off checks); text never imports audio
    orchestration_contracts: Callable[[], ModuleType]  # the unified run's contracts
    review_contracts: Callable[[], ModuleType]   # sermon_review_contracts: strict JSON, validators, size limits
    accounting_module: Callable[[], ModuleType]  # sermon_accounting, for callers reading beyond the Accounting port
    api_concurrency_module: Callable[[], ModuleType]   # layer2_api_concurrency (compute/)
    source_meaning_module: Callable[[], ModuleType]    # source_meaning_machine_adjudication (review/)
    load_meaning_notes: Callable[..., Any]       # (path, *, source, anchor, ...) source-meaning notes (review/)
    repair_instruction: Callable[..., str]       # (notes, source_unit_ids)
    record_cache_observation: Callable[..., Any]  # (role, saved, output, *, mode, origin=None)


@dataclass(frozen=True)
class TextBackend:
    core: ports.Core
    provider: ports.Provider
    code: ports.Code
    contracts: ports.Contracts
    snapshot: ports.Snapshot
    compute: ports.Compute
    resources: ports.Resources
    terminology: ports.Terminology
    measure: ports.Measure
    accounting: ports.Accounting
    workspace: ports.Workspace
    plugins: ports.Plugins
    transports: ports.Transports
    schemas: ports.Schemas
    diagnostic: ports.Diagnostic
    worker_command: Callable[..., list]          # (*arguments) -> [python, scripts/canonical_layer2_controller.py, *arguments]
    unmoved: Unmoved


_current: TextBackend | None = None


def configure(backend: TextBackend) -> None:
    global _current
    if not isinstance(backend, TextBackend):
        raise TypeError('TextBackend required')
    _current = backend


def current() -> TextBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.text needs a configured TextBackend')
    return _current

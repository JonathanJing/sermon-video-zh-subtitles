"""The collaborators shared compute receives from its host.

What compute still reaches in the host: the accounting session record, the
resource ledger that stays in orchestration, the artifact root and the job store's
private file primitives (until the closure window W).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable

from .. import ports


@dataclass(frozen=True)
class Unmoved:
    """Host modules the audio QC transport reaches until review R3 and L3 A3 move them."""
    waiver: Callable[[], ModuleType]                # machine_quality_waiver
    audio_qc: Callable[[], ModuleType]              # target_audio_auto_qc
    budget_authorization: Callable[[], ModuleType]  # machine_qc_budget_authorization
    screener: Callable[[], ModuleType]              # screen_target_language_audio_units
    predicted_schedule: Callable[[], ModuleType]    # target_audio_predicted_schedule
    formal_renderer: Callable[[], ModuleType]       # render_formal_target_language_speech
    voice_demos: Callable[[], ModuleType]           # render_multilingual_voice_demos
    jobs: Callable[[], ModuleType]                  # sermon_workflow_jobs


@dataclass(frozen=True)
class ComputeBackend:
    accounting: ports.Accounting               # subprocess_environment locates the outcome receipts
    resources: ports.Resources                 # the unified run's resource ledger (Codex CLI capacity)
    artifact_root: Callable[[], Path]          # default Codex call directories live under it
    job_files: Callable[[], ports.JobFiles]    # the job store's private file primitives, until W
    checkout_root: Callable[[], Path]          # the audio QC transport hash (T) reads files relative to it
    unmoved: Unmoved


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

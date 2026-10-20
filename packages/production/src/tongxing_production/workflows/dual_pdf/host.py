"""What the dual_pdf entries still reach in the host checkout.

The workflows build no layer backend (workflows design section 3 item 5); dual_pdf
needs the Cloud and observability helpers under ``backend/`` and a few ``scripts/``
modules that have no batch yet, so the host binds this one temporary record. Drop a
field when its module moves into the package.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable

from ... import ports


@dataclass(frozen=True)
class Unmoved:
    live_source_monitor: Callable[[], ModuleType]
    youtube_data_api: Callable[[], ModuleType]
    series_terminology: Callable[[], ModuleType]
    export_saturday_live_context: Callable[[], ModuleType]
    reading_edition: Callable[[], ModuleType]       # build_sermon_reading_edition_with_openai
    sentence_shadow: Callable[[], ModuleType]       # prepare_sentence_interpretation_shadow
    supervisor: Callable[[], ModuleType]            # sermon_production_supervisor
    supervisor_agent: Callable[[], ModuleType]      # run_sermon_production_supervisor_agent
    accounting: Callable[[], ModuleType]            # sermon_accounting, the module codex-local hands on
    dubbing_producer_hook: Callable[[], tuple]      # experiments/sermon-dubbing-poc bridge: (start, CandidateNotReady)
    upcoming_sunday: Callable[..., Any]             # backend.config.upcoming_sunday


@dataclass(frozen=True)
class DualPdfHost:
    cloud: ports.Cloud
    observability: ports.Observability
    unmoved: Unmoved
    leases: ports.Leases | None = None   # the production supervisor's stage leases (backend/leases.py)


_current: DualPdfHost | None = None


def configure(host: DualPdfHost) -> None:
    global _current
    if not isinstance(host, DualPdfHost):
        raise TypeError('DualPdfHost required')
    _current = host


def current() -> DualPdfHost:
    if _current is None:
        raise ports.Unbound('tongxing_production.workflows.dual_pdf needs a configured DualPdfHost')
    return _current


class HostModule:
    """A host module looked up at every use; attribute patches land on the host module."""

    def __init__(self, get):
        object.__setattr__(self, '_get', get)

    def __getattr__(self, name):
        return getattr(self._get(), name)

    def __setattr__(self, name, value):
        setattr(self._get(), name, value)

    def __delattr__(self, name):
        delattr(self._get(), name)

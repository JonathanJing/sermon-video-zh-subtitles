"""Host adapters for Tracker's not-yet-moved read-only report producers.

The projection package never imports the host. The old CLI facades configure
these ports; the host resolves the legacy report modules only when used.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Callable

from ... import ports


@dataclass(frozen=True)
class TrackerProjectionBackend:
    timeline: Callable[[], ModuleType]
    run_progress: Callable[[], ModuleType]
    weekly_report: Callable[[], ModuleType]


_current: TrackerProjectionBackend | None = None


def configure(backend: TrackerProjectionBackend) -> None:
    global _current
    if not isinstance(backend, TrackerProjectionBackend):
        raise TypeError("TrackerProjectionBackend required")
    _current = backend


def current() -> TrackerProjectionBackend:
    if _current is None:
        raise ports.Unbound("Tracker projections need a configured host backend")
    return _current


class _ModulePort:
    """Forward legacy module attributes at call time, including test patches."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, name: str):
        return getattr(getattr(current(), self._name)(), name)


timeline = _ModulePort("timeline")
run_progress = _ModulePort("run_progress")
weekly_report = _ModulePort("weekly_report")

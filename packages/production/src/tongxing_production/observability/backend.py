"""What observability still takes from its host.

Code identity keys, error locations and the git status of a run are relative to the
checkout the host binds, never to this package's own location (infrastructure design
section 4.4). ``load_producer_imports`` loads the modules the moved producers used to
import at their own load time, so the loaded-code identity matches the pre-move one.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import ports


@dataclass(frozen=True)
class ObservabilityBackend:
    checkout_root: Path
    load_producer_imports: Callable[[], None]


_current: ObservabilityBackend | None = None


def configure(backend: ObservabilityBackend) -> None:
    global _current
    if not isinstance(backend, ObservabilityBackend):
        raise TypeError('ObservabilityBackend required')
    _current = backend


def current() -> ObservabilityBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.observability needs a configured ObservabilityBackend')
    return _current


def checkout_root() -> Path:
    return current().checkout_root

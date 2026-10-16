"""The collaborators Layer 3 receives from its host."""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Callable

from .. import ports


@dataclass(frozen=True)
class Unmoved:
    """Cross-layer modules Layer 3 still reaches through its host.

    Each accessor returns the host's module at call time; it disappears when
    that module moves into the package and its callers import it directly.
    """
    local_model_observation: Callable[[], ModuleType]   # sermon_local_model_observation: SCHEMA, safe_observation, record


@dataclass(frozen=True)
class AudioBackend:
    core: ports.Core
    code: ports.Code
    compute: ports.Compute
    measure: ports.Measure
    accounting: ports.Accounting
    schemas: ports.Schemas
    diagnostic: ports.Diagnostic
    review: ports.Review
    waivers: ports.Waivers
    machine_qc: ports.MachineQc
    spoken_rules: ports.SpokenRules
    tts_runtime: ports.TtsRuntime
    dev_profile: ports.DevProfile
    unmoved: Unmoved


_current: AudioBackend | None = None


def configure(backend: AudioBackend) -> None:
    global _current
    if not isinstance(backend, AudioBackend):
        raise TypeError('AudioBackend required')
    _current = backend


def current() -> AudioBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.audio needs a configured AudioBackend')
    return _current

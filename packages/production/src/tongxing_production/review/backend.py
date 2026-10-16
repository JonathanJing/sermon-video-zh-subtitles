"""The collaborators cross-layer machine review receives from its host."""
from __future__ import annotations

from dataclasses import dataclass

from .. import ports


@dataclass(frozen=True)
class ReviewBackend:
    core: ports.Core                           # repo_root in place of a module-derived ROOT; jobs private names
    code: ports.Code                           # implementation_path for named closures; module_sha256 for self-hashes
    contracts: ports.Contracts                 # removed once review imports tongxing_production.contracts
    snapshot: ports.Snapshot
    schemas: ports.Schemas
    provider: ports.Provider                   # route, transcription_request, transcription_limits
    compute: ports.Compute                     # exclusive Spark session admission
    plugins: ports.Plugins                     # language_review_plugins.auto_qc_text_common
    transports: ports.Transports               # audio_qc
    audio: ports.AudioRules
    text: ports.TextRules
    source: ports.SourceEvidence
    gates: ports.StageGates
    scripture: ports.Scripture
    qc_runtime: ports.QcRuntime
    waivers: ports.Waivers                     # machine audio waiver rules the audio screening gate accepts


_current: ReviewBackend | None = None


def configure(backend: ReviewBackend) -> None:
    global _current
    if not isinstance(backend, ReviewBackend):
        raise TypeError('ReviewBackend required')
    _current = backend


def current() -> ReviewBackend:
    if _current is None:
        raise ports.Unbound('tongxing_production.review needs a configured ReviewBackend')
    return _current

"""Primitive collaborators a host injects into the production layers.

A layer backend (``orchestration.unified.backend.Backend``,
``source.backend.SourceBackend``) is composed from these records. The package
never imports a host; it reads the configured backend at call time. Every
callable keeps the signature of the implementation it stands in for, so a
host can bind it with a late-binding wrapper and tests that patch the host's
implementation still intercept the call.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


class Unbound(RuntimeError):
    """Raised when a layer is used before its host configured a backend."""


class AdjudicationRejected(ValueError):
    """A source-meaning adjudication receipt is not bound to its package and media."""


@dataclass(frozen=True)
class Core:
    """Checkout roots, the durable job store and the filesystem/clock helpers."""
    repo_root: Path
    artifact_root: Path
    jobs: Any                                  # digest, paths, lock, persist, sync_directory, peek_job, start_job, ACTIVE
    safe_path: Callable[..., Path]
    atomic_json: Callable[[Path, Any], None]
    utc_now: Callable[[], str]


@dataclass(frozen=True)
class Provider:
    """Model-provider transport as the L1 producers use it today."""
    chat_json: Callable[..., dict]             # (api_key, payload, retries=1, *, session_verifier=None)
    request_json: Callable[..., dict]          # (req, retries=3, *, response_observer=None, request_executor=None)
    reject_secret_override: Callable[[Any], None]
    bounded_legacy_chat_payload: Callable[[dict], dict]
    legacy_text_cache_contract: Callable[[], Any]
    legacy_text_execution_identity: Callable[..., Any]   # (api_key, payload, *, caller=None)
    access_secret: Callable[[str], str]        # named Secret Manager credential for an explicit CLI flag
    http_execute: Callable[..., dict]          # (req, timeout_seconds, *, deadline=None): at most one request
    transcription_request: Callable[[bytes, str], Any]   # (wav_bytes, expected_audio_sha256)
    outcomes: Any                              # request_identity, execution_binding, assert_replay_admitted, recover, before_dispatch


@dataclass(frozen=True)
class Compute:
    """Spark-session admission for model calls."""
    session_bound_caller: type                 # bound directly: producers construct it and test isinstance
    require_session: Callable[..., Any]        # (*, verifier=None): the exclusive Spark session is held


@dataclass(frozen=True)
class Resources:
    """The unified run's shared resource ledger (online API, Spark) as a reservation interface."""
    validate_policy: Callable[[Any], Any]
    identity: Callable[[Any], Any]
    reserve: Callable[..., bool]               # (policy, *, operation_id, owner, resource, units=1)
    release: Callable[..., Any]                # (policy, *, operation_id, owner)


@dataclass(frozen=True)
class Adjudication:
    """Cross-layer machine review of source meaning; Layer 1 only validates its receipts."""
    validate_receipt: Callable[..., None]      # (receipt, *, source, anchor, media_sha256, receipt_directory)
                                               # raises AdjudicationRejected


@dataclass(frozen=True)
class Terminology:
    """The shared series terminology table as frozen policy input."""
    context: Callable[[], dict]


@dataclass(frozen=True)
class Measure:
    """Producer timing in the progress ledger; it never gates review or release."""
    producer_step: Callable[..., Any]          # (ledger_path, step_id, *, locale=None) -> context manager


@dataclass(frozen=True)
class Code:
    """Code identity the producers record, without locating files themselves."""
    code_identity: Callable[[], str]
    module_sha256: Callable[[ModuleType], str]
    module_path: Callable[[ModuleType], Path]


@dataclass(frozen=True)
class Mfa:
    """Local MFA configuration derived from parsed CLI arguments."""
    options: Callable[[Any], dict]


@dataclass(frozen=True)
class Contracts:
    """Receipt contract helpers: fixed error codes, canonical and byte hashes."""
    error: type                                # the ContractError class callers catch
    require: Callable[[Any, str], None]
    bytes_sha256: Callable[[bytes], str]
    canonical_sha256: Callable[[Any], str]


@dataclass(frozen=True)
class Snapshot:
    """Stable read of one caller-selected regular file with its exact bytes."""
    read_snapshot: Callable[[Path], tuple]     # (value, raw_bytes)

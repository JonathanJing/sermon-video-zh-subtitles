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

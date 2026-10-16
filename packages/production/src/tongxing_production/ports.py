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
class Route:
    """The configured OpenAI project route; never a credential value."""
    selected: Callable[[], Any]
    safe: Callable[[Any], Any]
    project_headers: Callable[[str], dict]     # (api_key)


@dataclass(frozen=True)
class Provider:
    """Model-provider transport as the producers use it today."""
    chat_json: Callable[..., dict]             # (api_key, payload, retries=1, *, session_verifier=None)
    request_json: Callable[..., dict]          # (req, retries=3, *, response_observer=None, request_executor=None)
    reject_secret_override: Callable[[Any], None]
    bounded_legacy_chat_payload: Callable[[dict], dict]
    legacy_text_cache_contract: Callable[[], Any]
    legacy_text_execution_identity: Callable[..., Any]   # (api_key, payload, *, caller=None)
    access_secret: Callable[[str], str]        # named Secret Manager credential for an explicit CLI flag
    http_execute: Callable[..., dict]          # (req, timeout_seconds, *, deadline=None): at most one request
    transcription_request: Callable[[bytes, str], Any]   # (wav_bytes, expected_audio_sha256)
    outcomes: Any                              # request_identity, execution_binding, assert_replay_admitted, recover, before_dispatch, receipt_root
    request_metadata: Callable[[Any], dict]    # accounting settings recorded on a request
    route: Route


@dataclass(frozen=True)
class Compute:
    """Spark-session admission for model calls."""
    session_bound_caller: type                 # bound directly: producers construct it and test isinstance
    require_session: Callable[..., Any]        # (*, verifier=None): the exclusive Spark session is held
    load_profile: Callable[[Any], dict]        # (path): production concurrency profile
    validate_profile: Callable[[Any], dict]
    admit: Callable[..., Any]                  # (payload, request_limits, *, surface='canonical_api'): strict budget admission
    reject_cli_transport: Callable[[Any], None]   # (caller): CLI transports are not budget-admitted
    request_slot: Callable[[Any], Any]         # (job_root) -> context manager: host-wide L2 API request slot
    max_in_flight_api_calls: int
    max_group_workers_per_locale: int


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
class Workspace:
    """Exclusive lock on a producer's work directory."""
    work_lock: Callable[[Path], Any]           # (work) -> context manager


@dataclass(frozen=True)
class Accounting:
    """The run's accounting session around a producer."""
    session: Callable[..., Any]                # (directory, workflow, metadata=None, *, evidence_directory=None) -> context manager
    stage: Callable[..., Any]                  # (name, *, cache_hit=False, billing='local', ...) -> context manager
    record_workload: Callable[[str, dict], Any]
    record_log: Callable[..., Any]             # (code, *, level='INFO', fields=None, exception=None)
    bounded_dependencies: Callable[..., Any]   # (name, dependencies, *, work_unit_id)
    finalize: Callable[[Any, Any], Any]        # (action, original_error)


@dataclass(frozen=True)
class Review:
    """Operator review receipts a stage checks before it runs; review/ owns them."""
    validate_window: Callable[..., Any]        # (manifest, bindings=None, base='.')
    validate_review: Callable[..., Any]        # (kind, receipt_path, *, inputs, expected_source=None, expected_locale=None)
    audio_screening: Callable[..., Any]        # (audio, receipt, screening): Layer 3 audio screening review gate


@dataclass(frozen=True)
class Terminology:
    """The shared series terminology table as frozen policy input."""
    context: Callable[[], dict]
    table_path: Callable[[], Path]             # docs/series-terminology.zh.md, hashed into frozen policies
    parse_table: Callable[[str], Any]


@dataclass(frozen=True)
class Measure:
    """Producer timing in the progress ledger; it never gates review or release."""
    producer_step: Callable[..., Any]          # (ledger_path, step_id, *, locale=None) -> context manager
    producer_substage: Callable[..., Any]      # (name, *, billing='api') -> context manager


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


@dataclass(frozen=True)
class Plugins:
    """Policy-pinned language review plugins, executed and hashed as files where they are."""
    root: Callable[[], Path]
    implementation_file: Callable[[str], Path]   # a non-plugin file a plugin's hash includes, by name
    module: Callable[[str], Any]               # import a plugin or plugin dependency by its dotted name under scripts/


@dataclass(frozen=True)
class Transports:
    """Layer 2 model transports, owned by compute/. Each hashes its own file as adapterSha256."""
    caller: Callable[..., Any]                 # (backend, **options): 'openai-api' | 'codex-cli' | 'claude-cli'
    claude_chat_envelope: Callable[[Any, str], dict]   # (response, model)
    validate_codex_test_configuration: Callable[[Any], Any]


@dataclass(frozen=True)
class Schemas:
    """Checked-in JSON schemas and the Layer 2/3 hand-off schema check."""
    path: Callable[[str], Path]                # schemas/<name>
    validate: Callable[[Any, str, str], None]  # (value, filename, label)
    source_package_schema: Callable[[], str]   # the English Source Package schema the hand-off accepts


@dataclass(frozen=True)
class Diagnostic:
    """Diagnostic-run context checks shared by Layer 1, Layer 2 and plugins."""
    validate_source: Callable[..., Any]        # (source, anchor, context)
    validate_context: Callable[[Any], Any]
    require_policy_ready: Callable[..., Any]   # (identity, context=None)


@dataclass(frozen=True)
class RuntimeWeb:
    """The reader shell a release publishes; delivery scans its files at call time."""
    root: Callable[[], Path]                   # <checkout>/apps/listening-web


@dataclass(frozen=True)
class Hosting:
    """Hosting defaults a publication uses; lease, attempt and reconciliation rules stay in delivery."""
    authorized_request: Callable[[], Callable[..., Any]]   # () -> request(method, url, *, data=None, headers=None, timeout=60)
    public_reader: Callable[..., tuple]        # (url, *, timeout=120) -> (status, body)
    run: Callable[..., Any]                    # subprocess.run for the hosting CLI
    lease: Callable[..., Any]                  # (request, bucket, site) -> remote publication lease


@dataclass(frozen=True)
class Waivers:
    """Machine-quality waivers a release discloses; review/ owns their rules."""
    is_text_waiver: Callable[[dict], bool]
    validate_text_waiver: Callable[..., Any]   # (receipt, *, candidate, source_sha=None, ...)
    disclosure: Callable[[str], dict]          # (locale)
    is_audio_waiver: Callable[[dict], bool]
    validate_audio_waiver: Callable[..., None]   # (package, receipt, screening)
    audio_waiver_schema: str
    condensation_binding_schema: str

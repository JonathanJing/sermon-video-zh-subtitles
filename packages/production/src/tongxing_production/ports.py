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
    sync_directory_ancestry: Callable[[Path], None]   # persist every containing entry before side effects
    read_json: Callable[[Path], Any]           # a regular JSON evidence file, never through a symlink


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
    transcription_limits: Callable[[], Any]    # MAX_RESPONSE_BYTES, WALL_TIME_MS, MICROUSD_PER_MINUTE of one transcription request


@dataclass(frozen=True)
class Compute:
    """Spark-session admission for model calls."""
    session_bound_caller: type                 # bound directly: producers construct it and test isinstance
    session_error: Callable[[], type]          # the exclusive-session error a model call converts into its own failure
    require_session: Callable[..., Any]        # (*, verifier=None): the exclusive Spark session is held
    load_profile: Callable[[Any], dict]        # (path): production concurrency profile
    validate_profile: Callable[[Any], dict]
    admit: Callable[..., Any]                  # (payload, request_limits, *, surface='canonical_api'): strict budget admission
    reject_cli_transport: Callable[[Any], None]   # (caller): CLI transports are not budget-admitted
    request_slot: Callable[[Any], Any]         # (job_root) -> context manager: host-wide L2 API request slot
    max_in_flight_api_calls: int
    max_group_workers_per_locale: int
    require_bound_model_session: Callable[..., Any]   # (*, verifier=None): a local model call holds the bound Spark session


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
    orchestration: Callable[..., Any]          # (name, *, depends_on=None, work_unit_id=None) -> context manager


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
    record_substage_metrics: Callable[[dict], None]


@dataclass(frozen=True)
class Code:
    """Code identity the producers record, without locating files themselves."""
    code_identity: Callable[[], str]
    module_sha256: Callable[[ModuleType], str]
    module_path: Callable[[ModuleType], Path]
    implementation_path: Callable[[str], Path]   # (legacy identity key) -> the file it names today, via path_aliases


@dataclass(frozen=True)
class Mfa:
    """Local MFA configuration derived from parsed CLI arguments."""
    options: Callable[[Any], dict]


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
    audio_qc: Callable[[], ModuleType]         # machine_qc_audio_transports (compute/): primary/secondary ASR, TTS, fakes,
                                               # CallCache, asr_router, render_identity, implementation_sha256, qwen_inference_identity


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
    review_kind: str                           # the review kind a machine-waived hand-off records


@dataclass(frozen=True)
class MachineQc:
    """Audio machine-QC settings a Layer 3 package records; review/ owns target_audio_auto_qc."""
    screening_asr_settings: Callable[[dict], dict]   # (screening)


@dataclass(frozen=True)
class SpokenRules:
    """Spoken-number and citation rules Layer 3 scores and renders with.

    They stay in scripts/ (L3 decision 3): ``auto_qc_text_common`` and
    ``ko_spoken_numerals`` are pinned by the waiver, scoring and rate closures,
    so they are neither copied nor imported when the host loads. Each function
    is a late-binding wrapper; each constant is an accessor that returns the
    rule module's own object at call time.
    """
    # language_review_plugins.auto_qc_text_common
    fold: Callable[[str], str]                 # _fold
    ko_pattern: Callable[..., str]             # _ko_pattern(form, *, sino=False)
    book_citations: Callable[[str, str], list]   # (text, locale)
    english_numbers: Callable[[str], list]
    korean_sino: Callable[[int], str]
    korean_native: Callable[[int], tuple]
    en_book_codes: Callable[[], Any]           # _EN_BOOK_CODES
    es_book_codes: Callable[[], Any]           # _ES_BOOK_CODES
    ko_book_codes: Callable[[], Any]           # _KO_BOOK_CODES
    zh_book_codes: Callable[[], Any]           # _ZH_BOOK_CODES
    ko_citation: Callable[[], Any]             # _KO_CITATION
    ko_counters: Callable[[], Any]             # _KO_COUNTERS
    zh_measure_words: Callable[[], Any]        # _ZH_MEASURE_WORDS
    # ko_spoken_numerals
    ko_rule: Callable[[], str]                 # RULE
    ko_rule_v2: Callable[[], str]              # RULE_V2
    ko_rule_v3: Callable[[], str]              # RULE_V3
    spoken_form: Callable[[str], str]
    spoken_form_v2: Callable[[str], str]
    spoken_form_v3: Callable[[str], str]
    equivalent: Callable[..., bool]            # (approved, spoken, *, rule=RULE)
    bare_context_allowed: Callable[..., bool]  # (text, start, end, *, rule=RULE)
    bare_citation_matches: Callable[..., Any]  # (text, *, rule=RULE)
    ko_particles: Callable[[], Any]            # _PARTICLES
    ko_connector: Callable[[], Any]            # _CONNECTOR
    ko_range_particle: Callable[[], Any]       # _RANGE_PARTICLE
    ko_delimiters: Callable[[], Any]           # _DELIMITERS
    ko_numeric_token: Callable[[], Any]        # _NUMERIC_TOKEN
    ko_citations: Callable[[], Any]            # _CITATIONS


@dataclass(frozen=True)
class TtsRuntime:
    """Spark TTS worker adapters (compute/) and the voice checkpoint reader the formal renderer uses."""
    replica_pool: Callable[[], ModuleType]     # spark_tts_replica_pool: ReplicaPool; its file is hashed into replica identity
    window_scheduler: Callable[[], ModuleType]   # spark_tts_window_scheduler: ParallelBatchEngine; hashed with the pool
    bounded_cpu: Callable[[], ModuleType]      # bounded_audio_cpu: BoundedAudioCPU
    read_checkpoint_map: Callable[[Path, str], dict]   # (path, label)
    validate_checkpoint: Callable[[dict], Path]  # (task)


@dataclass(frozen=True)
class DevProfile:
    """Explicit Dev audio test settings; they never change production defaults."""
    default_profile_path: Callable[[], Path]   # data/benchmarks/.../next-dev-test-profile.json


# The records below are what cross-layer machine review (tongxing_production.review)
# takes from the stages. Review sits below the stages and never imports them; each
# function is a late-binding wrapper and each constant or class an accessor that
# returns the implementation's own object at call time, so binding them imports no
# waiver-closure file when the host loads.

@dataclass(frozen=True)
class AudioRules:
    """Layer 3 rate, predicted-schedule, scoring and normalization rules review/ checks against."""
    # target_audio_predicted_schedule
    predicted_schema: Callable[[], str]        # SCHEMA
    synthesis_identity_fields: Callable[[], tuple]   # SYNTHESIS_IDENTITY_FIELDS
    synthesis_identity: Callable[[dict], dict]   # (job)
    check_identity: Callable[[dict, str], None]  # _check_identity(identity, locale)
    policy_texts: Callable[..., list]          # (texts, locale, normalization_policy_sha256)
    speech_units: Callable[[str, str], float]  # (text, locale)
    budget: Callable[..., dict]                # (source_seconds, groups, rate, policy=None, *, synthesis_identity, ...)
    # screen_target_language_audio_units
    score: Callable[..., tuple]                # (expected, recognized, locale, min_similarity, scoring=None)
    scoring: Callable[[], str]                 # SCORING, the current scoring identity
    scoring_v3: Callable[[], str]              # SCORING_V3
    known_scorings: Callable[[], tuple]        # KNOWN_SCORINGS
    current_scoring_identity_problems: Callable[[dict], list]   # (settings)
    negations: Callable[[], dict]              # NEGATIONS
    zh_numerals: Callable[[], str]             # ZH_NUMERALS
    es_numbers: Callable[[], frozenset]        # ES_NUMBERS
    korean_number_spans: Callable[[str], list]   # (text)
    # render_formal_target_language_speech
    registered_normalization_policy: Callable[[dict], Any]   # (job)


@dataclass(frozen=True)
class TextRules:
    """Layer 2 policy and source checks review/ applies; the canonical hash its receipts record."""
    canonical_sha256: Callable[[Any], str]     # target_language_policy.canonical_sha256
    validate_policy: Callable[..., dict]       # (policy, *, series_table=None)
    validate_source_scope: Callable[..., None]   # (policy, source, anchor)
    validate_source_for_translation: Callable[[dict, dict], str]   # (source, anchor)
    human_ruling_schema: Callable[[], str]     # layer2_human_ruling.SCHEMA
    load_human_ruling: Callable[..., dict]     # (path, *, source, anchor)


@dataclass(frozen=True)
class SourceEvidence:
    """Layer 1 evidence and the source budget review/ reads and binds to."""
    text_review: Callable[[], ModuleType]      # source text review: MACHINE_AUTHORITY, MACHINE_RECEIPT_SCHEMA(_V1),
                                               # MACHINE_ROLE, SCHEMA_V2, STATUS, SUPPORTED_MODELS, UNIT_TIME_TOLERANCE
    text_sha256: Callable[[str], str]
    judge_cached_call: Callable[..., tuple]    # (*, out, stage, payload, api_key, requested_model, caller)
    reconcile_returned_response: Callable[..., Path]   # (*, marker_path, response, expected_request_sha256, requested_model)
    judge_run_schema: Callable[[], str]        # the judge cache's request schema (RUN_SCHEMA)
    atomic_json: Callable[[Path, Any], None]   # the judge cache's _atomic(path, value)
    model_result: Callable[[dict, str], dict]  # _model_result(response, requested_model) of the anchor model runner
    source_budget: Callable[[], type]          # SourceBudget
    budget_metrics: Callable[[], tuple]        # METRICS
    sha256: Callable[[Path], str]              # sentence interpretation file hash
    json_sha256: Callable[[Any], str]


@dataclass(frozen=True)
class StageGates:
    """The stage checks unified review ingestion runs for each review kind."""
    window_approval: Callable[..., tuple]      # supervisor validate_window_approval(approval, *, sunday, live_url, timeline_report=None)
    parse_timecode: Callable[[str], float]
    stable_hash: Callable[[str], str]
    english_review: Callable[..., tuple]       # English source package _review_payload(review_path, *, aligned_sha256,
                                               # anchor_json_sha256, source_unit_ids)
    text_release_basis: Callable[..., str]     # (source_package, anchor, candidate, receipt)
    study_ingest: Callable[[Any, Any], Any]    # study_artifacts.ingest_review(artifact, review)


@dataclass(frozen=True)
class Scripture:
    """The scripture library review/ adjudicates against; its files stay where plugins hash them."""
    cuv: Callable[[], ModuleType]              # cuv_scripture: CuvError, CuvLibrary, Reference, parse_reference, normalize_book, ...
    editions: Callable[[], ModuleType]         # scripture_editions: EditionError, LazyEdition, VERIFIED
    coverage: Callable[[], ModuleType]         # english_scripture_coverage: CoverageEdition, CoverageError, coverage, ...
    candidate_queue: Callable[[], ModuleType]  # scripture_candidate_queue: BOOKS, SIGNALS
    library_path: Callable[[], Path]           # cuv_scripture.DEFAULT_LIBRARY_PATH
    coverage_data_path: Callable[[], Path]     # english_scripture_coverage.DATA_PATH


@dataclass(frozen=True)
class QcRuntime:
    """What the two QC drivers use outside review: run reports, the Codex text transport, candidate checks."""
    write_report: Callable[..., Any]           # export_run_digest.write_report(run_dirs, label)
    codex_text_transport: Callable[[], ModuleType]   # sermon_codex_transport: TEXT_MODEL; its file hash is adapter identity
    validate_target_candidate: Callable[..., dict]   # (source_package, anchor, candidate, *, require_human_approval=True, ...)

"""Bind the production package's layer backends to this checkout.

Importing this module configures ``tongxing_production.source``. Every port is
a late-binding wrapper around the ``scripts/`` implementation it stands in
for: the implementation is imported inside the wrapper, so a test that patches
``scripts.sermon_pipeline.chat_json`` (or any other target) still intercepts
calls made through the port, and no import cycle forms with the producers that
import this module at load time.

``scripts/sermon_unified/__init__.py`` binds ``tongxing_production.orchestration``
the same way; the two hosts will share ``core()`` once that facade is revisited.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tongxing_production import ports  # noqa: E402
from tongxing_production.source import backend as source_backend  # noqa: E402
from tongxing_production.text import backend as text_backend  # noqa: E402


def core() -> ports.Core:
    from scripts import sermon_workflow_jobs as jobs
    from scripts.sermon_execution_harness import atomic_json, utc_now
    from scripts.sermon_release_workflow import safe_path
    return ports.Core(repo_root=ROOT, artifact_root=ROOT / 'artifacts', jobs=jobs,
                      safe_path=safe_path, atomic_json=atomic_json, utc_now=utc_now)


def _chat_json(api_key, payload, retries=1, *, session_verifier=None):
    from scripts import sermon_pipeline
    return sermon_pipeline.chat_json(api_key, payload, retries, session_verifier=session_verifier)


def _request_json(req, retries=3, *, response_observer=None, request_executor=None):
    from scripts import sermon_pipeline
    return sermon_pipeline.request_json(req, retries, response_observer=response_observer,
                                        request_executor=request_executor)


def _reject_secret_override(value):
    from scripts import sermon_openai_runtime
    return sermon_openai_runtime.reject_secret_override(value)


def _bounded_legacy_chat_payload(payload):
    from scripts import sermon_pipeline
    return sermon_pipeline.bounded_legacy_chat_payload(payload)


def _legacy_text_cache_contract():
    from scripts import sermon_pipeline
    return sermon_pipeline.legacy_text_cache_contract()


def _legacy_text_execution_identity(api_key, payload, *, caller=None):
    from scripts import sermon_pipeline
    return sermon_pipeline.legacy_text_execution_identity(api_key, payload, caller=caller)


def _access_secret(name):
    from backend.cloud import access_secret
    return access_secret(name)


def _http_execute(req, timeout_seconds, *, deadline=None):
    from scripts import sermon_provider_http
    return sermon_provider_http.execute(req, timeout_seconds, deadline=deadline)


def _transcription_request(wav_bytes, expected_audio_sha256):
    from scripts import sermon_transcription_request
    return sermon_transcription_request.build_request(wav_bytes, expected_audio_sha256)


def _request_metadata(payload):
    from scripts import sermon_accounting
    return sermon_accounting.request_metadata(payload)


def _selected_route():
    from scripts import sermon_openai_runtime
    return sermon_openai_runtime.selected_route()


def _safe_route(value):
    from scripts import sermon_openai_runtime
    return sermon_openai_runtime.safe_route(value)


def _project_headers(api_key):
    from scripts import sermon_openai_runtime
    return sermon_openai_runtime.project_headers(api_key)


def provider() -> ports.Provider:
    # api_cli_outcomes imports only the standard library at load; its functions
    # are looked up on the module at call time, so patches still intercept.
    from scripts import api_cli_outcomes
    return ports.Provider(chat_json=_chat_json, request_json=_request_json,
                          reject_secret_override=_reject_secret_override,
                          bounded_legacy_chat_payload=_bounded_legacy_chat_payload,
                          legacy_text_cache_contract=_legacy_text_cache_contract,
                          legacy_text_execution_identity=_legacy_text_execution_identity,
                          access_secret=_access_secret, outcomes=api_cli_outcomes,
                          http_execute=_http_execute, transcription_request=_transcription_request,
                          request_metadata=_request_metadata,
                          route=ports.Route(selected=_selected_route, safe=_safe_route,
                                            project_headers=_project_headers))


def _code_identity():
    from scripts import canonical_layer2_controller
    return canonical_layer2_controller.code_identity()


def module_path(module) -> Path:
    return Path(module.__file__).resolve()


def module_sha256(module) -> str:
    return hashlib.sha256(module_path(module).read_bytes()).hexdigest()


def code() -> ports.Code:
    return ports.Code(code_identity=_code_identity, module_sha256=module_sha256, module_path=module_path)


def _mfa_options(args):
    from scripts import sermon_pipeline
    return sermon_pipeline.mfa_options(args)


def mfa() -> ports.Mfa:
    return ports.Mfa(options=_mfa_options)


def _require(condition, code):
    from scripts import sermon_review_contracts
    return sermon_review_contracts.require(condition, code)


def _bytes_sha256(value):
    from scripts import sermon_review_contracts
    return sermon_review_contracts.bytes_sha256(value)


def _canonical_sha256(value):
    from scripts import sermon_review_contracts
    return sermon_review_contracts.canonical_sha256(value)


def contracts() -> ports.Contracts:
    # The error class is the one object callers catch, so it is bound directly.
    from scripts import sermon_review_contracts
    return ports.Contracts(error=sermon_review_contracts.ContractError, require=_require,
                           bytes_sha256=_bytes_sha256, canonical_sha256=_canonical_sha256)


def _read_snapshot(path):
    from scripts import sermon_public_snapshot
    return sermon_public_snapshot.read_snapshot(path)


def snapshot() -> ports.Snapshot:
    return ports.Snapshot(read_snapshot=_read_snapshot)


def compute() -> ports.Compute:
    # The class is the one object producers construct and test with isinstance.
    from scripts.production_spark_admission import SessionBoundCaller
    # The two host-wide limits are constants of a standard-library-only module.
    from scripts import layer2_api_concurrency
    return ports.Compute(session_bound_caller=SessionBoundCaller, require_session=_require_session,
                         load_profile=_load_profile, validate_profile=_validate_profile, admit=_admit,
                         reject_cli_transport=_reject_cli_transport, request_slot=_request_slot,
                         max_in_flight_api_calls=layer2_api_concurrency.MAX_IN_FLIGHT_API_CALLS,
                         max_group_workers_per_locale=layer2_api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE)


def _load_profile(path):
    from scripts import production_concurrency_profile
    return production_concurrency_profile.load_profile(path)


def _validate_profile(value):
    from scripts import production_concurrency_profile
    return production_concurrency_profile.validate_profile(value)


def _admit(payload, request_limits, *, surface='canonical_api'):
    from scripts import strict_budget_capability
    return strict_budget_capability.require_bounded_api_payload(payload, request_limits, surface=surface)


def _reject_cli_transport(caller):
    from scripts import strict_budget_capability
    return strict_budget_capability.reject_codex_cli_transport(caller)


def _request_slot(job_root):
    from scripts import layer2_api_concurrency
    return layer2_api_concurrency.request_slot(job_root)


def _require_session(*, verifier=None):
    from scripts import production_spark_admission
    return production_spark_admission.require_session(verifier=verifier)


def _resources():
    # Importing the scripts facade binds tongxing_production.orchestration first.
    from scripts.sermon_unified import resources
    return resources


def resources() -> ports.Resources:
    return ports.Resources(validate_policy=lambda policy: _resources().validate_policy(policy),
                           identity=lambda policy: _resources()._identity(policy),
                           reserve=lambda policy, **kw: _resources().reserve(policy, **kw),
                           release=lambda policy, **kw: _resources().release(policy, **kw))


def _validate_source_meaning_receipt(receipt, *, source, anchor, media_sha256, receipt_directory):
    from scripts import source_meaning_machine_adjudication as adjudicator
    try:
        adjudicator.validate_receipt(receipt, source=source, anchor=anchor, media_sha256=media_sha256,
                                     cache=receipt_directory / adjudicator.ADJUDICATOR_CACHE)
    except adjudicator.SourceAdjudicationError as exc:
        raise ports.AdjudicationRejected(str(exc)) from exc


def adjudication() -> ports.Adjudication:
    return ports.Adjudication(validate_receipt=_validate_source_meaning_receipt)


def _terminology_context():
    from scripts import series_terminology
    return series_terminology.context()


def _terminology_table_path():
    from scripts import series_terminology
    return series_terminology.REGISTRY


def _parse_terminology_table(text):
    from scripts import series_terminology
    return series_terminology.parse_table(text)


def terminology() -> ports.Terminology:
    return ports.Terminology(context=_terminology_context, table_path=_terminology_table_path,
                             parse_table=_parse_terminology_table)


def _producer_step(ledger_path, step_id, *, locale=None):
    from scripts import four_layer_measure
    return four_layer_measure.producer_step(ledger_path, step_id, locale=locale)


def _producer_substage(name, *, billing='api'):
    from scripts import four_layer_measure
    return four_layer_measure.producer_substage(name, billing=billing)


def measure() -> ports.Measure:
    return ports.Measure(producer_step=_producer_step, producer_substage=_producer_substage)


def _work_lock(work):
    from scripts.sermon_execution_harness import work_lock
    return work_lock(work)


def workspace() -> ports.Workspace:
    return ports.Workspace(work_lock=_work_lock)


def _accounting_session(directory, workflow, metadata=None, *, evidence_directory=None):
    from scripts import sermon_accounting
    return sermon_accounting.accounting_session(directory, workflow, metadata, evidence_directory=evidence_directory)


def _accounting_stage(name, **options):
    from scripts import sermon_accounting
    return sermon_accounting.stage(name, **options)


def _record_workload(name, metrics):
    from scripts import sermon_accounting
    return sermon_accounting.record_workload(name, metrics)


def _record_log(code, **options):
    from scripts import sermon_accounting
    return sermon_accounting.record_log(code, **options)


def _bounded_dependencies(name, dependencies, *, work_unit_id):
    from scripts import sermon_accounting
    return sermon_accounting.bounded_dependencies(name, dependencies, work_unit_id=work_unit_id)


def _finalize_accounting(action, original_error):
    from scripts import sermon_accounting
    return sermon_accounting._finalize(action, original_error)


def accounting() -> ports.Accounting:
    return ports.Accounting(session=_accounting_session, stage=_accounting_stage, record_workload=_record_workload,
                            record_log=_record_log, bounded_dependencies=_bounded_dependencies,
                            finalize=_finalize_accounting)


def _validate_window(manifest, bindings=None, base='.'):
    from scripts.sermon_unified_reviews import validate_window
    return validate_window(manifest, bindings, base)


def review() -> ports.Review:
    return ports.Review(validate_window=_validate_window)


def plugins() -> ports.Plugins:
    # Plugins run and hash as files in place (L2 design decision 1); the hash
    # covers file names and bytes, never this path.
    return ports.Plugins(root=lambda: ROOT / 'scripts/language_review_plugins',
                         implementation_file=lambda name: ROOT / 'scripts' / name,
                         module=lambda name: _module('scripts.' + name)())


def _transport_caller(backend, **options):
    if backend == 'openai-api':
        from scripts.openai_layer2_transport import OpenAILayer2Transport
        return OpenAILayer2Transport(**options)
    if backend == 'codex-cli':
        from scripts.codex_layer2_transport import CodexLayer2Transport
        return CodexLayer2Transport(**options)
    if backend == 'claude-cli':
        from scripts.claude_layer2_transport import ClaudeLayer2Transport
        return ClaudeLayer2Transport(**options)
    raise ValueError(f'unknown Layer 2 transport backend: {backend}')


def _claude_chat_envelope(response, model):
    from scripts.claude_layer2_transport import chat_envelope
    return chat_envelope(response, model)


def _validate_codex_test_configuration(configuration):
    from scripts.codex_layer2_transport import validate_test_configuration
    return validate_test_configuration(configuration)


def transports() -> ports.Transports:
    return ports.Transports(caller=_transport_caller, claude_chat_envelope=_claude_chat_envelope,
                            validate_codex_test_configuration=_validate_codex_test_configuration)


def _validate_handoff_schema(value, filename, label):
    from scripts import prepare_target_language_speech_job
    return prepare_target_language_speech_job._validate_schema(value, filename, label)


def _source_package_schema():
    from scripts import prepare_target_language_speech_job
    return prepare_target_language_speech_job.SOURCE_PACKAGE_SCHEMA


def schemas() -> ports.Schemas:
    return ports.Schemas(path=lambda name: ROOT / 'schemas' / name, validate=_validate_handoff_schema,
                         source_package_schema=_source_package_schema)


def _validate_diagnostic_source(source, anchor, context):
    from scripts import sermon_diagnostic_context
    return sermon_diagnostic_context.validate_source(source, anchor, context)


def _validate_diagnostic_context(context):
    from scripts import sermon_diagnostic_context
    return sermon_diagnostic_context.validate_context(context)


def _require_diagnostic_policy_ready(identity, context=None):
    from scripts import sermon_diagnostic_context
    return sermon_diagnostic_context.require_policy_ready(identity, context)


def diagnostic() -> ports.Diagnostic:
    return ports.Diagnostic(validate_source=_validate_diagnostic_source, validate_context=_validate_diagnostic_context,
                            require_policy_ready=_require_diagnostic_policy_ready)


def layer2_worker_command(*arguments):
    # Existing durable job requests record this argv; it keeps naming the
    # scripts/ entry point so recovery matches them byte for byte.
    return [sys.executable, str(ROOT / 'scripts/canonical_layer2_controller.py'), *arguments]


def _module(name):
    def load():
        import importlib
        return importlib.import_module(name)
    return load


def _load_meaning_notes(path, **options):
    from scripts import source_meaning_machine_adjudication
    return source_meaning_machine_adjudication.load_meaning_notes(path, **options)


def _repair_instruction(notes, source_unit_ids):
    from scripts import source_meaning_machine_adjudication
    return source_meaning_machine_adjudication.repair_instruction(notes, source_unit_ids)


def _record_cache_observation(role, saved, output, *, mode, origin=None):
    from scripts import sermon_cache_observation
    return sermon_cache_observation.record(role, saved, output, mode=mode, origin=origin)


def text_unmoved() -> text_backend.Unmoved:
    return text_backend.Unmoved(
        durable_jobs=_module('scripts.canonical_durable_jobs'),
        package_inspection=_module('scripts.inspect_canonical_packages'),
        pipeline_definition=_module('scripts.canonical_pipeline_definition'),
        liveness=_module('scripts.sermon_job_liveness'),
        review_budget=_module('scripts.sermon_review_budget'),
        speech_handoff=_module('scripts.prepare_target_language_speech_job'),
        orchestration_contracts=_module('scripts.sermon_unified.contracts'),
        review_contracts=_module('scripts.sermon_review_contracts'),
        load_meaning_notes=_load_meaning_notes, repair_instruction=_repair_instruction,
        record_cache_observation=_record_cache_observation)


# Each record is built once and shared by the layers that use it.
_core, _provider, _code, _contracts, _snapshot = core(), provider(), code(), contracts(), snapshot()
_compute, _resources_port, _terminology = compute(), resources(), terminology()
_measure, _workspace, _accounting = measure(), workspace(), accounting()

source_backend.configure(source_backend.SourceBackend(core=_core, provider=_provider, code=_code, mfa=mfa(),
                                                      contracts=_contracts, snapshot=_snapshot, compute=_compute,
                                                      resources=_resources_port, adjudication=adjudication(),
                                                      terminology=_terminology, measure=_measure,
                                                      workspace=_workspace, accounting=_accounting, review=review()))
text_backend.configure(text_backend.TextBackend(core=_core, provider=_provider, code=_code, contracts=_contracts,
                                                snapshot=_snapshot, compute=_compute, resources=_resources_port,
                                                terminology=_terminology, measure=_measure, accounting=_accounting,
                                                workspace=_workspace, plugins=plugins(), transports=transports(),
                                                schemas=schemas(), diagnostic=diagnostic(),
                                                worker_command=layer2_worker_command, unmoved=text_unmoved()))

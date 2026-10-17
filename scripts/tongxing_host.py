"""Bind the production package's layer backends to this checkout.

Importing this module configures the source, text, delivery, audio and review layers.
Every port is a late-binding wrapper around the ``scripts/`` implementation it
stands in for: the implementation is imported inside the wrapper, so a test
that patches ``scripts.sermon_pipeline.chat_json`` (or any other target) still
intercepts calls made through the port, and no import cycle forms with the
producers that import this module at load time.

``scripts/sermon_unified/__init__.py`` binds ``tongxing_production.orchestration``
the same way; the two hosts will share ``core()`` once that facade is revisited.
"""
from __future__ import annotations

from functools import partial
import contextlib
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tongxing_production import ports  # noqa: E402
from tongxing_production.contracts import schemas as contract_schemas  # noqa: E402
from tongxing_production.source import backend as source_backend  # noqa: E402
from tongxing_production.text import backend as text_backend  # noqa: E402
from tongxing_production.delivery import backend as delivery_backend  # noqa: E402
from tongxing_production.audio import backend as audio_backend  # noqa: E402
from tongxing_production.review import backend as review_backend  # noqa: E402
from tongxing_production.compute import backend as compute_backend  # noqa: E402
from tongxing_production.orchestration import jobs_host as jobs_host_module  # noqa: E402
from tongxing_production.observability import backend as observability_backend  # noqa: E402
from tongxing_production.workflows.dual_pdf import host as dual_pdf_host  # noqa: E402


def core() -> ports.Core:
    # The package module, not the scripts/ facade: core() runs while the host loads, and the
    # facade imports the host first, so binding the facade here would bind a half-initialized module.
    from tongxing_production.orchestration import jobs
    from scripts.sermon_execution_harness import atomic_json, utc_now
    from scripts.sermon_release_workflow import safe_path
    return ports.Core(repo_root=ROOT, artifact_root=ROOT / 'artifacts', jobs=jobs,
                      safe_path=safe_path, atomic_json=atomic_json, utc_now=utc_now,
                      sync_directory_ancestry=_sync_directory_ancestry, read_json=_read_json)


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


def _transcription_limits():
    from types import SimpleNamespace
    from scripts import sermon_transcription_request as transcription
    return SimpleNamespace(MAX_RESPONSE_BYTES=transcription.MAX_RESPONSE_BYTES, WALL_TIME_MS=transcription.WALL_TIME_MS,
                           MICROUSD_PER_MINUTE=transcription.MICROUSD_PER_MINUTE)


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


def _outcomes_function(name):
    def call(*arguments, **options):
        from tongxing_production.compute import outcomes as api_cli_outcomes
        return getattr(api_cli_outcomes, name)(*arguments, **options)
    call.__name__ = name
    return call


def outcomes() -> ports.Outcomes:
    return ports.Outcomes(**{name: _outcomes_function(name) for name in (
        'request_identity', 'execution_binding', 'assert_replay_admitted', 'recover', 'before_dispatch',
        'receipt_root')})


def provider() -> ports.Provider:
    return ports.Provider(chat_json=_chat_json, request_json=_request_json,
                          reject_secret_override=_reject_secret_override,
                          bounded_legacy_chat_payload=_bounded_legacy_chat_payload,
                          legacy_text_cache_contract=_legacy_text_cache_contract,
                          legacy_text_execution_identity=_legacy_text_execution_identity,
                          access_secret=_access_secret, outcomes=outcomes(),
                          http_execute=_http_execute, transcription_request=_transcription_request,
                          request_metadata=_request_metadata,
                          route=ports.Route(selected=_selected_route, safe=_safe_route,
                                            project_headers=_project_headers),
                          transcription_limits=_transcription_limits)


def _code_identity():
    from scripts import canonical_layer2_controller
    return canonical_layer2_controller.code_identity()


def module_path(module) -> Path:
    return Path(module.__file__).resolve()


def module_sha256(module) -> str:
    return hashlib.sha256(module_path(module).read_bytes()).hexdigest()


def code() -> ports.Code:
    return ports.Code(code_identity=_code_identity, module_sha256=module_sha256, module_path=module_path,
                      implementation_path=implementation_path)


def _mfa_options(args):
    from scripts import sermon_pipeline
    return sermon_pipeline.mfa_options(args)


def mfa() -> ports.Mfa:
    return ports.Mfa(options=_mfa_options)


def _read_snapshot(path):
    from scripts import sermon_public_snapshot
    return sermon_public_snapshot.read_snapshot(path)


def snapshot() -> ports.Snapshot:
    return ports.Snapshot(read_snapshot=_read_snapshot)


def compute() -> ports.Compute:
    # The class is the one object producers construct and test with isinstance.
    from tongxing_production.compute.spark_admission import SessionBoundCaller
    # The two host-wide limits are constants of a standard-library-only module.
    from scripts import layer2_api_concurrency
    return ports.Compute(session_bound_caller=SessionBoundCaller, session_error=_session_error,
                         require_session=_require_session,
                         load_profile=_load_profile, validate_profile=_validate_profile, admit=_admit,
                         reject_cli_transport=_reject_cli_transport, request_slot=_request_slot,
                         max_in_flight_api_calls=layer2_api_concurrency.MAX_IN_FLIGHT_API_CALLS,
                         max_group_workers_per_locale=layer2_api_concurrency.MAX_GROUP_WORKERS_PER_LOCALE,
                         require_bound_model_session=_require_bound_model_session)


def _load_profile(path):
    from scripts import production_concurrency_profile
    return production_concurrency_profile.load_profile(path)


def _validate_profile(value):
    from scripts import production_concurrency_profile
    return production_concurrency_profile.validate_profile(value)


def _admit(payload, request_limits, *, surface='canonical_api'):
    from tongxing_production.compute import budget_capability as strict_budget_capability
    return strict_budget_capability.require_bounded_api_payload(payload, request_limits, surface=surface)


def _reject_cli_transport(caller):
    from tongxing_production.compute import budget_capability as strict_budget_capability
    return strict_budget_capability.reject_codex_cli_transport(caller)


def _request_slot(job_root):
    from scripts import layer2_api_concurrency
    return layer2_api_concurrency.request_slot(job_root)


def _require_session(*, verifier=None):
    from tongxing_production.compute import spark_admission as production_spark_admission
    return production_spark_admission.require_session(verifier=verifier)


def _session_error():
    from scripts.spark_exclusive_session import SessionError
    return SessionError


def _resources():
    # Importing the scripts facade binds tongxing_production.orchestration first.
    from scripts.sermon_unified import resources
    return resources


@contextlib.contextmanager
def _ledger_transaction(policy):
    from scripts import sermon_workflow_jobs as jobs
    ledger_module = _resources()
    with jobs._lock(ledger_module._safe_path(policy['brokerRoot']), ledger_module.BROKER_LOCK_ID) as (folder, _, held):
        if not held:
            yield None
            return
        ledger = ledger_module._load(folder, policy)
        yield ledger, (lambda: ledger_module._save(folder, ledger))


def _resource_contract_error():
    from tongxing_production.orchestration.unified import contracts as unified_contracts
    return unified_contracts.ContractError


def resources() -> ports.Resources:
    return ports.Resources(validate_policy=lambda policy: _resources().validate_policy(policy),
                           identity=lambda policy: _resources()._identity(policy),
                           reserve=lambda policy, **kw: _resources().reserve(policy, **kw),
                           release=lambda policy, **kw: _resources().release(policy, **kw),
                           ledger_transaction=_ledger_transaction,
                           operation_key=lambda operation_id: _resources()._operation(operation_id),
                           contract_error=_resource_contract_error)


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


def _terminology_prompt_instruction():
    from scripts import series_terminology
    return series_terminology.PROMPT_INSTRUCTION


def terminology() -> ports.Terminology:
    return ports.Terminology(context=_terminology_context, table_path=_terminology_table_path,
                             parse_table=_parse_terminology_table,
                             prompt_instruction=_terminology_prompt_instruction)


def _producer_step(ledger_path, step_id, *, locale=None):
    from scripts import four_layer_measure
    return four_layer_measure.producer_step(ledger_path, step_id, locale=locale)


def _producer_substage(name, *, billing='api'):
    from scripts import four_layer_measure
    return four_layer_measure.producer_substage(name, billing=billing)


def measure() -> ports.Measure:
    return ports.Measure(producer_step=_producer_step, producer_substage=_producer_substage,
                         record_substage_metrics=_record_substage_metrics)


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


def _subprocess_environment():
    from scripts import sermon_accounting
    return sermon_accounting.subprocess_environment()


def _stage_outcome(name, **options):
    from scripts import sermon_accounting
    return sermon_accounting.stage_outcome(name, **options)


def _profile_session(directory, workflow, metadata=None, **options):
    from scripts import sermon_log_profile
    return sermon_log_profile.session(directory, workflow, metadata, **options)


def _profile_context(**fields):
    from scripts import sermon_log_profile
    return sermon_log_profile.context(**fields)


def _record_api_started(model, settings=None):
    from scripts import sermon_accounting
    return sermon_accounting.record_api_started(model, settings)


def _record_api_attempt(*arguments, **options):
    from scripts import sermon_accounting
    return sermon_accounting.record_api_attempt(*arguments, **options)


def _request_metadata(payload):
    from scripts import sermon_accounting
    return sermon_accounting.request_metadata(payload)


def _accounting_write_error():
    # The class itself, so isinstance checks match what the ledger raises.
    from scripts.sermon_accounting import AccountingWriteError
    return AccountingWriteError


def accounting() -> ports.Accounting:
    return ports.Accounting(session=_accounting_session, stage=_accounting_stage, record_workload=_record_workload,
                            record_log=_record_log, bounded_dependencies=_bounded_dependencies,
                            finalize=_finalize_accounting, orchestration=_accounting_orchestration,
                            subprocess_environment=_subprocess_environment, stage_outcome=_stage_outcome,
                            profile_session=_profile_session, profile_context=_profile_context,
                            record_api_started=_record_api_started, record_api_attempt=_record_api_attempt,
                            request_metadata=_request_metadata, write_error=_accounting_write_error)


def _validate_window(manifest, bindings=None, base='.'):
    from scripts.sermon_unified_reviews import validate_window
    return validate_window(manifest, bindings, base)


def _validate_review(kind, receipt_path, **binding):
    from scripts import sermon_unified_reviews
    return sermon_unified_reviews.validate_review(kind, receipt_path, **binding)


def _audio_screening_review(audio, receipt, screening):
    from scripts import stage_formal_multilingual_dev
    return stage_formal_multilingual_dev.validate_audio_screening_review(audio, receipt, screening)


def review() -> ports.Review:
    return ports.Review(validate_window=_validate_window, validate_review=_validate_review,
                        audio_screening=_audio_screening_review)


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
                            validate_codex_test_configuration=_validate_codex_test_configuration,
                            audio_qc=_module('scripts.machine_qc_audio_transports'))


def _validate_handoff_schema(value, filename, label):
    from tongxing_production.audio import speech_job
    return speech_job._validate_schema(value, filename, label)


def _source_package_schema():
    from tongxing_production.audio import speech_job
    return speech_job.SOURCE_PACKAGE_SCHEMA


def schemas() -> ports.Schemas:
    return ports.Schemas(path=contract_schemas.path, validate=_validate_handoff_schema,
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
        liveness=_module('scripts.sermon_job_liveness'),
        review_budget=_module('scripts.sermon_review_budget'),
        speech_handoff=_module('tongxing_production.audio.speech_job'),
        orchestration_contracts=_module('scripts.sermon_unified.contracts'),
        accounting_module=_module('scripts.sermon_accounting'),
        api_concurrency_module=_module('scripts.layer2_api_concurrency'),
        source_meaning_module=_module('scripts.source_meaning_machine_adjudication'),
        load_meaning_notes=_load_meaning_notes, repair_instruction=_repair_instruction,
        record_cache_observation=_record_cache_observation)


def runtime_web() -> ports.RuntimeWeb:
    # The checkout's reader shell (L4 decision 4); frozen inputs keep hashing these files.
    return ports.RuntimeWeb(root=lambda: ROOT / 'apps/listening-web')


def hosting() -> ports.Hosting:
    # The package's Hosting adapter (L4 D3). Each entry looks the adapter up per call,
    # so patches on tongxing_production.storage.hosting apply.
    from tongxing_production.storage import hosting as adapter
    return ports.Hosting(authorized_request=lambda: adapter.authenticated_transport(),
                         public_reader=lambda url, *, timeout=120: adapter.public_reader(url, timeout=timeout),
                         run=lambda *arguments, **options: adapter.run(*arguments, **options),
                         lease=lambda request, bucket, site: adapter.RemoteLease(request, bucket, site))


def _is_text_waiver(receipt):
    from tongxing_production.review import release_basis
    return release_basis.is_text_waiver(receipt)


def _validate_text_waiver(receipt, **binding):
    from tongxing_production.review import release_basis
    return release_basis.validate_text_waiver(receipt, **binding)


def _waiver_disclosure(locale):
    from tongxing_production.review import release_basis
    return release_basis.disclosure(locale)


def _is_basis_audio_waiver(receipt):
    from tongxing_production.review import release_basis
    return release_basis.is_audio_waiver(receipt)


def _is_audio_waiver(receipt):
    from scripts import machine_audio_waiver_acceptance
    return machine_audio_waiver_acceptance.is_audio_waiver(receipt)


def _validate_audio_waiver(package, receipt, screening):
    from scripts import machine_audio_waiver_acceptance
    return machine_audio_waiver_acceptance.validate_audio_waiver(package, receipt, screening)


def waivers() -> ports.Waivers:
    # The schema names and review kind are fixed strings of the waiver release basis,
    # recorded here so the record does not depend on import order; a test pins them.
    return ports.Waivers(is_text_waiver=_is_text_waiver, validate_text_waiver=_validate_text_waiver,
                         disclosure=_waiver_disclosure, is_audio_waiver=_is_audio_waiver, is_basis_audio_waiver=_is_basis_audio_waiver,
                         validate_audio_waiver=_validate_audio_waiver,
                         audio_waiver_schema='sermon-target-language-machine-audio-waiver-v2',
                         condensation_binding_schema='sermon-spoken-condensation-binding-v2',
                         review_kind='machine_quality_waiver')


def app_delivery_worker_command(*arguments):
    # Existing durable job requests record this argv; it keeps naming the
    # scripts/ entry point so recovery matches them byte for byte.
    return [sys.executable, str(ROOT / 'scripts/sermon_app_delivery_workflow.py'), *arguments]


def _legacy_weekly_release():
    # The v1 weekly catalog module; the legacy adapters used to put its folder on sys.path themselves.
    folder = str(ROOT / 'experiments/sermon-dubbing-poc')
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import weekly_release
    return weekly_release


def delivery_unmoved() -> delivery_backend.Unmoved:
    return delivery_backend.Unmoved(app_release=_module('scripts.build_full_video_app_release'),
                                    formal_stage=_module('scripts.stage_formal_multilingual_dev'),
                                    execution_harness=_module('scripts.sermon_execution_harness'))


def delivery_legacy() -> delivery_backend.Legacy:
    return delivery_backend.Legacy(weekly_release=_legacy_weekly_release,
                                   voice_demo=_module('scripts.stage_voice_demo_dev'),
                                   firebase_config=lambda name: ROOT / 'firebase' / name)


# Layer 3 (tongxing_production.audio). Every wrapper imports its implementation
# when called, so the renderer, audio QC and spoken-rule modules stay unloaded
# at host load.
def _sync_directory_ancestry(path):
    from scripts import sermon_workflow_jobs
    return sermon_workflow_jobs._sync_directory_ancestry(path)


def _read_json(path):
    from scripts import sermon_workflow_jobs
    return sermon_workflow_jobs._read(path)


def implementation_path(name) -> Path:
    # Closure keys stay legacy scripts/ paths; a moved file is read at its alias.
    from tongxing_production import path_aliases
    return ROOT / path_aliases.resolve(name)


def _require_bound_model_session(*, verifier=None):
    from tongxing_production.compute import spark_admission as production_spark_admission
    return production_spark_admission.require_bound_model_session(verifier=verifier)


def _record_substage_metrics(metrics):
    from scripts import four_layer_measure
    return four_layer_measure.record_substage_metrics(metrics)


def _accounting_orchestration(name, *, depends_on=None, work_unit_id=None):
    from scripts import sermon_accounting
    return sermon_accounting.orchestration(name, depends_on=depends_on, work_unit_id=work_unit_id)


def _screening_asr_settings(screening):
    from scripts import target_audio_auto_qc
    return target_audio_auto_qc.screening_asr_settings(screening)


def machine_qc() -> ports.MachineQc:
    return ports.MachineQc(screening_asr_settings=_screening_asr_settings)


def _rule_function(module, name):
    def call(*args, **kwargs):
        return getattr(_module(module)(), name)(*args, **kwargs)
    call.__name__ = name
    return call


def _rule_constant(module, name):
    return lambda: getattr(_module(module)(), name)


_PLUGIN_RULES = 'scripts.language_review_plugins.auto_qc_text_common'
_KO_NUMERALS = 'scripts.ko_spoken_numerals'


def spoken_rules() -> ports.SpokenRules:
    # Both files stay in scripts/ (L3 decision 3) and are pinned by the waiver,
    # scoring and rate closures; constants are the modules' own objects.
    plugin, plugin_constant = partial(_rule_function, _PLUGIN_RULES), partial(_rule_constant, _PLUGIN_RULES)
    ko, ko_constant = partial(_rule_function, _KO_NUMERALS), partial(_rule_constant, _KO_NUMERALS)
    return ports.SpokenRules(
        fold=plugin('_fold'), ko_pattern=plugin('_ko_pattern'), book_citations=plugin('book_citations'),
        english_numbers=plugin('english_numbers'), korean_sino=plugin('korean_sino'),
        korean_native=plugin('korean_native'), en_book_codes=plugin_constant('_EN_BOOK_CODES'),
        es_book_codes=plugin_constant('_ES_BOOK_CODES'), ko_book_codes=plugin_constant('_KO_BOOK_CODES'),
        zh_book_codes=plugin_constant('_ZH_BOOK_CODES'), ko_citation=plugin_constant('_KO_CITATION'),
        ko_counters=plugin_constant('_KO_COUNTERS'), zh_measure_words=plugin_constant('_ZH_MEASURE_WORDS'),
        ko_rule=ko_constant('RULE'), ko_rule_v2=ko_constant('RULE_V2'), ko_rule_v3=ko_constant('RULE_V3'),
        spoken_form=ko('spoken_form'), spoken_form_v2=ko('spoken_form_v2'), spoken_form_v3=ko('spoken_form_v3'),
        equivalent=ko('equivalent'), bare_context_allowed=ko('bare_context_allowed'),
        bare_citation_matches=ko('bare_citation_matches'), ko_particles=ko_constant('_PARTICLES'),
        ko_connector=ko_constant('_CONNECTOR'), ko_range_particle=ko_constant('_RANGE_PARTICLE'),
        ko_delimiters=ko_constant('_DELIMITERS'), ko_numeric_token=ko_constant('_NUMERIC_TOKEN'),
        ko_citations=ko_constant('_CITATIONS'))


def _read_checkpoint_map(path, label):
    from scripts import render_multilingual_voice_demos
    return render_multilingual_voice_demos.read_object(path, label)


def _validate_checkpoint(task):
    from scripts import render_multilingual_voice_demos
    return render_multilingual_voice_demos.validate_checkpoint(task)


def tts_runtime() -> ports.TtsRuntime:
    return ports.TtsRuntime(replica_pool=_module('scripts.spark_tts_replica_pool'),
                            window_scheduler=_module('scripts.spark_tts_window_scheduler'),
                            bounded_cpu=_module('scripts.bounded_audio_cpu'),
                            read_checkpoint_map=_read_checkpoint_map, validate_checkpoint=_validate_checkpoint)


def dev_profile() -> ports.DevProfile:
    # The Dev profile location the scripts/ module derives from its own file today.
    return ports.DevProfile(default_profile_path=lambda: ROOT / 'data/benchmarks/local-layer-latency/2026-10-01/'
                                                         'next-dev-test-profile.json')


def audio_unmoved() -> audio_backend.Unmoved:
    return audio_backend.Unmoved(local_model_observation=_module('scripts.sermon_local_model_observation'))


# Cross-layer review (tongxing_production.review). Most of what review reads from
# the stages is in the waiver, scoring or rate closure, or is a private name of a
# pinned file, so nothing here imports it at host load and no pinned file gains a
# public name: functions are called through their scripts/ module at call time, so
# patches still intercept, and constants and classes are read when used.
_PREDICTED = 'scripts.target_audio_predicted_schedule'
_SCREENING = 'scripts.screen_target_language_audio_units'
_RENDERER = 'scripts.render_formal_target_language_speech'


def audio_rules() -> ports.AudioRules:
    predicted, predicted_value = partial(_rule_function, _PREDICTED), partial(_rule_constant, _PREDICTED)
    screening, screening_value = partial(_rule_function, _SCREENING), partial(_rule_constant, _SCREENING)
    return ports.AudioRules(
        predicted_schema=predicted_value('SCHEMA'),
        synthesis_identity_fields=predicted_value('SYNTHESIS_IDENTITY_FIELDS'),
        synthesis_identity=predicted('synthesis_identity'), check_identity=predicted('_check_identity'),
        policy_texts=predicted('policy_texts'), speech_units=predicted('speech_units'), budget=predicted('budget'),
        score=screening('score'), scoring=screening_value('SCORING'), scoring_v3=screening_value('SCORING_V3'),
        known_scorings=screening_value('KNOWN_SCORINGS'),
        current_scoring_identity_problems=screening('current_scoring_identity_problems'),
        negations=screening_value('NEGATIONS'), zh_numerals=screening_value('ZH_NUMERALS'),
        es_numbers=screening_value('ES_NUMBERS'), korean_number_spans=screening('korean_number_spans'),
        registered_normalization_policy=_rule_function(_RENDERER, 'registered_normalization_policy'))


def text_rules() -> ports.TextRules:
    policy = partial(_rule_function, 'scripts.target_language_policy')
    return ports.TextRules(
        canonical_sha256=policy('canonical_sha256'), validate_policy=policy('validate_policy'),
        validate_source_scope=policy('validate_source_scope'),
        validate_source_for_translation=_rule_function('scripts.produce_target_language_candidate',
                                                       'validate_source_for_translation'),
        human_ruling_schema=_rule_constant('scripts.layer2_human_ruling', 'SCHEMA'),
        load_human_ruling=_rule_function('scripts.layer2_human_ruling', 'load'))


def source_evidence() -> ports.SourceEvidence:
    judge, judge_value = (partial(_rule_function, 'scripts.english_source_judge_cache'),
                          partial(_rule_constant, 'scripts.english_source_judge_cache'))
    interpretation = partial(_rule_function, 'scripts.sermon_sentence_interpretation')
    return ports.SourceEvidence(
        text_review=_module('scripts.sermon_source_text_review'),
        text_sha256=_rule_function('scripts.sermon_source_text_review', 'text_sha256'),
        judge_cached_call=judge('cached_call'), reconcile_returned_response=judge('reconcile_returned_response'),
        judge_run_schema=judge_value('RUN_SCHEMA'), atomic_json=judge('_atomic'),
        model_result=_rule_function('scripts.run_sentence_interpretation_models', '_model_result'),
        source_budget=_rule_constant('scripts.sermon_source_budget', 'SourceBudget'),
        budget_metrics=_rule_constant('scripts.sermon_source_budget', 'METRICS'),
        sha256=interpretation('sha256'), json_sha256=interpretation('json_sha256'))


def stage_gates() -> ports.StageGates:
    supervisor = partial(_rule_function, 'scripts.sermon_production_supervisor')
    return ports.StageGates(
        window_approval=supervisor('validate_window_approval'), parse_timecode=supervisor('parse_timecode'),
        stable_hash=supervisor('stable_hash'),
        english_review=_rule_function('scripts.build_english_source_package', '_review_payload'),
        text_release_basis=_rule_function('tongxing_production.audio.speech_job', 'validate_text_release_basis'),
        study_ingest=_rule_function('scripts.study_artifacts', 'ingest_review'))


def scripture() -> ports.Scripture:
    # The library files stay in scripts/: cuv_scripture is hashed into the zh-Hans
    # plugin by file name and bytes (L2 section 4.1).
    return ports.Scripture(cuv=_module('scripts.cuv_scripture'), editions=_module('scripts.scripture_editions'),
                           coverage=_module('scripts.english_scripture_coverage'),
                           candidate_queue=_module('scripts.scripture_candidate_queue'),
                           library_path=_rule_constant('scripts.cuv_scripture', 'DEFAULT_LIBRARY_PATH'),
                           coverage_data_path=_rule_constant('scripts.english_scripture_coverage', 'DATA_PATH'))


def qc_runtime() -> ports.QcRuntime:
    return ports.QcRuntime(write_report=_rule_function('scripts.export_run_digest', 'write_report'),
                           codex_text_transport=_module('scripts.sermon_codex_transport'),
                           validate_target_candidate=_rule_function('tongxing_production.audio.speech_job',
                                                                    'validate_target_candidate'),
                           implementation_freeze=_module('scripts.implementation_freeze'),
                           audio_waiver_acceptance=_module('scripts.machine_audio_waiver_acceptance'))


# The moved producers used to import these modules at load time. A plan freezes
# accounting.execution_identity() (the loaded project code) before it runs and
# checks it again at review and cache replay, so a module that now loads only on
# first use through a port would change that identity mid-run.
# execution_identity() calls load_producer_imports() before it reads the loaded
# set. Never call it while modules are still importing: these modules import
# facades and each other, so loading them from inside an import chain meets
# partially initialized modules.
EAGER_PRODUCER_IMPORTS = (
    'api_cli_outcomes', 'canonical_durable_jobs', 'canonical_pipeline_definition', 'four_layer_measure',
    'inspect_canonical_packages', 'layer2_api_concurrency', 'machine_quality_release_basis',
    'prepare_target_language_speech_job', 'production_spark_admission',
    'series_terminology', 'sermon_accounting', 'sermon_cache_observation',
    'sermon_execution_harness', 'sermon_job_liveness', 'sermon_pipeline', 'sermon_provider_http',
    'sermon_provider_limits', 'sermon_public_snapshot', 'sermon_release_workflow', 'sermon_review_budget',
    'sermon_review_contracts', 'sermon_transcription_request', 'sermon_unified_reviews', 'sermon_workflow_jobs',
    'source_meaning_machine_adjudication',
)


def _cloud_function(name):
    def call(*arguments, **options):
        from backend import cloud as implementation
        return getattr(implementation, name)(*arguments, **options)
    call.__name__ = name
    return call


def cloud() -> ports.Cloud:
    return ports.Cloud(**{name: _cloud_function(name) for name in (
        'access_secret', 'read_gcs_bytes', 'read_gcs_text', 'download_file_from_gcs',
        'upload_file_to_gcs', 'write_gcs_text')})


def _observability_function(name):
    def call(*arguments, **options):
        from backend import observability as implementation
        return getattr(implementation, name)(*arguments, **options)
    call.__name__ = name
    return call


def observability() -> ports.Observability:
    return ports.Observability(**{name: _observability_function(name) for name in (
        'log_event', 'stable_hash', 'url_summary')})


def _scripts_module(name):
    def get():
        import importlib
        return importlib.import_module('scripts.' + name)
    return get


def _dubbing_producer_hook():
    # The dubbing POC bridge lives under experiments/, outside the package.
    import importlib.util
    directory = ROOT / 'experiments' / 'sermon-dubbing-poc'
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('sermon_dubbing_producer_bridge',
                                                  directory / 'continue_saturday_dubbing.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.start_producer_candidate, module.CandidateNotReady


def _upcoming_sunday(*arguments, **options):
    from backend.config import upcoming_sunday
    return upcoming_sunday(*arguments, **options)


def compute_unmoved():
    return compute_backend.Unmoved(
        waiver=_scripts_module('machine_quality_waiver'), audio_qc=_scripts_module('target_audio_auto_qc'),
        budget_authorization=_scripts_module('machine_qc_budget_authorization'),
        screener=_scripts_module('screen_target_language_audio_units'),
        predicted_schedule=_scripts_module('target_audio_predicted_schedule'),
        formal_renderer=_scripts_module('render_formal_target_language_speech'),
        voice_demos=_scripts_module('render_multilingual_voice_demos'),
        jobs=_scripts_module('sermon_workflow_jobs'))


def dual_pdf_unmoved():
    return dual_pdf_host.Unmoved(
        live_source_monitor=_scripts_module('live_source_monitor'),
        youtube_data_api=_scripts_module('youtube_data_api'),
        series_terminology=_scripts_module('series_terminology'),
        export_saturday_live_context=_scripts_module('export_saturday_live_context'),
        reading_edition=_scripts_module('build_sermon_reading_edition_with_openai'),
        sentence_shadow=_scripts_module('prepare_sentence_interpretation_shadow'),
        supervisor=_scripts_module('sermon_production_supervisor'),
        supervisor_agent=_scripts_module('run_sermon_production_supervisor_agent'),
        accounting=_scripts_module('sermon_accounting'),
        dubbing_producer_hook=_dubbing_producer_hook, upcoming_sunday=_upcoming_sunday)


# What a moved entry imported at its own load time, now reached through proxies that
# load on first use. Loaded at identity capture only when that entry is loaded, as
# importing the entry did before W3c, so the identity still covers the code it runs.
ENTRY_LOAD_TIME_IMPORTS = {
    'tongxing_production.workflows.dual_pdf.timeline': (
        'backend.cloud', 'backend.config', 'backend.observability',
        'scripts.sermon_accounting', 'scripts.live_source_monitor',
        'scripts.youtube_data_api'),
    'tongxing_production.workflows.dual_pdf.local_post_live_download': (
        'backend.cloud', 'backend.config', 'scripts.live_source_monitor', 'scripts.youtube_data_api'),
    'tongxing_production.observability.weekly_projection': (
        'scripts.sermon_accounting', 'scripts.sermon_clock_evidence',
        'scripts.sermon_cache_observation', 'scripts.sermon_local_model_observation',
        'scripts.sermon_workflow_evidence', 'scripts.sermon_decision_accounting'),
    'tongxing_production.workflows.dual_pdf.post_live': (
        'backend.cloud', 'backend.observability', 'scripts.live_source_monitor',
        'tongxing_production.workflows.dual_pdf.run_status', 'scripts.series_terminology', 'scripts.sermon_accounting'),
    # L3 A3: the renderer and the package builder imported these at load time.
    'tongxing_production.audio.renderer': (
        'scripts.render_multilingual_voice_demos', 'scripts.sermon_accounting', 'scripts.four_layer_measure',
        'scripts.ko_spoken_numerals'),
    'tongxing_production.audio.package': ('scripts.sermon_accounting',),
    # G1: the audio QC transport imported the waiver and the audio QC checks at load time.
    'tongxing_production.compute.qc_audio_transports': ('scripts.machine_quality_waiver', 'scripts.target_audio_auto_qc'),
    # L4 D2: the app release builder imported the waiver release basis at load time.
    'tongxing_production.delivery.app_release': ('scripts.machine_quality_release_basis',),
    'tongxing_production.workflows.dual_pdf.codex_local': (
        'backend.config', 'backend.cloud', 'scripts.live_source_monitor',
        'scripts.run_sermon_production_supervisor_agent', 'scripts.sermon_accounting',
        'scripts.sermon_production_supervisor'),
}


def _jobs_worker_command(root, job_id, lock_fd):
    # The job worker keeps running the scripts/ entry (its facade dispatches main()).
    return [sys.executable, str(ROOT / 'scripts/sermon_workflow_jobs.py'), 'worker', '--root', str(root),
            '--job-id', job_id, '--lock-fd', str(lock_fd)]


def _bounded_process(*arguments, **options):
    from scripts import sermon_execution_harness
    return sermon_execution_harness.bounded_process(*arguments, **options)


def _execution_terminated():
    from scripts.sermon_execution_harness import ExecutionTerminated
    return ExecutionTerminated


def jobs_host() -> jobs_host_module.JobsHost:
    return jobs_host_module.JobsHost(repo_root=ROOT, worker_command=_jobs_worker_command,
                                     bounded_process=_bounded_process, execution_terminated=_execution_terminated,
                                     liveness=_scripts_module('sermon_job_liveness'))


def load_producer_imports():
    import importlib
    for name in EAGER_PRODUCER_IMPORTS:
        importlib.import_module('scripts.' + name)
    # An entry's imports can load another entry (the codex-local supervisor imports post-live).
    pending = True
    while pending:
        pending = False
        for entry, names in ENTRY_LOAD_TIME_IMPORTS.items():
            if entry in sys.modules:
                for name in names:
                    if name not in sys.modules:
                        importlib.import_module(name)
                        pending = True


# The checkout's schemas/ directory is the only editable schema source.
contract_schemas.configure(ROOT / 'schemas')

# Each record is built once and shared by the layers that use it.
_core, _provider, _code, _snapshot = core(), provider(), code(), snapshot()
_compute, _resources_port, _terminology = compute(), resources(), terminology()
_measure, _workspace, _accounting = measure(), workspace(), accounting()
_schemas, _review, _diagnostic, _waivers = schemas(), review(), diagnostic(), waivers()
_plugins, _transports = plugins(), transports()

def _observation_code(module):
    return _module(module)().CODE


def _safe_observation(module, fields):
    return _module(module)().safe_observation(fields)


observability_backend.configure(observability_backend.ObservabilityBackend(
    checkout_root=ROOT, load_producer_imports=load_producer_imports,
    local_model_code=lambda: _observation_code('scripts.sermon_local_model_observation'),
    safe_local_model_observation=lambda fields: _safe_observation('scripts.sermon_local_model_observation', fields),
    decision_code=lambda: _observation_code('scripts.sermon_decision_accounting'),
    safe_decision_observation=lambda fields: _safe_observation('scripts.sermon_decision_accounting', fields)))
jobs_host_module.configure(jobs_host())
compute_backend.configure(compute_backend.ComputeBackend(accounting=_accounting, resources=_resources_port,
                                                         artifact_root=lambda: _core.artifact_root,
                                                         checkout_root=lambda: ROOT, unmoved=compute_unmoved()))
source_backend.configure(source_backend.SourceBackend(core=_core, provider=_provider, code=_code, mfa=mfa(),
                                                      snapshot=_snapshot, compute=_compute,
                                                      resources=_resources_port, adjudication=adjudication(),
                                                      terminology=_terminology, measure=_measure,
                                                      workspace=_workspace, accounting=_accounting, review=_review))
text_backend.configure(text_backend.TextBackend(core=_core, provider=_provider, code=_code, snapshot=_snapshot,
                                                compute=_compute, resources=_resources_port,
                                                terminology=_terminology, measure=_measure, accounting=_accounting,
                                                workspace=_workspace, plugins=_plugins, transports=_transports,
                                                schemas=_schemas, diagnostic=_diagnostic,
                                                worker_command=layer2_worker_command, unmoved=text_unmoved()))
delivery_backend.configure(delivery_backend.DeliveryBackend(core=_core, code=_code,
                                                            schemas=_schemas, workspace=_workspace, review=_review,
                                                            runtime_web=runtime_web(), hosting=hosting(),
                                                            waivers=_waivers,
                                                            worker_command=app_delivery_worker_command,
                                                            legacy=delivery_legacy(), unmoved=delivery_unmoved()))
audio_backend.configure(audio_backend.AudioBackend(core=_core, code=_code, compute=_compute, measure=_measure,
                                                   accounting=_accounting, schemas=_schemas, diagnostic=_diagnostic,
                                                   review=_review, waivers=_waivers, machine_qc=machine_qc(),
                                                   spoken_rules=spoken_rules(), tts_runtime=tts_runtime(),
                                                   dev_profile=dev_profile(), unmoved=audio_unmoved()))
review_backend.configure(review_backend.ReviewBackend(core=_core, code=_code, snapshot=_snapshot,
                                                      schemas=_schemas, provider=_provider, compute=_compute,
                                                      plugins=_plugins, transports=_transports, audio=audio_rules(),
                                                      text=text_rules(), source=source_evidence(),
                                                      gates=stage_gates(), scripture=scripture(),
                                                      qc_runtime=qc_runtime(), waivers=_waivers))
dual_pdf_host.configure(dual_pdf_host.DualPdfHost(cloud=cloud(), observability=observability(),
                                                  unmoved=dual_pdf_unmoved()))

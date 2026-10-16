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
                          http_execute=_http_execute, transcription_request=_transcription_request)


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
    return ports.Compute(session_bound_caller=SessionBoundCaller, require_session=_require_session)


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


def terminology() -> ports.Terminology:
    return ports.Terminology(context=_terminology_context)


def _producer_step(ledger_path, step_id, *, locale=None):
    from scripts import four_layer_measure
    return four_layer_measure.producer_step(ledger_path, step_id, locale=locale)


def measure() -> ports.Measure:
    return ports.Measure(producer_step=_producer_step)


def _ordered_bounded_map(items, worker, workers):
    from scripts import sermon_unified_source
    return sermon_unified_source.ordered_bounded_map(items, worker, workers)


def unmoved() -> source_backend.Unmoved:
    return source_backend.Unmoved(ordered_bounded_map=_ordered_bounded_map)


source_backend.configure(source_backend.SourceBackend(core=core(), provider=provider(), code=code(), mfa=mfa(),
                                                      contracts=contracts(), snapshot=snapshot(), compute=compute(),
                                                      resources=resources(), adjudication=adjudication(),
                                                      terminology=terminology(), measure=measure(),
                                                      unmoved=unmoved()))

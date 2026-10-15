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


def provider() -> ports.Provider:
    return ports.Provider(chat_json=_chat_json, request_json=_request_json,
                          reject_secret_override=_reject_secret_override,
                          bounded_legacy_chat_payload=_bounded_legacy_chat_payload,
                          legacy_text_cache_contract=_legacy_text_cache_contract,
                          legacy_text_execution_identity=_legacy_text_execution_identity)


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


source_backend.configure(source_backend.SourceBackend(core=core(), provider=provider(), code=code(), mfa=mfa()))

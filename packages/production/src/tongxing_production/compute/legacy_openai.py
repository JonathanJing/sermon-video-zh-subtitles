"""Legacy OpenAI chat and transcription transport for the dual_pdf and Layer 1 legacy callers.

Moved out of scripts/sermon_pipeline.py (workflows/compute C4) so the functions the
outcome receipts bind (``_chat_json`` for production-text-call, ``multipart_request``
for source-audio-api) live in a small file that changes only with this transport.
"""
import inspect
import json
import re
import time
import urllib.error
import urllib.request
import uuid

from tongxing_production.contracts.reasons import PRE_DISPATCH_REASONS
from scripts import production_spark_admission as spark_admission
from scripts.sermon_accounting import AccountingWriteError, _finalize, stage, record_api_attempt, record_api_started, request_metadata


TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
CHAT_URL = "https://api.openai.com/v1/chat/completions"


# Strict adapters may recognize only these unambiguous request rejections.
# Other HTTP errors (including 408/409/5xx) do not prove execution did not occur.
KNOWN_REQUEST_REJECTIONS = frozenset({400, 401, 429})


class TransportRejection(RuntimeError):
    """Typed, body-free evidence of a known HTTP request rejection."""
    def __init__(self, http_status, diagnostic=None):
        if type(http_status) is not int or http_status not in KNOWN_REQUEST_REJECTIONS:
            raise ValueError('invalid_transport_rejection_status')
        self.http_status = http_status
        from scripts import sermon_provider_error
        self.diagnostic = sermon_provider_error.validate(diagnostic) if diagnostic is not None else None
        if self.diagnostic is not None and self.diagnostic['httpStatus'] != http_status:
            raise ValueError('invalid_transport_rejection_diagnostic')
        super().__init__('http_request_rejected')


class PreDispatchRejection(ValueError):
    """A local guard refused this attempt before any transport dispatch.

    Existing callers catching ValueError remain compatible. No provider receipt,
    permit refund or reconciliation of a prior unknown call is implied.
    """
    def __init__(self, reason_code):
        if type(reason_code) is not str or reason_code not in PRE_DISPATCH_REASONS:
            raise ValueError('invalid_pre_dispatch_reason')
        self.reason_code = reason_code
        self._attempt_id = None
        super().__init__(reason_code)

    @property
    def attempt_id(self):
        return self._attempt_id

    def bind_attempt(self, attempt_id):
        """Bind only the local API start ID, never a provider response ID."""
        if (type(attempt_id) is not str or re.fullmatch(r'[a-f0-9]{32}', attempt_id) is None
                or self._attempt_id not in (None, attempt_id)):
            raise ValueError('invalid_pre_dispatch_attempt_binding')
        self._attempt_id = attempt_id



def _http_error_diagnostic(error):
    from scripts import sermon_provider_error as errors
    safe=getattr(error,'safe_diagnostic',None)
    if safe is not None:
        safe=errors.validate(safe)
        if safe['httpStatus'] != error.code:
            raise ValueError('invalid_provider_error_diagnostic')
        return safe
    raw=b''
    try:
        raw=error.read(errors.MAX_ERROR_BYTES+1)
    except (OSError,ValueError):
        pass
    finally:
        error.close()
    return errors.diagnostic(error.code,raw)


def request_json(req, retries=3, *, response_observer=None, request_executor=None):
    from scripts import api_cli_outcomes
    if api_cli_outcomes.admitted():
        retries = 1  # An uncertain legacy request must never retry inside its hold.
    from scripts.sermon_openai_runtime import bind_request
    bind_request(req)
    # Strict recovery is explicitly authorized by D5, never an HTTP retry loop.
    if response_observer is not None or request_executor is not None:
        retries = 1
    for attempt in range(retries):
        started = time.monotonic()
        attempt_id = record_api_started(getattr(req, "accounting_model", "unknown"), getattr(req, "accounting_settings", {}))
        try:
            if response_observer is not None and hasattr(response_observer, "request_started"):
                response_observer.request_started(attempt_id)
        except BaseException as exc:
            # A trusted guard can prove no dispatch; arbitrary observer failures
            # (including durable-write failures) carry no such proof. Never feed
            # an observer's HTTPError into provider rejection/retry handling.
            if isinstance(exc, PreDispatchRejection):
                exc.bind_attempt(attempt_id)
            reason = exc.reason_code if isinstance(exc, PreDispatchRejection) else None
            _finalize(lambda: record_api_attempt(getattr(req, "accounting_model", "unknown"), None,
                time.monotonic() - started, "failed", type(exc).__name__,
                attempt_id=attempt_id, not_dispatched_reason=reason), exc)
            raise
        try:
            if request_executor is not None:
                result = request_executor(req)
            else:
                with urllib.request.urlopen(req, timeout=300) as response:
                    raw_body = response.read()
                    if api_cli_outcomes.observing():
                        api_cli_outcomes.observed_response(raw_body, http_status=response.status)
                    result = json.loads(raw_body.decode())
        except PreDispatchRejection as exc:
            api_cli_outcomes.observed_no_dispatch(exc.reason_code)
            exc.bind_attempt(attempt_id)
            _finalize(lambda: record_api_attempt(getattr(req, "accounting_model", "unknown"), None,
                time.monotonic() - started, "failed", type(exc).__name__,
                attempt_id=attempt_id, not_dispatched_reason=exc.reason_code), exc)
            raise
        except urllib.error.HTTPError as exc:
            if api_cli_outcomes.observing():
                raw_error = exc.read()
                api_cli_outcomes.observed_response(raw_error, http_status=exc.code)
                from scripts import sermon_provider_error as provider_errors
                exc.safe_diagnostic = provider_errors.diagnostic(exc.code, raw_error)
            if response_observer is not None and exc.code in KNOWN_REQUEST_REJECTIONS:
                rejection = TransportRejection(exc.code, _http_error_diagnostic(exc))
                if hasattr(response_observer, "request_rejected"):
                    # Publish typed durable proof BEFORE finish telemetry. A failed
                    # observer write propagates and never permits another request.
                    try:
                        response_observer.request_rejected(rejection, attempt_id)
                    except BaseException as observer_error:
                        # HTTP status was observed, but durable rejection proof
                        # failed. Close telemetry without granting retry/settlement.
                        observer_error.sermon_logging_failed = True
                        _finalize(lambda: record_api_attempt(getattr(req, "accounting_model", "unknown"), None,
                            time.monotonic() - started, "failed", type(observer_error).__name__,
                            attempt_id=attempt_id, http_status=exc.code), observer_error)
                        raise
                _finalize(lambda: record_api_attempt(getattr(req, "accounting_model", "unknown"), None,
                    time.monotonic() - started, "failed", type(rejection).__name__,
                    attempt_id=attempt_id, http_status=exc.code), rejection)
                raise rejection from None
            _finalize(lambda: record_api_attempt(getattr(req, "accounting_model", "unknown"), None, time.monotonic() - started, "failed", type(exc).__name__, attempt_id=attempt_id, http_status=exc.code), exc)
            if getattr(exc, "sermon_logging_failed", False):
                raise
            if response_observer is not None:
                raise RuntimeError("strict_transport_http_outcome_unknown") from None
            diagnostic=_http_error_diagnostic(exc)
            if attempt == retries - 1 or exc.code < 500:
                raise RuntimeError(diagnostic['summary']) from None
        except urllib.error.URLError as exc:
            _finalize(lambda: record_api_attempt(getattr(req, "accounting_model", "unknown"), None, time.monotonic() - started, "failed", type(exc).__name__, attempt_id=attempt_id), exc)
            if getattr(exc, "sermon_logging_failed", False) or attempt == retries - 1:
                raise
        except BaseException as exc:
            _finalize(lambda: record_api_attempt(getattr(req, "accounting_model", "unknown"), None, time.monotonic() - started, "failed", type(exc).__name__, attempt_id=attempt_id), exc)
            raise
        else:
            # Receipt failure is not a network failure and must never repeat a
            # request whose successful response has already been received.
            elapsed = time.monotonic() - started
            if response_observer is not None:
                # Strict adapters persist the returned private response before a
                # telemetry finish failure can interrupt control flow. No retry.
                response_observer(result, attempt_id, elapsed)
            record_api_attempt(getattr(req, "accounting_model", "unknown"), result, elapsed, attempt_id=attempt_id, http_status=200)
            return result
        with stage("api.retry_backoff"):
            time.sleep(2**attempt)
    raise RuntimeError("Request failed")


def multipart_request(url, api_key, fields, file_field, file_path, retries=3):
    from scripts.sermon_openai_runtime import project_headers
    boundary = "----codex-" + uuid.uuid4().hex
    body = bytearray()

    def add_field(name, value):
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")

    for key, value in fields.items():
        if isinstance(value, list):
            for item in value:
                add_field(key, item)
        else:
            add_field(key, value)

    data = file_path.read_bytes()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
            "Content-Type: audio/mp4\r\n\r\n"
        ).encode()
    )
    body.extend(data)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            **project_headers(api_key),
        },
        method="POST",
    )
    req.accounting_model = fields.get("model", "unknown")
    req.accounting_settings = request_metadata(fields)
    return request_json(req, retries=retries)


def json_request(url, api_key, payload, retries=3, *, response_observer=None):
    from scripts.sermon_openai_runtime import project_headers
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **project_headers(api_key),
        },
        method="POST",
    )
    req.accounting_model = payload.get("model", "unknown")
    req.accounting_settings = request_metadata(payload)
    options = {"response_observer": response_observer} if response_observer is not None else {}
    return request_json(req, retries=retries, **options)


LEGACY_TEXT_CACHE_SCHEMA = "sermon-legacy-bounded-text-cache-v3"


def legacy_text_cache_contract():
    from scripts.sermon_provider_limits import DEFAULT_REQUEST_LIMITS, validate_request_limits, LEGACY_VISION_SCHEMA, LEGACY_MAX_IMAGE_BYTES, LEGACY_MAX_IMAGES
    return {"schemaVersion": LEGACY_TEXT_CACHE_SCHEMA,
            "requestLimits": validate_request_limits(DEFAULT_REQUEST_LIMITS),
            "visionBounds":{"schemaVersion":LEGACY_VISION_SCHEMA,"maxImageBytes":LEGACY_MAX_IMAGE_BYTES,
                            "maxImages":LEGACY_MAX_IMAGES,"textInputTokenAllowance":DEFAULT_REQUEST_LIMITS['maxInputTokens'],
                            "visionTokenCostBound":"not_claimed"}}


def bounded_legacy_chat_payload(payload):
    from scripts.sermon_provider_limits import bounded_legacy_payload
    limits = legacy_text_cache_contract()["requestLimits"]
    return bounded_legacy_payload(payload,limits)


def legacy_text_execution_identity(api_key,payload,*,caller=None,purpose=None):
    """Bind derived caches to the exact bounded caller and its outcome scope."""
    from scripts import api_cli_outcomes as outcomes
    payload=bounded_legacy_chat_payload(payload)
    directory=None
    if isinstance(caller,spark_admission.SessionBoundCaller):
        directory=caller.outcome_directory
        purpose=purpose or caller.purpose
        target=caller.caller
        kwargs={}
    elif caller is None or caller is chat_json:
        target=_chat_json;purpose=purpose or 'production-text-call';kwargs={'retries':1}
    else:
        target=caller;purpose=purpose or 'production-text-call';kwargs={}
    arguments=inspect.signature(target).bind(api_key,payload,**kwargs)
    arguments.apply_defaults()
    binding=outcomes.execution_binding(target,arguments.arguments)
    try:root=outcomes.receipt_root(directory)
    except ValueError as error:
        if str(error)!='api_cli_outcome_directory_required_before_dispatch':raise
    else:outcomes.assert_replay_admitted(directory,purpose=purpose,binding=binding)
    return {'schemaVersion':'sermon-legacy-text-execution-v1',
            'outcomeRequestSha256':outcomes.request_identity(target,(api_key,payload),kwargs,purpose),
            'executionBinding':binding}


def chat_json(api_key, payload, retries=1, *, session_verifier=None):
    payload = bounded_legacy_chat_payload(payload)
    return spark_admission.SessionBoundCaller(_chat_json, verifier=session_verifier,
        purpose="production-text-call", requires_spark=False)(api_key, payload, retries=retries)


def _chat_json(api_key, payload, retries=1):
    from scripts import api_cli_outcomes
    if api_cli_outcomes.admitted():
        retries = 1
    from scripts.sermon_provider_limits import DEFAULT_REQUEST_LIMITS
    from scripts.strict_budget_capability import require_bounded_api_payload
    from scripts.sermon_provider_limits import bounded_legacy_payload
    try:validated=bounded_legacy_payload(payload,DEFAULT_REQUEST_LIMITS)
    except (ValueError,TypeError) as error:raise ValueError('unsupported_budget_capability') from error
    if validated!=payload:raise ValueError('unsupported_budget_capability')
    # The canonical budget-capability contract stays text/json_object only.
    if payload['response_format']=={'type':'json_object'} and all(isinstance(row['content'],str) for row in payload['messages']):
        require_bounded_api_payload(payload, DEFAULT_REQUEST_LIMITS, surface="legacy_text_api")
    last_error = None
    for attempt in range(retries):
        try:
            return json_request(CHAT_URL, api_key, payload, retries=1)
        except Exception as exc:
            if isinstance(exc, AccountingWriteError) or getattr(exc, "sermon_logging_failed", False):
                raise
            last_error = exc
            if "temperature" in str(exc) and "temperature" in payload:
                payload = {key: value for key, value in payload.items() if key != "temperature"}
            with stage("chat.retry_backoff"):
                time.sleep(2**attempt)
    raise last_error

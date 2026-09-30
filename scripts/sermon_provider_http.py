"""Single-request, wall-time-bounded stdlib provider transport.

``execute(Request, timeout_seconds) -> dict`` is an injectable pipeline executor,
not a retry policy. The trusted caller constructs the POST and authorization.
Only two exact OpenAI endpoints are permitted. Credentials and media travel over
private subprocess stdin, never argv, inherited environment, files or logs.
The isolated worker disables proxies/redirects and uses normal verified TLS.
Its stdout is a bounded private result pipe; stderr is discarded.

A timeout kills and reaps the worker but cannot cancel a remote provider request:
its outcome remains unknown. HTTP errors preserve only their numeric status for
the pipeline's existing rejection policy. No HTTP response body reaches errors.
This module neither loads credentials nor grants budget/execution authority.
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path
import re
import ssl
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

MAX_REQUEST_BYTES = 25 * 1024 * 1024
MAX_RESPONSE_BYTES = 200 * 1024
MAX_HEADER_BYTES = 16 * 1024
MAX_RESULT_BYTES = MAX_RESPONSE_BYTES + 4096
ENDPOINTS = frozenset({
    'https://api.openai.com/v1/chat/completions',
    'https://api.openai.com/v1/audio/transcriptions',
})
_HEADERS = frozenset({'authorization', 'content-type', 'openai-project', 'openai-organization'})


class ProviderTimeout(TimeoutError):
    """The local worker deadline elapsed; remote execution is unknown."""


class ProviderOutcomeUnknown(RuntimeError):
    """No usable, bounded provider result or known HTTP status was observed."""


def _require(value, code):
    if not value:
        raise ValueError(code)


def _timeout(value):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 86400,
             'invalid_provider_timeout')
    return float(value)


def _metadata(url, headers, body_length, timeout_seconds):
    _require(type(url) is str and url in ENDPOINTS, 'provider_endpoint_not_allowed')
    _require(type(body_length) is int and 0 < body_length <= MAX_REQUEST_BYTES,
             'provider_request_size_limit')
    _require(type(headers) is dict and {'authorization', 'content-type'} <= set(headers)
             and set(headers) <= _HEADERS, 'provider_headers_not_allowed')
    for key, value in headers.items():
        _require(type(value) is str and 0 < len(value) <= 4096 and
                 all(32 <= ord(char) <= 126 for char in value), 'invalid_provider_header')
    _require(re.fullmatch(r'Bearer [A-Za-z0-9._~-]+', headers['authorization']) is not None,
             'invalid_provider_authorization')
    content_type = headers['content-type']
    if url.endswith('/chat/completions'):
        _require(content_type == 'application/json', 'invalid_provider_content_type')
    else:
        _require(re.fullmatch(r'multipart/form-data; boundary=[A-Za-z0-9_-]{1,200}', content_type)
                 is not None, 'invalid_provider_content_type')
    for key in ('openai-project', 'openai-organization'):
        if key in headers:
            _require(re.fullmatch(r'[A-Za-z0-9_-]{1,200}', headers[key]) is not None,
                     'invalid_provider_routing_header')
    return {'url': url, 'headers': headers, 'bodyLength': body_length,
            'timeoutSeconds': _timeout(timeout_seconds)}


def _encode_request(req, timeout_seconds):
    _require(isinstance(req, urllib.request.Request) and req.get_method() == 'POST',
             'provider_requires_post_request')
    _require(type(req.data) is bytes, 'provider_requires_bytes_body')
    headers = {}
    for name, value in req.header_items():
        name = name.lower()
        _require(name not in headers, 'duplicate_provider_header')
        headers[name] = value
    metadata = _metadata(req.full_url, headers, len(req.data), timeout_seconds)
    encoded = json.dumps(metadata, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    _require(len(encoded) <= MAX_HEADER_BYTES, 'provider_header_size_limit')
    return struct.pack('!I', len(encoded)) + encoded + req.data


def _strict_json(raw):
    def invalid_constant(_):
        raise ValueError('invalid_provider_json')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, 'duplicate_provider_json_key')
            result[key] = value
        return result
    value = json.loads(raw, parse_constant=invalid_constant, object_pairs_hook=unique)
    _require(type(value) is dict, 'provider_requires_json_object')
    return value


def execute(req, timeout_seconds):
    """Perform at most one request, returning its parsed JSON object.

    All validation happens before spawning. HTTPError carries an empty body and
    no response headers. Other worker failures are deliberately unknown, never
    evidence of a safe retry. This function itself performs no retry.
    """
    timeout_seconds = _timeout(timeout_seconds)
    packet = _encode_request(req, timeout_seconds)
    deadline = time.monotonic() + timeout_seconds
    command = [sys.executable, '-I', str(Path(__file__).resolve()), '--worker']
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env={}, close_fds=True)
    except Exception:
        raise ProviderOutcomeUnknown('provider_worker_start_failed') from None
    try:
        output, _ = process.communicate(packet, timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _kill_and_reap(process)
        raise ProviderTimeout('provider_wall_timeout_outcome_unknown') from None
    except BaseException:
        _kill_and_reap(process)
        raise ProviderOutcomeUnknown('provider_worker_outcome_unknown') from None
    if process.returncode != 0 or len(output) > MAX_RESULT_BYTES:
        raise ProviderOutcomeUnknown('provider_worker_result_invalid') from None
    try:
        envelope = _strict_json(output)
        if set(envelope) == {'status', 'response'} and envelope['status'] == 'ok':
            _require(type(envelope['response']) is dict, 'invalid_provider_response')
            return envelope['response']
        if set(envelope) == {'status', 'httpStatus'} and envelope['status'] == 'http_error':
            code = envelope['httpStatus']
            _require(type(code) is int and 300 <= code <= 599, 'invalid_provider_http_status')
        else:
            raise ValueError('provider_outcome_unknown')
    except (ValueError, TypeError, RecursionError):
        raise ProviderOutcomeUnknown('provider_worker_outcome_unknown') from None
    raise urllib.error.HTTPError(req.full_url, code, 'provider_http_error', {}, io.BytesIO(b'')) from None


def _kill_and_reap(process):
    try:
        process.kill()
    except ProcessLookupError:
        pass
    # The worker creates no children. communicate also drains/closes both pipes.
    process.communicate()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def _read_exact(stream, size):
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        _require(bool(chunk), 'incomplete_provider_packet')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _read_packet(stream):
    size = struct.unpack('!I', _read_exact(stream, 4))[0]
    _require(0 < size <= MAX_HEADER_BYTES, 'provider_header_size_limit')
    metadata = _strict_json(_read_exact(stream, size))
    _require(set(metadata) == {'url', 'headers', 'bodyLength', 'timeoutSeconds'}, 'invalid_provider_packet')
    metadata = _metadata(metadata['url'], metadata['headers'], metadata['bodyLength'], metadata['timeoutSeconds'])
    body = _read_exact(stream, metadata['bodyLength'])
    _require(stream.read(1) == b'', 'provider_packet_trailing_data')
    return metadata, body


def _perform(metadata, body, opener):
    request = urllib.request.Request(metadata['url'], data=body, headers=metadata['headers'], method='POST')
    try:
        with opener.open(request, timeout=metadata['timeoutSeconds']) as response:
            _require(response.geturl() == metadata['url'], 'provider_redirect_rejected')
            _require(type(response.status) is int and 200 <= response.status < 300,
                     'invalid_provider_success_status')
            content_length = response.headers.get('Content-Length')
            if content_length is not None:
                _require(content_length.isdecimal() and int(content_length) <= MAX_RESPONSE_BYTES,
                         'provider_response_size_limit')
            content_encoding = response.headers.get('Content-Encoding', 'identity')
            _require(content_encoding.lower() == 'identity', 'provider_response_encoding_not_allowed')
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            _require(len(raw) <= MAX_RESPONSE_BYTES, 'provider_response_size_limit')
            result = _strict_json(raw.decode('utf-8'))
            return {'status': 'ok', 'response': result}
    except urllib.error.HTTPError as error:
        # Never read/log/return body, headers, reason text or redirect Location.
        code = error.code
        error.close()
        _require(type(code) is int and 300 <= code <= 599, 'invalid_provider_http_status')
        return {'status': 'http_error', 'httpStatus': code}


def _worker(stdin, stdout, *, opener=None):
    """Private stream seam for offline tests; production uses a fixed opener."""
    try:
        metadata, body = _read_packet(stdin)
        result = _perform(metadata, body, _opener() if opener is None else opener)
        output = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        _require(len(output) <= MAX_RESULT_BYTES, 'provider_result_size_limit')
    except Exception:
        output = b'{"status":"outcome_unknown"}'
    stdout.write(output)
    stdout.flush()


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit(2)
    try:
        _worker(sys.stdin.buffer, sys.stdout.buffer)
    except BaseException:
        # No tracebacks: exceptions can contain private request/response values.
        raise SystemExit(1) from None

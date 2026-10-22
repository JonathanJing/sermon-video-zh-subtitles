"""Single-attempt DeepSeek official API transport for Layer 2 language calls.

The DeepSeek API is OpenAI-compatible: one JSON request returns the standard
``choices[0].message.content`` and ``usage`` envelope. No API fallback, retry,
tool call or key fallback is attempted here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import urllib.request

SCHEMA = 'deepseek-layer2-transport-identity-v1'
DEFAULT_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-flash'
DEFAULT_TIMEOUT_SECONDS = 300


class DeepSeekLayer2Transport:
    billing = 'api'

    def __init__(self, *, model: str = DEFAULT_MODEL, effort: str = 'high',
                 base_url: str | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        if model != DEFAULT_MODEL:
            raise ValueError('unsupported_deepseek_language_model')
        if effort not in ('low', 'high', 'max'):
            raise ValueError('unsupported_deepseek_language_effort')
        if timeout_seconds <= 0:
            raise ValueError('invalid_deepseek_language_timeout')
        key = os.environ.get('DEEPSEEK_API_KEY', '')
        if not key:
            raise ValueError('deepseek_layer2_requires_DEEPSEEK_API_KEY')
        self.key = key
        self.model = model
        self.effort = effort
        self.base_url = (base_url or os.environ.get('DEEPSEEK_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')
        self.timeout_seconds = timeout_seconds
        self.execution_identity = {
            'schemaVersion': SCHEMA,
            'backend': 'deepseek_api',
            'provider': 'deepseek',
            'authMode': 'api_key',
            'baseUrl': self.base_url,
            'model': model,
            'reasoningEffort': effort,
            'timeoutSeconds': timeout_seconds,
            'adapterSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }

    def __call__(self, api_key, payload):
        if api_key:
            raise ValueError('deepseek_language_must_not_receive_api_key')
        if payload.get('model') != self.model or payload.get('reasoning_effort') != self.effort:
            raise ValueError('deepseek_payload_model_or_effort_changed')
        url = self.base_url + '/chat/completions'
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read()
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError('deepseek_response_is_not_an_object')
        return value

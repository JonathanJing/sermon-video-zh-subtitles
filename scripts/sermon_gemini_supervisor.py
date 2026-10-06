"""Read-only Gemini API transport for diagnostic supervisor snapshots.

One immutable request per output directory. Unknown provider outcomes are never
retried automatically, and only a successful parsed response releases its slot.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import uuid

import jsonschema

from scripts.sermon_unified import resources
from scripts.sermon_execution_harness import atomic_json

MODEL = 'gemini-3.8-flash'
ENDPOINT = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent'


def _key():
    value = os.environ.get('GOOGLE_API_KEY', '').strip()
    if value:
        return value
    path = Path(__file__).resolve().parents[1] / '.env'
    if path.is_file():
        for line in path.read_text().splitlines():
            if line.startswith('GOOGLE_API_KEY='):
                value = line.split('=', 1)[1].strip().strip('"\'')
                if value:
                    return value
    raise ValueError('gemini_api_key_missing')


def call_json(prompt, *, model=MODEL, reasoning='low', service_tier=None,
              output_schema=None, output_dir=None, timeout_seconds=60,
              resource_policy=None, concurrency_profile=None, resource_class='supervisor'):
    if (model != MODEL or reasoning not in {'low', 'medium', 'high'}
            or resource_class != 'supervisor' or service_tier is not None
            or not isinstance(prompt, str) or not prompt.strip()
            or output_dir is None or timeout_seconds <= 0):
        raise ValueError('unsupported_gemini_supervisor_configuration')
    if (resource_policy is None) != (concurrency_profile is None):
        raise ValueError('gemini_profile_and_resource_policy_required_together')
    if output_schema is not None:
        jsonschema.Draft202012Validator.check_schema(output_schema)
    key = _key()  # pre-dispatch validation; never persisted
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = directory / 'started.json'
    if started.exists():
        raise RuntimeError('gemini_supervisor_outcome_requires_reconciliation')
    owner = {'role': 'diagnostic_supervisor', 'callId': uuid.uuid4().hex}
    operation_id = 'gemini-supervisor-' + owner['callId']
    if resource_policy is not None:
        resources.validate_policy(resource_policy)
        deadline = time.monotonic() + 180
        while not resources.reserve(resource_policy, operation_id=operation_id,
                                    owner=owner, resource='online_api'):
            if time.monotonic() >= deadline:
                raise RuntimeError('gemini_supervisor_api_capacity_busy')
            time.sleep(.1)
    payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
               'generationConfig': {'thinkingConfig': {'thinkingLevel': reasoning.upper()},
                                    'responseMimeType': 'application/json', 'maxOutputTokens': 1024}}
    if output_schema is not None:
        payload['generationConfig']['responseJsonSchema'] = output_schema
    identity = {'schemaVersion': 'sermon-gemini-supervisor-call-v1', 'provider': 'google',
                'backend': 'gemini_api', 'role': 'supervisor', 'requestedModel': model,
                'reasoning': reasoning, 'promptSha256': hashlib.sha256(prompt.encode()).hexdigest(),
                'operationId': operation_id, 'owner': owner, 'timeoutSeconds': timeout_seconds}
    atomic_json(started, identity)
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'x-goog-api-key': key},
                                     method='POST')
    begin = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = json.load(response)
    elapsed = time.monotonic() - begin
    atomic_json(directory / 'provider-response.json', raw)
    candidates = raw.get('candidates') or []
    if len(candidates) != 1 or candidates[0].get('finishReason') != 'STOP':
        raise RuntimeError('gemini_supervisor_incomplete_response')
    output = json.loads(''.join(part.get('text', '') for part in candidates[0]['content']['parts']))
    if output_schema is not None:
        jsonschema.validate(output, output_schema)
    usage = raw.get('usageMetadata', {})
    receipt = {'schemaVersion': 'sermon-gemini-supervisor-result-v1', 'identity': identity,
               'elapsedSeconds': elapsed, 'timingScope': 'complete_request',
               'usageSource': 'provider_reported',
               'inputTokens': usage.get('promptTokenCount'),
               'outputTokens': usage.get('candidatesTokenCount'),
               'thinkingTokens': usage.get('thoughtsTokenCount'),
               'totalTokens': usage.get('totalTokenCount'),
               'requestOutputTokensPerSecond':
                   (usage['candidatesTokenCount'] / elapsed if elapsed > 0 and usage.get('candidatesTokenCount') is not None else None),
               'result': output}
    atomic_json(directory / 'result.json', receipt)
    if resource_policy is not None:
        resources.release(resource_policy, operation_id=operation_id, owner=owner)
    return output

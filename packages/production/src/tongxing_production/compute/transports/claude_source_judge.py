"""Claude subscription-authenticated CLI transport for the Layer 1 English source judge.

The judge's strict output schema travels in the request payload. This module
reuses the Layer 2 Claude CLI contract (subscription login only, no tools, no
API key, no retry) without touching the Layer 2 adapter, whose file hash is part
of frozen Layer 2 cache identities.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import jsonschema
from ...observability import model_call_observation as observation
from .codex_layer2 import _hash, _write, _write_bytes
from .claude_layer2 import GUARD, SCHEMA, ClaudeLayer2Transport, chat_envelope, normalize_usage

ROLE = 'source_judge'


def payload_schema(payload):
    """The strict JSON schema the judge payload requires its answer to follow."""
    response_format = payload.get('response_format')
    spec = response_format.get('json_schema') if isinstance(response_format, dict) else None
    if (not isinstance(spec, dict) or response_format.get('type') != 'json_schema'
            or spec.get('strict') is not True or not isinstance(spec.get('schema'), dict)):
        raise ValueError('claude_source_judge_requires_strict_json_schema')
    jsonschema.Draft202012Validator.check_schema(spec['schema'])
    return spec['schema']


class ClaudeSourceJudgeTransport(ClaudeLayer2Transport):
    def __init__(self, cli_path=None, *, model='claude-opus-5-5', effort='high',
                 timeout_seconds=300, receipts_dir=None):
        super().__init__(cli_path, model=model, effort=effort, timeout_seconds=timeout_seconds,
                         receipts_dir=receipts_dir)
        identity = dict(self.execution_identity)
        identity.pop('outputSchemaSha256')
        self.execution_identity = dict(
            identity, schemaVersion='claude-source-judge-transport-identity-v1', role=ROLE,
            promptAdapterVersion='source-judge-no-tools-v1', outputSchemaSource='payload.response_format',
            adapterSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            layer2AdapterSha256=identity['adapterSha256'])

    def __call__(self, api_key, payload):
        if api_key:
            raise ValueError('claude_language_must_not_receive_api_key')
        if payload.get('model') != self.model or payload.get('reasoning_effort') != self.effort:
            raise ValueError('claude_source_judge_payload_identity_mismatch')
        schema = payload_schema(payload)
        output_cap = payload.get('max_completion_tokens')
        if type(output_cap) is not int or output_cap <= 0:
            raise ValueError('claude_language_output_cap_required')
        call_env = {**self.env, 'CLAUDE_CODE_MAX_OUTPUT_TOKENS': str(output_cap),
                    'CLAUDE_CODE_MAX_RETRIES': '0', 'MAX_STRUCTURED_OUTPUT_RETRIES': '1'}
        messages = payload['messages']
        if len(messages) != 2 or [row['role'] for row in messages] != ['system', 'user']:
            raise ValueError('invalid_claude_language_prompt')
        command = [str(self.cli_path), '-p', '--model', self.model, '--effort', self.effort,
                   '--output-format', 'json', '--json-schema', json.dumps(schema, separators=(',', ':')),
                   '--system-prompt', GUARD + messages[0]['content'], '--tools', '', '--no-session-persistence',
                   '--setting-sources', '', '--strict-mcp-config', '--disable-slash-commands']
        call_id = uuid.uuid4().hex
        call_directory = None
        if self.receipts_dir is not None:
            call_directory = self.receipts_dir / (ROLE + '-' + call_id)
            call_directory.mkdir(parents=True, mode=0o700)
            _write(call_directory / 'command.json', command)
            _write(call_directory / 'limits.json', {key: call_env[key] for key in
                ('CLAUDE_CODE_MAX_OUTPUT_TOKENS', 'CLAUDE_CODE_MAX_RETRIES', 'MAX_STRUCTURED_OUTPUT_RETRIES')})
        with observation.invocation(self.model, backend='agent_session', provider='claude',
                                    role='production', timing_scope='agent_session_including_tools',
                                    usage_source='host_telemetry', call_id=call_id) as receipt:
            started = time.monotonic()
            with tempfile.TemporaryDirectory(prefix='tongxing-claude-source-judge-') as work:
                try:
                    process = subprocess.run(command, input=messages[1]['content'], env=call_env, cwd=work,
                                             capture_output=True, text=True, timeout=self.timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    if call_directory is not None:
                        _write(call_directory / 'failure.json', {'status': 'unknown_outcome',
                               'errorType': 'TimeoutExpired', 'requestedModel': self.model})
                        for name, value in [('stdout', exc.stdout), ('stderr', exc.stderr)]:
                            _write_bytes(call_directory / name, value.encode() if isinstance(value, str) else value or b'')
                    raise
            elapsed = time.monotonic() - started
            if call_directory is not None:
                for name, value in [('result.json', process.stdout), ('stderr.txt', process.stderr)]:
                    _write_bytes(call_directory / name, value.encode())
            try:
                result = json.loads(process.stdout)
            except json.JSONDecodeError:
                raise RuntimeError('claude_language_unreadable_result_inspect_receipt') from None
            usage = normalize_usage(result.get('usage'))
            receipt['usage'] = usage
            model_usage = result.get('modelUsage') or {}
            content = result.get('structured_output')
            if process.returncode or result.get('is_error') is not False or result.get('subtype') != 'success' \
                    or result.get('permission_denials') or content is None:
                raise RuntimeError('claude_language_terminal_failure_inspect_receipt')
            # The CLI counts its own structured-output repair turn: with
            # MAX_STRUCTURED_OUTPUT_RETRIES=1 one schema violation adds a turn,
            # so a valid answer can report 3. Observed 2026-10-21 (1 batch in
            # 109): turns=3, is_error=false, schema-valid structured output.
            # No tools are allowed and the answer is still schema-validated,
            # so this only tolerates the documented repair turn.
            if type(result.get('num_turns')) is not int or not 1 <= result['num_turns'] <= 3:
                raise RuntimeError('claude_language_unexpected_turn_count')
            if set(model_usage) != {self.model}:
                raise RuntimeError('claude_language_model_identity_missing')
            jsonschema.validate(content, schema)
            response = {'schemaVersion': SCHEMA, 'id': 'claude:' + str(result.get('session_id')),
                        'sessionId': result.get('session_id'), 'requestedModel': self.model,
                        'reportedModels': sorted(model_usage), 'requestedEffort': self.effort,
                        'serviceTier': (result.get('usage') or {}).get('service_tier'),
                        'completed': True, 'exitCode': process.returncode,
                        'content': json.dumps(content, ensure_ascii=False), 'usage': usage,
                        'rawUsage': result.get('usage'), 'modelUsage': model_usage,
                        'listPriceUsd': result.get('total_cost_usd'), 'numTurns': result.get('num_turns'),
                        'elapsedSeconds': elapsed, 'apiDurationMs': result.get('duration_api_ms'),
                        'enabledTools': []}
            if call_directory is not None:
                _write(call_directory / 'response.json', response)
        envelope = chat_envelope(response, self.model)
        envelope['claudeCli']['executionIdentity'] = self.execution_identity
        return envelope

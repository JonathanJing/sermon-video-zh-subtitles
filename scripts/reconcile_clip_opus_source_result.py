#!/usr/bin/env python3
"""Admit one known-terminal Opus source result after a local adapter rejection.

Reads the original CLI result and L1 started marker. It never invokes Claude.
The result must match the marker's model, prompt, schema and sentence IDs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import judge_english_source_for_translation as judge
from scripts.claude_layer2_transport import GUARD, SCHEMA, chat_envelope, normalize_usage
from scripts.english_source_judge_cache import reconcile_returned_response, _atomic
from scripts.sermon_sentence_interpretation import json_sha256


def recover(marker_path: Path, cli_directory: Path) -> Path:
    marker_path, cli_directory = marker_path.resolve(), cli_directory.resolve()
    marker = json.loads(marker_path.read_text())
    request = marker['request']
    if (marker['requestSha256'] != json_sha256(request)
            or not request.get('stage', '').startswith('english-source-judge-')):
        raise ValueError('L1 started marker identity changed')
    payload = request['payload']
    model = payload['model']
    if model != 'claude-opus-5-5' or payload['reasoning_effort'] != 'high':
        raise ValueError('L1 started marker names another model')
    command = json.loads((cli_directory / 'command.json').read_text())
    flag = lambda name: command[command.index(name) + 1]
    if (flag('--model') != model or flag('--effort') != 'high'
            or json.loads(flag('--json-schema')) != judge._response_schema()
            or flag('--system-prompt') != GUARD + payload['messages'][0]['content']
            or flag('--tools') != '' or '--no-session-persistence' not in command):
        raise ValueError('Opus CLI command differs from the started judge request')
    limits = json.loads((cli_directory / 'limits.json').read_text())
    if limits != {'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '7000', 'CLAUDE_CODE_MAX_RETRIES': '0',
                  'MAX_STRUCTURED_OUTPUT_RETRIES': '1'}:
        raise ValueError('Opus CLI limits differ from the source judge')
    raw_path = cli_directory / 'result.json'
    raw = json.loads(raw_path.read_text())
    if (raw.get('is_error') is not False or raw.get('subtype') != 'success'
            or raw.get('permission_denials') or set(raw.get('modelUsage') or {}) != {model}
            or type(raw.get('num_turns')) is not int or not 1 <= raw['num_turns'] <= 3
            or not isinstance(raw.get('total_cost_usd'), (int, float))
            or raw['total_cost_usd'] < 0 or not raw.get('session_id')):
        raise ValueError('Opus CLI result is not a known-terminal source result')
    content = raw.get('structured_output')
    jsonschema.validate(content, judge._response_schema())
    expected = json.loads(payload['messages'][1]['content'])['sentences']
    judge._checked_batch(content, expected)
    usage = normalize_usage(raw.get('usage'))
    if type(usage['inputTokens']) is not int or type(usage['outputTokens']) is not int:
        raise ValueError('Opus CLI usage is missing')
    response = {'schemaVersion': SCHEMA, 'id': 'claude:' + raw['session_id'],
                'sessionId': raw['session_id'], 'requestedModel': model,
                'reportedModels': [model], 'requestedEffort': 'high', 'completed': True,
                'content': json.dumps(content, ensure_ascii=False), 'usage': usage,
                'rawUsage': raw['usage'], 'modelUsage': raw['modelUsage'],
                'listPriceUsd': raw['total_cost_usd'], 'numTurns': raw['num_turns'],
                'apiDurationMs': raw.get('duration_api_ms'), 'enabledTools': []}
    saved = cli_directory / 'response.json'
    if saved.exists() and json.loads(saved.read_text()) != response:
        raise ValueError('Existing normalized Opus response differs')
    if not saved.exists():
        _atomic(saved, response)
    envelope = chat_envelope(response, model)
    envelope['created'] = int(raw_path.stat().st_mtime)
    return reconcile_returned_response(marker_path=marker_path, response=envelope,
                                       expected_request_sha256=marker['requestSha256'],
                                       requested_model=model)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--started-marker', required=True, type=Path)
    parser.add_argument('--cli-directory', required=True, type=Path)
    args = parser.parse_args()
    print(recover(args.started_marker, args.cli_directory))

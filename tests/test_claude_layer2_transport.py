"""Claude CLI candidate transport: subscription login only, validated structured output."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts.claude_layer2_transport import ClaudeLayer2Transport, child_environment, normalize_usage

SOURCE = {'translationGroupId': 'g001', 'sourceUnitIds': ['u1']}
CONTENT = {'translationGroupId': 'g001', 'sourceUnitIds': ['u1'], 'targetUtterances': ['你好。'],
           'coverage': [{'sourceUnitId': 'u1', 'targetText': '你好。'}]}
PAYLOAD = {'max_completion_tokens': 4096, 'messages': [{'role': 'system', 'content': 'Translate.'},
                        {'role': 'user', 'content': json.dumps(SOURCE)}]}

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
state = json.loads(open(os.environ['FAKE_CLAUDE_STATE']).read())
if args[:2] == ['auth', 'status']:
    print(json.dumps(state['auth'])); sys.exit(0)
if args == ['--version']:
    print('9.9.9 (Claude Code)'); sys.exit(0)
with open(os.environ['FAKE_CLAUDE_LOG'], 'a') as log:
    log.write(json.dumps({'args': args, 'stdin': sys.stdin.read(),
                          'apiKey': os.environ.get('ANTHROPIC_API_KEY'),
                          'caps': {k: os.environ.get(k) for k in ['CLAUDE_CODE_MAX_OUTPUT_TOKENS', 'CLAUDE_CODE_MAX_RETRIES', 'MAX_STRUCTURED_OUTPUT_RETRIES']}}) + '\n')
print(json.dumps(state['result'])); sys.exit(state.get('exit', 0))
'''


def result(**overrides):
    value = {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's-1',
             'num_turns': 2, 'total_cost_usd': 0.05, 'permission_denials': [], 'duration_api_ms': 1200,
             'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 900, 'cache_read_input_tokens': 100,
                       'output_tokens': 300, 'output_tokens_details': {'thinking_tokens': 120},
                       'service_tier': 'standard'},
             'modelUsage': {'claude-opus-5-5': {'inputTokens': 10, 'outputTokens': 300}},
             'structured_output': CONTENT}
    value.update(overrides)
    return value


class ClaudeTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cli = self.root / 'claude'
        self.cli.write_text(FAKE)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IEXEC)
        self.state = self.root / 'state.json'
        self.log = self.root / 'log.jsonl'
        self.set_state(result())
        patcher = patch.dict(os.environ, {'FAKE_CLAUDE_STATE': str(self.state), 'FAKE_CLAUDE_LOG': str(self.log),
                                          'ANTHROPIC_API_KEY': 'sk-must-not-leak'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_state(self, value, auth=None, exit_code=0):
        self.state.write_text(json.dumps({'auth': auth or {'loggedIn': True, 'authMethod': 'claude.ai',
                                                            'apiProvider': 'firstParty'},
                                          'result': value, 'exit': exit_code}))

    def transport(self):
        return ClaudeLayer2Transport(self.cli, receipts_dir=self.root / 'calls')

    def test_successful_call_returns_validated_content_and_strips_api_key(self):
        response = self.transport()('', PAYLOAD)
        self.assertEqual(json.loads(response['content']), CONTENT)
        self.assertEqual(response['requestedModel'], 'claude-opus-5-5')
        self.assertEqual(response['usage']['inputTokens'], 1010)
        self.assertEqual(response['usage']['cachedInputTokens'], 100)
        self.assertEqual(response['usage']['reasoningTokens'], 120)
        call = json.loads(self.log.read_text().splitlines()[0])
        self.assertIsNone(call['apiKey'])
        self.assertEqual(call['caps'], {'CLAUDE_CODE_MAX_OUTPUT_TOKENS': '4096',
            'CLAUDE_CODE_MAX_RETRIES': '0', 'MAX_STRUCTURED_OUTPUT_RETRIES': '1'})
        self.assertEqual(call['stdin'], json.dumps(SOURCE))
        self.assertIn('--json-schema', call['args'])
        self.assertEqual(call['args'][call['args'].index('--tools') + 1], '')
        self.assertTrue(call['args'][call['args'].index('--system-prompt') + 1].endswith('Translate.'))
        self.assertEqual(len(list((self.root / 'calls').glob('*/response.json'))), 1)

    def test_api_key_login_is_rejected_before_any_call(self):
        self.set_state(result(), auth={'loggedIn': True, 'authMethod': 'api_key', 'apiProvider': 'firstParty'})
        with self.assertRaisesRegex(ValueError, 'subscription'):
            self.transport()
        self.assertFalse(self.log.exists())

    def test_caller_api_key_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'api_key'):
            self.transport()('sk-x', PAYLOAD)

    def test_missing_model_identity_fails(self):
        self.set_state(result(modelUsage={'claude-haiku-5-5': {}}))
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            self.transport()('', PAYLOAD)

    def test_fallback_model_is_rejected(self):
        self.set_state(result(modelUsage={'claude-opus-5-5': {}, 'claude-opus-5': {}}))
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            self.transport()('', PAYLOAD)

    def test_missing_output_cap_is_rejected_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'output_cap_required'):
            self.transport()('', {'messages': PAYLOAD['messages']})
        self.assertFalse(self.log.exists())

    def test_error_or_schema_violation_fails(self):
        for value in (result(is_error=True), result(structured_output=None),
                      result(structured_output={'translationGroupId': 'g001'})):
            with self.subTest(value=value):
                self.set_state(value)
                with self.assertRaises(Exception):
                    self.transport()('', PAYLOAD)

    def test_unsupported_model_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'configuration'):
            ClaudeLayer2Transport(self.cli, model='claude-fable-5-1')


class HelperTests(unittest.TestCase):
    def test_child_environment_drops_credentials_and_parent_session(self):
        env = child_environment({'PATH': '/bin', 'ANTHROPIC_API_KEY': 'x', 'ANTHROPIC_AUTH_TOKEN': 'y',
                                 'CLAUDE_CODE_SESSION_ID': 'z', 'CLAUDECODE': '1', 'HOME': '/h'})
        self.assertEqual(env, {'PATH': '/bin', 'HOME': '/h'})

    def test_missing_usage_stays_unknown(self):
        self.assertIsNone(normalize_usage(None)['inputTokens'])
        self.assertIsNone(normalize_usage({'output_tokens': 3})['inputTokens'])


if __name__ == '__main__':
    unittest.main()

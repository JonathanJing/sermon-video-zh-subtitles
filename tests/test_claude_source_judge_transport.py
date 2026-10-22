"""Layer 1 source judge through the subscription Claude CLI: payload schema, no API key, own identity."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.compute.transports import claude_layer2
from tongxing_production.compute.transports.claude_source_judge import ClaudeSourceJudgeTransport
from tongxing_production.source import english_source_judge as judge

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
                          'sdk': os.environ.get('CLAUDE_AGENT_SDK_VERSION')}) + '\n')
print(json.dumps(state['result'])); sys.exit(0)
'''

ANSWER = {'schemaVersion': judge.BATCH_SCHEMA, 'sentences': [{
    'sourceSentenceId': 's1', 'sourceUnitIds': ['u1'], 'verdict': 'pass', 'risk': 'low',
    'checks': {name: 'pass' for name in judge.CHECKS}, 'evidence': 'Synthetic.', 'unresolvedIssues': []}]}


def payload(**overrides):
    value = {'model': 'claude-opus-5-5', 'reasoning_effort': 'high', 'max_completion_tokens': 4096,
             'service_tier': 'default',
             'response_format': {'type': 'json_schema', 'json_schema': {
                 'name': 'english_source_machine_judge', 'strict': True, 'schema': judge._response_schema()}},
             'messages': [{'role': 'system', 'content': 'Judge.'}, {'role': 'user', 'content': '{"sentences": []}'}]}
    value.update(overrides)
    return value


def result(**overrides):
    value = {'type': 'result', 'subtype': 'success', 'is_error': False, 'session_id': 's-1', 'num_turns': 2,
             'total_cost_usd': 0.05, 'permission_denials': [], 'duration_api_ms': 1200,
             'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 900, 'cache_read_input_tokens': 100,
                       'output_tokens': 300},
             'modelUsage': {'claude-opus-5-5': {'inputTokens': 10, 'outputTokens': 300}},
             'structured_output': ANSWER}
    value.update(overrides)
    return value


class ClaudeSourceJudgeTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cli = self.root / 'claude'
        self.cli.write_text(FAKE)
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IEXEC)
        self.state, self.log = self.root / 'state.json', self.root / 'log.jsonl'
        self.set_state(result())
        patcher = patch.dict(os.environ, {'FAKE_CLAUDE_STATE': str(self.state), 'FAKE_CLAUDE_LOG': str(self.log),
                                          'ANTHROPIC_API_KEY': 'sk-must-not-leak',
                                          'CLAUDE_AGENT_SDK_VERSION': '9.9.9'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def set_state(self, value):
        self.state.write_text(json.dumps({'auth': {'loggedIn': True, 'authMethod': 'claude.ai',
                                                   'apiProvider': 'firstParty'}, 'result': value}))

    def transport(self):
        return ClaudeSourceJudgeTransport(self.cli, receipts_dir=self.root / 'calls')

    def test_payload_schema_drives_the_cli_and_returns_a_chat_envelope(self):
        envelope = self.transport()('', payload())
        self.assertEqual(envelope['model'], 'claude-opus-5-5')
        self.assertEqual(json.loads(envelope['choices'][0]['message']['content']), ANSWER)
        self.assertEqual(envelope['usage'], {'prompt_tokens': 1010, 'completion_tokens': 300, 'total_tokens': 1310})
        identity = envelope['claudeCli']['executionIdentity']
        self.assertEqual(identity['schemaVersion'], 'claude-source-judge-transport-identity-v1')
        self.assertEqual(identity['role'], 'source_judge')
        call = json.loads(self.log.read_text().splitlines()[0])
        self.assertIsNone(call['apiKey'])
        schema = json.loads(call['args'][call['args'].index('--json-schema') + 1])
        self.assertEqual(schema, judge._response_schema())
        self.assertEqual(call['args'][call['args'].index('--tools') + 1], '')
        self.assertEqual(len(list((self.root / 'calls').glob('source_judge-*/response.json'))), 1)

    def test_layer2_adapter_file_is_untouched_and_named_separately(self):
        identity = self.transport().execution_identity
        layer2 = Path(claude_layer2.__file__).read_bytes()
        self.assertEqual(identity['layer2AdapterSha256'], hashlib.sha256(layer2).hexdigest())
        self.assertNotEqual(identity['adapterSha256'], identity['layer2AdapterSha256'])

    def test_api_key_missing_schema_wrong_identity_or_cap_are_refused_before_dispatch(self):
        transport = self.transport()
        cases = [('sk-x', payload(), 'api_key'),
                 ('', payload(response_format={'type': 'json_object'}), 'strict_json_schema'),
                 ('', payload(model='claude-haiku-5-5'), 'identity_mismatch'),
                 ('', payload(reasoning_effort='medium'), 'identity_mismatch'),
                 ('', {k: v for k, v in payload().items() if k != 'max_completion_tokens'}, 'output_cap')]
        for key, value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                transport(key, value)
        self.assertFalse(self.log.exists())

    def test_structured_output_repair_turn_is_tolerated_and_runaway_turns_are_not(self):
        self.set_state(result(num_turns=3))
        envelope = self.transport()('', payload())
        self.assertEqual(json.loads(envelope['choices'][0]['message']['content']), ANSWER)
        for turns in (0, 4):
            with self.subTest(turns=turns):
                self.set_state(result(num_turns=turns))
                with self.assertRaisesRegex(RuntimeError, 'unexpected_turn_count'):
                    self.transport()('', payload())

    def test_auxiliary_model_usage_is_recorded_and_a_foreign_answer_is_refused(self):
        aside = {'claude-haiku-4-5-20251001': {'inputTokens': 3697, 'outputTokens': 14}}
        self.set_state(result(modelUsage={'claude-opus-5-5': {'inputTokens': 2, 'outputTokens': 2616}, **aside}))
        envelope = self.transport()('', payload())
        self.assertEqual(json.loads(envelope['choices'][0]['message']['content']), ANSWER)
        response = json.loads(next((self.root / 'calls').glob('*/response.json')).read_text())
        self.assertEqual(response['auxiliaryModelUsage'], aside)
        self.assertEqual(response['reportedModels'], ['claude-opus-5-5'])
        self.assertEqual(envelope['claudeCli']['auxiliaryModelUsage'], aside)
        logged = json.loads(self.log.read_text().splitlines()[-1])
        self.assertIsNone(logged['sdk'])
        for usage in ({'claude-haiku-4-5-20251001': {'inputTokens': 10, 'outputTokens': 300}},
                      {'claude-opus-5-5': {'inputTokens': 2, 'outputTokens': 20},
                       'claude-haiku-4-5-20251001': {'inputTokens': 10, 'outputTokens': 30}}):
            with self.subTest(usage=usage):
                self.set_state(result(modelUsage=usage))
                with self.assertRaisesRegex(RuntimeError, 'model_identity_missing|unexpected_model_usage'):
                    self.transport()('', payload())

    def test_answer_outside_the_payload_schema_fails(self):
        self.set_state(result(structured_output={'schemaVersion': judge.BATCH_SCHEMA}))
        with self.assertRaises(Exception):
            self.transport()('', payload())


if __name__ == '__main__':
    unittest.main()

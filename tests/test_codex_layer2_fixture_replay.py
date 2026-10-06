"""Fixture replay is isolated from CLI construction, billing and live calls."""
import contextlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import run_codex_layer2_test as subject
from scripts import target_language_policy as policy


class FixtureReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.receipts = self.root / 'receipts'
        self.receipts.mkdir()
        self.identity = {'backend': 'codex_cli', 'authMode': 'chatgpt'}
        self.write('test-context.json', {'modelTransportIdentity': self.identity})
        self.payloads = {}
        for i in range(1, 14):
            for suffix, role, model in [('astra', 'translator', 'gpt-6-astra'), ('sol', 'reviewer', 'gpt-6-sol')]:
                stem = f'group-{i:04d}-{suffix}'
                payload = {'model': model, 'messages': [{'content': str(i)}]}
                content = {'translationGroupId': f'g{i}', 'sourceUnitIds': [f'u{i}'],
                    'targetUtterances': ['测试。'], 'coverage': [{'sourceUnitId': f'u{i}', 'targetText': '测试。'}]}
                if role == 'reviewer':
                    content['semanticReview'] = {'status': 'pass', 'checks': {k: 'pass' for k in
                        ['completeMeaning', 'negationsNumbersNames', 'quotationAttribution', 'noAddedMeaning']},
                        'evidence': 'Fixture only', 'uncertainty': [], 'issues': []}
                response = {'schemaVersion': 'codex-cli-layer2-response-v1', 'requestedModel': model,
                    'completed': True, 'exitCode': 0, 'threadId': stem, 'id': 'codex:' + stem,
                    'content': json.dumps(content)}
                self.write(stem + '.raw.json', {'payloadSha256': policy.canonical_sha256(
                    {'payload': payload, 'modelTransportIdentity': self.identity}), 'response': response})
                self.write(stem + '.policy-preview.json', {'payload': payload})
                self.payloads[stem] = payload

    def write(self, name, value):
        (self.receipts / name).write_text(json.dumps(value))

    def test_replay_has_separate_identity_and_never_constructs_live_transport(self):
        with patch.object(subject.CodexLayer2Transport, '__init__', side_effect=AssertionError('CLI constructed')), \
             patch('subprocess.check_output', side_effect=AssertionError('Version called')):
            transport = subject.FixtureLayer2Transport(self.receipts)
            response = transport('', self.payloads['group-0001-astra'])
        self.assertEqual(transport.execution_identity['backend'], 'fixture_replay')
        self.assertEqual(len(transport.execution_identity['files']), 53)
        self.assertFalse(response['realModelCalls'])
        self.assertTrue(response['id'].startswith('fixture:'))
        self.assertEqual(response['historicalResponseId'], 'codex:group-0001-astra')
        self.assertEqual(subject.FixtureLayer2Transport.completed_content(response, 'gpt-6-astra', 'translator'), response['content'])

    def test_request_drift_receipt_drift_and_api_key_are_rejected(self):
        transport = subject.FixtureLayer2Transport(self.receipts)
        with self.assertRaisesRegex(ValueError, 'exactly matching'):
            transport('', {'model': 'gpt-6-astra', 'messages': []})
        with self.assertRaisesRegex(ValueError, 'API key'):
            transport('do-not-print', self.payloads['group-0001-astra'])
        p = self.receipts / 'group-0001-astra.raw.json'
        p.write_text(p.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'receipt changed'):
            transport('', self.payloads['group-0001-astra'])

    def test_original_hash_binding_and_missing_response_are_rejected_before_replay(self):
        self.write('group-0001-astra.policy-preview.json', {'payload': {'model': 'changed'}})
        with self.assertRaisesRegex(ValueError, 'original payload binding'):
            subject.FixtureLayer2Transport(self.receipts)
        self.write('group-0001-astra.policy-preview.json', {'payload': self.payloads['group-0001-astra']})
        (self.receipts / 'group-0013-sol.raw.json').unlink()
        with self.assertRaises(FileNotFoundError):
            subject.FixtureLayer2Transport(self.receipts)

    def test_command_mock_mode_reports_no_live_models_or_approval(self):
        fixture = self.root / 'fixture'
        fixture.mkdir()
        docs = {
            'simulation-scope-report.json': {'simulationOnly': True, 'productionEligible': False, 'actualHumanApproval': False},
            'source.json': {'source': {'media': {'sha256': '79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b', 'durationSeconds': 180.013167}}},
            'anchor.json': {'sourceUnits': [{'sourceUnitId': f'u{i}', 'english': 'Text.'} for i in range(39)]},
            'zh-Hans/candidate.json': {'groups': [{'translationGroupId': f'g{i}', 'sourceUnitIds': [f'u{i}']} for i in range(13)]},
            'policy.json': {'targetLocale': 'zh-Hans', 'batching': {'workers': 1}},
        }
        for name, value in docs.items():
            p = fixture / name
            p.parent.mkdir(exist_ok=True)
            p.write_text(json.dumps(value))
        out = self.root / 'artifacts' / 'out'
        out.parent.mkdir()
        def run(*args, **kwargs):
            transport = args[5]
            transport('', self.payloads['group-0001-astra'])
            out.mkdir()
            return {'groups': [{} for _ in range(13)]}
        with patch.object(subject, '__file__', str(self.root / 'scripts/run_codex_layer2_test.py')), \
             patch.object(subject.CodexLayer2Transport, '__init__', side_effect=AssertionError('CLI constructed')), \
             patch.object(subject.runner, 'validate_standalone_worker_budget'), \
             patch.object(subject.runner, 'group_plan'), \
             patch.object(subject.runner, '_run_prepared_groups', side_effect=run), \
             patch.object(subject.accounting, 'accounting_session', return_value=contextlib.nullcontext()), \
             patch('builtins.print'):
            # The command binds its own bytes; create that harmless synthetic source.
            p = Path(subject.__file__)
            p.parent.mkdir()
            p.write_text('fixture command')
            report = subject.run_test(fixture, fixture / 'policy.json', out,
                cli_path=self.root / 'does-not-exist', mock_responses_dir=self.receipts)
        self.assertEqual(report['status'], 'fixture_replay_pass_test_only')
        self.assertFalse(report['realModelCalls'])
        self.assertFalse(report['humanApproval'])
        self.assertFalse(report['productionEligible'])


if __name__ == '__main__':
    unittest.main()

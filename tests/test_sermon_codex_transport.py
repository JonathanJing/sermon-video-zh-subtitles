"""Mock-only production CLI contract checks; no actual subprocess/model call."""
import base64
import fcntl
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import jsonschema
from scripts import sermon_codex_transport as mod


@contextmanager
def no_observation(*args, **kwargs):
    yield {}


class ProductionCodexTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cli = self.root / 'codex'
        self.cli.write_bytes(b'fake-cli-not-executable')
        self.home = self.root / 'auth'
        self.home.mkdir()
        self.auth = self.home / 'auth.json'
        self.auth.write_text(json.dumps({'auth_mode': 'chatgpt'}))
        self.directory = self.root / 'receipt'
        self.executions = []
        self.content = '{"ok":true}'
        self.tool = False
        self.returncode = 0
        self.env_patch = patch.dict(mod.os.environ, {'CODEX_HOME': str(self.home), 'SERMON_CODEX_CLI': str(self.cli),
            'OPENAI_API_KEY': 'do-not-forward', 'OPENAI_PROJECT_ID': 'do-not-forward',
            'CODEX_API_KEY': 'do-not-forward'}, clear=True)
        self.env_patch.start(); self.addCleanup(self.env_patch.stop)
        self.version_patch = patch.object(mod.subprocess, 'check_output', return_value='codex test-1\n')
        self.version = self.version_patch.start(); self.addCleanup(self.version_patch.stop)
        self.exec_patch = patch.object(mod.subprocess, 'run', side_effect=self.fake_run)
        self.run = self.exec_patch.start(); self.addCleanup(self.exec_patch.stop)
        self.observe_patch = patch.object(mod.observation, 'invocation', no_observation)
        self.observe_patch.start(); self.addCleanup(self.observe_patch.stop)

    def fake_run(self, command, **kwargs):
        attachments = [(Path(command[i+1]).suffix, Path(command[i+1]).read_bytes()) for i, value in enumerate(command) if value == '--image']
        self.executions.append((command, kwargs, attachments))
        Path(command[command.index('-o')+1]).write_text(self.content)
        rows = [{'type': 'thread.started', 'thread_id': 'thread-test'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': self.content}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 20}}]
        if self.tool:
            rows.insert(1, {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'unexpected'}})
        return subprocess.CompletedProcess(command, self.returncode, '\n'.join(json.dumps(row) for row in rows), '')

    def call(self, **kwargs):
        return mod._call('Bound source task', model='gpt-6.1-sol', reasoning='high', output_dir=self.directory, **kwargs)

    def test_fixed_model_effort_fast_private_workdir_and_stripped_credentials(self):
        result = self.call()
        command, kwargs, _ = self.executions[0]
        self.assertEqual(command[command.index('-m')+1], 'gpt-6.1-sol')
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertIn('service_tier="fast"', command)
        self.assertEqual(command[command.index('-s')+1], 'read-only')
        self.assertIn('--ephemeral', command)
        self.assertIn('--ignore-user-config', command)
        self.assertFalse(any(name.upper().startswith('OPENAI_') or name.upper() == 'CODEX_API_KEY' for name in kwargs['env']))
        self.assertNotEqual(Path(kwargs['cwd']), mod.ROOT)
        self.assertFalse(Path(kwargs['cwd']).exists())
        self.assertIsNone(result['serverModel'])
        self.assertEqual(result['requestedReasoningEffort'], 'high')
        for path in self.directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertNotIn('do-not-forward', path.read_text())

    def test_chatgpt_auth_required_before_dispatch(self):
        self.auth.write_text(json.dumps({'auth_mode': 'apikey', 'OPENAI_API_KEY': 'private'}))
        with self.assertRaisesRegex(ValueError, 'chatgpt_auth'):
            self.call()
        self.run.assert_not_called()
        self.assertFalse((self.directory / "started.json").exists())
        self.assertFalse((self.directory / "identity.json").exists())

    def test_missing_json_schema_rejects_without_auth_or_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'codex_json_schema_required'):
            mod.chat_json('', {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high',
                'messages': [{'role': 'user', 'content': 'Bound source'}],
                'response_format': {'type': 'json_schema'}})
        self.version.assert_not_called()
        self.run.assert_not_called()

    def test_tool_execution_is_rejected_and_replay_blocked(self):
        self.tool = True
        with self.assertRaisesRegex(RuntimeError, 'tool_failure'):
            self.call()
        self.assertFalse((self.directory / 'response.json').exists())
        with self.assertRaisesRegex(RuntimeError, 'reconciliation'):
            self.call()
        self.assertEqual(self.run.call_count, 1)

    def test_timeout_preserves_unknown_and_never_reissues(self):
        self.run.side_effect = subprocess.TimeoutExpired(['fake'], 1, output='partial', stderr='failure')
        with self.assertRaises(subprocess.TimeoutExpired):
            self.call()
        self.assertEqual(json.loads((self.directory/'outcome.json').read_text())['status'], 'unknown_outcome')
        with self.assertRaisesRegex(RuntimeError, 'reconciliation'):
            self.call()
        self.assertEqual(self.run.call_count, 1)

    def test_same_directory_concurrent_dispatch_is_blocked(self):
        self.directory.mkdir()
        with (self.directory/'call.lock').open('a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'already_running'):
                self.call()
        self.run.assert_not_called()

    def test_result_file_and_final_event_must_match(self):
        def mismatched(command, **kwargs):
            result = self.fake_run(command, **kwargs)
            Path(command[command.index('-o')+1]).write_text('{"ok":false}')
            return result
        self.run.side_effect = mismatched
        with self.assertRaisesRegex(RuntimeError, 'mismatch'):
            self.call()
        self.assertFalse((self.directory/'response.json').exists())

    def test_valid_response_reused_without_second_dispatch(self):
        first = self.call()
        self.assertEqual(self.call(), first)
        self.assertEqual(self.run.call_count, 1)

    def test_identity_change_blocked_before_dispatch(self):
        self.call()
        with self.assertRaisesRegex(ValueError, 'identity_changed'):
            mod._call('Different source', model='gpt-6.1-sol', reasoning='high', output_dir=self.directory)
        self.assertEqual(self.run.call_count, 1)

    def test_tampered_response_content_rejected(self):
        self.call()
        path = self.directory/'response.json'
        response = json.loads(path.read_text()); response['content'] = '{"ok":false}'
        path.write_text(json.dumps(response))
        with self.assertRaises((ValueError, RuntimeError)):
            self.call()
        self.assertEqual(self.run.call_count, 1)

    def test_schema_failure_does_not_admit_or_retry(self):
        with self.assertRaises(jsonschema.ValidationError):
            self.call(output_schema={'type': 'object', 'properties': {'ok': {'const': False}}, 'required': ['ok']})
        self.assertFalse((self.directory/'response.json').exists())
        with self.assertRaisesRegex(RuntimeError, 'reconciliation'):
            self.call(output_schema={'type': 'object', 'properties': {'ok': {'const': False}}, 'required': ['ok']})
        self.assertEqual(self.run.call_count, 1)

    def test_api_output_cap_rejected_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'output_cap'):
            mod.chat_json('', {'model': 'gpt-6.1-sol', 'messages': [], 'max_completion_tokens': 100})
        self.run.assert_not_called(); self.version.assert_not_called()

    def test_bound_data_image_is_preserved_as_attachment(self):
        raw = b'\x89PNG\r\n\x1a\nmock-image-data'
        payload = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'response_format': {'type': 'json_object'},
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'bound source'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,'+base64.b64encode(raw).decode()}}]}]}
        # Keep all files in the test directory rather than normal artifact storage.
        real_call = mod._call
        def private_call(prompt, **kwargs):
            return real_call(prompt, output_dir=self.directory, **kwargs)
        with patch.object(mod, '_call', side_effect=private_call):
            result = mod.chat_json('ignored-key', payload)
        self.assertEqual(self.executions[0][2], [('.png', raw)])
        self.assertIn('BOUND IMAGE 1', self.executions[0][1]['input'])
        self.assertEqual(result['modelIdentityKind'], 'requested')

    def test_remote_or_mislabeled_image_rejected_before_dispatch(self):
        for url in ['https://example.com/image.png', 'data:image/png;base64,'+base64.b64encode(b'wrong').decode()]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                mod.chat_json('', {'model': 'gpt-6.1-sol', 'messages': [{'role':'user', 'content':[{'type':'image_url','image_url':{'url':url}}]}]})
        self.run.assert_not_called(); self.version.assert_not_called()

    def test_invalid_schema_rejected_before_auth_or_dispatch(self):
        with self.assertRaises(jsonschema.SchemaError):
            self.call(output_schema={'type': 'unknown-json-type'})
        self.run.assert_not_called(); self.version.assert_not_called()

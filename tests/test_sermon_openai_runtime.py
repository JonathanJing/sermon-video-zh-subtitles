import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from scripts import sermon_openai_runtime as runtime


def selected(environment='dev'):
    return {'SERMON_OPENAI_ENVIRONMENT': environment,
            'SERMON_OPENAI_CREDENTIAL_ALIAS': f'tongxing-{environment}-runtime',
            'OPENAI_PROJECT_ID': 'proj_' + environment, 'OPENAI_API_KEY': 'test-key'}


class RuntimeBindingTests(unittest.TestCase):
    def test_legacy_requests_keep_existing_behavior(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime.project_headers('legacy'), {})
            runtime.reject_secret_override('legacy-secret-reference')

    def test_selected_project_and_override_guards(self):
        for environment in ('dev', 'prod'):
            with patch.dict(os.environ, selected(environment), clear=True):
                self.assertEqual(runtime.project_headers('test-key'), {'OpenAI-Project': 'proj_' + environment})
                with self.assertRaisesRegex(ValueError, '^selected_openai_credential_override$'):
                    runtime.project_headers('different-key')
                with self.assertRaisesRegex(ValueError, '^selected_openai_secret_override$'):
                    runtime.reject_secret_override('old-secret')
                self.assertNotIn('test-key', json.dumps(runtime.selected_route()))

    def test_central_transport_guards_raw_headers_before_dispatch(self):
        from scripts import sermon_pipeline as pipeline
        import urllib.request
        with patch.dict(os.environ, selected(), clear=True):
            for key, project, expected in [('other-key', 'proj_dev', 'credential_override'),
                                           ('test-key', 'proj_prod', 'project_override')]:
                request = urllib.request.Request('https://api.openai.com/v1/responses',
                    headers={'Authorization': 'Bearer ' + key, 'OpenAI-Project': project})
                with patch.object(pipeline.urllib.request, 'urlopen') as send:
                    with self.assertRaisesRegex(ValueError, expected):
                        pipeline.request_json(request)
                    send.assert_not_called()
            request = urllib.request.Request('https://api.openai.com/v1/responses', headers={'Authorization': 'Bearer test-key'})
            runtime.bind_request(request)
            self.assertEqual(request.get_header('Openai-project'), 'proj_dev')

    def test_incomplete_or_mismatched_context_rejected(self):
        for name in ('OPENAI_PROJECT_ID', 'OPENAI_API_KEY', 'SERMON_OPENAI_CREDENTIAL_ALIAS'):
            env = selected(); env.pop(name)
            with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, '^invalid_selected_openai_runtime$'):
                runtime.project_headers('test-key')

    def test_json_and_audio_transports_bind_project(self):
        from scripts import sermon_pipeline as pipeline
        with patch.dict(os.environ, selected(), clear=True), patch.object(pipeline, 'request_json', return_value={}) as send:
            pipeline.json_request('https://api.openai.com/v1/responses', 'test-key', {'model': 'model'})
            self.assertEqual(send.call_args.args[0].get_header('Openai-project'), 'proj_dev')
            with tempfile.TemporaryDirectory() as tmp:
                audio = Path(tmp) / 'audio.m4a'; audio.write_bytes(b'test')
                pipeline.multipart_request('https://api.openai.com/v1/audio/transcriptions', 'test-key', {'model': 'model'}, 'file', audio)
            self.assertEqual(send.call_args.args[0].get_header('Openai-project'), 'proj_dev')

    def test_agents_transport_binds_selected_project(self):
        from scripts.sermon_agents_api import AgentsAPIClient
        with patch.dict(os.environ, selected('prod'), clear=True):
            client = AgentsAPIClient()
            client._opener = Mock()
            client._opener.open.return_value = io.BytesIO(b'{"id":"session"}')
            client._request('GET', '/agents/sessions/session')
            request = client._opener.open.call_args.args[0]
            self.assertEqual(request.get_header('Openai-project'), 'proj_prod')

    def test_judge_rejects_secret_override_before_cloud_access(self):
        from scripts import judge_english_source_for_translation as judge
        import sys
        argv = ['judge', '--aligned-segments', 'unused', '--anchor-manifest', 'unused',
                '--out', 'unused', '--api-key-secret', 'legacy-secret']
        with patch.dict(os.environ, selected(), clear=True), patch.object(sys, 'argv', argv):
            with self.assertRaisesRegex(ValueError, '^selected_openai_secret_override$'):
                judge.main()

    def test_actual_ledger_and_report_capture_safe_configured_route(self):
        from scripts import sermon_accounting as accounting
        from scripts import sermon_log_profile as profile
        from scripts.sermon_model_call_report import report
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, selected(), clear=True):
            with profile.session(tmp, 'runtime-test', work_kind='engineering', evidence_mode='synthetic'):
                with accounting.stage('model-call', executor_type='production_model'), profile.context(logicalCallId='runtime-call'):
                    ident = accounting.record_api_started('test-model')
                    accounting.record_api_attempt('test-model', {'model': 'test-model', 'usage': {'input_tokens': 3, 'output_tokens': 2}}, 1, attempt_id=ident)
            raw = (Path(tmp) / 'events.jsonl').read_text()
            self.assertNotIn('test-key', raw)
            events = [json.loads(line) for line in raw.splitlines()]
            calls = report(events)['calls']
            self.assertEqual(calls[0]['openaiRoute'], runtime.selected_route())
            self.assertEqual(calls[0]['openaiRoute']['identitySource'], 'configured_runtime')

    def test_imported_api_observation_does_not_inherit_local_route(self):
        from scripts import sermon_accounting as accounting
        from scripts import sermon_model_call_observation as observation
        captured = []
        with patch.object(observation, '_emit', side_effect=captured.append):
            with observation.invocation('foreign-model', backend='api', provider='openai', role='supervisor'):
                pass
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, selected(), clear=True):
            with accounting.accounting_session(tmp, 'import-test'):
                for fields in captured:
                    observation._emit(fields)
            events = [json.loads(line) for line in (Path(tmp)/'events.jsonl').read_text().splitlines()]
            self.assertNotIn('openaiRoute', next(e for e in events if e.get('code') == 'model_call_observation'))


if __name__ == '__main__':
    unittest.main()

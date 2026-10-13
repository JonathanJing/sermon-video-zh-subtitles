"""New production role defaults and API dispatch; no model executions."""
import json
import os
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from scripts import sermon_pipeline, generate_notes_with_openai as notes
from scripts import run_post_live_subtitle_generation as post_live
from scripts import sermon_production_supervisor as supervisor
from scripts import sermon_source_text_review as source_review


class TextRoleDefaultTests(unittest.TestCase):
    def test_post_live_defaults_all_text_roles_to_sol_high_api(self):
        with patch.object(sys, 'argv', ['post-live', '--sunday', '2026-10-04', '--state-file', 'unused.json']):
            args = post_live.parse_args()
        for model in (args.zh_model, args.en_correction_model, args.reading_edition_model, args.interpretation_model):
            self.assertEqual(model, 'gpt-6.1-sol')
        for effort in (args.reasoning_effort, args.reading_edition_reasoning_effort, args.interpretation_reasoning_effort):
            self.assertEqual(effort, 'high')
        self.assertEqual(args.reading_edition_provider, 'openai')
        self.assertEqual(supervisor.SupervisorConfig.__dataclass_fields__['reading_model'].default, 'gpt-6.1-sol')
        self.assertEqual(notes.DEFAULT_MODEL, 'gpt-6.1-sol')
        self.assertEqual(notes.DEFAULT_REASONING_EFFORT, 'high')
        self.assertEqual(source_review.SUPPORTED_MODELS, {'gpt-6-astra', 'gpt-6.1-sol'})

    def test_migrated_legacy_chat_caps_valid_copy_without_mutating_input(self):
        from scripts.sermon_provider_limits import DEFAULT_REQUEST_LIMITS
        payload={'model':'gpt-6.1-sol','reasoning_effort':'high',
                 'messages':[{'role':'user','content':'synthetic'}], 'response_format':{'type':'json_object'}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_ACCOUNTING_DIR':tmp}), patch.object(sermon_pipeline,'json_request',return_value={'ok':True}) as api:
            sermon_pipeline.chat_json('synthetic-key',payload)
        self.assertNotIn('max_completion_tokens',payload)
        sent=api.call_args.args[2]
        self.assertEqual(sent['max_completion_tokens'],DEFAULT_REQUEST_LIMITS['maxCompletionTokens'])
        self.assertEqual(sent['service_tier'],'default')
        self.assertEqual(sent['messages'],payload['messages'])

    def test_already_supplied_cap_is_not_increased_or_silently_changed(self):
        from scripts.sermon_provider_limits import DEFAULT_REQUEST_LIMITS
        payload={'model':'gpt-6.1-sol','reasoning_effort':'high',
                 'messages':[{'role':'user','content':'synthetic'}], 'response_format':{'type':'json_object'},
                 'max_completion_tokens':DEFAULT_REQUEST_LIMITS['maxCompletionTokens']-1}
        with patch.object(sermon_pipeline,'json_request') as api:
            with self.assertRaises(ValueError):sermon_pipeline.chat_json('synthetic-key',payload)
        api.assert_not_called()

    def test_supervisor_defaults_cli_and_preserves_explicit_historical_api(self):
        from scripts import run_sermon_production_supervisor_agent as agent
        argv = ['supervisor', '--sunday', '2026-10-04', '--state-file', 'unused.json']
        with patch.object(sys, 'argv', argv):
            self.assertEqual(agent.parse_args().agent_backend, 'codex-cli')
        with patch.object(sys, 'argv', argv + ['--agent-backend', 'agents-api']):
            self.assertEqual(agent.parse_args().agent_backend, 'agents-api')

    def test_notes_api_preserves_response_shape(self):
        envelope = {'model': 'gpt-6.1-sol', 'output_text': '{"summaryZh":"sample"}', 'usage': {'total_tokens': 12}}
        response = Mock(status_code=200, content=json.dumps(envelope).encode())
        response.json.return_value = envelope
        payload = {'model': 'gpt-6.1-sol', 'reasoning': {'effort': 'high'}, 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'source'}]}]}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'SERMON_ACCOUNTING_DIR':tmp}), patch.object(notes.requests, 'post', return_value=response) as api, patch('scripts.sermon_openai_runtime.project_headers', return_value={}):
            result = notes.request_openai_notes(payload, 'synthetic-key', session_verifier=lambda: {'status':'offline_test'})
        api.assert_called_once()
        self.assertEqual(json.loads(notes.extract_response_text(result)), {'summaryZh': 'sample'})
        self.assertEqual(api.call_args.kwargs['json']['reasoning']['effort'], 'high')

    def test_actual_legacy_builders_pass_validated_caps_to_offline_transport(self):
        from scripts import build_sermon_reading_edition_with_openai as reading
        from scripts.sermon_provider_limits import DEFAULT_REQUEST_LIMITS
        sent=[]
        def respond(url,key,payload,**kwargs):
            sent.append(payload)
            user=payload['messages'][1]['content']
            if '<timed_segments>' in user:result={'segments':[{'id':0,'text':'Hello.'}]}
            elif '<context>' in user:result={'id':0,'zh':'您好。'}
            else:result={'blocks':[{'id':0,'zh':'您好。'}]}
            return {'model':payload['model'],'choices':[{'message':{'content':json.dumps(result)}}]}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SERMON_ACCOUNTING_DIR':tmp}),patch.object(sermon_pipeline,'json_request',side_effect=respond):
            root=Path(tmp);segments=[{'id':0,'start':0.0,'end':1.0,'text':'Hello.'}]
            sermon_pipeline.correct_english('synthetic-key',segments,[],root/'correct','gpt-6.1-sol',{},30)
            sermon_pipeline.translate_chinese('synthetic-key',segments,root/'translate','gpt-6.1-sol',{})
            blocks=[{'id':0,'start':0.0,'end':1.0,'en':'Hello.','zh':'您好。'}]
            for qa in (False,True):
                reading.edit_batch('synthetic-key',blocks,blocks,0,root/'reading',model='gpt-6.1-sol',
                    reasoning_effort='high',qa_pass=qa,provider='openai',codex_cli=Path('unused'),schema_path=Path('unused'))
        self.assertEqual(len(sent),4)
        for payload in sent:
            self.assertEqual(payload['max_completion_tokens'],DEFAULT_REQUEST_LIMITS['maxCompletionTokens'])
            self.assertEqual(payload['service_tier'],'default')
            self.assertEqual(payload['reasoning_effort'],'high')

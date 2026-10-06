"""New production role defaults and API dispatch; no model executions."""
import json
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

    def test_migrated_chat_uses_api(self):
        caller = Mock(return_value={'choices': [{'message': {'content': '{}'}}]})
        payload = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'messages': []}
        with patch.object(sermon_pipeline, 'json_request', caller) as api:
            result = sermon_pipeline.chat_json('unrelated-asr-key', payload, session_verifier=lambda: {'status':'offline_test'})
        api.assert_called_once_with(sermon_pipeline.CHAT_URL, 'unrelated-asr-key', payload, retries=1)
        self.assertEqual(result['choices'][0]['message']['content'], '{}')

    def test_notes_api_preserves_response_shape(self):
        envelope = {'model': 'gpt-6.1-sol', 'output_text': '{"summaryZh":"sample"}', 'usage': {'total_tokens': 12}}
        response = Mock(status_code=200)
        response.json.return_value = envelope
        payload = {'model': 'gpt-6.1-sol', 'reasoning': {'effort': 'high'}, 'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'source'}]}]}
        with patch.object(notes.requests, 'post', return_value=response) as api, patch('scripts.sermon_openai_runtime.project_headers', return_value={}):
            result = notes.request_openai_notes(payload, 'synthetic-key', session_verifier=lambda: {'status':'offline_test'})
        api.assert_called_once()
        self.assertEqual(json.loads(notes.extract_response_text(result)), {'summaryZh': 'sample'})
        self.assertEqual(api.call_args.kwargs['json']['reasoning']['effort'], 'high')

import os
import unittest
from unittest.mock import patch

from scripts import openai_layer2_transport as transport
from scripts import sermon_pipeline


class OpenAILayer2TransportTests(unittest.TestCase):
    def test_requires_explicit_project_and_single_attempt(self):
        environment = {
            'SERMON_OPENAI_ENVIRONMENT': 'dev',
            'SERMON_OPENAI_CREDENTIAL_ALIAS': 'tongxing-dev-runtime',
            'OPENAI_PROJECT_ID': 'proj_testdev',
            'OPENAI_API_KEY': 'synthetic-test-key',
        }
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(sermon_pipeline, 'json_request', return_value={'id': 'response'}) as request:
            caller = transport.OpenAILayer2Transport()
            self.assertEqual(caller.execution_identity['backend'], 'openai_api')
            self.assertEqual(caller.execution_identity['route']['projectId'], 'proj_testdev')
            with self.assertRaisesRegex(ValueError, 'selected_openai_credential_override'):
                caller('different', {'model': 'gpt-6.1-sol'})
            with self.assertRaisesRegex(ValueError, 'fast_tier_lacks_worst_case_authorization'):
                caller('synthetic-test-key', {'model': 'gpt-6.1-sol', 'service_tier': 'fast'})
            request.assert_not_called()

    def test_unbound_environment_blocks_before_request(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(sermon_pipeline, 'json_request', side_effect=AssertionError('no dispatch')) as request:
            with self.assertRaisesRegex(ValueError, 'openai_layer2_requires_explicit_dev_or_prod_launcher'):
                transport.OpenAILayer2Transport()
            request.assert_not_called()

    def test_shared_text_call_refuses_uncapped_sol_before_request(self):
        payload = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'service_tier': 'fast'}
        with patch.object(sermon_pipeline, 'json_request', side_effect=AssertionError('dispatched')) as request:
            with self.assertRaisesRegex(ValueError, 'unsupported_budget_capability'):
                sermon_pipeline._chat_json('synthetic-test-key', payload)
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()

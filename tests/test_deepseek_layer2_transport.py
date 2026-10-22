import json
import os
import unittest
from unittest.mock import patch

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.compute.transports import deepseek_layer2 as transport
from tongxing_production.text import controller


class _Response:
    def __init__(self, body):
        self._body = body
    def read(self):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False


class DeepSeekLayer2TransportTests(unittest.TestCase):
    def test_requires_key_and_rejects_credential_override(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'requires_DEEPSEEK_API_KEY'):
                transport.DeepSeekLayer2Transport()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'synthetic-key'}, clear=True):
            caller = transport.DeepSeekLayer2Transport()
            self.assertEqual(caller.execution_identity['backend'], 'deepseek_api')
            self.assertEqual(caller.execution_identity['model'], 'deepseek-flash')
            with self.assertRaisesRegex(ValueError, 'must_not_receive_api_key'):
                caller('override', {'model': 'deepseek-flash', 'reasoning_effort': 'high'})

    def test_posts_openai_compatible_request_without_retry(self):
        body = json.dumps({'id': 'x', 'model': 'deepseek-flash', 'choices': [
            {'message': {'role': 'assistant', 'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 2}}).encode()
        payload = {'model': 'deepseek-flash', 'reasoning_effort': 'high',
                   'messages': [{'role': 'user', 'content': 'x'}], 'response_format': {'type': 'json_object'}}
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'synthetic-key'}, clear=True), \
                patch.object(transport.urllib.request, 'urlopen', return_value=_Response(body)) as opened:
            caller = transport.DeepSeekLayer2Transport()
            value = caller('', payload)
            self.assertEqual(value['model'], 'deepseek-flash')
            request = opened.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.deepseek.com/chat/completions')
            self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-key')
            self.assertEqual(json.loads(request.data), payload)
            opened.assert_called_once()

    def test_controller_identity_binds_both_roles_and_the_backend(self):
        class Fake:
            def __init__(self, effort):
                self.execution_identity = {'model': 'deepseek-flash', 'reasoningEffort': effort}
        identity = controller.deepseek_model_transport_identity(
            {'translator': Fake('high'), 'reviewer': Fake('max')})
        self.assertEqual(identity['backend'], 'deepseek_api')
        self.assertEqual(identity['layer2Backend'], 'deepseek_flash')
        self.assertEqual(identity['transports']['reviewer']['reasoningEffort'], 'max')

    def test_rejects_a_payload_for_another_model_or_effort(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'synthetic-key'}, clear=True):
            caller = transport.DeepSeekLayer2Transport(model='deepseek-flash', effort='max')
            for payload in ({'model': 'gpt-6.1-sol', 'reasoning_effort': 'max'},
                            {'model': 'deepseek-flash', 'reasoning_effort': 'high'}):
                with self.assertRaisesRegex(ValueError, 'payload_model_or_effort_changed'):
                    caller('', payload)


if __name__ == '__main__':
    unittest.main()

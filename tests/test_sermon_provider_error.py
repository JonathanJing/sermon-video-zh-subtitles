"""Offline error fixtures never use provider requests or real secrets."""
import json
import unittest
from scripts import sermon_provider_error as errors

class ErrorDiagnosticsTests(unittest.TestCase):
    def test_code_parameter_and_summary_are_safe_and_bounded(self):
        raw=json.dumps({'error':{'code':'unsupported_parameter','param':'max_completion_tokens',
            'message':'API_KEY=private /Users/private source transcript'}}).encode()
        value=errors.diagnostic(400,raw)
        self.assertEqual(value['reasonCode'],'unsupported_parameter')
        self.assertEqual(value['errorParam'],'max_completion_tokens')
        self.assertEqual(errors.validate(value),value)
        self.assertNotIn('private',json.dumps(value))
        self.assertLess(len(value['summary']),160)

    def test_unknown_labels_and_raw_messages_never_survive(self):
        raw=json.dumps({'error':{'code':'sk_secret123','param':'private_transcript',
            'message':'Bearer private; /Users/private; source words'}}).encode()
        value=errors.diagnostic(400,raw)
        self.assertIsNone(value['errorCode']);self.assertIsNone(value['errorParam'])
        self.assertNotIn('private',json.dumps(value))
        for raw in (b'not-json',b'{"error":{},"error":{"code":"unsupported_parameter"}}',
                    b'x'*(errors.MAX_ERROR_BYTES+1),b'{"error":{"code":[],"param":{}}}'):
            self.assertEqual(errors.diagnostic(400,raw)['reasonCode'],'http_request_rejected')

    def test_legacy_http_exception_has_fixed_summary_and_retains_audio_fallback_signal(self):
        import io
        import urllib.error
        import urllib.request
        from unittest.mock import Mock
        from scripts import sermon_pipeline as pipeline
        for message,expected in (('API_KEY=private /Users/private source','http_request_rejected'),
                ('Audio file might be corrupted or unsupported; private','Audio file might be corrupted or unsupported')):
            raw=json.dumps({'error':{'message':message}}).encode()
            error=urllib.error.HTTPError('https://example.test',400,'private',{},io.BytesIO(raw))
            with self.assertRaises(RuntimeError) as caught:
                pipeline.request_json(urllib.request.Request('https://example.test'),
                    request_executor=Mock(side_effect=error))
            self.assertIn(expected,str(caught.exception))
            self.assertNotIn('private',str(caught.exception))

    def test_json_mode_pattern_has_fixed_reason_without_copying_message(self):
        raw=json.dumps({'error':{'code':None,'param':'messages',
            'message':"Messages must contain the word 'json'. Private quoted source."}}).encode()
        value=errors.diagnostic(400,raw)
        self.assertEqual(value['reasonCode'],'json_mode_requires_json_word')
        self.assertNotIn('Private',json.dumps(value))
        changed={**value,'summary':'private'}
        with self.assertRaisesRegex(ValueError,'invalid_provider_error_diagnostic'):errors.validate(changed)

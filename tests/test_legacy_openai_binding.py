"""C4: the functions outcome receipts bind live in compute/legacy_openai.

production-text-call binds ``_chat_json`` and source-audio-api binds
``multipart_request``. Both now hash the small transport file, so an edit to any
other function of scripts/sermon_pipeline.py no longer changes their bindings.
"""
import hashlib
from pathlib import Path
import unittest

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.workflows.dual_pdf import pipeline as sermon_pipeline
from tongxing_production.compute import legacy_openai, outcomes


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class LegacyOpenAiBindingTests(unittest.TestCase):
    def test_old_names_are_the_moved_objects(self):
        for name in ('chat_json', '_chat_json', 'json_request', 'request_json', 'multipart_request',
                     'bounded_legacy_chat_payload', 'legacy_text_cache_contract', 'legacy_text_execution_identity',
                     'TransportRejection', 'PreDispatchRejection', 'KNOWN_REQUEST_REJECTIONS', 'CHAT_URL',
                     'TRANSCRIBE_URL', 'LEGACY_TEXT_CACHE_SCHEMA'):
            with self.subTest(name=name):
                self.assertIs(getattr(sermon_pipeline, name), getattr(legacy_openai, name))

    def test_bound_functions_hash_the_transport_file_not_the_monolith(self):
        transport, monolith = file_sha256(legacy_openai.__file__), file_sha256(sermon_pipeline.__file__)
        for function, arguments in ((legacy_openai._chat_json, {'api_key': 'k', 'payload': {}, 'retries': 1}),
                                    (legacy_openai.multipart_request, {'url': 'u', 'api_key': 'k', 'fields': {},
                                                                       'file_field': 'file', 'file_path': 'a.m4a',
                                                                       'retries': 1})):
            with self.subTest(function=function.__name__):
                caller = outcomes.execution_binding(function, arguments)['caller']
                self.assertEqual(caller['module'], 'tongxing_production.compute.legacy_openai')
                self.assertEqual(caller['sourceSha256'], transport)
                self.assertNotEqual(caller['sourceSha256'], monolith)

    def test_default_legacy_cache_identity_binds_the_moved_chat_function(self):
        payload = {'model': 'gpt-6.1-sol', 'reasoning_effort': 'high', 'messages': [{'role': 'user', 'content': 'x'}],
                   'response_format': {'type': 'json_object'}}
        identity = sermon_pipeline.legacy_text_execution_identity('k', payload)
        self.assertEqual(identity['executionBinding']['caller']['qualname'], '_chat_json')
        self.assertEqual(identity['executionBinding']['caller']['sourceSha256'], file_sha256(legacy_openai.__file__))


if __name__ == '__main__':
    unittest.main()

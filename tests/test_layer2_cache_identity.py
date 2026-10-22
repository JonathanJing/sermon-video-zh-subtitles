"""The cache key is content identity; the transport is provenance, not identity."""
import unittest
from types import SimpleNamespace

from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.text import models


class CacheIdentityTests(unittest.TestCase):
    def test_transport_identity_is_not_part_of_the_cache_key(self):
        payload = {'model': 'gpt-6.1-sol', 'messages': [{'role': 'user', 'content': 'x'}]}
        first = SimpleNamespace(execution_identity={
            'backend': 'openai_api', 'budgetAuthorizationSha256': 'a' * 64})
        second = SimpleNamespace(execution_identity={
            'backend': 'openai_api', 'budgetAuthorizationSha256': 'b' * 64})
        self.assertEqual(models._model_fingerprint(payload, first, 'key'),
                         models._model_fingerprint(payload, second, 'key'))

    def test_content_change_changes_the_cache_key(self):
        caller = SimpleNamespace(execution_identity={'backend': 'openai_api'})
        base = {'model': 'gpt-6.1-sol', 'messages': [{'role': 'user', 'content': 'x'}]}
        changed = {'model': 'gpt-6.1-sol', 'messages': [{'role': 'user', 'content': 'y'}]}
        self.assertNotEqual(models._model_fingerprint(base, caller, 'key'),
                            models._model_fingerprint(changed, caller, 'key'))


if __name__ == '__main__':
    unittest.main()

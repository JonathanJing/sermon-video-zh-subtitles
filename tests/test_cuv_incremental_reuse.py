"""Exercise real cache lineage across a local quotation-map correction."""
import copy
import json
import unittest
from unittest import mock
from tests import test_sermon_cuv_translation as fixtures
from scripts import sermon_cuv_translation as mod


class IncrementalQuotationReuseTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.CuvTranslationTests('test_full_chain_exact_injection_and_offline_spoken_gate')
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)

    def fake_chat(self, key, payload):
        response = self.fx.fake_chat(key, payload)
        if mod.SELECT in payload['messages'][0]['content']:
            data = json.loads(payload['messages'][1]['content'])
            if data['quotations'][0]['sourceText'] == 'I am Alpha':
                result = json.loads(response['choices'][0]['message']['content'])
                result['quotes'][0]['parts'][0]['text'] = '我是阿拉法'
                response = self.fx.response(result)
        return response

    def run_fake(self, out, **kwargs):
        with mock.patch.dict(mod.os.environ, {'OPENAI_API_KEY': 'test-only'}), \
             mock.patch.object(mod, 'chat_json', side_effect=self.fake_chat) as api:
            result = mod.run(self.fx.parent, out, reference_map_path=self.fx.map, batch_size=1, **kwargs)
        self.assertEqual('passed', result['status'])
        return api.call_count

    def test_metadata_only_change_reuses_identical_audit_and_translation(self):
        old = self.fx.out
        self.assertEqual(6, self.run_fake(old))
        revised = copy.deepcopy(self.fx.mapping)
        revised['revisionNote'] = 'Independent review requested; source spans unchanged'
        self.fx.map = self.fx.root / 'metadata-map.json'
        self.fx.write(self.fx.map, revised)
        new = self.fx.root / 'metadata-revision'
        self.assertEqual(0, self.run_fake(new, reuse_from=old))
        audit = mod.read(next((new / 'cache').glob('audit-quotes-*.json')))
        self.assertIn('reuseFrom', audit)
        for stage in ('translate-0', 'review-0', 'translate-1', 'review-1'):
            receipt = mod.read(next((new / 'cache').glob(stage + '-*.json')))
            self.assertIn('reuseFrom', receipt, stage)

    def test_local_quote_change_reuses_unrelated_batches_but_reaudits_globally(self):
        old = self.fx.out
        self.assertEqual(6, self.run_fake(old))
        old_manifest = mod.read(old / 'cuv-manifest.json')
        self.assertEqual(mod.PREFLIGHT_POLICY, old_manifest['preflightPolicy'])
        revised = copy.deepcopy(self.fx.mapping)
        revised['blocks'][0]['quotes'][0]['sourceText'] = 'I am Alpha'
        self.fx.map = self.fx.root / 'revised-map.json'
        self.fx.write(self.fx.map, revised)
        new = self.fx.root / 'revised'
        self.assertEqual(4, self.run_fake(new, reuse_from=old))
        for stage in ('translate-1', 'review-1'):
            prior = mod.read(next((old / 'cache').glob(stage + '-*.json')))
            current = mod.read(next((new / 'cache').glob(stage + '-*.json')))
            self.assertIn('reuseFrom', current, stage)
            self.assertEqual(prior['request'], current['request'])
            self.assertEqual(prior['response'], current['response'])
        for stage in ('select-0', 'translate-0', 'review-0', 'audit-quotes'):
            current = mod.read(next((new / 'cache').glob(stage + '-*.json')))
            self.assertNotIn('reuseFrom', current, stage)
        with mock.patch.object(mod, 'chat_json', side_effect=AssertionError('offline')):
            self.assertEqual('passed', mod.validate(new)['status'])
        # Reused outputs still depend on immutable original model receipts.
        dependency = next((old / 'cache').glob('translate-1-*.json'))
        receipt = mod.read(dependency)
        receipt['response']['model'] = 'tampered'
        self.fx.write(dependency, receipt)
        with mock.patch.object(mod, 'chat_json', side_effect=AssertionError('offline')):
            with self.assertRaises(ValueError):
                mod.validate(new)


if __name__ == '__main__':
    unittest.main()

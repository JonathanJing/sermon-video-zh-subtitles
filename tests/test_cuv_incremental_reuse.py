"""Exercise real cache lineage across a local quotation-map correction."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest import mock
from tests import test_sermon_cuv_translation as fixtures
from tongxing_production.text import cuv_translation as mod
from scripts.tongxing_host import cuv_poc_code_closure_sha256


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

    def test_implementation_identity_blocks_legacy_resume_reuse_and_validation(self):
        old = self.fx.out
        self.assertEqual(6, self.run_fake(old))
        manifest_path = old / 'cuv-manifest.json'
        manifest = mod.read(manifest_path)
        self.assertEqual('sermon-cuv-translation-v3', manifest['schemaVersion'])
        self.assertEqual('sermon-cuv-translation-v1', mod.VERSION)
        self.assertEqual(mod.implementation_identity(), manifest['implementationIdentity'])
        self.assertEqual('sermon-cuv-implementation-v3', manifest['implementationIdentity']['schemaVersion'])
        self.assertEqual(mod.VERSION, mod.read(old / 'report.json')['schemaVersion'])
        self.assertEqual(mod.VERSION, mod.read(old / 'spoken-review.json')['cuvTranslation']['schemaVersion'])
        manifest['schemaVersion'] = 'sermon-cuv-translation-v2'
        self.fx.write(manifest_path, manifest)
        with mock.patch.object(mod, 'chat_json', side_effect=AssertionError('paid call')):
            with self.assertRaisesRegex(ValueError, 'frozen checkout'):
                mod.validate(old)
        del manifest['implementationIdentity']
        manifest['schemaVersion'] = mod.VERSION
        self.fx.write(manifest_path, manifest)
        fresh = self.fx.root / 'fresh'
        with mock.patch.object(mod, 'chat_json', side_effect=AssertionError('paid call')):
            with self.assertRaisesRegex(ValueError, 'frozen checkout'):
                mod.validate(old)
            with self.assertRaisesRegex(ValueError, 'v1 manifest'):
                mod.run(self.fx.parent, old, reference_map_path=self.fx.map, batch_size=1)
            with self.assertRaisesRegex(ValueError, 'schemaVersion'):
                mod.run(self.fx.parent, fresh, reference_map_path=self.fx.map,
                        batch_size=1, reuse_from=old)
        self.assertFalse(fresh.exists())

    def test_delegated_code_change_blocks_validation_and_reuse(self):
        old = self.fx.out
        self.assertEqual(6, self.run_fake(old))
        manifest = mod.read(old / 'cuv-manifest.json')
        self.assertEqual(mod.backend.current().code.code_identity(),
                         manifest['implementationIdentity']['projectCodeClosureSha256'])
        original_backend = mod.backend.current()
        changed_code = replace(original_backend.code, code_identity=lambda: 'changed-delegated-code')
        with mock.patch.object(mod.backend, '_current', replace(original_backend, code=changed_code)), \
             mock.patch.object(mod, 'chat_json', side_effect=AssertionError('paid call')):
            with self.assertRaisesRegex(ValueError, 'implementation identity changed'):
                mod.validate(old)
            current = {**manifest, 'implementationIdentity': mod.implementation_identity()}
            with self.assertRaisesRegex(ValueError, 'implementationIdentity'):
                mod.compatible_reuse(current, manifest)

    def test_poc_code_change_blocks_validation_resume_and_reuse_before_provider(self):
        old = self.fx.out
        self.assertEqual(6, self.run_fake(old))
        manifest = mod.read(old / 'cuv-manifest.json')
        original_backend = mod.backend.current()
        self.assertEqual(original_backend.cuv_poc_code_closure_sha256(),
                         manifest['implementationIdentity']['cuvPocCodeClosureSha256'])
        changed_backend = replace(original_backend, cuv_poc_code_closure_sha256=lambda: 'changed-poc-code')
        fresh = self.fx.root / 'poc-changed'
        with mock.patch.object(mod.backend, '_current', changed_backend), \
             mock.patch.object(mod, 'chat_json', side_effect=AssertionError('paid call')):
            with self.assertRaisesRegex(ValueError, 'implementation identity changed'):
                mod.validate(old)
            with self.assertRaisesRegex(ValueError, 'implementation identity changed'):
                mod.run(self.fx.parent, old, reference_map_path=self.fx.map, batch_size=1)
            with self.assertRaisesRegex(ValueError, 'implementationIdentity'):
                mod.run(self.fx.parent, fresh, reference_map_path=self.fx.map,
                        batch_size=1, reuse_from=old)
        self.assertFalse(fresh.exists())

    def test_poc_closure_hash_includes_relative_paths_and_nested_python_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            poc = root / 'experiments' / 'sermon-dubbing-poc'
            nested = poc / 'nested' / 'helper.py'
            nested.parent.mkdir(parents=True)
            nested.write_bytes(b'original')
            first = cuv_poc_code_closure_sha256(root)
            nested.write_bytes(b'changed')
            self.assertNotEqual(first, cuv_poc_code_closure_sha256(root))
            nested.write_bytes(b'original')
            self.assertEqual(first, cuv_poc_code_closure_sha256(root))
            nested.rename(poc / 'renamed.py')
            self.assertNotEqual(first, cuv_poc_code_closure_sha256(root))

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

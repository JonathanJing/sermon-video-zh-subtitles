import copy
import json
import unittest
from unittest.mock import patch

from scripts import migrate_target_language_model_cache as subject
from scripts import run_target_language_models as models
from scripts import target_language_policy as policies
from tests import test_run_target_language_models as fixtures


class CacheMigrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RunTargetLanguageModelsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture.fixture
        self.f = f
        self.old = self.fixture.out
        models.run(f.source, f.anchor, f.policy, self.old, 'fixture-key', self.fixture.fake_call,
                   plugin_path=f.plugin_path)
        self.fixture.calls.clear()
        self.new = self.old.parent / 'migrated'

    def run_migration(self, policy=None, plugin=None):
        return subject.migrate(old_source=self.f.source, source=self.f.source, anchor=self.f.anchor,
            old_policy=self.f.policy, policy=policy or self.f.policy, old_run=self.old,
            old_plugin=self.f.plugin_path, plugin=plugin or self.f.plugin_path, out=self.new)

    def test_new_run_reuses_exact_payloads_with_zero_api_calls(self):
        before = {p.name: p.read_bytes() for p in self.old.glob('*') if p.is_file()}
        with patch.object(models.sermon_pipeline, 'chat_json', side_effect=AssertionError('network')):
            result = self.run_migration()
        self.assertEqual(result['modelCalls'], 0)
        self.assertEqual(result['reusedModelResponses'], 4)
        self.assertEqual(result['oldRulePreflightSha256'], result['newRulePreflightSha256'])
        self.assertEqual(result['requestIds']['translator'], ['response-1', 'response-3'])
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.old.glob('*') if p.is_file()})
        candidate = json.loads((self.new / 'candidate.json').read_text())
        self.assertEqual(candidate['humanReview']['translation'], 'pending')
        self.assertFalse(candidate['releaseEligible'])

    def test_plugin_only_revision_revalidates_plugin_without_new_api(self):
        new_plugin = self.old.parent / 'new-plugin.py'
        new_plugin.write_text(self.f.plugin_path.read_text() + '\n# implementation-only revision\n')
        policy = copy.deepcopy(self.f.policy)
        from scripts import produce_target_language_candidate as producer
        policy['languageReview']['pluginImplementationSha256'] = producer.plugin_implementation_sha256(new_plugin)
        policy['componentSha256']['languageReview'] = policies.canonical_sha256(policy['languageReview'])
        result = self.run_migration(policy, new_plugin)
        self.assertNotEqual(result['oldPolicySha256'], result['newPolicySha256'])
        self.assertEqual(result['modelCalls'], 0)
        self.assertEqual(result['reusedModelResponses'], 4)
        old_rules = json.loads((self.old / 'rule-preflight.json').read_text())
        new_rules = json.loads((self.new / 'rule-preflight.json').read_text())
        self.assertEqual(old_rules['modelRules'], new_rules['modelRules'])
        self.assertNotEqual(result['oldRulePreflightSha256'], result['newRulePreflightSha256'])

    def test_legacy_run_without_rule_proof_is_rejected_before_new_run(self):
        self.old = self.old.parent / 'legacy'
        request = models.producer.prepare_request(self.f.source, self.f.anchor, self.f.policy)
        models._run_prepared_groups(request, self.f.anchor, self.f.policy, self.old,
                                    'fixture-key', self.fixture.fake_call)
        self.fixture.calls.clear()
        with patch.object(models.sermon_pipeline, 'chat_json', side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError, 'lacks frozen rule receipt'):
                self.run_migration()
        self.assertFalse(self.new.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_missing_actual_payload_proof_is_rejected_before_new_run(self):
        (self.old / 'group-0001-astra.policy-preview.json').unlink()
        with self.assertRaisesRegex(ValueError, 'lacks frozen model payload'):
            self.run_migration()
        self.assertFalse(self.new.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_plugin_model_rules_change_has_no_paid_fallback(self):
        plugin = self.old.parent / 'changed-rules-plugin.py'
        plugin.write_text(self.f.plugin_path.read_text() + '\nNUMBERS = {"five": "五"}\n')
        policy = copy.deepcopy(self.f.policy)
        policy['languageReview']['pluginImplementationSha256'] = models.producer.plugin_implementation_sha256(plugin)
        policy['componentSha256']['languageReview'] = policies.canonical_sha256(policy['languageReview'])
        with self.assertRaisesRegex(ValueError, 'Migration payload changed'):
            self.run_migration(policy, plugin)
        self.assertFalse(self.new.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_rehashed_old_cache_without_actual_rule_consumption_is_rejected(self):
        parsed = self.old / 'group-0001-astra.json'
        path = parsed.with_suffix('.policy-preview.json')
        preview = json.loads(path.read_text())
        payload = preview['payload']
        actual = json.loads(payload['messages'][1]['content'])
        actual.pop('modelRules')
        payload['messages'][1]['content'] = json.dumps(actual, ensure_ascii=False)
        fingerprint = policies.canonical_sha256(payload)
        preview['payloadSha256'] = fingerprint
        path.write_text(json.dumps(preview))
        for cache in (parsed, parsed.with_suffix('.raw.json')):
            value = json.loads(cache.read_text())
            value['payloadSha256'] = fingerprint
            cache.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'actual model rule input differs'):
            self.run_migration()
        self.assertFalse(self.new.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_cli_wrapped_cache_identity_cannot_migrate_across_runs(self):
        identity = {'backend': 'codex_cli', 'fixture': True}
        for suffix in ('astra', 'sol'):
            for index in (1, 2):
                parsed = self.old / f'group-{index:04d}-{suffix}.json'
                preview = json.loads(parsed.with_suffix('.policy-preview.json').read_text())
                fingerprint = policies.canonical_sha256({'payload': preview['payload'],
                                                         'modelTransportIdentity': identity})
                for path in (parsed, parsed.with_suffix('.raw.json')):
                    value = json.loads(path.read_text())
                    value['payloadSha256'] = fingerprint
                    path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'prior model payload does not match cached response'):
            self.run_migration()
        self.assertFalse(self.new.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_unknown_original_request_is_rejected_before_new_run(self):
        (self.old / 'group-0001-astra.started.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Unknown prior request'):
            self.run_migration()
        self.assertFalse(self.new.exists())

    def test_content_prompt_change_has_no_paid_fallback(self):
        policy = copy.deepcopy(self.f.policy)
        policy['translator']['promptVersion'] += '-changed'
        policy['componentSha256']['translator'] = policies.canonical_sha256(policy['translator'])
        with self.assertRaisesRegex(ValueError, 'Migration payload changed'):
            self.run_migration(policy)
        self.assertFalse((self.new / 'candidate.json').exists())
        self.assertEqual(self.fixture.calls, [])

    def test_failed_semantic_evidence_is_not_promoted(self):
        evidence_path = self.old / 'evidence.json'
        evidence = json.loads(evidence_path.read_text())
        evidence['groups'][0]['semanticReview']['status'] = 'fail'
        evidence_path.write_text(json.dumps(evidence))
        with self.assertRaises(ValueError):
            self.run_migration()
        self.assertFalse(self.new.exists())

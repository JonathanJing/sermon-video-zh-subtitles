import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import target_language_policy_preview as subject
from scripts import run_target_language_models as runner


class ConsumedPolicyPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = {'translator': {'model': 'test', 'reasoningEffort': 'low'},
                       'languageReview': {'pluginImplementationSha256': 'a'},
                       'sourceScope': {'termApprovalReceipt': {'reviewedBy': 'human'}}}
        self.payload = {'model': 'test', 'messages': [{'role': 'system', 'content': 'Keep whole quotations.'}]}

    def freeze(self, name, policy=None, payload=None):
        return subject.freeze_payload_preview('translator', payload or self.payload,
                                              policy or self.policy, self.root / name)

    def test_actual_provider_payload_matches_frozen_preview(self):
        prompt = {'instruction': 'Preserve whole sentences.', 'input': {'englishUnits': ['A full sentence.']}}
        out = self.root / 'response.json'
        def caller(key, payload):
            preview = json.loads(out.with_suffix('.policy-preview.json').read_text())
            self.assertEqual(preview['payload'], payload)
            self.assertEqual(preview['policy'], self.policy)
            return {'id': 'request-1', 'model': 'test', 'choices': [
                {'finish_reason': 'stop', 'message': {'content': '{}'}}]}
        runner._model_call('translator', prompt, self.policy, out, '', caller)

    def test_plugin_only_does_not_retranslate_but_never_promotes_unknown(self):
        old = self.freeze('old.json')
        policy = copy.deepcopy(self.policy)
        policy['languageReview']['pluginImplementationSha256'] = 'b'
        new = self.freeze('new.json', policy)
        result = subject.compare_previews(old, new)
        self.assertEqual(result['classification'], 'plugin_only_migration')
        self.assertNotIn('translator', result['dependencyClosure'])
        self.assertTrue(result['blockedByPriorOutcome'])
        self.assertFalse(result['automaticReuseAuthorized'])

    def test_approval_rebinding_and_content_changes_are_distinct(self):
        old = self.freeze('old.json')
        policy = copy.deepcopy(self.policy)
        policy['sourceScope']['termApprovalReceipt']['reviewedBy'] = 'second human'
        new = self.freeze('new.json', policy)
        self.assertEqual(subject.compare_previews(old, new)['classification'], 'approval_rebinding')
        payload = copy.deepcopy(self.payload)
        payload['messages'][0]['content'] = 'Split quotations.'
        changed = self.freeze('changed.json', payload=payload)
        result = subject.compare_previews(old, changed, prior_outcome='failed')
        self.assertEqual(result['classification'], 'content_modified')
        self.assertIn('translator', result['dependencyClosure'])
        self.assertTrue(result['blockedByPriorOutcome'])

    def test_preview_tampering_and_in_place_change_rejected(self):
        old = self.freeze('old.json')
        with self.assertRaisesRegex(ValueError, 'Frozen model input changed'):
            self.freeze('old.json', payload={'model': 'other'})
        old['payload']['model'] = 'other'
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            subject.compare_previews(old, old)

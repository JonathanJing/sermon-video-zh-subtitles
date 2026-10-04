"""Independent owner/CAS/scope audit. All effects are local fixtures or inert callbacks."""
import copy
import unittest
from unittest.mock import patch
from tests.test_sermon_unified_cli import UnifiedCliTests
from scripts.sermon_unified import runtime as r, contracts as c, adapters
from scripts.sermon_temporal import unified


class IndependentUnifiedSafetyAudit(unittest.TestCase):
    setUp = UnifiedCliTests.setUp
    freeze = UnifiedCliTests.freeze

    def test_unknown_temporal_owner_is_reconciled_before_activity_returns(self):
        state = self.freeze()
        state['scheduler'] = 'temporal'
        state['steps']['media'].update(process='running', intentSha256='a' * 64)
        state = r.save(self.root, state['runKey'], state, state['stateRevision'])
        result = unified.execute(unified.UnifiedRequest(str(self.root), state['runKey'], state['planHash']))
        self.assertEqual(result['outcome'], 'unknown', 'A fresh Temporal activity must not complete with an orphaned running step')

    def test_revision_does_not_reuse_missing_success_receipt(self):
        state = self.freeze()
        r.pump(self.root, state['runKey'])
        state = r.load(self.root, state['runKey'])
        response = r.folder(self.root, state['runKey']) / ('response-' + c.digest(c.job_identity(state['manifest'], state['manifest']['steps'][0])) + '.json')
        response.unlink()
        state = r.mutate(self.root, state['runKey'], 'drain', state['stateRevision'])
        self.m['runRevision'] = 2
        try:
            result = r.submit(self.m, self.base, self.root, c.plan_hash(self.m), state['stateRevision'])
        except c.ContractError:
            return
        self.assertNotEqual(result['steps']['media']['process'], 'succeeded', 'Missing receipt cannot be reused as success')

    def test_canary_pump_never_dispatches_above_active_scope(self):
        state = self.freeze()
        # Isolate the dispatch scope guard; no provider call or content validation.
        extra = {'id': 'paid', 'stageId': 'layer2_group', 'adapter': 'canonical.layer2', 'locale': 'zh-Hans',
                 'scope': 'layer2_machine_candidate', 'dependsOn': ['media'], 'maxCostMicroUsd': 1}
        state['manifest']['steps'].append(extra)
        state['manifest']['budget']['limitMicroUsd'] = 1
        state['steps']['paid'] = {'process': 'not_started', 'artifact': 'not_started', 'review': 'not_required', 'publication': 'not_started', 'device': 'not_checked'}
        r.save(self.root, state['runKey'], state, state['stateRevision'])
        called = []
        def execute(m, base, step, out):
            called.append(step['id'])
            if step['id'] == 'media':
                return {'status': 'succeeded', 'kind': 'media_identity', 'artifact': 'verified', 'mediaSha256': m['source']['mediaSha256']}
            return {'status': 'succeeded', 'kind': 'target_language_candidate', 'artifact': 'verified', 'review': 'human_pending'}
        with patch.object(c, 'admit', return_value=[]), patch.object(adapters, 'inspect_step'):
            r.pump(self.root, state['runKey'], executor=execute)
        self.assertEqual(called, ['media'], 'A media canary cannot continue into a paid Layer 2 stage')

    def test_four_endpoints_for_one_locale_cannot_complete_three_locales(self):
        steps = [{'id': 'media', 'stageId': 'media_verify', 'adapter': 'media.verify'},
                 {'id': 'english', 'stageId': 'english_source', 'adapter': 'canonical.inspect'}]
        rows = {step['id']: {'process': 'succeeded', 'artifact': 'verified'} for step in steps}
        for locale in ('zh-Hans', 'ko', 'es'):
            for stage in ('layer2_group', 'translation_review', 'layer3_screen', 'listen_review'):
                sid = stage + '.' + locale
                steps.append({'id': sid, 'stageId': stage, 'locale': locale, 'adapter': 'review.gate'})
                rows[sid] = {'process': 'succeeded', 'artifact': 'verified', 'review': 'approved'}
            for kind in ('outline', 'reflection'):
                sid = kind + '.' + locale
                steps.append({'id': sid, 'stageId': 'study_product', 'locale': locale, 'adapter': 'review.gate', 'reviewKind': kind})
                rows[sid] = {'process': 'succeeded', 'artifact': 'verified', 'review': 'approved'}
        steps.append({'id': 'publish.zh', 'stageId': 'publish_endpoint', 'adapter': 'app.delivery', 'locale': 'zh-Hans'})
        rows['publish.zh'] = {'process': 'succeeded', 'artifact': 'verified', 'locales': ['zh-Hans'],
                              'validatedLocales': ['zh-Hans'], 'validatedEndpoints': ['ios_beta', 'firebase_dev', 'ios_prod', 'firebase_prod']}
        state = {'manifest': {'activeScope': 'dual_production_verified', 'transport': 'provider', 'locales': ['zh-Hans', 'ko', 'es'], 'steps': steps}, 'steps': rows}
        self.assertFalse(r.scope_satisfied(state), 'Korean/Spanish endpoint evidence is absent')

    def test_completion_scope_is_not_stage_entry_prerequisite(self):
        for stage, adapter, wrong_scope in [('asr', 'fixture.replay', 'media_verified'), ('layer3_unit', 'canonical.audio', 'translation_approved')]:
            manifest = copy.deepcopy(self.m)
            manifest['steps'].append({'id': 'wrong_scope', 'stageId': stage, 'adapter': adapter,
                                      'scope': wrong_scope, 'dependsOn': ['media']})
            self.assertIn('stage_scope_mismatch', c.admit(manifest, self.base))
        media_manifest = {'activeScope': 'media_verified', 'steps': [
            {'id': 'media', 'stageId': 'media_verify', 'scope': 'media_verified'},
            {'id': 'asr', 'stageId': 'asr', 'scope': 'english_ready_for_translation'}]}
        self.assertEqual([step['id'] for step in r.active_steps(media_manifest)], ['media'])
        text_manifest = {'activeScope': 'translation_approved', 'steps': [
            {'id': 'human_text', 'stageId': 'translation_review', 'scope': 'translation_approved'},
            {'id': 'tts', 'stageId': 'layer3_unit', 'scope': 'audio_screened'}]}
        self.assertEqual([step['id'] for step in r.active_steps(text_manifest)], ['human_text'])

    def test_reuse_preserves_original_receipt_across_three_revisions(self):
        state = self.freeze()
        r.pump(self.root, state['runKey'])
        for revision in (2, 3, 4):
            state = r.load(self.root, state['runKey'])
            state = r.mutate(self.root, state['runKey'], 'drain', state['stateRevision'])
            self.m['runRevision'] = revision
            state = r.submit(self.m, self.base, self.root, c.plan_hash(self.m), state['stateRevision'])
            self.assertEqual(state['revisionReuse']['reused'], ['media'], f'Revision {revision} must retain original receipt identity')
            r.pump(self.root, state['runKey'], executor=lambda *args: self.fail('Previously verified media repeated'))

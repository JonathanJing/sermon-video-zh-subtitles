"""Safety regression tests for the unified CLI's durable state machine."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.sermon_unified import runtime as runtime
from scripts.sermon_unified import contracts as contracts
from scripts.sermon_unified import adapters


class UnifiedRuntimeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = 'a' * 64

    def state(self):
        return {'runKey': self.key, 'stateRevision': 1, 'manifest': {
            'transport': 'production', 'activeScope': 'layer2_machine_candidate',
            'steps': [{'id': 'media', 'stageId': 'media_verify', 'adapter': 'media.verify',
                       'scope': 'layer2_machine_candidate', 'dependsOn': []}]},
            'steps': {'media': {'process': 'succeeded', 'artifact': 'verified'}},
            'cancelRequested': False, 'admission': 'open', 'events': [],
            'ownerEpoch': 0, 'owner': None}

    def test_media_step_cannot_claim_layer2_completion_by_scope_label(self):
        outcome, _ = runtime._project(self.state())
        self.assertNotEqual(outcome, 'succeeded')

    def test_read_only_load_does_not_create_missing_run(self):
        before = list(self.root.rglob('*'))
        with self.assertRaises(contracts.ContractError):
            runtime.load(self.root, self.key)
        self.assertEqual(list(self.root.rglob('*')), before)

    def test_stale_cas_cannot_cancel_current_state(self):
        state = self.state()
        runtime.save(self.root, self.key, state)
        with self.assertRaises(contracts.ContractError):
            runtime.mutate(self.root, self.key, 'cancel', expected=0)
        self.assertFalse(runtime.load(self.root, self.key)['cancelRequested'])

    def test_cancel_keeps_inflight_effect_and_closes_admission(self):
        state = self.state()
        state['steps']['media']['process'] = 'running'
        runtime.save(self.root, self.key, state)
        current = runtime.load(self.root, self.key)
        result = runtime.mutate(self.root, self.key, 'cancel', current['stateRevision'])
        self.assertEqual(result['steps']['media']['process'], 'running')
        self.assertEqual(result['admission'], 'closed')
        self.assertTrue(result['cancelRequested'])

    def test_lost_owner_requires_reconciliation_not_redispatch(self):
        state = self.state()
        state['steps']['media']['process'] = 'running'
        runtime.save(self.root, self.key, state)
        with patch.object(runtime.jobs, 'start_job', side_effect=AssertionError('duplicate dispatch')):
            result = runtime.start_owner(self.root, self.key)
        self.assertEqual(result['steps']['media']['process'], 'waiting_reconciliation')

    def test_translation_review_cannot_pass_machine_candidate_only(self):
        step = {'id': 'review', 'stageId': 'translation_review', 'adapter': 'canonical.inspect', 'locale': 'zh-Hans'}
        machine_only = {'nodes': {'text.zh-Hans': {'status': 'validated'},
                                 'audio.zh-Hans': {'status': 'blocked', 'reasonCode': 'translation_review_required'}}}
        with patch.object(adapters, 'inspect_step'), patch.object(adapters, 'config_path', return_value=Path('/unused')), \
                patch('scripts.sermon_unified_canonical_binding.inspect_bound', return_value=machine_only):
            result = adapters.execute({}, Path('/'), step, self.root / 'out.json')
        self.assertNotEqual(result['status'], 'succeeded')

from unittest.mock import patch
from tests.test_sermon_unified_cli import UnifiedCliTests
from scripts.sermon_temporal import unified
from scripts.sermon_unified import runtime as r,contracts as c

class UnifiedTemporalTests(UnifiedCliTests):
    def test_requires_drain_before_transfer(self):
        state=self.freeze()
        with self.assertRaises(c.ContractError):unified.transfer(self.root,state['runKey'],state['stateRevision'],scheduler='temporal')
    def test_same_store_temporal_execute_and_canonical_refusal(self):
        state=self.freeze();state=r.mutate(self.root,state['runKey'],'drain',state['stateRevision'])
        state=unified.transfer(self.root,state['runKey'],state['stateRevision'],scheduler='temporal')
        with self.assertRaises(c.ContractError):r.start_owner(self.root,state['runKey'])
        request=unified.UnifiedRequest(str(self.root),state['runKey'],state['planHash'])
        self.assertEqual(unified.execute(request)['outcome'],'succeeded')
        self.assertEqual(unified.execute(request)['outcome'],'succeeded')
    def test_unknown_effect_blocks_transfer(self):
        state=self.freeze();state['admission']='closed';state['steps']['media']['process']='waiting_reconciliation';state=r.save(self.root,state['runKey'],state,state['stateRevision'])
        with self.assertRaises(c.ContractError):unified.transfer(self.root,state['runKey'],state['stateRevision'],scheduler='temporal')

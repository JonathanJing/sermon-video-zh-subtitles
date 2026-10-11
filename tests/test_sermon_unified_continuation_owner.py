"""Owner CAS / CLI slot integration, with real continuation materialization.

Only c.admit's top-level execution/capability policy is stubbed for owner-CAS
storage tests: the fixture intentionally contains a source-only, not full-run,
capability plan. Producer inspect/response checks, generated JSON, file hashes,
revision reuse, state locks and all evidence validators remain real. CLI tests
stub only continue_owner so no detached process or model can be launched.
"""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sermon
from scripts.sermon_unified import contracts as c, runtime
from tests import test_sermon_unified_continuation as continuation_fixture


class ContinuationOwnerTests(unittest.TestCase):
    def setUp(self):
        self.f=continuation_fixture.ContinuationTests('test_unknown_is_zero_write_and_zero_dispatch')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root
        self.f.recipe['stages'][1]['requiredEvidence'].append(
            {'binding':'extraBudget','kind':'budget_authorization'})
        self.f.bind_recipe();self.f.state['planHash']=c.plan_hash(self.f.manifest)
        self.f.complete_source()
        self.f.state.update(schemaVersion='sermon-unified-state-v1',manifestSha256=c.digest(self.f.manifest),
            admission='open',scheduler='canonical',ownerJobId='test-existing-owner',ownerEpoch=3,
            owner=None,traceId='trace-offline',attemptId='attempt-offline',events=[],
            createdAt=runtime.now(),historicalReservedMicroUsd=17,historicalBudgetAuthorities=['b'*64])
        self.f.state['steps']['source'].update(review='human_pending',publication='not_started',
            device='not_checked',reservedMicroUsd=11)
        # A previously admitted, unchanged evidence reference must survive CAS.
        self.f.state['continuationEvidence']={'retainedBudget':copy.deepcopy(self.f.manifest['bindings']['budget'])}
        self.state=runtime.save(self.root,self.f.state['runKey'],self.f.state)
        self.key=self.state['runKey']

    def advance(self):
        # Explicit stub: testing storage/owner identity, not complete c.admit
        # readiness. Fixed adapter admission/materialization is NOT stubbed.
        with patch.object(c,'admit',return_value=[]):
            state,continued=runtime._advance_continuation(self.root,self.key,runtime.load(self.root,self.key))
        self.assertTrue(continued)
        return state

    def args(self,binding,path,revision=None):
        current=runtime.load(self.root,self.key)
        return sermon.parser().parse_args(['review','ingest','--run-id',self.key,
            '--state-root',str(self.root),'--binding',binding,'--receipt',str(path),
            '--expected-revision',str(current['stateRevision'] if revision is None else revision)])

    def supply_external_review(self):
        self.f.state=runtime.load(self.root,self.key)
        self.f.external_review()
        # External producer fixture creates files, not trusted owner state.
        return self.f.state['continuationEvidence']['englishReceipt']['path']

    def test_owner_revision_receipt_and_identity_are_persisted_atomically(self):
        writes=[];persist=runtime.jobs._persist
        def record(path,value):
            if Path(path).name=='unified-state.json':writes.append(copy.deepcopy(value))
            return persist(path,value)
        with patch.object(runtime.jobs,'_persist',side_effect=record):
            state=self.advance()
        self.assertEqual(state['manifest']['runRevision'],2)
        self.assertEqual(state['ownerJobId'],'test-existing-owner')
        self.assertEqual(state['ownerEpoch'],3)
        self.assertEqual(state['manifest']['budget'],self.state['manifest']['budget'])
        self.assertEqual(state['historicalReservedMicroUsd'],17)
        self.assertEqual(state['historicalBudgetAuthorities'],['b'*64])
        self.assertEqual(state['steps']['source']['reservedMicroUsd'],11)
        self.assertEqual(state['continuationEvidence'],self.state['continuationEvidence'])
        self.assertEqual(state['revisionReuse']['reused'],['source'])
        receipt=state['continuationReceipt']
        self.assertEqual(c.file_sha(receipt['path']),receipt['sha256'])
        self.assertEqual(c.read(receipt['path'])['priorPlanHash'],self.state['planHash'])
        new_writes=[s for s in writes if s['manifest']['runRevision']==2]
        self.assertEqual(len(new_writes),1)
        self.assertEqual(new_writes[0]['continuationReceipt'],receipt)
        self.assertEqual(runtime.load(self.root,self.key),state)

    def test_slot_ingest_records_evidence_without_manufacturing_gate_approval(self):
        state=self.advance();path=self.supply_external_review()
        before_reviews=copy.deepcopy(state['reviews'])
        before_gate=copy.deepcopy(state['steps']['english-review'])
        with patch.object(runtime,'continue_owner') as resume:
            result,code=sermon.run(self.args('englishReceipt',path))
        self.assertEqual(code,0)
        self.assertEqual(result['reviewIngest']['decision'],'accepted')
        resume.assert_called_once_with(self.root,self.key)
        current=runtime.load(self.root,self.key)
        self.assertEqual(current['continuationEvidence']['englishReceipt']['sha256'],c.file_sha(path))
        self.assertEqual(current['reviews'],before_reviews)
        self.assertEqual(current['steps']['english-review'],before_gate)
        self.assertNotEqual(current['steps']['english-review'].get('review'),'approved')

    def test_unbound_slot_and_fixture_transport_are_rejected_without_state_write(self):
        self.advance();path=self.supply_external_review()
        original=runtime.load(self.root,self.key)
        with patch.object(runtime,'continue_owner') as resume:
            with self.assertRaisesRegex(ValueError,'evidence_slot_missing'):
                sermon.run(self.args('unregisteredSlot',path))
            resume.assert_not_called()
        self.assertEqual(runtime.load(self.root,self.key),original)
        changed=copy.deepcopy(original);changed['manifest']['transport']='fixture'
        runtime.save(self.root,self.key,changed,original['stateRevision'])
        before=runtime.load(self.root,self.key)
        with patch.object(runtime,'continue_owner') as resume:
            with self.assertRaisesRegex(ValueError,'fixture_cannot_grant_human_approval'):
                sermon.run(self.args('englishReceipt',path))
            resume.assert_not_called()
        self.assertEqual(runtime.load(self.root,self.key),before)

    def test_hardcap_and_stale_cas_reject_slot_ingest_without_gate_approval(self):
        self.advance()
        authorization=c.read(self.f.source.root/'budget.json')
        approval=c.read(self.f.source.root/'budget-approval.json')
        authorization['authority']['globalBounds']['costMicrousd']=10000001
        approval['binding']['globalBounds']['costMicrousd']=10000001
        approval_path=self.f.source.root/'over-cap-approval.json'
        approval_path.write_text(json.dumps(approval))
        authorization['approvalReceipt']=str(approval_path)
        authorization['authority']['approvalSha256']=c.file_sha(approval_path)
        auth_path=self.f.source.root/'over-cap-authorization.json'
        auth_path.write_text(json.dumps(authorization))
        before=runtime.load(self.root,self.key)
        with patch.object(runtime,'continue_owner') as resume:
            with self.assertRaisesRegex(ValueError,'budget_execution_binding_changed'):
                sermon.run(self.args('extraBudget',auth_path))
            with self.assertRaisesRegex(ValueError,'state_revision_conflict'):
                sermon.run(self.args('extraBudget',auth_path,revision=before['stateRevision']-1))
            resume.assert_not_called()
        self.assertEqual(runtime.load(self.root,self.key),before)
        self.assertEqual(before['reviews'],{})

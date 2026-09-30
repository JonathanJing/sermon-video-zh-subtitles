import copy
import json
import unittest
from unittest.mock import patch
from scripts import sermon_strict_repair_planner as adapter
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from tests import test_sermon_strict_revisions as revisions
from tests import test_sermon_review_budget as budget_fixtures
from tests import test_sermon_strict_budget_adapter as runtime_fixtures


class DurablePlanningTests(unittest.TestCase):
    def setUp(self):
        self.f=revisions.RevisionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.store=budget.BudgetStore(self.f.f.root/'budget',budget_fixtures.authority())
        self.identity={k:self.f.parent[k] for k in budget.IDENTITY_FIELDS if k not in ('workUnitId','rubricSha256')}
        self.identity.update(workUnitId=self.f.parent['workUnitIds'][0],rubricSha256=self.f.review['rubricSha256'])
        self.planner=adapter.RepairPlanner(self.store,self.f.f.root/'jobs','7'*64)
        self.values=dict(candidate=self.f.parent,candidate_bytes=self.f.parent_bytes,review=self.f.review,
            review_bytes=(self.f.root/'review-receipt.json').read_bytes(),rubric=self.f.f.prepared['rubric'],
            input_manifest=self.f.inputs,gate=self.f.gate,state_revision=self.f.state,
            graph=[dict(workUnitId=self.identity['workUnitId'],layer=2,targetLocale='zh-Hans',dependsOn=[])])

    def record_review(self):
        row=self.store.reserve(self.identity,operation_id='review-1',kind='review',revision_id='r1',
            revision_number=1,input_sha256=c.canonical_sha256(self.f.inputs),bounds=budget_fixtures.amounts())
        self.store.mark_request(row['reservationId'])
        self.store.record_result(row['reservationId'],dict(executionStatus='succeeded',contentStatus='fail',
            receiptSha256=c.canonical_sha256(self.f.review),usage=budget_fixtures.amounts()))

    def test_only_verified_durable_review_can_propose_and_replay_same_plan(self):
        with self.assertRaisesRegex(ValueError,'repair_review_not_in_durable_budget'):
            self.planner.plan(lambda ledger:self.values)
        self.record_review()
        before=len(self.f.f.calls)
        result=self.planner.plan(lambda ledger:self.values)
        self.assertEqual(result['planning']['status'],'proposal')
        self.assertEqual(result,self.planner.plan(lambda ledger:self.values))
        strict.validate_repair(self.f.f.prepared,'candidate',result['repair']['plan']['toRevisionId'],result['repair'])
        self.assertEqual(len(self.f.f.calls),before)
        changed=adapter.RepairPlanner(self.store,self.f.f.root/'jobs','6'*64)
        with self.assertRaisesRegex(ValueError,'repair_history_binding_changed'):changed.plan(lambda ledger:self.values)

    def test_unknown_reservation_blocks_even_when_original_review_is_known(self):
        self.record_review();result=self.planner.plan(lambda ledger:self.values)
        self.store.reserve(self.identity,operation_id='repair-2',kind='content_revision',
            revision_id=result['repair']['plan']['toRevisionId'],revision_number=2,
            input_sha256='a'*64,bounds=budget_fixtures.amounts())
        outcome=self.planner.plan(lambda ledger:self.values)
        self.assertEqual(outcome['planning']['action'],'reconcile')
        self.assertIsNone(outcome['repair'])

    def test_write_failure_never_returns_proposal_and_restart_recovers_history(self):
        self.record_review()
        with patch.object(adapter.jobs,'_persist',side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):self.planner.plan(lambda ledger:self.values)
        first=self.planner.plan(lambda ledger:self.values)
        restarted=adapter.RepairPlanner(budget.BudgetStore(self.store.root,self.store.authority),
            self.f.f.root/'jobs','7'*64)
        self.assertEqual(restarted.plan(lambda ledger:self.values),first)

    def test_changed_gate_or_receipt_blocks_before_persisting_proposal(self):
        self.record_review()
        values=copy.deepcopy(self.values);values['gate']['stateRevision']='1'*64
        with self.assertRaisesRegex(ValueError,'stale_gate_state'):self.planner.plan(lambda ledger:values)
        values=copy.deepcopy(self.values);values['review']['reviewId']='renamed'
        values['review']['receiptSha256']=c.receipt_sha256(values['review'])
        with self.assertRaisesRegex(ValueError,'repair_review_not_in_durable_budget'):self.planner.plan(lambda ledger:values)

    def test_history_capacity_uses_persisted_bytes_before_write(self):
        self.record_review()
        captured=[]
        with patch.object(adapter.jobs,'_persist',side_effect=lambda path,value:captured.append(copy.deepcopy(value))):
            self.planner.plan(lambda ledger:self.values)
        history=captured[-1]
        compact=len(c.canonical_bytes(history))
        actual=len((json.dumps(history,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
        self.assertGreater(actual,compact)
        with patch.object(c,'MAX_BYTES',(compact+actual)//2), patch.object(adapter.jobs,'_persist') as persist:
            with self.assertRaisesRegex(ValueError,'repair_history_size_limit'):
                self.planner.plan(lambda ledger:self.values)
            persist.assert_not_called()


if __name__=='__main__':unittest.main()


class RealAdapterPlanningTests(unittest.TestCase):
    def setUp(self):
        self.runtime=runtime_fixtures.StrictBudgetTests();self.runtime.setUp();self.addCleanup(self.runtime.doCleanups)
        self.f=self.runtime.f
        self.planner=adapter.RepairPlanner(self.runtime.store,self.f.root/'jobs','7'*64)
        self.graph=[dict(workUnitId=self.f.prepared['workUnitId'],layer=2,targetLocale='zh-Hans',dependsOn=[])]
        with self.f.session():
            self.runtime.generate();self.f.mode='fail';self.runtime.review()

    def plan(self,root=None):
        return self.planner.plan_group(self.f.prepared,root or self.runtime.root,self.graph,
            created_at='2026-09-30T00:00:00Z')

    def test_actual_failed_group_plans_then_repeated_failure_survives_restart_and_revision(self):
        first=self.plan();self.assertEqual(first['planning']['action'],'repair_translation')
        self.assertEqual(first['planning']['status'],'proposal')
        self.assertEqual(first,self.plan())
        repair=first['repair'];child=self.f.root/'child';revision=repair['plan']['toRevisionId']
        with self.f.session():
            self.runtime.subject.generate(self.f.prepared,child,'candidate',revision,'synthetic',self.f.transport,
                bounds=runtime_fixtures.bounds(),usage_resolver=runtime_fixtures.measured,repair=repair)
            self.runtime.subject.review(self.f.prepared,child,'candidate',revision,'synthetic',self.f.transport,
                bounds=runtime_fixtures.bounds(),usage_resolver=runtime_fixtures.measured)
        self.runtime.restart()
        self.planner=adapter.RepairPlanner(self.runtime.store,self.f.root/'jobs','7'*64)
        second=self.plan(child)
        self.assertEqual(second['planning']['reasonCode'],'repeated_failure_without_new_evidence')
        self.assertIsNone(second['repair']);self.assertEqual(len(self.f.calls),4)

    def test_tampered_source_and_hidden_review_inventory_fail_without_new_transport(self):
        prepared=copy.deepcopy(self.f.prepared);prepared['units'][0]['english']='different'
        with self.assertRaises(ValueError):
            self.planner.plan_group(prepared,self.runtime.root,self.graph,created_at='2026-09-30T00:00:00Z')
        path=self.runtime.root/'review-receipt.json';path.rename(self.runtime.root/'hidden.json')
        with self.assertRaises(ValueError):self.plan()
        self.assertEqual(len(self.f.calls),2)

    def test_ledger_review_status_must_agree_with_exact_receipt(self):
        with self.runtime.store._locked() as (folder,ledger):
            row=next(r for r in ledger['reservations'].values() if r['request']['kind']=='review')
            row['result']['contentStatus']='pass'
            self.runtime.store._save(folder,ledger)
        with self.assertRaisesRegex(ValueError,'repair_review_budget_status_mismatch'):self.plan()
        self.assertEqual(len(self.f.calls),2)

    def test_actual_plan_receipt_logs_with_dependency_and_log_failure_replays_without_calls(self):
        with self.f.session():
            with adapter.accounting.stage('finished_review') as review_span:pass
            completed=[]
            result=self.planner.plan_group(self.f.prepared,self.runtime.root,self.graph,
                created_at='2026-09-30T00:00:00Z',depends_on=[review_span],completion_spans=completed)
            with patch.object(adapter.observation,'record',side_effect=adapter.accounting.AccountingWriteError('synthetic')):
                with self.assertRaises(adapter.accounting.AccountingWriteError):self.plan()
            self.assertEqual(self.plan(),result)
        self.assertEqual(len(completed),1)
        events,_=adapter.accounting.read_events(self.f.root/'logs')
        start=next(e for e in events if e['event']=='stage_started' and e.get('spanId')==completed[0])
        self.assertEqual(start['dependsOn'],[review_span])
        observed=next(e for e in events if e['event']=='rqc_observation' and e.get('spanId')==completed[0])
        self.assertEqual(observed['rqcEvidence']['receiptCanonicalJsonSha256'],
                         c.canonical_sha256(result['planning']['repairPlan']))
        self.assertEqual(observed['role'],'repair')
        self.assertEqual(len(self.f.calls),2)

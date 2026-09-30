"""Bound one-group repair to actual synthetic strict receipts and pure D5 plans."""
import copy
import json
import unittest
from unittest.mock import patch
from scripts import sermon_strict_layer2 as s
from scripts import sermon_review_contracts as c
from scripts import sermon_repair_planning as planning
from scripts import sermon_accounting as accounting
from tests import test_sermon_strict_layer2 as fixtures


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.StrictAdapterTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        with self.f.session():
            self.parent=self.f.generate();self.f.mode='fail';self.review=self.f.review()
        self.root=self.f.root/'revision';self.child=self.f.root/'repair'
        self.parent_bytes=(self.root/'candidate.json').read_bytes()
        self.inputs=c.read_snapshot(self.root/'review-input.json')[0]
        self.state='8'*64
        budget=planning.BudgetSnapshot('7'*64,self.state,'candidate',self.f.prepared['workUnitId'],
            'r1','r1','a'*64,'b'*64,0,1,0)
        gate={'schemaVersion':'sermon-review-gate-decision-v1',
            **{k:self.parent[k] for k in ('candidateId','revisionId','targetLocale','workUnitIds','artifactSha256','policySha256')},
            'gateDecisionId':'gate','gateVersion':'rqc-layer2-gate-v1','stateRevision':self.state,
            'reviewReceiptRefs':[s.reference('review',(self.root/'review-receipt.json').read_bytes())],
            'rubricSha256':c.canonical_sha256(self.f.prepared['rubric']), 'approvalReceiptRefs':[],
            'admissionStatus':'blocked','reasonCodes':['review_failed'],'allowedNextActions':['repair_translation'],
            'createdAt':'2026-09-30T00:00:00Z'}
        result=planning.plan_repair(candidate=self.parent,candidate_bytes=self.parent_bytes,review=self.review,
            review_bytes=(self.root/'review-receipt.json').read_bytes(),rubric=self.f.prepared['rubric'],
            input_manifest=self.inputs,gate=gate,state_revision=self.state,budget=budget,
            graph=[dict(workUnitId=self.f.prepared['workUnitId'],layer=2,targetLocale='zh-Hans',dependsOn=[])])
        self.plan=result['repairPlan'];self.assertIsNotNone(self.plan)
        self.repair=dict(parentRevision=self.parent,parentCandidateBytes=self.parent_bytes,plan=self.plan,
            triggerReview=self.review,inputManifest=self.inputs,priorRevisions=[],priorRepairs=[],
            sidecars={self.plan[k]['artifactId']:c.canonical_bytes(result[v]) for k,v in
                [('constraintsRef','constraints'),('budgetRef','budgetSnapshot'),('dependencyClosureRef','dependencyClosure')]})

    def generate(self,repair=None):
        return s.generate(self.f.prepared,self.child,'candidate',self.plan['toRevisionId'],'fixture',
            self.f.transport,repair=self.repair if repair is None else repair)

    def test_repair_is_new_immutable_group_and_reviewer_never_sees_generator_context(self):
        with self.f.session():
            child=self.generate();self.assertEqual(child['revisionNumber'],2)
            self.assertEqual(child['parentRevisionId'],'r1')
            self.assertEqual(child['repairPlanId'],self.plan['repairPlanId'])
            self.assertEqual((self.root/'candidate.json').read_bytes(),self.parent_bytes)
            request=json.loads(self.f.calls[-1]['messages'][1]['content'])
            self.assertEqual(request['repairPlanId'],self.plan['repairPlanId'])
            self.assertEqual(request['issues'],self.review['issues'])
            self.f.mode='pass'
            receipt=s.review(self.f.prepared,self.child,'candidate',child['revisionId'],'fixture',self.f.transport)
            self.assertEqual(receipt['reviewVerdict'],'pass')
            reviewer_input=json.loads(self.f.calls[-1]['messages'][1]['content'])
            self.assertNotIn('parentCandidate',reviewer_input)
            self.assertNotIn('issues',reviewer_input)
            self.assertEqual(self.generate(),child);self.assertEqual(len(self.f.calls),4)
            c.validate_revision_lineage(child,self.parent,self.plan)

    def test_stale_identity_scope_sidecars_or_limit_reject_before_call(self):
        for change in ('identity','scope','sidecar','limit','source'):
            with self.subTest(change=change),self.f.session():
                repair=copy.deepcopy(self.repair)
                if change=='identity':repair['plan']['candidateId']='other'
                elif change=='scope':repair['plan']['affectedWorkUnitIds']=['l2.zh-Hans.other']
                elif change=='sidecar':repair['sidecars'][next(iter(repair['sidecars']))]=b'{}'
                elif change=='limit':repair['parentRevision']['revisionNumber']=3
                else:repair['parentCandidateBytes']+=b' '
                with self.assertRaises(ValueError):self.generate(repair)
                self.assertEqual(len(self.f.calls),2)

    def test_saved_repair_response_recovers_without_regenerating_parent_or_second_call(self):
        with self.f.session():
            with patch.object(accounting,'record_api_attempt',side_effect=accounting.AccountingWriteError('fault')):
                with self.assertRaises(accounting.AccountingWriteError):self.generate()
            self.assertEqual(len(self.f.calls),3)
            self.generate();self.assertEqual(len(self.f.calls),3)
            self.assertEqual((self.root/'candidate.json').read_bytes(),self.parent_bytes)

    def test_review_rejects_missing_or_changed_repair_context_before_call(self):
        with self.f.session():
            child=self.generate();path=self.child/'repair-plan.json'
            value=c.read_snapshot(path)[0];value['fromRevisionId']='other';path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                s.review(self.f.prepared,self.child,'candidate',child['revisionId'],'fixture',self.f.transport)
            self.assertEqual(len(self.f.calls),3)


if __name__=='__main__':unittest.main()

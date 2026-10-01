"""Bounded structural reasons, using the actual model-facing contract."""
import copy
import json
import unittest

from scripts import sermon_review_contracts as c
from scripts import sermon_review_diagnostics as d
from scripts import sermon_strict_layer2 as s
from tests import test_sermon_strict_layer2 as strict_fixtures


class ReviewDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        f=strict_fixtures.StrictAdapterTests();f.setUp();self.addCleanup(f.doCleanups)
        self.ids=f.group['sourceUnitIds'];self.hash='a'*64
        self.schema=s.response_contract(f.prepared,'reviewer',
            candidate={'targetUtterances':['fixture']},input_manifest={'reviewedArtifactSha256':self.hash})
        self.value=dict(reviewedArtifactSha256=self.hash,reviewVerdict='pass',
            checks=[dict(checkId=x,result='pass',evidence='fixture') for x in sorted(c.HARD_CHECKS)],
            issues=[],assessedUnitIds=self.ids,unassessedUnitIds=[])

    def classify(self,value):return d.classify(value,self.schema,self.ids,c.HARD_CHECKS)

    def test_fixed_reasons_do_not_expose_illegal_keys_or_values(self):
        cases=[]
        v=copy.deepcopy(self.value);v['private-header-api-key']='secret';cases.append((v,'invalid_fields',[]))
        v=copy.deepcopy(self.value);v['checks'][0]['result']='private-secret';cases.append((v,'invalid_enum',['checks',0,'result']))
        v=copy.deepcopy(self.value);v['checks'][0]['private-message']='secret';cases.append((v,'invalid_fields',['checks',0]))
        v=copy.deepcopy(self.value);v.pop('reviewVerdict');cases.append((v,'invalid_fields',['reviewVerdict']))
        v=copy.deepcopy(self.value);v['checks']={};cases.append((v,'invalid_field_type',['checks']))
        v=copy.deepcopy(self.value);v['checks']=[];cases.append((v,'invalid_field_bounds',['checks']))
        v=copy.deepcopy(self.value);v['reviewedArtifactSha256']='secret';cases.append((v,'changed_reviewed_artifact',['reviewedArtifactSha256']))
        v=copy.deepcopy(self.value);v['checks'][0]['evidence']=' ';cases.append((v,'invalid_evidence',['checks',0,'evidence']))
        for value,reason,path in cases:
            with self.subTest(reason=reason,path=path):
                finding=self.classify(value)
                self.assertEqual(finding,dict(reasonCode=reason,fieldPath=path))
                self.assertNotIn('secret',json.dumps(finding));self.assertNotIn('private',json.dumps(finding))

    def test_semantic_reasons_include_duplicates_partition_and_verdict_support(self):
        cases=[]
        v=copy.deepcopy(self.value);v['checks'][1]=copy.deepcopy(v['checks'][0]);cases.append((v,'duplicate_check'))
        v=copy.deepcopy(self.value);v['unassessedUnitIds']=self.ids[:1];cases.append((v,'coverage_partition_mismatch'))
        v=copy.deepcopy(self.value);v['assessedUnitIds']=[];cases.append((v,'coverage_partition_mismatch'))
        v=copy.deepcopy(self.value);v['checks'][0]['result']='fail';cases.append((v,'unsupported_pass'))
        v=copy.deepcopy(self.value);v['reviewVerdict']='needs_rework';cases.append((v,'rework_evidence_missing'))
        v=copy.deepcopy(self.value);v['reviewVerdict']='inconclusive';cases.append((v,'inconclusive_evidence_missing'))
        v=copy.deepcopy(self.value);v['reviewVerdict']='not_assessed';cases.append((v,'not_assessed_has_assessment'))
        issue=dict(issueId='issue-1',reasonCode='meaning_omission',severity='major',
            sourceUnitIds=self.ids,targetUnitIds=[],evidence='fixture')
        v=copy.deepcopy(self.value);v['issues']=[issue,copy.deepcopy(issue)];cases.append((v,'duplicate_issue'))
        for value,reason in cases:
            with self.subTest(reason=reason):self.assertEqual(self.classify(value)['reasonCode'],reason)

    def test_unhashable_arbitrary_json_is_classified_before_semantics(self):
        v=copy.deepcopy(self.value);v['checks'][0]['checkId']={'secret':'message'}
        self.assertEqual(self.classify(v)['reasonCode'],'invalid_enum')
        self.assertEqual(d.finding('invalid_fields',['checks',0,'secret-key','evidence']),
                         dict(reasonCode='invalid_fields',fieldPath=['checks',0]))
        with self.assertRaises(ValueError):d.finding('secret-reason')

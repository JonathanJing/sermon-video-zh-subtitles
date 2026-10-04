import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from scripts.experiments import ste_paired_admission as subject
from tests import test_produce_target_language_candidate as fixture


class PairedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.ProduceTargetLanguageCandidateTests('test_compiles_valid_candidate_without_human_approval')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        def ref(name, value):
            path = self.root/name
            path.write_text(value if isinstance(value,str) else json.dumps(value))
            return {'path':name,'sha256':subject.identity.sha256(path)}
        self.ref = ref
        a, b = 'Keep all rules. OLD. Preserve source.', 'Keep all rules. NEW. Preserve source.'
        unit = self.fixture.anchor['sourceUnits'][0]
        self.samples = [{'id':f's{i}','locale':'zh-Hans','stratum':('reading','metadata','spoken')[i%3],
                         'split':'holdout' if i==5 else 'evaluation','sourceUnitIds':[unit['sourceUnitId']],
                         'caseTags':[tag], 'fixedDraft':ref(f'draft-{i}.json',{'draft':'fixed'})}
                        for i,tag in enumerate(sorted(subject.CASE_TAGS))]
        params = {'reasoning_effort':'medium','response_format':{'type':'json_object'},'max_completion_tokens':100}
        payloads = []
        for sample in self.samples:
            data = {'translationGroupId':sample['id'],'sourceUnitIds':sample['sourceUnitIds'],
                    'englishUnits':[{'sourceUnitId':unit['sourceUnitId'],'english':unit['english']}],
                    'targetLocale':'zh-Hans','draft':{'draft':'fixed'}}
            for arm, text in (('A',a),('B',b)):
                body = {'model':'fixture-model', **params, 'messages':[{'role':'system','content':text},
                                                {'role':'user','content':json.dumps(data)}]}
                payloads.append({'sampleId':sample['id'],'arm':arm,'artifact':ref(f"{sample['id']}-{arm}.json",body)})
        self.plan = {'schemaVersion':subject.SCHEMA,'experimentId':'fixture-ste','revision':1,
            'changeKind':'reviewer_issues','candidateA':ref('a.txt',a),'candidateB':ref('b.txt',b),
            'replacement':{'start':a.index('OLD'),'end':a.index('OLD')+3,'text':'NEW'},
            'referenceRules':{'reading':'fixture reading rule','metadata':'fixture metadata rule','spoken':'fixture spoken rule'},
            'source':ref('source.json',self.fixture.source),'anchor':ref('anchor.json',self.fixture.anchor),
            'samples':self.samples,'model':'fixture-model','parameters':params,
            'promptVersions':{'A':'a-v1','B':'b-v1'},'policyVersions':{'A':'pa-v1','B':'pb-v1'},
            'payloads':payloads,'budget':{'maxCostMicroUsd':100,'perArmMaxCalls':6,'maxInputTokens':1000,
                                        'maxOutputTokens':100,'repeats':1,'maxWallSeconds':100},
            'pricing':ref('prices.json',{'model':'fixture-model','inputMicroUsdPerMillionTokens':10,
                'outputMicroUsdPerMillionTokens':10,'sourceUrl':'https://openai.com/api/pricing/','verifiedAt':'2026-10-04T00:00:00Z'}),
            'blinding':{'reviewersRequired':2,'codeMode':'random_per_pair','keyOpening':'after_scores_frozen',
                        'adjudicationRule':'Independent human resolves disagreements'},
            'noninferiority':{'fidelityLossMax':0.01,'unauthorizedReferencesMax':0,'missedConcernRateDeltaMax':0.01,
                             'naturalnessDeltaMin':-0.1,'criticalErrorsMax':0,'uncertaintyMethod':'paired bootstrap 95 percent'},
            'execution':{'startsAt':'2026-10-04T00:00:00Z','endsAt':'2026-10-05T00:00:00Z',
                'cacheNamespace':'artifacts/ste-ab/fixture','unknownOutcome':'reconcile_without_retry',
                'rollback':'keep_production_A_unchanged','productionPromptMutation':False},'approval':None}
        self.now = datetime(2026,10,4,12,tzinfo=timezone.utc)

    def approve_fixture(self):
        self.plan['approval'] = self.ref('approval.json',{'schemaVersion':'sermon-ste-experiment-approval-v1',
            'planSha256':subject.digest(self.plan),'humanApproval':True,'reviewedBy':'fixture-human',
            'reviewedAt':'2026-10-04T01:00:00Z','approvedScopes':['candidate','samples','budget','window']})

    def test_pending_candidate_never_dispatches_and_signed_plan_has_isolated_request_ids(self):
        result = subject.admit(self.plan,self.root,now=self.now)
        self.assertEqual(result['status'],'blocked'); self.assertEqual(result['apiCallsMade'],0)
        self.approve_fixture()
        result = subject.admit(self.plan,self.root,now=self.now)
        self.assertEqual(result['status'],'admitted_for_isolated_runner')
        self.assertEqual(len(set(result['requestIdentities'])),12)
        self.assertFalse(result['productionPromptMutation'])

    def test_candidate_extra_edit_model_change_and_budget_overflow_fail(self):
        for mutate, error in [
            (lambda p:p.update(candidateB=self.ref('bad.txt','unrelated prompt')), 'beyond'),
            (lambda p:p['budget'].update(maxCostMicroUsd=0), 'hard budgets'),
            (lambda p:p['execution'].update(cacheNamespace='artifacts/ste-ab/../../production'), 'escapes')]:
            plan = copy.deepcopy(self.plan); mutate(plan)
            with self.assertRaisesRegex(ValueError,error):subject.admit(plan,self.root,now=self.now)
        row = self.plan['payloads'][0]
        body = json.loads((self.root/row['artifact']['path']).read_text()); body['model']='different-model'
        row['artifact'] = self.ref('bad-model.json',body)
        with self.assertRaisesRegex(ValueError,'model or fixed API'):subject.admit(self.plan,self.root,now=self.now)

    def test_approval_is_invalidated_by_threshold_change(self):
        self.approve_fixture(); self.plan['noninferiority']['fidelityLossMax']=0.1
        with self.assertRaisesRegex(ValueError,'not bound'):subject.admit(self.plan,self.root,now=self.now)

    def test_partial_repair_retains_unresolved_concerns(self):
        subject.check_unresolved_concerns(['one','two'],['one'],['two'],status='fail')
        with self.assertRaisesRegex(ValueError,'lost'):
            subject.check_unresolved_concerns(['one','two'],['one'],[],status='pass')
        subject.check_unresolved_concerns(['one','two'],['one','two'],[],status='pass')

    def test_blind_sheet_reuses_semantic_gate_without_revealing_arms(self):
        outputs = {}
        for sample in self.samples:
            result = {'translationGroupId':sample['id'],'sourceUnitIds':sample['sourceUnitIds'],
                      'targetUtterances':['样本文字。'],
                      'coverage':[{'sourceUnitId':sample['sourceUnitIds'][0],'targetText':'样本文字。'}],
                      'semanticReview':{'status':'pass',
                         'checks':{key:'pass' for key in subject.layer2_ab.production.SEMANTIC_CHECKS},
                         'evidence':'fixture','uncertainty':[],'issues':[]}}
            outputs[sample['id']]={'A':copy.deepcopy(result),'B':copy.deepcopy(result)}
        outputs['s0']['B']['semanticReview'].update(status='fail',issues=['unresolved concern'])
        sheet, key = subject.blind_pairs(self.plan,outputs)
        encoded = json.dumps(sheet)
        self.assertNotIn('"arm"',encoded);self.assertNotIn('machineGate',encoded)
        self.assertEqual(len(key['codes']),12)
        self.assertEqual(sum(row['machineGate']=='fail' for row in key['codes']),1)

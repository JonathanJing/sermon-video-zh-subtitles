import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import sermon_study_generation as g
from scripts import sermon_unified_study as owner
from scripts import sermon_provider_limits as limits
from scripts.sermon_unified import contracts as c

class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.manifest={'productionRunId':'run','source':{},'content':{'pageId':'page'},'bindings':{}}
        values={'source':{},'anchor':{'sourceUnits':[{'sourceUnitId':'u1','text':'English'}]},
            'candidate':{'groups':[{'sourceUnitIds':['u1'],'targetText':'翻译'}]},'translationReview':{},
            'policy':{'schemaVersion':'sermon-study-generation-policy-v1','model':'gpt-6-sol',
                'reasoningEffort':'high','promptVersion':'grounded-study-v1','batchGroups':1,
                'requestLimits':limits.DEFAULT_REQUEST_LIMITS},'terminology':{'series':'统一名称'}}
        for k,v in values.items():self.bind(k,v)
        self.config=self.root/'config.json';self.config.write_text(json.dumps({'schemaVersion':'sermon-unified-study-inputs-v2',
            'kind':'outline','revision':'r1','jobRoot':str(self.root/'jobs'),
            'inputs':{k:k for k in [*values,'budgetAuthorization']}}))
        self.step={'id':'outline','locale':'zh-Hans'}
        self.review=patch.object(g,'validate_review');self.review.start();self.addCleanup(self.review.stop)
        self.code=patch.object(g,'code_identity',return_value='c'*64);self.code.start();self.addCleanup(self.code.stop)
        self.authorize()
        self.calls=[]
    def bind(self,k,v):
        path=self.root/(k+'.json');path.write_text(json.dumps(v,ensure_ascii=False))
        self.manifest['bindings'][k]={'path':str(path),'sha256':c.file_sha(path)}
    def authorize(self,cost=1000000):
        p=g.prepare(self.manifest,self.root,self.config,self.step,authorize=False)
        bounds={'requests':10,'wallTimeMs':3000000,'costMicrousd':cost}
        binding={'productionRunId':'run','executionSha256':p['identity'],'codeIdentitySha256':p['codeIdentity'],
            'budgetRoot':str(p['root']),'globalBounds':bounds,'requestLimits':p['limits']}
        approval={'schemaVersion':'sermon-study-budget-approval-v1','binding':binding,'humanApproval':True,
            'decision':'approved','operatorEvidence':'offline fixture only','reviewedBy':'test','reviewedAt':'2026-10-04T00:00:00Z'}
        self.bind('approval',approval);sha=self.manifest['bindings']['approval']['sha256']
        self.bind('budgetAuthorization',{'schemaVersion':'sermon-study-budget-authorization-v1','binding':binding,
            'authority':{'approvalSha256':sha,'globalBounds':bounds,'requestLimits':p['limits']},
            'approvalReceipt':'approval.json','approvalReceiptSha256':sha})
    def provider(self,*args):
        self.calls.append(args)
        return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'sections':[
            {'title':'主题','body':'默想','sourceUnitIds':['u1']}]})}}],'usage':{'prompt_tokens':12,'completion_tokens':9}}
    def run_generation(self,transport=None):
        return owner.execute(self.manifest,self.root,self.config,self.step,self.root/'result.json',transport=transport or self.provider)
    def test_generation_resume_human_pending_and_verify(self):
        self.assertEqual(owner.inspect(self.manifest,self.root,self.config,self.step)['requestCount'],1)
        result=self.run_generation();self.assertEqual(result['freshApiAttempts'],1)
        self.assertEqual(result['review'],'human_pending');self.assertFalse(result['productionEligible'])
        again=self.run_generation();self.assertEqual(again['freshApiAttempts'],0);self.assertEqual(len(self.calls),1)
        owner.verify_result(self.manifest,self.root,self.config,self.step,again)
    def test_invalid_grounding_retained_no_paid_retry(self):
        def bad(*args):
            result=self.provider(*args);result['choices'][0]['message']['content']=json.dumps({'sections':[{'title':'a','body':'b','sourceUnitIds':['other']}]});return result
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'grounding'):self.run_generation(bad)
        self.assertEqual(len(self.calls),1)
    def test_unknown_outcome_never_retried(self):
        def fail(*args):self.calls.append(args);raise TimeoutError('unknown')
        with self.assertRaises(TimeoutError):self.run_generation(fail)
        with self.assertRaisesRegex(ValueError,'outcome_unknown'):self.run_generation()
        self.assertEqual(len(self.calls),1)
    def test_tiny_budget_zero_calls(self):
        self.authorize(cost=1)
        with self.assertRaisesRegex(ValueError,'budget_exhausted'):self.run_generation()
        self.assertEqual(self.calls,[])
    def test_changed_terminology_zero_calls(self):
        (self.root/'terminology.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'binding_changed'):self.run_generation()
        self.assertEqual(self.calls,[])
    def test_missing_approval_zero_calls(self):
        (self.root/'approval.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'approval_not_bound'):self.run_generation()
        self.assertEqual(self.calls,[])
    def test_oversized_prompt_zero_calls(self):
        self.bind('terminology',{'text':'x'*18000})
        with self.assertRaisesRegex(ValueError,'input_bound_exceeded'):self.run_generation()
        self.assertEqual(self.calls,[])
    def test_code_drift_zero_calls(self):
        with patch.object(g,'code_identity',return_value='d'*64),self.assertRaisesRegex(ValueError,'budget_binding_changed'):
            self.run_generation()
        self.assertEqual(self.calls,[])
    def test_retained_raw_response_tamper_rejected(self):
        result=self.run_generation()
        receipt=c.read(result['generationReceiptPath'])
        raw=self.root/'.jobs.study-budget'/'responses'/(receipt['calls'][0]['requestSha256']+'.json')
        raw.write_text('{}')
        with self.assertRaisesRegex(ValueError,'retained_study_response_changed'):
            owner.verify_result(self.manifest,self.root,self.config,self.step,result)
        self.assertEqual(len(self.calls),1)
    def test_existing_other_output_rejected_before_call(self):
        (self.root/'outline-study.json').write_text(json.dumps({'producerIdentity':'other'}))
        with self.assertRaisesRegex(ValueError,'study_output_changed'):self.run_generation()
        self.assertEqual(self.calls,[])

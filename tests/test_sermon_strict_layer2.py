"""D3 focused developer tests: synthetic provider responses only."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import sermon_strict_layer2 as s
from scripts import sermon_review_contracts as c
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import target_language_policy as policies
from tests import test_produce_target_language_candidate as legacy_fixtures
from tests.test_sermon_review_contracts import load


class StrictAdapterTests(unittest.TestCase):
    def setUp(self):
        f=legacy_fixtures.ProduceTargetLanguageCandidateTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.calls=[]
        draft=copy.deepcopy(f.policy);draft.pop('componentSha256');draft['schemaVersion']=policies.POLICY_V3
        draft['reviewMode']='strict_verifier';draft['translator']['promptVersion']='astra-strict-generator-v1';draft['reviewer']['promptVersion']='sol-strict-verifier-v1'
        rubric=load('rubric');rubric['requiredLanguagePluginChecks']=draft['languageReview']['requiredChecks']
        draft['reviewContract']=dict(rubricCanonicalJsonSha256=c.canonical_sha256(rubric),reviewReceiptSchemaVersion='sermon-review-receipt-v1',candidateRevisionSchemaVersion='sermon-candidate-revision-v1',inputManifestSchemaVersion='sermon-review-input-manifest-v1',revisionGranularity='translation_group')
        policy=policies.freeze_strict_policy(draft,rubric)
        self.args=[s.material_bytes(v) for v in (f.source,f.anchor,policy,rubric)]
        self.group={k:f.evidence['groups'][0][k] for k in ('translationGroupId','sourceUnitIds')}
        self.prepared=s.prepare(*self.args,self.group)
        self.mode='pass'

    def transport(self,key,payload,*,response_observer):
        self.calls.append(payload);inp=json.loads(payload['messages'][1]['content'])
        aid=accounting.record_api_started(payload['model'],accounting.request_metadata(payload))
        if hasattr(response_observer,'request_started'):response_observer.request_started(aid)
        if payload['model']=='gpt-6-astra':
            value={k:self.f.evidence['groups'][0][k] for k in ('translationGroupId','sourceUnitIds','targetUtterances','coverage')}
        else:
            value=dict(reviewedArtifactSha256=inp['reviewedArtifactSha256'],reviewVerdict='pass',
                checks=[dict(checkId=check,result='pass',evidence='synthetic evidence') for check in sorted(c.HARD_CHECKS)],
                issues=[],assessedUnitIds=inp['sourceUnitIds'],unassessedUnitIds=[])
            if self.mode=='rewrite':value['targetUtterances']=['unauthorized change']
            if self.mode=='fail':
                value['reviewVerdict']='needs_rework';value['checks'][0]['result']='fail'
                value['issues']=[dict(issueId='issue-1',reasonCode='meaning_omission',severity='major',sourceUnitIds=inp['sourceUnitIds'],targetUnitIds=inp['targetUnitIds'],evidence='synthetic omission')]
        response={'id':'response-'+str(len(self.calls)),'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
            'usage':{'input_tokens':100,'output_tokens':20}}
        response_observer(response,aid,.01)
        accounting.record_api_attempt(payload['model'],response,.01,attempt_id=aid)
        return response

    def session(self):return profile.session(self.root/'logs','strict-test',work_kind='production',evidence_mode='synthetic')
    def generate(self):return s.generate(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport)
    def review(self):return s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport)

    def test_immutable_generator_and_read_only_reviewer_use_independent_inputs(self):
        with self.session():
            manifest=self.generate();before=(self.root/'revision/candidate.json').read_bytes();receipt=self.review()
            self.assertEqual((self.root/'revision/candidate.json').read_bytes(),before)
            self.assertEqual([p['model'] for p in self.calls],['gpt-6-astra','gpt-6-sol'])
            inp=json.loads(self.calls[1]['messages'][1]['content'])
            self.assertEqual(inp['candidate'],json.loads(before));self.assertNotIn('generationReceiptRef',inp)
            self.assertNotIn('astraDraft',inp);self.assertNotIn('parentConversation',inp)
            self.assertEqual(receipt['reviewVerdict'],'pass');self.assertEqual(receipt['executionStatus'],'succeeded')
            self.assertNotIn('targetUtterances',receipt);self.assertNotIn('admissionStatus',receipt)
            self.assertEqual(self.generate(),manifest);self.assertEqual(self.review(),receipt)
            self.assertEqual(len(self.calls),2)
        rows,damaged=accounting.read_events(self.root/'logs');self.assertFalse(damaged)
        self.assertEqual(len([e for e in rows if e['event']=='api_attempt']),2)
        self.assertEqual(len([e for e in rows if e['event']=='rqc_observation']),4)

    def test_content_failure_is_receipt_not_rewrite_or_automatic_retranslation(self):
        with self.session():
            self.generate();before=(self.root/'revision/candidate.json').read_bytes();self.mode='fail';receipt=self.review()
            self.assertEqual(receipt['reviewVerdict'],'needs_rework');self.assertEqual(receipt['executionStatus'],'succeeded')
            self.assertEqual(self.review(),receipt);self.assertEqual(len(self.calls),2)
            self.assertEqual((self.root/'revision/candidate.json').read_bytes(),before)

    def test_reviewer_cannot_return_candidate_changes(self):
        with self.session():
            self.generate();before=(self.root/'revision/candidate.json').read_bytes();self.mode='rewrite'
            receipt=self.review();self.assertEqual(receipt['executionStatus'],'failed')
            self.assertEqual(receipt['reviewVerdict'],'not_assessed')
            self.assertEqual((self.root/'revision/candidate.json').read_bytes(),before);self.assertEqual(len(self.calls),2)
            self.assertEqual(self.review(),receipt)
            self.assertEqual(len(self.calls),2)

    def test_changed_candidate_during_review_is_rejected(self):
        with self.session():
            self.generate();original=self.transport
            def changed(*args,**kwargs):
                response=original(*args,**kwargs);(self.root/'revision/candidate.json').write_text('{}');return response
            with self.assertRaisesRegex(c.ContractError,'candidate_changed_during_review'):
                s.review(self.prepared,self.root/'revision','candidate','r1','fixture',changed)
            self.assertFalse((self.root/'revision/review-receipt.json').exists())

    def test_source_or_policy_preflight_rejects_before_transport(self):
        source=json.loads(self.args[0]);source['source']['media']=None
        with self.assertRaises(ValueError):s.prepare(s.material_bytes(source),*self.args[1:],self.group)
        policy=json.loads(self.args[2]);policy['schemaVersion']=policies.POLICY_V2
        with self.assertRaises(ValueError):s.prepare(*self.args[:2],s.material_bytes(policy),self.args[3],self.group)
        self.assertEqual(self.calls,[])

    def test_valid_response_survives_finish_logging_failure_without_second_call(self):
        original=accounting.record_api_attempt
        with self.session():
            with patch.object(accounting,'record_api_attempt',side_effect=accounting.AccountingWriteError('fault')):
                with self.assertRaises(accounting.AccountingWriteError):self.generate()
            self.assertTrue((self.root/'revision/generator.raw.json').is_file())
            self.assertFalse((self.root/'revision/revision.json').exists())
            self.generate();self.assertEqual(len(self.calls),1)
        self.assertEqual(len(accounting.summarize(self.root/'logs')['unfinishedApiAttempts']),1)

    def test_unknown_transport_outcome_blocks_reviewer_without_regeneration(self):
        with self.session():
            self.generate();before=(self.root/'revision/candidate.json').read_bytes();attempts=[]
            def lost(key,payload,*,response_observer):
                attempts.append(True)
                aid=accounting.record_api_started(payload['model'],accounting.request_metadata(payload))
                response_observer.request_started(aid)
                raise TimeoutError('synthetic private detail must not be logged')
            receipt=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',lost)
            self.assertEqual(receipt['executionStatus'],'outcome_unknown');self.assertEqual(receipt['reviewVerdict'],'not_assessed')
            self.assertEqual(s.review(self.prepared,self.root/'revision','candidate','r1','fixture',lost),receipt)
            self.assertEqual(attempts,[True]);self.assertEqual(len(self.calls),1)
            self.assertEqual((self.root/'revision/candidate.json').read_bytes(),before)
        self.assertNotIn('synthetic private detail',(self.root/'logs/events.jsonl').read_text())

    def test_review_refuses_changed_source_bytes_and_prepared_mutation_before_call(self):
        with self.session():
            self.generate();prepared=copy.deepcopy(self.prepared)
            prepared['units'][0]['english']='changed'
            with self.assertRaisesRegex(c.ContractError,'strict_prepared_inputs_changed'):
                s.review(prepared,self.root/'revision','candidate','r1','fixture',self.transport)
            changed=s.prepare(self.args[0]+b' ',*self.args[1:],self.group)
            with self.assertRaisesRegex(c.ContractError,'review_source_bytes_changed'):
                s.review(changed,self.root/'revision','candidate','r1','fixture',self.transport)
            self.assertEqual(len(self.calls),1)

    def test_shared_http_path_persists_before_log_failure_without_hidden_retry(self):
        from scripts import sermon_pipeline as pipeline
        value={k:self.f.evidence['groups'][0][k] for k in ('translationGroupId','sourceUnitIds','targetUtterances','coverage')}
        response=dict(id='real-path-synthetic-response',model='gpt-6-astra',choices=[dict(finish_reason='stop',message={'content':json.dumps(value)})])
        class HTTP:
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def read(self):return json.dumps(response).encode()
        def caller(key,payload,*,response_observer):
            return pipeline.json_request(pipeline.CHAT_URL,key,payload,retries=1,response_observer=response_observer)
        with self.session(),patch.object(pipeline.urllib.request,'urlopen',return_value=HTTP()) as transport:
            with patch.object(pipeline,'record_api_attempt',side_effect=accounting.AccountingWriteError('fault')):
                with self.assertRaises(accounting.AccountingWriteError):
                    s.generate(self.prepared,self.root/'revision','candidate','r1','fixture',caller)
            raw=json.loads((self.root/'revision/generator.raw.json').read_text())
            self.assertEqual(raw['response'],response)
            self.assertEqual(raw['accounting']['modelCallId'],json.loads((self.root/'revision/generator.call.json').read_text())['modelCallId'])
            s.generate(self.prepared,self.root/'revision','candidate','r1','fixture',caller)
            self.assertEqual(transport.call_count,1)
            self.assertEqual((self.root/'revision/generator.raw.json').stat().st_mode&0o777,0o600)

    def test_measured_role_calls_dependencies_and_missing_cache_tokens(self):
        from scripts import weekly_pipeline_report as weekly
        generated=[];reviewed=[]
        with self.session():
            s.generate(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport,
                       depends_on=[],completion_spans=generated)
            s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport,
                     depends_on=generated,completion_spans=reviewed)
        rows,damaged=accounting.read_events(self.root/'logs');self.assertFalse(damaged)
        start=next(e for e in rows if e['event']=='stage_started' and e['stage']=='rqc.review')
        self.assertEqual(start['dependsOn'],generated);self.assertEqual(len(reviewed),1)
        receipts=[e for e in rows if e['event']=='api_attempt']
        self.assertEqual({e['role'] for e in receipts},{'generation','quality_review'})
        self.assertEqual([e['model'] for e in receipts],['gpt-6-astra','gpt-6-sol'])
        self.assertEqual(sum(e['usage']['inputTokens'] for e in receipts),200)
        self.assertTrue(all(e['usage']['cachedInputTokens'] is None for e in receipts))
        run=weekly.project(self.root/'logs')['runs'][0]
        self.assertEqual(len(run['reviewObservations']),2)
        self.assertEqual(run['observabilityCoverage']['queueTiming'],'missing_instrumentation')

    def test_cached_raw_receipt_must_bind_the_original_call_and_output(self):
        with self.session():
            self.generate();raw_path=self.root/'revision/generator.raw.json';raw=json.loads(raw_path.read_text())
            raw['accounting']['modelCallId']='other-call';raw_path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(c.ContractError,'strict_raw_receipt_binding_changed'):self.generate()
            self.assertEqual(len(self.calls),1)

    def test_duplicate_model_json_keys_do_not_silently_choose_last_value(self):
        from scripts import run_target_language_models as shared
        payload={'id':'fixture-duplicate','model':'gpt-6-astra',
            'choices':[{'finish_reason':'stop','message':{'content':'{"translationGroupId":"bad","translationGroupId":"g1"}'}}]}
        def caller(key,request,*,response_observer):
            aid=accounting.record_api_started(request['model']);response_observer.request_started(aid)
            response_observer(payload,aid,.01);accounting.record_api_attempt(request['model'],payload,.01,attempt_id=aid);return payload
        with self.session(),self.assertRaises(c.ContractError):
            s.generate(self.prepared,self.root/'revision','candidate','r1','fixture',caller)
        self.assertFalse((self.root/'revision/revision.json').exists())


if __name__=='__main__':unittest.main()

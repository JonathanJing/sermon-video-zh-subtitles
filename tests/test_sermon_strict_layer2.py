"""D3 focused developer tests: synthetic provider responses only."""
import copy
import json
import io
import urllib.error
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator, ValidationError
from scripts import sermon_strict_layer2 as s
from scripts import sermon_review_contracts as c
from scripts import sermon_accounting as accounting
from scripts import sermon_log_profile as profile
from scripts import target_language_policy as policies
from tests import test_produce_target_language_candidate as legacy_fixtures
from tests.test_sermon_review_contracts import load


class StrictAdapterTests(unittest.TestCase):
    def setUp(self):
        f=legacy_fixtures.ProduceTargetLanguageCandidateTests();self.addCleanup(f.doCleanups); f.setUp();self.f=f
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.calls=[]
        draft=copy.deepcopy(f.policy);draft.pop('componentSha256');draft['schemaVersion']=policies.POLICY_V3
        draft['reviewMode']='strict_verifier'
        # Preserved API contract; new CLI defaults cannot replace its fixture models.
        draft['translator'].update(model='gpt-6-astra',reasoningEffort='medium',promptVersion='astra-strict-generator-v1')
        draft['reviewer'].update(model='gpt-6-sol',reasoningEffort='medium',promptVersion='sol-strict-verifier-v1')
        rubric=load('rubric');rubric['requiredLanguagePluginChecks']=draft['languageReview']['requiredChecks']
        draft['reviewContract']=dict(rubricCanonicalJsonSha256=c.canonical_sha256(rubric),reviewReceiptSchemaVersion='sermon-review-receipt-v1',candidateRevisionSchemaVersion='sermon-candidate-revision-v1',inputManifestSchemaVersion='sermon-review-input-manifest-v1',revisionGranularity='translation_group')
        policy=policies.freeze_strict_policy(draft,rubric)
        self.args=[s.material_bytes(v) for v in (f.source,f.anchor,policy,rubric)]
        self.group={k:f.evidence['groups'][0][k] for k in ('translationGroupId','sourceUnitIds')}
        from scripts import produce_target_language_candidate as producer
        from scripts import run_target_language_models as models
        from scripts import target_language_rule_preflight as rule_preflight
        request = producer.prepare_request(f.source, f.anchor, policy, strict_rubric=rubric)
        self.rule_preflight = rule_preflight.preflight(
            request, policy, f.plugin_path, models.group_plan(request, f.anchor))
        self.prepared=s.prepare(*self.args,self.group,rule_preflight=self.rule_preflight)
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
            if self.mode=='duplicate_check':
                value['checks'][1]['checkId']=value['checks'][0]['checkId']
            if self.mode=='overlap_coverage':
                value['unassessedUnitIds']=inp['sourceUnitIds'][:1]
            if self.mode=='invalid_enum':value['checks'][0]['result']='private-illegal-value'
            if self.mode=='invalid_field':value['checks'][0]['private-illegal-field']='private message'
            if self.mode=='invalid_issue_enum':
                value['issues']=[dict(issueId='issue-1',reasonCode='private-illegal-value',severity='major',
                    sourceUnitIds=inp['sourceUnitIds'],targetUnitIds=[],evidence='private message')]
            if self.mode in ('duplicate_check','overlap_coverage'):
                # These fit the declared JSON shape but violate semantic gates.
                Draft202012Validator(inp['responseContract']).validate(value)
        response={'id':'response-'+str(len(self.calls)),'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
            'usage':{'input_tokens':100,'output_tokens':20}}
        if payload['model']=='gpt-6-sol' and self.mode=='invalid_json':
            response['choices'][0]['message']['content']='{"private-message":'
        if payload['model']=='gpt-6-sol' and self.mode=='duplicate_json':
            response['choices'][0]['message']['content']='{"private-message":1,"private-message":2}'
        if payload['model']=='gpt-6-sol' and self.mode=='invalid_envelope':
            response['choices'][0]['finish_reason']='length'
        response_observer(response,aid,.01)
        accounting.record_api_attempt(payload['model'],response,.01,attempt_id=aid)
        return response

    def session(self):return profile.session(self.root/'logs','strict-test',work_kind='production',evidence_mode='synthetic')
    def generate(self):return s.generate(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport)
    def review(self):return s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport)

    def test_live_call_without_frozen_rules_sends_nothing(self):
        bare = s.prepare(*self.args, self.group)
        sent = []
        with self.session(), self.assertRaisesRegex(ValueError, 'strict_rule_preflight_required'):
            s.call_model(bare, 'translator', s.prompt(bare, 'translator'), self.root / 'bare.json',
                         'fixture', lambda *args, **kwargs: sent.append(args))
        self.assertEqual(sent, [])
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'bare.json').exists())

    def test_json_mode_prompt_contract_covers_generator_and_verifier_shapes(self):
        original = self.transport
        responses = []
        def contract_transport(key, payload, *, response_observer):
            # The real API JSON mode requires JSON to be explicit in messages.
            self.assertEqual(payload['response_format'], {'type':'json_object'})
            self.assertIn('JSON', payload['messages'][0]['content'])
            self.assertIn(s.RESPONSE_CONTRACT_VERSION, payload['messages'][0]['content'])
            inp = json.loads(payload['messages'][1]['content'])
            schema = inp['responseContract']
            Draft202012Validator.check_schema(schema)
            response = original(key, payload, response_observer=response_observer)
            content = json.loads(response['choices'][0]['message']['content'])
            Draft202012Validator(schema).validate(content)
            responses.append((schema, content))
            return response
        with self.session():
            s.generate(self.prepared,self.root/'revision','candidate','r1','fixture',contract_transport)
            receipt=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',contract_transport)
        self.assertEqual(receipt['reviewVerdict'],'pass')
        generator_schema, generated = responses[0]
        bad = copy.deepcopy(generated)
        bad['coverage'] = {row['sourceUnitId']:row['targetText'] for row in bad['coverage']}
        with self.assertRaises(ValidationError):Draft202012Validator(generator_schema).validate(bad)
        if len(generated['coverage']) > 1:
            bad = copy.deepcopy(generated);bad['coverage'].reverse()
            with self.assertRaises(ValidationError):Draft202012Validator(generator_schema).validate(bad)
        reviewer_schema, reviewed = responses[1]
        checks=reviewer_schema['properties']['checks']['items']['properties']['checkId']['enum']
        self.assertEqual(set(checks),c.HARD_CHECKS)
        self.assertTrue(set(self.prepared['rubric']['requiredLanguagePluginChecks'])-set(checks))
        bad=copy.deepcopy(reviewed)
        bad['checks'].append(dict(checkId='languagePluginCheck',result='pass',evidence='synthetic'))
        with self.assertRaises(ValidationError):Draft202012Validator(reviewer_schema).validate(bad)
        issue_schema=reviewer_schema['properties']['issues']['items']['properties']
        receipt_issue=c.validator('sermon-review-receipt-v1').schema['properties']['issues']['items']['properties']
        self.assertEqual(issue_schema['reasonCode'],receipt_issue['reasonCode'])
        self.assertEqual(issue_schema['severity'],receipt_issue['severity'])
        bad=copy.deepcopy(reviewed)
        bad['issues']=[dict(issueId='issue-1',reasonCode='invented_reason',severity='major',
            sourceUnitIds=self.group['sourceUnitIds'],targetUnitIds=[],evidence='synthetic')]
        with self.assertRaises(ValidationError):Draft202012Validator(reviewer_schema).validate(bad)

    def test_response_contract_version_change_cannot_reuse_old_paid_cache(self):
        with self.session():
            self.generate()
            before=(self.root/'revision/generator.raw.json').read_bytes()
            with patch.object(s,'RESPONSE_CONTRACT_VERSION','strict-layer2-response-next'):
                with self.assertRaises(ValueError):self.generate()
            self.assertEqual(len(self.calls),1)
            self.assertEqual((self.root/'revision/generator.raw.json').read_bytes(),before)

    def test_shape_valid_review_still_requires_unique_checks_and_partitioned_coverage(self):
        base=self.root
        for mode in ('duplicate_check','overlap_coverage'):
            with self.subTest(mode=mode):
                self.root=base/mode
                with self.session():
                    self.generate();self.mode=mode;before=(self.root/'revision/candidate.json').read_bytes()
                    receipt=self.review()
                    self.assertEqual(receipt['executionStatus'],'failed')
                    self.assertEqual(receipt['reviewVerdict'],'not_assessed')
                    self.assertEqual((self.root/'revision/candidate.json').read_bytes(),before)

    def test_failed_review_structural_diagnostic_is_safe_bound_and_restart_cached(self):
        base=self.root
        for mode,reason in [('invalid_enum','invalid_enum'),('invalid_field','invalid_fields'),
                            ('invalid_issue_enum','invalid_enum'),('duplicate_check','duplicate_check'),
                            ('overlap_coverage','coverage_partition_mismatch'),('rewrite','invalid_fields'),
                            ('invalid_json','invalid_json'),('duplicate_json','invalid_json'),
                            ('invalid_envelope','invalid_response_envelope')]:
            with self.subTest(mode=mode):
                self.root=base/mode;prior=len(self.calls)
                with self.session():
                    self.generate();self.mode=mode;receipt=self.review()
                path=self.root/'revision/reviewer.structural-diagnostic.json'
                detail,data=c.read_snapshot(path)
                self.assertEqual(detail['reasonCode'],reason)
                self.assertEqual(detail['rawFileBytesSha256'],c.bytes_sha256((path.parent/'reviewer.raw.json').read_bytes()))
                self.assertEqual(detail['candidateBytesSha256'],c.bytes_sha256((path.parent/'candidate.json').read_bytes()))
                self.assertEqual(detail['reviewerInputBytesSha256'],c.bytes_sha256((path.parent/'review-input.json').read_bytes()))
                self.assertEqual(detail['modelCallId'],receipt['modelCallId'])
                self.assertEqual(detail['candidateArtifactSha256'],receipt['reviewedArtifactSha256'])
                self.assertEqual(receipt['evidenceRefs'][-1],s.reference('review-structural-diagnostic',data))
                self.assertNotIn(b'private-illegal',data);self.assertNotIn(b'private message',data)
                self.assertEqual(c.read_snapshot(path.parent/'reviewer.failure.json')[0]['reasonCode'],'invalid_review_response')
                with self.session():self.assertEqual(self.review(),receipt)
                self.assertEqual(len(self.calls),prior+2)

    def test_second_review_structural_sidecar_binds_its_own_returned_call(self):
        with self.session():
            self.generate();self.mode='invalid_enum';first=self.review()
            second=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport,attempt_number=2)
            detail,data=c.read_snapshot(self.root/'revision/reviewer-2.structural-diagnostic.json')
            self.assertEqual(second['evidenceRefs'][-1],s.reference('review-structural-diagnostic-2',data))
            self.assertEqual(detail['modelCallId'],second['modelCallId'])
            self.assertNotEqual(detail['modelCallId'],first['modelCallId'])
            with self.assertRaisesRegex(ValueError,'strict_review_diagnostic_context_required'):
                s._validate_cached_review_evidence(second,c.read_snapshot(self.root/'revision/revision.json')[0],self.root/'revision/reviewer-2.json')
            self.assertEqual(s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.transport,attempt_number=2),second)
        self.assertEqual(len(self.calls),3)

    def test_succeeded_review_rejects_injected_unbound_failure_diagnostic(self):
        with self.session():
            self.generate();self.review()
            (self.root/'revision/reviewer.structural-diagnostic.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'conflicting_strict_review_evidence'):self.review()
        self.assertEqual(len(self.calls),2)

    def test_structural_diagnostic_rejects_tampering_without_dispatch(self):
        base=self.root
        for name in ['reviewer.raw.json','reviewer.call.json','reviewer.structural-diagnostic.json','review-input.json','candidate.json']:
            with self.subTest(name=name):
                self.root=base/name.replace('.','-');prior=len(self.calls)
                with self.session():
                    self.generate();self.mode='invalid_enum';self.review()
                    path=self.root/'revision'/name;value=json.loads(path.read_text())
                    if name=='reviewer.raw.json':value['response']['usage']['input_tokens']=999
                    elif name=='reviewer.call.json':value['modelCallId']='tampered-call'
                    elif name=='reviewer.structural-diagnostic.json':value['reasonCode']='invalid_fields'
                    elif name=='review-input.json':value['sourceUnitIds']=[]
                    else:value['targetUtterances'][0]='tampered'
                    path.write_text(json.dumps(value))
                    with self.assertRaises((ValueError,OSError)):self.review()
                self.assertEqual(len(self.calls),prior+2)

    def test_old_failure_receipt_without_structural_sidecar_remains_read_only(self):
        with self.session():
            self.generate();self.mode='rewrite';receipt=self.review()
            sidecar=self.root/'revision/reviewer.structural-diagnostic.json';sidecar.unlink()
            receipt['evidenceRefs']=receipt['evidenceRefs'][:-1];receipt['receiptSha256']=c.receipt_sha256(receipt)
            path=self.root/'revision/review-receipt.json';path.write_bytes(s.material_bytes(receipt))
            before=path.read_bytes()
            self.assertEqual(self.review(),receipt)
            self.assertEqual(path.read_bytes(),before);self.assertFalse(sidecar.exists())
        self.assertEqual(len(self.calls),2)

    def test_structural_failure_preserves_d5_actual_usage_and_reservation_bounds(self):
        from scripts import sermon_review_budget as budget
        from scripts import sermon_strict_budget_adapter as adapter
        from tests.test_sermon_strict_budget_adapter import authority,bounds,measured
        store=budget.BudgetStore(self.root/'shared-budget',authority());subject=adapter.StrictBudgetAdapter(store)
        root=self.root/'revision'
        def run(subject,role,usage=measured):
            return getattr(subject,role)(self.prepared,root,'candidate','r1','fixture',self.transport,
                bounds=bounds(),usage_resolver=usage)
        with self.session():
            run(subject,'generate');self.mode='invalid_enum';receipt=run(subject,'review')
            self.assertEqual(receipt['executionStatus'],'failed');self.assertEqual(receipt['budgetStatus'],'recorded')
            snapshot=store.snapshot(adapter.chain_identity(self.prepared))
            row=next(row for row in snapshot['reservations'] if row['kind']=='review')
            with store._locked() as (_,ledger):
                self.assertEqual(ledger['reservations'][row['reservationId']]['result']['usage'],measured(None))
            self.assertEqual(snapshot['remaining']['global']['costMicrousd'],authority()['globalBounds']['costMicrousd']-2*bounds()['costMicrousd'])
            restarted=adapter.StrictBudgetAdapter(budget.BudgetStore(store.root,authority()))
            self.assertEqual(run(restarted,'review',lambda _:self.fail('cached measured usage must be preserved')),receipt)
        self.assertEqual(len(self.calls),2)

    def test_structural_sidecar_write_failure_keeps_budget_pending_and_recovers_without_call(self):
        from tests import test_sermon_strict_budget_adapter as fixtures
        runtime=fixtures.StrictBudgetTests();self.addCleanup(runtime.doCleanups); runtime.setUp()
        original=s.save_once
        def broken(path,value):
            if str(path).endswith('.structural-diagnostic.json'):raise OSError('synthetic write failure')
            return original(path,value)
        with runtime.f.session():
            runtime.generate();runtime.f.mode='invalid_enum'
            with patch.object(s,'save_once',side_effect=broken),self.assertRaises(OSError):runtime.review()
            self.assertTrue(runtime.snapshot()['unknownReservations'])
            self.assertFalse((runtime.root/'reviewer.budget-result.json').exists())
            before=(runtime.root/'reviewer.raw.json').read_bytes()
            runtime.restart();result=runtime.review()
            self.assertEqual(result['executionStatus'],'failed');self.assertEqual(result['budgetStatus'],'recorded')
            self.assertEqual((runtime.root/'reviewer.raw.json').read_bytes(),before)
        self.assertEqual(len(runtime.f.calls),2)

    def test_closed_provider_run_is_typed_non_dispatch_with_safe_reason_and_cached_terminal(self):
        from unittest.mock import Mock
        from scripts import sermon_pipeline as pipeline
        from scripts import sermon_strict_budget_adapter as adapter
        from tests import test_sermon_strict_budget_adapter as fixtures
        runtime=fixtures.StrictBudgetTests();self.addCleanup(runtime.doCleanups); runtime.setUp()
        executor=Mock(side_effect=AssertionError('closed run must not dispatch'))
        def closed(key,payload,*,response_observer):
            request=pipeline.urllib.request.Request(pipeline.CHAT_URL)
            request.accounting_model=payload['model'];request.accounting_settings=accounting.request_metadata(payload)
            def observer(response,call_id,elapsed):response_observer(response,call_id,elapsed)
            def guard(call_id):raise pipeline.PreDispatchRejection('provider_run_permanently_closed')
            observer.request_started=guard
            return pipeline.request_json(request,response_observer=observer,request_executor=executor)
        with runtime.f.session():
            result=runtime.generate(caller=closed)
            self.assertEqual(result['failureEvidence']['reasonCode'],'provider_run_permanently_closed')
            self.assertEqual(result['failureEvidence']['providerOutcome'],'not_dispatched')
            self.assertEqual(result['budgetStatus'],'recorded')
            self.assertEqual(adapter.safe_failure_reason(pipeline.PreDispatchRejection('provider_run_permanently_closed')),'provider_run_permanently_closed')
            runtime.restart();self.assertEqual(runtime.generate(caller=closed),result)
        executor.assert_not_called()
        events,_=accounting.read_events(runtime.f.root/'logs')
        terminal=[row for row in events if row['event']=='api_attempt']
        self.assertEqual(len(terminal),1)
        self.assertEqual(terminal[0]['metrics']['dispatched'],False)
        self.assertEqual(terminal[0]['reasonCode'],'provider_run_permanently_closed')

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

    def test_cached_review_receipt_revalidates_reviewer_result_raw_and_call_evidence(self):
        base=self.root
        for evidence_file in ('reviewer.json','reviewer.raw.json','reviewer.call.json'):
            with self.subTest(evidence_file=evidence_file), self.session():
                self.root=base/evidence_file.replace('.','-')
                prior_calls=len(self.calls)
                self.generate();self.review()
                path=self.root/'revision'/evidence_file
                value=json.loads(path.read_text())
                if evidence_file=='reviewer.json':
                    value['result']['reviewVerdict']='needs_rework'
                elif evidence_file=='reviewer.raw.json':
                    value['response']['choices'][0]['message']['content']=json.dumps({'tampered':True})
                else:
                    value['modelCallId']='tampered-call'
                path.write_text(json.dumps(value))
                with self.assertRaises(c.ContractError):self.review()
                self.assertEqual(len(self.calls),prior_calls+2)

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
            changed=s.prepare(self.args[0]+b' ',*self.args[1:],self.group,rule_preflight=self.rule_preflight)
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
        self.assertEqual(run['observabilityCoverage']['queueTiming'],'measured_recorded_timestamps')
        queue = run['telemetryEvidence']['queue']
        self.assertEqual(queue['observedReadyAndDispatchCount'], len(run['workUnits']))
        self.assertEqual(queue['resourceQueueStatus'], 'not_established')
        self.assertEqual(queue['meaning'], 'inline_dispatch_to_stage_entry_is_not_resource_or_provider_queue_wait')

    def test_cached_raw_receipt_must_bind_the_original_call_and_output(self):
        with self.session():
            self.generate();raw_path=self.root/'revision/generator.raw.json';raw=json.loads(raw_path.read_text())
            raw['accounting']['modelCallId']='other-call';raw_path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(c.ContractError,'strict_raw_receipt_binding_changed'):self.generate()
            self.assertEqual(len(self.calls),1)

    def test_known_http_rejections_are_failed_without_content_assessment_or_retry(self):
        from scripts import sermon_pipeline as pipeline
        base=self.root
        def caller(key,payload,*,response_observer):
            # Deliberately use the legacy default; a strict observer must remain single-attempt.
            return pipeline.json_request(pipeline.CHAT_URL,key,payload,response_observer=response_observer)
        for status in (400,401,429):
            with self.subTest(status=status):
                self.root=base/str(status)
                with self.session():
                    self.generate()
                    error=urllib.error.HTTPError(pipeline.CHAT_URL,status,'private status text',{},io.BytesIO(b'private rejection body'))
                    with patch.object(pipeline.urllib.request,'urlopen',side_effect=error) as transport:
                        receipt=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',caller)
                        self.assertEqual(receipt['executionStatus'],'failed')
                        self.assertEqual(receipt['reviewVerdict'],'not_assessed')
                        self.assertEqual(s.review(self.prepared,self.root/'revision','candidate','r1','fixture',caller),receipt)
                    self.assertEqual(transport.call_count,1)
                    self.assertEqual(receipt['checks'],[]);self.assertEqual(receipt['issues'],[])
                    self.assertEqual(receipt['coverage']['assessedUnitIds'],[])
                    for path in self.root.rglob('*.json*'):
                        self.assertNotIn('private rejection body',path.read_text())
                        self.assertNotIn('private status text',path.read_text())

    @staticmethod
    def http_caller(key,payload,*,response_observer):
        from scripts import sermon_pipeline as pipeline
        return pipeline.json_request(pipeline.CHAT_URL,key,payload,response_observer=response_observer)

    def test_ambiguous_http_and_transport_failures_stay_unknown_without_retry(self):
        from scripts import sermon_pipeline as pipeline
        base=self.root
        errors=[urllib.error.HTTPError(pipeline.CHAT_URL,status,'private',{},io.BytesIO(b'private'))
                for status in (408,409,500,502,503,504)]
        errors += [urllib.error.URLError('private network detail'),TimeoutError('private timeout')]
        for index,error in enumerate(errors):
            with self.subTest(error=type(error).__name__,index=index):
                self.root=base/str(index)
                with self.session():
                    self.generate()
                    with patch.object(pipeline.urllib.request,'urlopen',side_effect=error) as transport, patch.object(pipeline.time,'sleep') as sleep:
                        receipt=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller)
                        self.assertEqual(receipt['executionStatus'],'outcome_unknown')
                        self.assertEqual(receipt['reviewVerdict'],'not_assessed')
                        self.assertEqual(s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller),receipt)
                    self.assertEqual(transport.call_count,1);sleep.assert_not_called()
                    self.assertFalse((self.root/'revision/reviewer.rejection.json').exists())

    def test_rejection_is_durable_before_finish_logging_and_recovery_does_not_call(self):
        from scripts import sermon_pipeline as pipeline
        with self.session():
            self.generate()
            error=urllib.error.HTTPError(pipeline.CHAT_URL,429,'private',{},io.BytesIO(b'private'))
            def fail_finish(*args,**kwargs):
                marker=json.loads((self.root/'revision/reviewer.rejection.json').read_text())
                self.assertEqual(marker['httpStatus'],429)
                self.assertEqual(marker['modelCallId'],json.loads((self.root/'revision/reviewer.call.json').read_text())['modelCallId'])
                raise accounting.AccountingWriteError('injected finish failure')
            with patch.object(pipeline.urllib.request,'urlopen',side_effect=error) as transport:
                with patch.object(pipeline,'record_api_attempt',side_effect=fail_finish):
                    with self.assertRaises(pipeline.TransportRejection) as raised:
                        s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller)
                self.assertTrue(raised.exception.sermon_logging_failed)
                self.assertFalse((self.root/'revision/review-receipt.json').exists())
                # Same persisted evidence is sufficient after the logging failure;
                # no new request or fabricated model/content result is needed.
                receipt=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller,cache_only=True)
                self.assertEqual(receipt['executionStatus'],'failed')
                self.assertIsNone(receipt['reviewerModelActual'])
                self.assertIsNone(receipt['providerResponseId'])
            self.assertEqual(transport.call_count,1)
            self.assertEqual((self.root/'revision/reviewer.rejection.json').stat().st_mode&0o777,0o600)

    def test_rejection_marker_must_bind_original_payload_and_call(self):
        from scripts import sermon_pipeline as pipeline
        base=self.root
        for field,value in [('modelCallId','different-call'),('payloadSha256','0'*64),('httpStatus',500),('httpStatus',True)]:
            with self.subTest(field=field,value=value):
                self.root=base/(field+str(value))
                with self.session():
                    self.generate()
                    error=urllib.error.HTTPError(pipeline.CHAT_URL,400,'private',{},io.BytesIO(b'private'))
                    with patch.object(pipeline.urllib.request,'urlopen',side_effect=error) as transport:
                        with patch.object(pipeline,'record_api_attempt',side_effect=accounting.AccountingWriteError('injected')):
                            with self.assertRaises(pipeline.TransportRejection):
                                s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller)
                        path=self.root/'revision/reviewer.rejection.json'
                        marker=json.loads(path.read_text());marker[field]=value;path.write_text(json.dumps(marker))
                        with self.assertRaises(c.ContractError):
                            s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller)
                    self.assertEqual(transport.call_count,1)
                    self.assertFalse((self.root/'revision/review-receipt.json').exists())

    def test_typed_exception_without_durable_rejection_proof_stays_unknown(self):
        from scripts import sermon_pipeline as pipeline
        def unproven(key,payload,*,response_observer):
            aid=accounting.record_api_started(payload['model'])
            response_observer.request_started(aid)
            raise pipeline.TransportRejection(400)
        with self.session():
            self.generate()
            receipt=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',unproven)
            self.assertEqual(receipt['executionStatus'],'outcome_unknown')

    def test_rejection_persistence_failure_keeps_pending_and_propagates(self):
        from scripts import sermon_pipeline as pipeline
        original=s.save_once
        def fail(path,value):
            if path.name.endswith('.rejection.json'):raise OSError('injected persistence fault')
            return original(path,value)
        with self.session():
            self.generate()
            error=urllib.error.HTTPError(pipeline.CHAT_URL,401,'private',{},io.BytesIO(b'private'))
            with patch.object(pipeline.urllib.request,'urlopen',side_effect=error) as transport:
                with patch.object(s,'save_once',side_effect=fail),patch.object(pipeline,'record_api_attempt') as finish:
                    with self.assertRaises(accounting.AccountingWriteError):
                        s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller)
                    finish.assert_called_once()
                    self.assertEqual(finish.call_args.args[3:5],('failed','AccountingWriteError'))
                    self.assertEqual(finish.call_args.kwargs['http_status'],401)
                    self.assertNotIn('not_dispatched_reason',finish.call_args.kwargs)
                self.assertTrue((self.root/'revision/reviewer.started.json').exists())
                self.assertFalse((self.root/'revision/review-receipt.json').exists())
                receipt=s.review(self.prepared,self.root/'revision','candidate','r1','fixture',self.http_caller)
                self.assertEqual(receipt['executionStatus'],'outcome_unknown')
            self.assertEqual(transport.call_count,1)

    def test_target_unit_id_boundary_is_validated_before_transport(self):
        prefix='l2.zh-Hans.'
        valid=dict(self.group,translationGroupId='g'*(85-len(prefix)))
        prepared=s.prepare(*self.args,valid,rule_preflight=self.rule_preflight)
        self.assertEqual(len(prepared['workUnitId']),85)
        self.f.evidence['groups'][0]['translationGroupId']=valid['translationGroupId']
        with self.session():
            manifest=s.generate(prepared,self.root/'valid-boundary','candidate','r1','fixture',self.transport)
        self.assertTrue(all(len(unit)==100 for unit in manifest['targetUnitIds']))
        invalid=dict(self.group,translationGroupId='g'*(86-len(prefix)))
        with patch.object(self,'transport') as transport:
            with self.assertRaisesRegex(c.ContractError,'invalid_strict_target_unit_label'):
                prepared=s.prepare(*self.args,invalid)
                s.generate(prepared,self.root/'invalid-boundary','candidate','r1','fixture',transport)
            transport.assert_not_called()

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

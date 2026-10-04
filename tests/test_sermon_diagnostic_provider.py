"""Offline integration: real strict producers/ledgers, injected HTTP executor."""
from copy import deepcopy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import urllib.error

from scripts import sermon_diagnostic_provider as p
from scripts import sermon_provider_limits as limits
from scripts import sermon_provider_error as errors
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_strict_budget_adapter as adapter
from scripts import sermon_accounting as accounting
from scripts import sermon_strict_candidate_bridge as bridge
from tests import test_sermon_strict_layer2 as fixtures


def config(**kw):
    result = dict(schemaVersion=p.SCHEMA, runId='1'*64, approvalSha256='2'*64, codeSha256='3'*64,
        sourceMediaSha256='1'*64, sourceClipSha256='5'*64,sourceAudioSha256='9'*64, sourceWindowSeconds=[60,240],
        targetMicrousd=25_000_000, hardLimitMicrousd=40_000_000,totalWallSeconds=5400,maxRequests=124,
        credentialReferenceSha256='6'*64,projectId=None,organizationId=None,transcriptionModel='gpt-transcribe')
    return {**result,**kw}


def authority():
    bound=dict(requests=124,inputTokens=2_000_000,outputTokens=1_000_000,wallTimeMs=40_000_000,costMicrousd=40_000_000)
    return dict(approvalSha256='2'*64,globalBounds=bound,unitBounds=bound,limits=budget.DEFAULT_LIMITS)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        from tests.test_build_english_source_package import EnglishSourcePackageTests
        original = EnglishSourcePackageTests.build
        def scoped_build(fixture, **kwargs):
            summary=json.loads(fixture.summary_path.read_text())
            summary.update(sermonStartSeconds=60.,sermonEndSeconds=240.)
            fixture.summary_path.write_text(json.dumps(summary))
            return original(fixture, **kwargs)
        self.f=fixtures.StrictAdapterTests()
        self.addCleanup(self.f.doCleanups)
        with patch.object(EnglishSourcePackageTests,'build',scoped_build):self.f.setUp()
        self.root=self.f.root/'revision';self.store=budget.BudgetStore(self.f.root/'budget',authority())
        self.clock=100.;self.calls=[];self.selected=deepcopy(limits.DEFAULT_REQUEST_LIMITS)
        self.prepared=strict.prepare(*self.f.args,self.f.group,request_limits=self.selected)
        self.provider=self.provider_for()
        self.bound=dict(requests=1,inputTokens=8192,outputTokens=4096,wallTimeMs=300000,costMicrousd=307200)
        self.subject=adapter.StrictBudgetAdapter(self.store)

    def provider_for(self,**kw):
        subject = p.DiagnosticProvider(self.store,config(**kw),self.selected,executor=self.http,
            monotonic=lambda:self.clock,domain=lambda:'7'*64)
        # Isolate chat/budget unit checks; the complete ASR-to-source binding is
        # exercised without this stub in the bounded-run integration tests.
        subject.source_check_payload=Mock(side_effect=self.payload)
        return subject

    def payload(self):
        return limits.bounded_payload(dict(model='gpt-6-astra',reasoning_effort='high',
            messages=[dict(role='user',content='Return JSON test.')],response_format={'type':'json_object'}),self.selected)

    def http(self,req,timeout,*,deadline=None):
        self.calls.append((req,timeout));payload=json.loads(req.data)
        inp=json.loads(payload['messages'][1]['content']) if len(payload['messages'])>1 else None
        if inp is None: value={'ok':True}
        elif payload['model']=='gpt-6-astra':
            value={k:self.f.f.evidence['groups'][0][k] for k in ('translationGroupId','sourceUnitIds','targetUtterances','coverage')}
        else:
            value=dict(reviewedArtifactSha256=inp['reviewedArtifactSha256'],reviewVerdict='pass',
                checks=[dict(checkId=check,result='pass',evidence='synthetic evidence') for check in sorted(c.HARD_CHECKS)],
                issues=[],assessedUnitIds=inp['sourceUnitIds'],unassessedUnitIds=[])
        return {'id':'resp-'+str(len(self.calls)),'model':payload['model'],
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':20}}

    def generate(self):
        return self.subject.generate(self.prepared,self.root,'candidate','r1','synthetic',self.provider,
            bounds=self.bound,usage_resolver=self.provider.usage_resolver)

    def test_strict_generation_review_and_restart_bind_actual_capped_requests(self):
        with self.f.session():
            generated=self.generate();self.assertEqual(generated['budgetStatus'],'recorded')
            reviewed=self.subject.review(self.prepared,self.root,'candidate','r1','synthetic',self.provider,
                bounds=self.bound,usage_resolver=self.provider.usage_resolver)
            self.assertEqual(reviewed['contentStatus'],'pass');self.assertEqual(reviewed['budgetStatus'],'recorded')
            self.provider=self.provider_for();self.assertEqual(self.generate(),generated)
        self.assertEqual(len(self.calls),2)
        for name,(req,timeout) in zip(('generator','reviewer'),self.calls):
            payload=json.loads(req.data);saved,_=c.read_snapshot(self.root/(name+'.json'))
            self.assertEqual(payload['max_completion_tokens'],4096);self.assertEqual(payload['service_tier'],'default')
            self.assertEqual(saved['payloadSha256'],c.canonical_sha256(payload));self.assertLessEqual(timeout,300)
        self.assertEqual(self.provider.snapshot()['requestCount'],2)
        self.assertEqual(c.read_snapshot(self.root/'request-limits.json')[0],self.selected)
        rows,_=accounting.read_events(self.f.root/'logs')
        api=[r for r in rows if r.get('event')=='api_attempt'];self.assertEqual(len(api),2)
        self.assertTrue(all(r['usage']['cachedInputTokens'] is None for r in api))

    def test_changed_cap_cannot_reset_existing_operation(self):
        with self.f.session():
            self.generate();self.selected['maxCompletionTokens']=2048
            self.prepared=strict.prepare(*self.f.args,self.f.group,request_limits=self.selected)
            self.provider=self.provider_for()
            with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.generate()
        self.assertEqual(len(self.calls),1)

    def test_input_bound_rejects_before_any_reservation_or_transport(self):
        self.selected['maxInputTokens']=1
        self.prepared=strict.prepare(*self.f.args,self.f.group,request_limits=self.selected)
        self.provider=self.provider_for()
        with self.f.session(),self.assertRaisesRegex(ValueError,'input_bound_exceeded'):self.generate()
        self.assertEqual(self.calls,[]);self.assertFalse(self.store.root.exists())

    def test_initial_group_count_and_input_bounds_are_preflighted_without_calls(self):
        with self.assertRaisesRegex(ValueError,'diagnostic_locale_group_limit'):
            self.provider.preflight_locale([self.prepared]*19)
        changed=deepcopy(self.prepared);changed['units'][0]['english']='x'*9000
        with self.assertRaisesRegex(ValueError,'input_bound_exceeded'):
            self.provider.preflight_locale([self.prepared,changed])
        self.assertEqual(self.calls,[])
        self.assertFalse(self.store.root.exists())

    def test_global_limit_shared_by_source_checks_and_strict_calls_across_restart(self):
        payload=self.payload();cost=limits.request_bounds(payload,self.selected)['costMicrousd']
        self.provider=self.provider_for(targetMicrousd=cost,hardLimitMicrousd=cost)
        with self.f.session():
            self.provider.chat('synthetic',payload)
            self.provider=self.provider_for(targetMicrousd=cost,hardLimitMicrousd=cost)
            ledger=self.store.root/budget.STORE_ID/'provider-run/state.json'
            frozen=ledger.read_bytes()
            result=self.generate()
            self.assertEqual(result['executionStatus'],'failed')
            self.assertEqual(result['budgetStatus'],'recorded')
            self.assertIsNone(result['artifact'])
            self.assertEqual(result['failureEvidence']['reasonCode'],'provider_cost_limit')
            self.assertEqual(result['failureEvidence']['providerOutcome'],'not_dispatched')
            self.assertEqual(ledger.read_bytes(),frozen)
            self.subject=adapter.StrictBudgetAdapter(self.store)
            self.assertEqual(self.generate(),result)
            self.assertEqual(ledger.read_bytes(),frozen)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.provider.snapshot()['remainingMicrousd'],0)
        rows,damaged=accounting.read_events(self.f.root/'logs')
        self.assertFalse(damaged)
        self.assertEqual(len([r for r in rows if r['event']=='api_attempt_started']),2)
        terminal=[r for r in rows if r['event']=='api_attempt']
        self.assertEqual(len(terminal),2)
        self.assertEqual(terminal[-1]['reasonCode'],'provider_cost_limit')
        self.assertEqual(terminal[-1]['metrics'],{'dispatched':False})
        self.assertFalse(accounting.summarize(self.f.root/'logs')['unfinishedApiAttempts'])

    def test_request_cap_denial_closes_api_attempt_without_dispatch_or_refund(self):
        self.provider=self.provider_for(maxRequests=1)
        with self.f.session():
            self.provider.chat('synthetic',self.payload(),operation_id='source.first')
            before=self.provider.snapshot()
            ledger=self.store.root/budget.STORE_ID/'provider-run/state.json'
            frozen=ledger.read_bytes()
            with self.assertRaisesRegex(p.pipeline.PreDispatchRejection,'provider_request_limit'):
                self.provider.chat('synthetic',self.payload(),operation_id='source.second')
            self.assertEqual(ledger.read_bytes(),frozen)
            self.assertEqual(self.provider.snapshot(),before)
        rows,damaged=accounting.read_events(self.f.root/'logs')
        self.assertEqual(damaged,[])
        starts=[r for r in rows if r['event']=='api_attempt_started']
        terminals=[r for r in rows if r['event']=='api_attempt']
        self.assertEqual(len(starts),2)
        self.assertEqual({r['attemptId'] for r in starts},{r['attemptId'] for r in terminals})
        rejected=next(r for r in terminals if r['status']=='failed')
        self.assertEqual(rejected['metrics'],{'dispatched':False})
        self.assertEqual(rejected['reasonCode'],'provider_request_limit')
        self.assertEqual(rejected['cost']['estimatedUsd'],0)
        self.assertIsNone(rejected['responseId'])
        self.assertTrue(all(v is None for v in rejected['usage'].values()))
        from scripts import sermon_log_contract as log_contract
        self.assertFalse(any(r['code']=='missing_model_finish'
            for r in log_contract.replay_integrity(rows)['diagnostics']))
        self.assertEqual(len(self.calls),1)

    def test_configuration_stop_is_scoped_persistent_and_recovery_does_not_retry_or_reset(self):
        original=self.http
        def configured(req,timeout,*,deadline=None):
            if json.loads(req.data)['model']=='gpt-6-astra':
                self.calls.append((req,timeout))
                error=urllib.error.HTTPError(req.full_url,400,'private',{},io.BytesIO(b''))
                error.safe_diagnostic=errors.diagnostic(400,json.dumps({'error':{
                    'code':'unsupported_parameter','param':'max_completion_tokens','message':'private'}}).encode())
                raise error
            return original(req,timeout,deadline=deadline)
        self.provider.executor=configured
        with self.f.session():
            with self.assertRaises(p.pipeline.TransportRejection) as rejected:
                self.provider.chat('synthetic',self.payload(),operation_id='source.first')
            self.assertEqual(rejected.exception.diagnostic['errorCode'],'unsupported_parameter')
            snapshot=self.provider.snapshot()
            root=self.store.root/budget.STORE_ID/'provider-run'
            state_bytes=(root/'state.json').read_bytes()
            self.provider=self.provider_for();self.provider.executor=configured
            with self.assertRaisesRegex(p.pipeline.PreDispatchRejection,'provider_configuration_blocked'):
                self.provider.chat('synthetic',self.payload(),operation_id='source.second')
            self.assertEqual((root/'state.json').read_bytes(),state_bytes)
            self.assertEqual(self.provider.snapshot(),snapshot)
            # Different valid model scope is still allowed in this SAME ledger.
            other={**self.payload(),'model':'gpt-6-sol'}
            self.provider._scoped_payloads.add(c.canonical_sha256(other))
            self.provider.chat('synthetic',other,response_observer=Mock())
            stop_path=next((root/'configuration-stops').glob('*.stop.json'))
            stop=c.read_snapshot(stop_path)[0]
            preserved=(root/'state.json').read_bytes()
            recovery=self.provider.recover_configuration(c.canonical_sha256(stop),
                resolution_evidence_sha256='a'*64,approval_sha256='2'*64)
            self.assertTrue(recovery['requiresNewAttempt'])
            self.assertFalse(recovery['automaticDispatch'])
            self.assertEqual((root/'state.json').read_bytes(),preserved)
            self.assertEqual(len(self.calls),2)
            # Old rejected source operation cannot silently become a new request.
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):
                self.provider.chat('synthetic',self.payload(),operation_id='source.first')
            self.assertEqual(len(self.calls),2)
            self.assertTrue(stop_path.is_file())
            self.assertEqual(self.provider.recover_configuration(c.canonical_sha256(stop),
                resolution_evidence_sha256='a'*64,approval_sha256='2'*64),recovery)
            with self.assertRaisesRegex(ValueError,'provider_recovery_approval_changed'):
                self.provider.recover_configuration(c.canonical_sha256(stop),
                    resolution_evidence_sha256='a'*64,approval_sha256='3'*64)

    def test_configuration_stop_skips_untouched_locale_groups_without_new_reservations(self):
        from scripts import sermon_strict_locale as locale
        calls=[]
        def rejected(req,timeout,*,deadline=None):
            calls.append(req)
            error=urllib.error.HTTPError(req.full_url,400,'private',{},io.BytesIO(b''))
            error.safe_diagnostic=errors.diagnostic(400,json.dumps({'error':{
                'code':'unsupported_parameter','param':'max_completion_tokens'}}).encode())
            raise error
        self.provider.executor=rejected
        plan=[{key:row[key] for key in ('translationGroupId','sourceUnitIds')}
              for row in self.f.f.evidence['groups']]
        graph=[{'workUnitId':strict.prepare(*self.f.args,row)['workUnitId'],
                'layer':2,'targetLocale':'zh-Hans','dependsOn':[]} for row in plan]
        with self.f.session():
            result=locale.run_locale(*self.f.args,root=self.f.root/'locale',store=self.store,
                job_root=self.f.root/'jobs',production_run_id='b'*64,graph=graph,
                plugin_path=self.f.f.plugin_path,expected_plugin_sha256=self.f.f.plugin_sha,
                api_key='synthetic',caller=self.provider,bounds=self.bound,
                usage_resolver=self.provider.usage_resolver,group_plan=plan,
                request_limits=self.selected)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['groups'][1]['status'],'not_started')
        self.assertEqual(result['groups'][1]['reasonCode'],'provider_configuration_blocked')
        self.assertEqual(len(self.store.snapshot(adapter.chain_identity(self.prepared))['reservations']),1)
        self.assertFalse((self.f.root/'locale'/'machine-candidates').exists())
        self.assertEqual(len(list((self.f.root/'locale'/'not-started').glob('*.json'))),1)

    def test_reviewer_configuration_stop_preserves_generation_and_does_not_auto_retry(self):
        from scripts import sermon_strict_controller as controller
        from tests import test_sermon_strict_budget_adapter as budgets
        original=self.http
        def configured(req,timeout,*,deadline=None):
            if json.loads(req.data)['model']=='gpt-6-sol':
                self.calls.append((req,timeout))
                error=urllib.error.HTTPError(req.full_url,400,'private',{},io.BytesIO(b''))
                error.safe_diagnostic=errors.diagnostic(400,json.dumps({'error':{
                    'code':'unsupported_parameter','param':'max_completion_tokens'}}).encode())
                raise error
            return original(req,timeout,deadline=deadline)
        self.provider.executor=configured
        graph=[{'workUnitId':self.prepared['workUnitId'],'layer':2,
            'targetLocale':'zh-Hans','dependsOn':[]}]
        def run():
            return controller.run_group(self.prepared,root=self.f.root/'controller',store=self.store,
                job_root=self.f.root/'jobs',production_run_id='b'*64,graph=graph,
                candidate_id='candidate',api_key='synthetic',caller=self.provider,
                bounds=self.bound,usage_resolver=budgets.measured)
        with self.f.session():
            result=run()
            self.assertEqual(result['reasonCode'],'provider_configuration_blocked')
            self.assertEqual(result['failureEvidence']['diagnostic']['errorParam'],'max_completion_tokens')
            self.assertEqual(result['reviewAttempt'],1)
            generator=Path(result['root'])/'generator.raw.json'
            frozen=generator.read_bytes()
            self.provider=self.provider_for();self.provider.executor=configured
            again=run()
            self.assertEqual(again['reasonCode'],'provider_configuration_blocked')
            self.assertEqual(generator.read_bytes(),frozen)
            self.assertEqual(again['reviewAttempt'],1)
        self.assertEqual(len(self.calls),2)
        self.assertFalse((Path(result['root'])/'reviewer-2.started.json').exists())
        diagnostic=c.read_snapshot(Path(result['root'])/'reviewer.rejection-diagnostic.json')[0]
        self.assertEqual(diagnostic['diagnostic']['errorCode'],'unsupported_parameter')

    def test_stop_receipt_write_failure_is_unknown_preserves_reservation_and_closes_api_terminal(self):
        def rejected(req,timeout,*,deadline=None):
            self.calls.append((req,timeout))
            error=urllib.error.HTTPError(req.full_url,400,'private',{},io.BytesIO(b''))
            error.safe_diagnostic=errors.diagnostic(400,json.dumps({'error':{
                'code':'unsupported_parameter','param':'max_completion_tokens'}}).encode())
            raise error
        self.provider.executor=rejected
        original=strict.save_once
        def failing(path,value):
            if str(path).endswith('.stop.json'):raise OSError('private-secret')
            return original(path,value)
        with self.f.session(),patch.object(strict,'save_once',side_effect=failing):
            with self.assertRaises(OSError) as failure:
                self.provider.chat('synthetic',self.payload())
            self.assertTrue(failure.exception.sermon_logging_failed)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.provider.snapshot()['unknownModelCallIds']),1)
        rows,invalid=accounting.read_events(self.f.root/'logs')
        self.assertEqual(invalid,[])
        self.assertEqual(len([r for r in rows if r['event']=='api_attempt_started']),1)
        terminal=next(r for r in rows if r['event']=='api_attempt')
        self.assertEqual(terminal['httpStatus'],400)
        self.assertIsNone(terminal['cost']['estimatedUsd'])
        self.assertNotIn('metrics',terminal)
        self.assertNotIn('private-secret',json.dumps(rows))

    def test_unknown_400_and_temporary_429_do_not_stop_the_configuration(self):
        for code,error_code in ((400,None),(429,'rate_limit_exceeded')):
            with self.subTest(code=code):
                store=budget.BudgetStore(self.f.root/str(code),authority())
                def rejected(req,timeout,*,deadline=None):
                    self.calls.append((req,timeout))
                    error=urllib.error.HTTPError(req.full_url,code,'private',{},io.BytesIO(b''))
                    error.safe_diagnostic=errors.diagnostic(code,json.dumps({'error':{'code':error_code}}).encode())
                    raise error
                subject=p.DiagnosticProvider(store,config(),self.selected,executor=rejected,
                    monotonic=lambda:self.clock,domain=lambda:'7'*64)
                subject.source_check_payload=Mock(side_effect=self.payload)
                before=len(self.calls)
                with self.f.session():
                    for n in range(2):
                        with self.assertRaises(p.pipeline.TransportRejection):
                            subject.chat('synthetic',self.payload(),operation_id='source.'+str(n))
                self.assertEqual(len(self.calls)-before,2)
                self.assertFalse((store.root/budget.STORE_ID/'provider-run/configuration-stops').exists())

    def test_unknown_timeout_and_restart_never_issue_another_request(self):
        self.provider.executor=Mock(side_effect=TimeoutError('synthetic'))
        with self.f.session():
            with self.assertRaises(TimeoutError):self.provider.chat('synthetic',self.payload())
            self.provider=self.provider_for()
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.provider.chat('synthetic',self.payload())
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.provider.snapshot()['unknownModelCallIds']),1)

    def test_missing_tokens_keeps_unknown_cache_and_blocks_more_calls(self):
        original=self.http
        def missing(req,timeout,*,deadline=None):
            response=original(req,timeout);response.pop('usage');return response
        self.provider.executor=missing
        with self.f.session():
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.generate()
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.provider.chat('synthetic',self.payload())
        self.assertEqual(len(self.calls),1)

    def test_total_deadline_and_boot_change_do_not_reset_on_restart(self):
        with self.f.session():
            self.provider.chat('synthetic',self.payload());self.clock+=5400
            self.provider=self.provider_for()
            new=self.payload()
            with self.assertRaisesRegex(ValueError,'deadline_reached'):self.provider.chat('synthetic',new,operation_id='source.second')
            self.clock-=5400;self.provider.domain=lambda:'8'*64
            with self.assertRaisesRegex(ValueError,'clock_domain_changed'):self.provider.chat('synthetic',new,operation_id='source.second')
        self.assertEqual(len(self.calls),1)

    def test_remaining_total_time_limits_single_attempt(self):
        self.provider.snapshot();self.clock+=5395
        with self.f.session():self.provider.chat('synthetic',self.payload())
        self.assertEqual(self.calls[0][1],5)

    def test_slow_reservation_persistence_cannot_renew_deadline(self):
        self.provider.snapshot();self.clock+=5395
        original=self.provider._save
        def slow(root,state):
            original(root,state);self.clock+=10
        with self.f.session(),patch.object(self.provider,'_save',side_effect=slow):
            with self.assertRaisesRegex(ValueError,'attempt_deadline_reached'):
                self.provider.chat('synthetic',self.payload())
        self.assertEqual(self.calls,[])
        snapshot=self.provider.snapshot()
        self.assertEqual(len(snapshot['unknownModelCallIds']),1)
        self.assertGreater(snapshot['reservedMicrousd'],0)
        rows,damaged=accounting.read_events(self.f.root/'logs')
        terminal=next(r for r in rows if r['event']=='api_attempt')
        self.assertEqual(damaged,[])
        self.assertEqual(terminal['reasonCode'],'provider_attempt_deadline_reached')
        self.assertEqual(terminal['metrics'],{'dispatched':False})

    def test_foreign_source_or_window_rejects_before_both_ledgers(self):
        for field in ('media', 'window'):
            prepared=deepcopy(self.prepared)
            if field=='media':prepared['source']['source']['media']['sha256']='f'*64
            else:prepared['source']['source']['approvedWindow']['startSeconds']=61
            with self.assertRaisesRegex(ValueError,'approved_source_scope_changed'):
                self.provider.preflight_locale([prepared])
            with self.assertRaisesRegex(ValueError,'approved_source_scope_changed'):
                self.provider.preflight(prepared,'initial_generation',self.root)
        self.assertEqual(self.calls,[]);self.assertFalse(self.store.root.exists())

    def test_unknown_response_neither_fresh_nor_cached_is_success(self):
        base=self.http
        for change in ({'model':'other-model'}, {'usage':None},
                       {'usage':{'prompt_tokens':-1,'completion_tokens':20}}):
            with self.subTest(change=change):
                store=budget.BudgetStore(self.f.root/c.canonical_sha256(change),authority())
                def execute(req,timeout,*,deadline=None):
                    return {**base(req,timeout),**change}
                subject=p.DiagnosticProvider(store,config(),executor=execute,
                    monotonic=lambda:self.clock,domain=lambda:'7'*64)
                subject.source_check_payload=Mock(side_effect=self.payload)
                before=len(self.calls)
                with self.f.session():
                    for _ in range(2):
                        with self.assertRaisesRegex(ValueError,'reconciliation_required'):
                            subject.chat('synthetic',self.payload())
                self.assertEqual(len(self.calls),before+1)
                self.assertEqual(len(subject.snapshot()['unknownModelCallIds']),1)

    def test_transcription_model_is_not_an_automatic_fallback(self):
        self.assertEqual(p.validate_config(config())['transcriptionModel'],'gpt-transcribe')
        with self.assertRaisesRegex(ValueError,'specific_user_approval'):
            p.validate_config(config(transcriptionModel='local-whisper'))

    def test_receipt_persisted_before_logging_failure_and_no_same_paid_retry(self):
        original=accounting.record_api_attempt
        with self.f.session(),patch.object(p.pipeline,'record_api_attempt',side_effect=accounting.AccountingWriteError('synthetic')):
            with self.assertRaises(accounting.AccountingWriteError):self.generate()
        self.assertTrue((self.root/'generator.raw.json').is_file())
        with self.f.session():
            self.provider=self.provider_for();result=self.generate()
            self.assertEqual(result['budgetStatus'],'recorded')
        self.assertEqual(len(self.calls),1)

    def test_source_logging_failure_recovers_saved_response_without_second_call(self):
        with self.f.session(),patch.object(p.pipeline,'record_api_attempt',side_effect=accounting.AccountingWriteError('synthetic')):
            with self.assertRaises(accounting.AccountingWriteError):
                self.provider.chat('synthetic',self.payload(),operation_id='source-check.1')
        with self.f.session():
            self.provider=self.provider_for()
            result=self.provider.chat('synthetic',self.payload(),operation_id='source-check.1')
            self.assertEqual(result['id'],'resp-1')
            changed=self.payload();changed['messages'][0]['content']='changed'
            with self.assertRaisesRegex(ValueError,'source_check_payload_changed'):
                self.provider.chat('synthetic',changed,operation_id='source-check.1')
        self.assertEqual(len(self.calls),1)

    def test_header_routing_only_explicit_metadata_and_no_persisted_key(self):
        self.provider=self.provider_for(projectId='proj_existing',organizationId='org-existing')
        with self.f.session():self.provider.chat('synthetic-private-key',self.payload())
        req=self.calls[0][0];self.assertEqual(req.get_header('Openai-project'),'proj_existing')
        for path in self.store.root.rglob('*.json'):
            self.assertNotIn('synthetic-private-key',path.read_text())

    def test_corrupt_or_missing_state_and_unknown_audio_price_fail_closed(self):
        self.provider.snapshot();path=self.store.root/budget.STORE_ID/'provider-run/state.json';path.unlink()
        with self.f.session(),self.assertRaises(FileNotFoundError):self.provider.chat('synthetic',self.payload())
        self.assertEqual(self.calls,[])

    def test_authority_and_limit_changes_are_not_new_run(self):
        self.provider.snapshot()
        changed=p.DiagnosticProvider(self.store,config(hardLimitMicrousd=39_000_000),executor=self.http,
            monotonic=lambda:self.clock,domain=lambda:'7'*64)
        with self.assertRaisesRegex(ValueError,'run_identity_changed'):changed.snapshot()
        with self.assertRaisesRegex(ValueError,'invalid_provider_run_limit'):config_value=config(hardLimitMicrousd=40_000_001);p.validate_config(config_value)



class BoundedAdmissionTests(unittest.TestCase):
    def test_bounded_payload_survives_public_bridge_and_locked_admission(self):
        from tests.test_sermon_strict_gate_admission import AdmissionTests
        fixture=AdmissionTests();self.addCleanup(fixture.doCleanups)
        original=strict.prepare
        def prepare(*args,**kwargs):
            return original(*args,request_limits=kwargs.get('request_limits') or limits.DEFAULT_REQUEST_LIMITS)
        with patch.object(strict,'prepare',side_effect=prepare):fixture.setUp()
        result=fixture.admit();self.assertEqual(result['status'],'committed')
        self.assertEqual(fixture.admit()['status'],'existing')
        root=fixture.f.revisions[0][0]
        selected=c.read_snapshot(root/'request-limits.json')[0];selected['maxCompletionTokens']=2048
        (root/'request-limits.json').write_bytes(c.canonical_bytes(selected))
        with self.assertRaises(ValueError):fixture.boundary.snapshot()

    def test_locale_entry_passes_caps_through_controller_and_bridge(self):
        from tests.test_sermon_strict_locale import LocaleTests
        fixture=LocaleTests();self.addCleanup(fixture.doCleanups); fixture.setUp()
        with fixture.f.session():
            result=fixture.run_locale(request_limits=limits.DEFAULT_REQUEST_LIMITS)
            self.assertEqual(result['status'],'waiting_human')
            repeated=fixture.run_locale(request_limits=limits.DEFAULT_REQUEST_LIMITS)
            self.assertEqual(repeated['candidateSha256'],result['candidateSha256'])
        self.assertEqual(len(fixture.f.calls),4)
        self.assertTrue(all(call['max_completion_tokens']==4096 for call in fixture.f.calls))

class TranscriptionIntegrationTests(unittest.TestCase):
    setUp = ProviderTests.setUp
    provider_for = ProviderTests.provider_for
    http = ProviderTests.http
    payload = ProviderTests.payload
    def wav(self,seconds=1):
        import wave
        out=io.BytesIO()
        with wave.open(out,'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000)
            stream.writeframes(b'\0\0'*(16000*seconds))
        return out.getvalue()

    def audio_provider(self,raw,**overrides):
        def execute(req,timeout,*,deadline=None):
            self.calls.append((req,timeout))
            return {'text':'Synthetic ASR evidence.','usage':{'type':'duration','seconds':180}}
        subject=p.DiagnosticProvider(self.store,config(sourceAudioSha256=c.bytes_sha256(raw),**overrides),
            executor=execute,monotonic=lambda:self.clock,domain=lambda:'7'*64)
        subject.source_check_payload=Mock(side_effect=self.payload)
        return subject

    def test_audio_decode_price_and_restart_no_second_transcription(self):
        raw=self.wav(180);subject=self.audio_provider(raw)
        with self.f.session():
            result=subject.transcribe('synthetic',raw)
            self.assertEqual(subject.transcribe('synthetic',raw),result)
            subject=self.audio_provider(raw)
            self.assertEqual(subject.transcribe('synthetic',raw),result)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(subject.snapshot()['reservedMicrousd'],13500)
        req,timeout=self.calls[0]
        self.assertEqual(req.full_url,p.pipeline.TRANSCRIBE_URL)
        self.assertIn(b'name="model"\r\n\r\ngpt-transcribe',req.data)
        self.assertLessEqual(timeout,300)
        rows,_=accounting.read_events(self.f.root/'logs')
        receipt=next(row for row in rows if row['event']=='api_attempt')
        self.assertIsNone(receipt['usage']['inputTokens']);self.assertEqual(receipt['usage']['audioSeconds'],180)

    def test_audio_request_cap_denial_has_matching_undispatched_terminal(self):
        raw=self.wav(180);subject=self.audio_provider(raw,maxRequests=1)
        with self.f.session():
            subject.transcribe('synthetic',raw)
            before=subject.snapshot()
            with self.assertRaisesRegex(p.pipeline.PreDispatchRejection,'provider_request_limit'):
                subject.transcribe('synthetic',raw,operation_id='transcription.explicit-second')
            self.assertEqual(subject.snapshot(),before)
        rows,damaged=accounting.read_events(self.f.root/'logs')
        starts=[r for r in rows if r['event']=='api_attempt_started']
        terminals=[r for r in rows if r['event']=='api_attempt']
        self.assertEqual(damaged,[])
        self.assertEqual({r['attemptId'] for r in starts},{r['attemptId'] for r in terminals})
        failed=next(r for r in terminals if r['status']=='failed')
        self.assertEqual(failed['metrics'],{'dispatched':False})
        self.assertEqual(failed['reasonCode'],'provider_request_limit')
        self.assertEqual(len(self.calls),1)

    def test_audio_and_chat_share_hard_ceiling_without_zero_tokens(self):
        raw=self.wav(180);subject=self.audio_provider(raw,targetMicrousd=13500,hardLimitMicrousd=13500)
        with self.f.session():
            subject.transcribe('synthetic',raw)
            with self.assertRaisesRegex(ValueError,'provider_cost_limit'):subject.chat('synthetic',self.payload())
        self.assertEqual(len(self.calls),1)
        state=c.read_snapshot(self.store.root/budget.STORE_ID/'provider-run/state.json')[0]
        self.assertNotIn('inputTokens',next(iter(state['requests'].values()))['bounds'])

    def test_audio_failures_no_local_fallback_and_unknown_blocks_retry(self):
        raw=self.wav(180);subject=self.audio_provider(raw)
        subject.executor=Mock(side_effect=TimeoutError('synthetic'))
        with self.f.session():
            with self.assertRaises(TimeoutError):subject.transcribe('synthetic',raw)
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):
                subject.transcribe('synthetic',raw,operation_id='transcription.review-recovery')
        self.assertEqual(subject.executor.call_count,1)

    def test_audio_max_two_known_attempts_and_saved_response_on_logging_failure(self):
        raw=self.wav(180);subject=self.audio_provider(raw)
        with self.f.session(),patch.object(p.pipeline,'record_api_attempt',side_effect=accounting.AccountingWriteError('synthetic')):
            with self.assertRaises(accounting.AccountingWriteError):subject.transcribe('synthetic',raw)
        with self.f.session():
            subject.transcribe('synthetic',raw)
            subject.transcribe('synthetic',raw,operation_id='transcription.second')
            with self.assertRaisesRegex(ValueError,'source_call_limit'):
                subject.transcribe('synthetic',raw,operation_id='transcription.third')
        self.assertEqual(len(self.calls),2)


if __name__ == '__main__':
    unittest.main()

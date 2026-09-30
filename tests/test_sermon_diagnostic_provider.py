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
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_strict_budget_adapter as adapter
from scripts import sermon_accounting as accounting
from scripts import sermon_strict_candidate_bridge as bridge
from tests import test_sermon_strict_layer2 as fixtures


def config(**kw):
    result = dict(schemaVersion=p.SCHEMA, runId='1'*64, approvalSha256='2'*64, codeSha256='3'*64,
        sourceMediaSha256='4'*64, sourceClipSha256='5'*64,sourceAudioSha256='9'*64, sourceWindowSeconds=[60,240],
        targetMicrousd=25_000_000, hardLimitMicrousd=40_000_000,totalWallSeconds=5400,maxRequests=124,
        credentialReferenceSha256='6'*64,projectId=None,organizationId=None,transcriptionModel='gpt-transcribe')
    return {**result,**kw}


def authority():
    bound=dict(requests=124,inputTokens=2_000_000,outputTokens=1_000_000,wallTimeMs=40_000_000,costMicrousd=40_000_000)
    return dict(approvalSha256='2'*64,globalBounds=bound,unitBounds=bound,limits=budget.DEFAULT_LIMITS)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.StrictAdapterTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root/'revision';self.store=budget.BudgetStore(self.f.root/'budget',authority())
        self.clock=100.;self.calls=[];self.selected=deepcopy(limits.DEFAULT_REQUEST_LIMITS)
        self.prepared=strict.prepare(*self.f.args,self.f.group,request_limits=self.selected)
        self.provider=self.provider_for()
        self.bound=dict(requests=1,inputTokens=8192,outputTokens=4096,wallTimeMs=300000,costMicrousd=307200)
        self.subject=adapter.StrictBudgetAdapter(self.store)

    def provider_for(self,**kw):
        return p.DiagnosticProvider(self.store,config(**kw),self.selected,executor=self.http,
            monotonic=lambda:self.clock,domain=lambda:'7'*64)

    def payload(self):
        return limits.bounded_payload(dict(model='gpt-6-astra',reasoning_effort='high',
            messages=[dict(role='user',content='Return JSON test.')],response_format={'type':'json_object'}),self.selected)

    def http(self,req,timeout):
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
            with self.assertRaisesRegex(ValueError,'provider_cost_limit'):self.generate()
        self.assertEqual(len(self.calls),1);self.assertEqual(self.provider.snapshot()['remainingMicrousd'],0)

    def test_unknown_timeout_and_restart_never_issue_another_request(self):
        self.provider.executor=Mock(side_effect=TimeoutError('synthetic'))
        with self.f.session():
            with self.assertRaises(TimeoutError):self.provider.chat('synthetic',self.payload())
            self.provider=self.provider_for()
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.provider.chat('synthetic',self.payload())
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.provider.snapshot()['unknownModelCallIds']),1)

    def test_missing_tokens_keeps_unknown_cache_and_blocks_more_calls(self):
        original=self.http
        def missing(req,timeout):
            response=original(req,timeout);response.pop('usage');return response
        self.provider.executor=missing
        with self.f.session():
            result=self.generate();self.assertEqual(result['budgetStatus'],'reconciliation_required')
            with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.provider.chat('synthetic',self.payload())
        self.assertEqual(len(self.calls),1)

    def test_total_deadline_and_boot_change_do_not_reset_on_restart(self):
        with self.f.session():
            self.provider.chat('synthetic',self.payload());self.clock+=5400
            self.provider=self.provider_for()
            new=self.payload();new['messages'][0]['content']='Distinct request.'
            with self.assertRaisesRegex(ValueError,'deadline_reached'):self.provider.chat('synthetic',new)
            self.clock-=5400;self.provider.domain=lambda:'8'*64
            with self.assertRaisesRegex(ValueError,'clock_domain_changed'):self.provider.chat('synthetic',new)
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
        self.assertEqual(len(self.provider.snapshot()['unknownModelCallIds']),1)

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
            with self.assertRaisesRegex(ValueError,'operation_input_changed'):
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
        fixture=LocaleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
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
        def execute(req,timeout):
            self.calls.append((req,timeout))
            return {'text':'Synthetic ASR evidence.','usage':{'type':'duration','seconds':180}}
        return p.DiagnosticProvider(self.store,config(sourceAudioSha256=c.bytes_sha256(raw),**overrides),
            executor=execute,monotonic=lambda:self.clock,domain=lambda:'7'*64)

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

"""Full ASR -> fixed source check -> strict locale with one captured transport.

All content/approval fixtures are synthetic. Legacy HTTP and subprocess entry
points are actively denied, not substituted with successful fake producers.
"""
import io
import json
import socket
import struct
import subprocess
import unittest
from unittest.mock import Mock
import urllib.request

from scripts import run_bounded_diagnostic as run
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_review_contracts as c
from scripts import sermon_accounting as accounting
from scripts import sermon_strict_layer2 as strict
from scripts import sermon_transcription_request as audio
from tests import test_sermon_diagnostic_provider as provider_fixtures
config = provider_fixtures.config
from tests.test_sermon_transcription_request import wav, riff_size


class BoundedRunTests(unittest.TestCase):
    def setUp(self):
        self.fixture=provider_fixtures.ProviderTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture.f
        self.raw=wav(frames=16000*180)
        self.calls=[]
        self.clip=self.f.root/'source-180s.mp4'
        self.clip.write_bytes(b'synthetic approved clip')
        self.subject=provider.DiagnosticProvider(self.fixture.store,
            config(sourceAudioSha256=c.bytes_sha256(self.raw), sourceClipSha256=c.bytes_sha256(self.clip.read_bytes())), executor=self.capture,
            monotonic=lambda:100.,domain=lambda:'7'*64)
        self.runner=run.BoundedRun(self.subject,'synthetic',self.f.root,source_clip=self.clip)
        self.groups=self.f.f.evidence['groups'].copy()
        self.plan=[{k:row[k] for k in ('translationGroupId','sourceUnitIds')} for row in self.groups]
        self.graph=[{'workUnitId':strict.prepare(*self.f.args,row)['workUnitId'],
                     'layer':2,'targetLocale':'zh-Hans','dependsOn':[]} for row in self.plan]

    def capture(self,req,timeout,*,deadline):
        self.calls.append((req,timeout,deadline))
        if req.full_url.endswith('/audio/transcriptions'):
            return {'text':'Synthetic English source.','usage':{'type':'duration','seconds':180}}
        payload=json.loads(req.data)
        inputs=json.loads(payload['messages'][1]['content'])
        if 'translationGroupId' not in inputs:
            value={'issues':[],'uncertainty':[]}
        elif payload['model']=='gpt-6-astra':
            group=next(row for row in self.groups if row['translationGroupId']==inputs['translationGroupId'])
            value={key:group[key] for key in ('translationGroupId','sourceUnitIds','targetUtterances','coverage')}
        else:
            value={'reviewedArtifactSha256':inputs['reviewedArtifactSha256'],'reviewVerdict':'pass',
                'checks':[{'checkId':key,'result':'pass','evidence':'synthetic'} for key in sorted(c.HARD_CHECKS)],
                'issues':[],'assessedUnitIds':inputs['sourceUnitIds'],'unassessedUnitIds':[]}
        return {'id':'capture-'+str(len(self.calls)), 'model':payload['model'],
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':20}}

    def locale(self):
        return self.runner.run_locale(*self.f.args,graph=self.graph,plugin_path=self.f.f.plugin_path,
            plugin_sha256=self.f.f.plugin_sha,group_plan=self.plan)

    def test_all_six_calls_share_ledger_trace_caps_and_resume_without_new_calls(self):
        with self.f.session():
            self.runner.transcribe(self.raw)
            self.runner.source_check(operation_id='source.initial')
            result=self.locale()
            self.assertEqual(result['status'],'waiting_human')
            self.runner.transcribe(self.raw)
            self.runner.source_check(operation_id='source.initial')
            again=self.locale()
            self.assertEqual(again['candidateSha256'],result['candidateSha256'])
        self.assertEqual(len(self.calls),6)
        self.assertEqual(self.subject.snapshot()['requestCount'],6)
        self.assertTrue(all(deadline==400. and timeout==300. for _,timeout,deadline in self.calls))
        models=['gpt-transcribe']+[json.loads(req.data)['model'] for req,_,_ in self.calls[1:]]
        self.assertEqual(models,['gpt-transcribe','gpt-6-astra','gpt-6-astra','gpt-6-sol','gpt-6-astra','gpt-6-sol'])
        rows,errors=accounting.read_events(self.f.root/'logs');self.assertFalse(errors)
        receipts=[row for row in rows if row['event']=='api_attempt']
        self.assertEqual(len(receipts),6)
        self.assertTrue(all(row['executorType']=='production_model' for row in receipts))
        source_receipt=next(row for row in receipts if row['stage']=='diagnostic.source_model')
        self.assertIsNotNone(source_receipt['parentSpanId'])
        source_spans=[row for row in rows if row['event']=='stage_finished'
                      and row['spanId']==source_receipt['spanId']]
        self.assertEqual(len(source_spans),1)
        self.assertGreaterEqual(source_spans[0]['elapsedSeconds'],source_receipt['elapsedSeconds'])
        from scripts.weekly_pipeline_report import project
        report=project(self.f.root/'logs')
        self.assertEqual(report['observedProviderCalls']['directReceiptCount'],len(self.calls))
        self.assertEqual(report['reportGenerationNetworkCalls'],0)
        self.assertEqual(len({row['providerScopeKey'] for row in receipts}),1)
        self.assertEqual(len({row['productionRunId'] for row in receipts}),1)
        self.assertEqual(len({row['modelCallId'] for row in receipts}),6)
        self.assertIsNone(receipts[0]['usage']['inputTokens'])
        self.assertTrue(all(row['usage']['inputTokens']==100 for row in receipts[1:]))
        checks=[row for row in rows if row['event']=='rqc_observation']
        self.assertTrue(checks)

    def test_changed_clip_rejects_every_phase_before_reservation(self):
        self.clip.write_bytes(b'different unapproved clip')
        for action in (lambda: run.BoundedRun(self.subject,'synthetic',self.f.root,source_clip=self.clip),
                       lambda: self.runner.transcribe(self.raw),
                       lambda: self.runner.source_check(operation_id='source.initial'), self.locale):
            with self.assertRaisesRegex(ValueError,'diagnostic_source_clip_changed'):action()
        self.assertFalse(self.subject.store.root.exists())
        self.assertEqual(self.calls,[])

    def test_simulated_human_context_keeps_one_bounded_provider_and_real_review(self):
        from scripts import sermon_diagnostic_context as diagnostic
        from tests.test_sermon_diagnostic_context import reidentify
        source,anchor,policy,rubric=map(c.decode_json,self.f.args)
        source.update(status='blocked',translationEligible=False,candidateTranslationEligible=False)
        source['review'].update(humanApproval=False,reviewedBy=None,reviewedAt=None,
            reviewedSourceUnitIds=[],evidence=None,checks={k:'pending' for k in diagnostic.PENDING_CHECKS})
        source['source']['approvedWindow'].update(status='pending',humanApproval=False,evidence=None)
        source['transcript']['completenessReview']='pending'
        source['issues']=[{'stage':'source','type':'approved_sermon_window_missing'}]+[
            {'stage':'review','type':k+'_review_pending'} for k in diagnostic.PENDING_CHECKS]
        reidentify(source)
        policy['sourceScope']['englishSourcePackageJsonSha256']=c.canonical_sha256(source)
        policy['componentSha256']['sourceScope']=c.canonical_sha256(policy['sourceScope'])
        raw=[strict.material_bytes(x) for x in (source,anchor,policy,rubric)]
        ctx=dict(schemaVersion=diagnostic.SCHEMA,runId=self.subject.config['runId'],
            runConfigSha256=c.canonical_sha256(self.subject.config),storeSha256=self.subject.store.store_sha256,
            sourceCanonicalSha256=c.canonical_sha256(source),anchorCanonicalSha256=c.canonical_sha256(anchor),
            simulationAuthorizationRef='a'*64,continuationCodeCommit='b'*40,
            humanAcceptance='pending',productionEligible=False)
        with self.f.session():
            self.runner.transcribe(self.raw)
            self.runner.source_check(operation_id='source.initial')
            kwargs=dict(graph=self.graph,plugin_path=self.f.f.plugin_path,
                plugin_sha256=self.f.f.plugin_sha,group_plan=self.plan,diagnostic_context=ctx)
            result=self.runner.run_locale(*raw,**kwargs)
            replay=self.runner.run_locale(*raw,**kwargs)
        self.assertEqual(result['status'],'waiting_human')
        self.assertEqual(result['candidateSha256'],replay['candidateSha256'])
        self.assertEqual(len(self.calls),6)
        self.assertEqual(self.subject.snapshot()['requestCount'],6)
        self.assertFalse(source['review']['humanApproval'])
        self.assertFalse(source['translationEligible'])

    def test_source_check_requires_actual_saved_asr_and_cannot_substitute_prompt(self):
        with self.f.session():
            with self.assertRaisesRegex(ValueError,'verified_transcription_required'):
                self.runner.source_check(operation_id='source.initial')
            self.runner.transcribe(self.raw)
            payload=self.subject.source_check_payload()
            contents=json.loads(payload['messages'][1]['content'])
            self.assertEqual(contents['transcript'],'Synthetic English source.')
            self.assertEqual(contents['sourceAudioSha256'],c.bytes_sha256(self.raw))
            payload['messages'][1]['content']='Another unapproved sermon'
            with self.assertRaisesRegex(ValueError,'source_check_payload_changed'):
                self.subject.chat('synthetic',payload,request_limits=run.limits.MAX_REQUEST_LIMITS)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.subject.snapshot()['requestCount'],1)

    def test_legacy_parent_http_and_unbounded_subprocess_are_denied(self):
        with run.bounded_network_only():
            with self.assertRaisesRegex(RuntimeError,'legacy_network_forbidden'):
                socket.create_connection(('example.invalid',443))
            with self.assertRaisesRegex(ValueError,'unbounded_subprocess_forbidden'):
                subprocess.run(['curl','https://example.invalid'],check=True)
        self.assertEqual(self.calls,[])

    def test_changed_source_or_unknown_asr_stops_downstream(self):
        self.subject.executor=Mock(return_value={'model':'wrong-model','text':'Synthetic',
                                                 'usage':{'type':'duration','seconds':180}})
        with self.f.session():
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'reconciliation_required'):self.runner.transcribe(self.raw)
            with self.assertRaisesRegex(ValueError,'verified_transcription_required'):
                self.runner.source_check(operation_id='source.initial')
        self.subject.executor.assert_called_once()

    def test_multipart_overflow_fails_before_reservation_or_transport(self):
        base=wav();padding=audio.MAX_AUDIO_BYTES-len(base)-8
        raw=riff_size(base+b'JUNK'+struct.pack('<I',padding)+bytes(padding))
        self.subject.config['sourceAudioSha256']=c.bytes_sha256(raw)
        with self.f.session(),self.assertRaisesRegex(ValueError,'multipart_size_limit'):
            self.runner.transcribe(raw)
        self.assertFalse(self.subject.store.root.exists());self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()

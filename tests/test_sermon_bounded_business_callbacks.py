import json
import socket
import unittest
from unittest.mock import patch
from scripts import sermon_bounded_business_callbacks as callbacks
from scripts import sermon_review_contracts as c
from tests import test_run_bounded_diagnostic as fixtures


class BusinessCallbacksTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BoundedRunTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.transport=callbacks.OfflineHTTPTransport(f.capture,fixture_id='business_fixture')
        f.subject.executor=self.transport
        self.subject=callbacks.BoundedBusinessCallbacks(f.subject,f.f.root,source_clip=f.clip,
            fixture_id='business_fixture',offline=True)

    def locale(self, **kwargs):
        f=self.fixture
        return self.subject.locale(*f.f.args,graph=f.graph,plugin_path=f.f.f.plugin_path,
            plugin_sha256=f.f.f.plugin_sha,group_plan=f.plan,**kwargs)

    def test_real_business_calls_share_ledger_and_restart_without_transport(self):
        f=self.fixture
        with f.f.session():
            asr=self.subject.transcribe(f.raw)
            source=self.subject.source_check(depends_on=asr['completionSpans'])
            result=self.locale(depends_on=source['completionSpans'])
            self.assertEqual(result['result']['status'],'waiting_human')
            state=self.subject.provider_evidence()
            self.assertEqual(len(state['requests']),6)
            self.assertEqual(len(self.transport.observations),6)
            resumed=callbacks.BoundedBusinessCallbacks(f.subject,f.f.root,source_clip=f.clip,
                fixture_id='business_fixture',offline=True)
            resumed.transcribe(f.raw);resumed.source_check()
            again=self.locale()
            self.assertEqual(again['result']['candidateSha256'],result['result']['candidateSha256'])
            self.assertEqual(again['result']['output'],result['result']['output'])
            self.assertEqual(len(self.transport.observations),6)
            self.assertEqual(resumed.provider_evidence(),state)
            candidate=c.read_snapshot(__import__('pathlib').Path(result['result']['output'])/'candidate.json')[0]
            self.assertFalse(candidate['releaseEligible'])
            self.assertEqual(candidate['humanReview']['translation'],'pending')
        from scripts import sermon_accounting as accounting
        rows,errors=accounting.read_events(f.f.root/'logs');self.assertFalse(errors)
        starts={r['spanId']:r for r in rows if r['event']=='stage_started'}
        self.assertEqual(starts[source['completionSpans'][0]]['dependsOn'],asr['completionSpans'])
        self.assertTrue(all(r.get('evidenceMode')=='synthetic' for r in rows))

    def test_existing_source_builder_keeps_frozen_review_and_scope(self):
        f=self.fixture
        source=c.decode_json(f.f.args[0])
        metadata=source['source']
        kwargs=dict(summary_path=source['evidence']['pipelineSummary']['path'],
            approval_evidence_path=metadata['approvedWindow']['evidence']['path'],
            review_path=source['review']['evidence']['path'],
            machine_judge_path=(source['evidence']['machineJudge'] or {}).get('path'),
            source_id=metadata['sourceId'],source_url_hash=metadata['sourceUrlHash'],
            service_date=metadata['serviceDate'])
        from pathlib import Path
        kwargs={k:Path(v) if k.endswith('_path') and v is not None else v for k,v in kwargs.items()}
        with f.f.session():
            result=self.subject.source_package(Path(source['transcript']['artifact']['path']),
                Path(source['anchors']['artifact']['path']), **kwargs)
            self.assertEqual(result['result'],source)
            self.assertEqual(self.transport.observations,[])
            summary=kwargs['summary_path'];original=summary.read_bytes()
            changed=json.loads(original);changed['sermonEndSeconds']=241
            summary.write_text(json.dumps(changed))
            try:
                with self.assertRaisesRegex(ValueError,'scope_changed'):
                    self.subject.source_package(Path(source['transcript']['artifact']['path']),
                        Path(source['anchors']['artifact']['path']), **kwargs)
            finally:summary.write_bytes(original)

    def test_unknown_receipt_blocks_repeat_and_retains_original_reservation(self):
        f=self.fixture
        def unknown(req,timeout,*,deadline):raise TimeoutError('synthetic')
        self.transport.responder=unknown
        with f.f.session():
            with self.assertRaises(TimeoutError):self.subject.transcribe(f.raw)
            before=self.subject.provider_evidence()
            self.assertEqual(len(before['requests']),1)
            with self.assertRaises(ValueError):self.subject.transcribe(f.raw)
            self.assertEqual(self.subject.provider_evidence(),before)
        self.assertEqual(len(self.transport.observations),1)

    def test_no_network_even_if_fixture_responder_attempts_it(self):
        f=self.fixture
        self.transport.responder=lambda *a,**k: socket.create_connection(('example.invalid',443))
        with f.f.session(), self.assertRaisesRegex(RuntimeError,'transport_forbidden'):
            self.subject.transcribe(f.raw)
        self.assertEqual(len(self.transport.observations),1)

    def test_default_real_executor_or_non_synthetic_profile_refused(self):
        f=self.fixture
        with self.assertRaisesRegex(ValueError,'offline_provider'):
            callbacks.BoundedBusinessCallbacks(f.subject,f.f.root,source_clip=f.clip,
                fixture_id='business_fixture')
        with self.assertRaisesRegex(ValueError,'synthetic_accounting'):
            self.subject.transcribe(f.raw)
        self.assertEqual(self.transport.observations,[])

    def test_ambient_accounting_outside_fixture_is_rejected_before_write(self):
        from scripts import sermon_log_profile as profile
        from scripts import sermon_accounting as accounting
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            outside=Path(temp)/'ledger';outside.mkdir()
            marker=outside/'unchanged';marker.write_bytes(b'unchanged')
            with profile.context(workKind='engineering',evidenceMode='synthetic'), \
                 patch.dict(__import__('os').environ, {accounting.ENV_KEYS[0]:str(outside),accounting.ENV_KEYS[1]:'outside'}):
                with self.assertRaisesRegex(ValueError,'accounting_outside_scope'):
                    self.subject.transcribe(self.fixture.raw)
            self.assertEqual(list(outside.iterdir()),[marker])
            self.assertEqual(marker.read_bytes(),b'unchanged')
            self.assertEqual(self.transport.observations,[])

    def test_changed_inputs_and_transport_rejected_before_dispatch(self):
        f=self.fixture
        f.clip.write_bytes(b'changed')
        with f.f.session(), self.assertRaisesRegex(ValueError,'source_clip_changed'):
            self.subject.transcribe(f.raw)
        self.assertEqual(self.transport.observations,[])
        f.subject.executor=lambda *a,**kw: None
        with f.f.session(), self.assertRaisesRegex(ValueError,'identity_changed'):
            self.subject.source_check()


if __name__=='__main__':unittest.main()

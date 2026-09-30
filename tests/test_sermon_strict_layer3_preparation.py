import unittest
import json
from unittest.mock import patch
from scripts import sermon_strict_layer3_preparation as prep
from scripts import sermon_review_contracts as c
from scripts import sermon_public_snapshot as public
from scripts import sermon_review_budget as budget
from scripts import sermon_strict_gate_admission as admission
from tests import test_sermon_strict_gate_admission as gates
from tests import test_prepare_target_language_speech_job as voices


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.f=gates.AdmissionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.intent=self.f.admit()['intent']['intentId']
        fixture=voices.TargetLanguageSpeechJobTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.registry=fixture.registry;self.adapter=fixture.adapter
        capability=next(row for row in self.registry['speakers'][0]['localeCapabilities'] if row['targetLocale']=='zh-Hans')
        capability.pop('adapterOverride',None)
        self.adapter.update(targetLocale='zh-Hans',languageParameter=capability['modelLanguage'],
            capabilityEvidenceSha256=c.canonical_sha256(capability['reviewEvidence']),
            registryJsonSha256=c.canonical_sha256(self.registry))
        self.adapter_path=self.f.root/'speech-adapter.json';self.registry_path=self.f.root/'registry.json'
        self.adapter_path.write_bytes(c.canonical_bytes(self.adapter));self.registry_path.write_bytes(c.canonical_bytes(self.registry))
        self.out=self.f.root/'speech-output'

    def prepare(self,out=None):
        return prep.prepare(self.f.boundary,self.intent,adapter_path=self.adapter_path,
            registry_path=self.registry_path,out=out or self.out)

    def test_actual_existing_speech_builder_preserves_all_gates_and_runs_no_models(self):
        count=len(self.f.f.f.calls)
        result=self.prepare();self.assertEqual(result['status'],'prepared')
        self.assertFalse(result['synthesisEligible']);self.assertFalse(result['dispatched'])
        self.assertEqual(self.prepare(),result);self.assertEqual(len(self.f.f.f.calls),count)
        job=c.read_snapshot(self.out/'job.json')[0]
        candidate=c.read_snapshot(self.f.root/'public.json')[0]
        self.assertEqual([u['text'] for u in job['units']],[g['targetText'] for g in candidate['groups']])
        with self.assertRaisesRegex(ValueError,'speech_preparation_identity_changed'):
            self.prepare(self.f.root/'moved-output')

    def test_unknown_write_reconciles_exact_job_without_rebuilding(self):
        original=prep.jobs._persist
        def lost(path,value):
            original(path,value)
            if path.name=='job.json':raise OSError('synthetic lost acknowledgement')
        with patch.object(prep.jobs,'_persist',side_effect=lost):
            with self.assertRaises(OSError):self.prepare()
        before=(self.out/'job.json').read_bytes()
        self.prepare();self.assertEqual((self.out/'job.json').read_bytes(),before)

    def test_new_approval_or_changed_adapter_does_not_reuse_old_permission(self):
        human=self.f.root/'human.json';data=c.read_snapshot(human)[0];data['reviewer']='different'
        human.write_bytes(c.canonical_bytes(data))
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.out.exists())

    def test_reissued_valid_receipt_prepares_with_new_intent_only(self):
        candidate = (self.f.root / 'public.json').read_bytes()
        calls = len(self.f.f.f.calls)
        self.f.approve(evidence='Synthetic reissued receipt for unchanged candidate')
        self.assertEqual((self.f.root / 'public.json').read_bytes(), candidate)
        with self.assertRaisesRegex(ValueError, 'layer3_admission_evidence_changed'):
            self.prepare()
        self.assertFalse(self.out.exists())
        result = self.f.admit()
        self.assertEqual(result['status'], 'committed', result)
        self.assertNotEqual(result['intent']['intentId'], self.intent)
        self.intent = result['intent']['intentId']
        prepared = self.prepare()
        self.assertEqual(prepared['status'], 'prepared')
        self.assertEqual(self.prepare(), prepared)
        self.assertEqual(len(self.f.f.f.calls), calls)

    def test_completed_job_deletion_is_not_silently_recreated(self):
        self.prepare();(self.out/'job.json').unlink()
        with self.assertRaisesRegex(ValueError,'completed_output_missing'):self.prepare()


class LargePreparationTests(unittest.TestCase):
    prepare=PreparationTests.prepare

    def setUp(self):
        PreparationTests.setUp(self)
        for group in self.f.f.groups:
            original=''.join(group['targetUtterances'])
            group['targetUtterances']=[original+'爱'*15500,'爱'*15500,'爱'*15500]
        fixture=self.f.f.f;original_transport=fixture.transport
        def utf8_transport(key,payload,*,response_observer):
            def observed(response,call_id,elapsed):
                content=response['choices'][0]['message']['content']
                response['choices'][0]['message']['content']=json.dumps(json.loads(content),ensure_ascii=False)
                return response_observer(response,call_id,elapsed)
            observed.request_started=response_observer.request_started
            if hasattr(response_observer,'request_rejected'):
                observed.request_rejected=response_observer.request_rejected
            return original_transport(key,payload,response_observer=observed)
        fixture.transport=utf8_transport
        self.f.store=budget.BudgetStore(self.f.root/'large-budget',self.f.store.authority)
        self.f.generate_groups();self.f.approve()
        self.f.boundary=admission.AdmissionBoundary(self.f.config,self.f.store)
        self.intent=self.f.admit()['intent']['intentId']
        for root,_ in self.f.f.revisions:
            for path in root.glob('*.json'):
                self.assertLessEqual(path.stat().st_size,c.MAX_BYTES)
        self.calls=len(fixture.calls)

    def marker(self):
        rows=list((self.f.store.root/budget.STORE_ID).glob('gate-*/prepare-'+self.intent+'.json'))
        self.assertEqual(len(rows),1)
        return rows[0]

    def assert_large_job(self):
        path=self.out/'job.json';raw=path.read_bytes()
        self.assertGreater(len(raw),c.MAX_BYTES)
        self.assertLessEqual(len(raw),public.MAX_BYTES)
        with self.assertRaises(ValueError):c.read_snapshot(path)
        job=public.read_snapshot(path)[0]
        self.assertEqual(len(job['units']),2)
        self.assertFalse(job['releaseEligible'])
        return raw

    def test_large_prepared_job_replays_without_new_calls_or_byte_changes(self):
        first=self.prepare();self.assertEqual(first['status'],'prepared')
        raw=self.assert_large_job()
        self.assertEqual(c.read_snapshot(self.marker())[0]['status'],'prepared')
        self.assertEqual(self.prepare(),first)
        self.assertEqual((self.out/'job.json').read_bytes(),raw)
        self.assertEqual(len(self.f.f.f.calls),self.calls)

    def test_large_reserved_job_recovers_after_lost_write_acknowledgement(self):
        original=prep.jobs._persist
        def lost(path,value):
            original(path,value)
            if path.name=='job.json':raise OSError('synthetic lost acknowledgement')
        with patch.object(prep.jobs,'_persist',side_effect=lost):
            with self.assertRaises(OSError):self.prepare()
        raw=self.assert_large_job()
        self.assertEqual(c.read_snapshot(self.marker())[0]['status'],'reserved')
        resumed=self.prepare();self.assertEqual(resumed['status'],'prepared')
        self.assertEqual((self.out/'job.json').read_bytes(),raw)
        self.assertEqual(c.read_snapshot(self.marker())[0]['status'],'prepared')
        self.assertEqual(self.prepare(),resumed)
        self.assertEqual(len(self.f.f.f.calls),self.calls)

    def test_large_reserved_job_with_no_output_recovers_once(self):
        original=prep.jobs._persist
        def failed(path,value):
            if path.name=='job.json':raise OSError('synthetic write interrupted')
            return original(path,value)
        with patch.object(prep.jobs,'_persist',side_effect=failed):
            with self.assertRaises(OSError):self.prepare()
        self.assertFalse((self.out/'job.json').exists())
        self.assertEqual(c.read_snapshot(self.marker())[0]['status'],'reserved')
        result=self.prepare();self.assertEqual(result['status'],'prepared')
        self.assert_large_job();self.assertEqual(self.prepare(),result)
        self.assertEqual(len(self.f.f.f.calls),self.calls)


class PreparationSizeLimitTests(unittest.TestCase):
    prepare=PreparationTests.prepare

    def setUp(self):PreparationTests.setUp(self)

    def test_formatted_public_job_limit_rejects_before_marker_or_output(self):
        config=self.f.boundary.config
        expected=prep.speech.prepare_job(config.source,config.anchor,config.public_candidate,config.policy,
            config.human_receipt,self.adapter_path,self.registry_path,self.out,
            strict_rubric=c.read_snapshot(config.rubric)[0],build_only=True)
        formatted=(json.dumps(expected,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
        cap=len(formatted)-1
        self.assertLess((self.f.root/'public.json').stat().st_size,cap)
        self.assertLess(len(c.canonical_bytes(expected)),cap)
        before=len(self.f.f.f.calls)
        with patch.object(public,'MAX_BYTES',cap):
            with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.out.exists())
        self.assertEqual(list((self.f.store.root/budget.STORE_ID).glob('gate-*/prepare-*.json')),[])
        self.assertEqual(len(self.f.f.f.calls),before)


if __name__=='__main__':unittest.main()

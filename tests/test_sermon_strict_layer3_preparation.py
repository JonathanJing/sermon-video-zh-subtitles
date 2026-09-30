import unittest
from unittest.mock import patch
from scripts import sermon_strict_layer3_preparation as prep
from scripts import sermon_review_contracts as c
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

    def test_completed_job_deletion_is_not_silently_recreated(self):
        self.prepare();(self.out/'job.json').unlink()
        with self.assertRaisesRegex(ValueError,'completed_output_missing'):self.prepare()


if __name__=='__main__':unittest.main()

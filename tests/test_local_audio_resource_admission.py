import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import local_audio_resource_admission as subject
from scripts.sermon_unified import resources, contracts


class LocalAudioAdmissionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.job=self.root/'tts';self.job.mkdir()
        self.identity={'schemaVersion':'diagnostic-v1','diagnosticOnly':True,'stage':'tts'}
        self.policy={'schemaVersion':resources.POLICY_VERSION,'brokerRoot':str(self.root/'broker'),
                     'capacities':{'cpu':1,'online_api':0,'codex_cli':1,'spark_tts':1,'publisher':0}}
    def held(self):
        d=contracts.read(self.root/'broker'/resources.BROKER_LOCK_ID/'resources.json')
        return [x for x in d['reservations'].values() if x['status']=='held']
    def manifest(self):
        d={**self.identity,'status':'completed_diagnostic'}
        (self.job/'manifest.json').write_text(json.dumps(d));return d
    def test_tts_and_asr_share_capacity_and_unknown_is_not_replayed(self):
        subject.admit(self.job,self.identity,self.policy)
        other=self.root/'asr';other.mkdir()
        with self.assertRaisesRegex(contracts.ContractError,'resource_capacity_busy'):
            subject.admit(other,{'stage':'asr'},self.policy)
        with self.assertRaisesRegex(contracts.ContractError,'already_reserved'):
            subject.admit(self.job,self.identity,self.policy)
        self.assertEqual(len(self.held()),1)
    def test_completed_manifest_releases_and_recovery_is_idempotent(self):
        subject.admit(self.job,self.identity,self.policy)
        report=self.manifest()
        subject.finish(self.job,self.identity,self.policy,report)
        subject.finish(self.job,self.identity,self.policy,report)
        self.assertEqual(self.held(),[])
        with self.assertRaisesRegex(contracts.ContractError,'already_reserved'):
            subject.admit(self.job,self.identity,self.policy)
    def test_failed_durable_outcome_write_does_not_release(self):
        subject.admit(self.job,self.identity,self.policy);report=self.manifest()
        with patch.object(subject,'atomic_json',side_effect=OSError('storage failure')):
            with self.assertRaises(OSError):subject.finish(self.job,self.identity,self.policy,report)
        self.assertEqual(len(self.held()),1)
        subject.finish(self.job,self.identity,self.policy,report)
        self.assertEqual(self.held(),[])
    def test_changed_manifest_never_releases(self):
        subject.admit(self.job,self.identity,self.policy);report=self.manifest()
        (self.job/'manifest.json').write_text('{}')
        with self.assertRaisesRegex(contracts.ContractError,'terminal_unconfirmed'):
            subject.finish(self.job,self.identity,self.policy,report)
        self.assertEqual(len(self.held()),1)
    def test_zero_capacity_busy_can_retry_without_dispatch(self):
        subject.admit(self.job,self.identity,self.policy)
        other=self.root/'asr';other.mkdir()
        with self.assertRaises(contracts.ContractError):subject.admit(other,{'stage':'asr'},self.policy)
        subject.finish(self.job,self.identity,self.policy,self.manifest())
        subject.admit(other,{'stage':'asr'},self.policy)
        self.assertEqual(len(self.held()),1)

    def test_gpu_cleanup_proof_required_before_release(self):
        self.identity['gpuCleanupRequired']=True
        subject.admit(self.job,self.identity,self.policy);report=self.manifest()
        with self.assertRaisesRegex(contracts.ContractError,'gpu_cleanup_unconfirmed'):
            subject.finish(self.job,self.identity,self.policy,report)
        self.assertEqual(len(self.held()),1)
        subject.record_cleanup(self.job,self.identity)
        subject.finish(self.job,self.identity,self.policy,report)
        self.assertEqual(self.held(),[])

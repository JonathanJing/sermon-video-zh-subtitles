"""Strict-policy L3 compatibility with synthetic files only, no model loading."""
import copy
import unittest
from unittest.mock import Mock, patch

from scripts import build_target_language_audio_package as package
from scripts import prepare_target_language_speech_job as speech
from scripts import render_formal_target_language_speech as render
from scripts import review_target_language_audio as audio_review
from scripts import target_language_policy as policies
from scripts import sermon_review_contracts as contracts
from scripts import validate_target_language_audio_unit as integrity
from tests import test_build_target_language_audio_package as fixtures
from tests.test_sermon_review_contracts import load


class StrictLayer3Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AudioPackageTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        self.rubric=load('rubric');self.rubric['targetLocale']='ko'
        self.rubric['requiredLanguagePluginChecks']=f.policy['languageReview']['requiredChecks']
        draft=copy.deepcopy(f.policy);draft.pop('componentSha256')
        draft.update(schemaVersion=policies.POLICY_V3,reviewMode='strict_verifier')
        draft['translator']['promptVersion']='astra-strict-generator-v1'
        draft['reviewer']['promptVersion']='sol-strict-verifier-v1'
        draft['reviewContract']=dict(rubricCanonicalJsonSha256=contracts.canonical_sha256(self.rubric),
            reviewReceiptSchemaVersion='sermon-review-receipt-v1',
            candidateRevisionSchemaVersion='sermon-candidate-revision-v1',
            inputManifestSchemaVersion='sermon-review-input-manifest-v1',revisionGranularity='translation_group')
        f.policy=policies.freeze_strict_policy(draft,self.rubric)
        f.candidate['translationPolicySha256']=policies.validate_strict_policy(f.policy,self.rubric)['translationPolicySha256']
        for role in ('translator','reviewer'):
            f.candidate['generation'][role]['promptVersion']=f.policy[role]['promptVersion']
        f.human_receipt['translationPolicySha256']=f.candidate['translationPolicySha256']
        f.human_receipt['candidateJsonSha256']=package.json_sha256(f.candidate)
        f.clip_auth['targetLanguageCandidateJsonSha256']=package.json_sha256(f.candidate)
        for key,value in (('candidate',f.candidate),('policy',f.policy),
                          ('human_receipt',f.human_receipt),('clip_voice_authorization',f.clip_auth)):
            fixtures.write_json(f.paths[key],value)
        # Synthetic fixture approvals are rebound only inside this test. The
        # production preparer still checks each existing independent receipt.
        f.job=self.prepare(self.rubric)
        fixtures.write_json(f.paths['job'],f.job)
        f.manifest['targetLanguageCandidateJsonSha256']=package.json_sha256(f.candidate)
        f.manifest['targetLanguageSpeechJobJsonSha256']=package.json_sha256(f.job)
        for index,row in enumerate(f.manifest['units']):
            receipt=integrity.build_receipt(f.paths['job'],index,f.asset_root/row['audio']['path'],
                strict_rubric=self.rubric)
            relative=f'receipts/unit-{index:04d}.json'
            fixtures.write_json(f.asset_root/relative,receipt)
            row['receipt']=f.artifact(relative,json_artifact=True)
        f.screening['targetLanguageSpeechJobJsonSha256']=package.json_sha256(f.job)
        relative=f.manifest['machineScreeningReceipt']['path']
        fixtures.write_json(f.asset_root/relative,f.screening)
        f.manifest['machineScreeningReceipt']=f.artifact(relative,json_artifact=True)
        fixtures.write_json(f.manifest_path,f.manifest)

    def prepare(self,rubric):
        f=self.f
        return speech.prepare_job(f.paths['source'],f.paths['anchor'],f.paths['candidate'],f.paths['policy'],
            f.paths['human_receipt'],f.paths['adapter'],f.paths['registry'],f.asset_root,
            clip_voice_authorization_path=f.paths['clip_voice_authorization'],
            clip_voice_capability_path=f.paths['clip_voice_capability'],
            clip_timeline_map_path=f.paths['clip_timeline_map'],strict_rubric=rubric,build_only=True)

    def build(self,rubric=None):
        f=self.f
        return package.build_package(f.paths,f.manifest_path,f.asset_root,strict_rubric=rubric)

    def test_strict_job_build_and_human_review_remain_compatible_and_pending(self):
        self.assertTrue(self.f.job['synthesisEligible'])
        self.assertFalse(self.f.job['releaseEligible'])
        value=self.build(self.rubric)
        self.assertEqual(value['status'],'machine_screened')
        self.assertEqual(value['targetLocale'],'ko')
        self.assertFalse(value['humanReview']['humanApproval'])
        worksheet=audio_review.prepare(value,self.f.screening)
        self.assertEqual(worksheet['decision'],'pending')
        self.assertEqual(worksheet['videoSync1x'],'pending')
        with self.assertRaises(ValueError):audio_review.approve(value,self.f.screening,worksheet)

    def test_missing_changed_or_cross_locale_rubric_fails_before_render_or_package(self):
        changed=copy.deepcopy(self.rubric);changed['rubricVersion']='changed'
        other=copy.deepcopy(self.rubric);other['targetLocale']='es'
        for rubric in (None,changed,other):
            with self.subTest(rubric=rubric):
                with self.assertRaises(ValueError):self.prepare(rubric)
                with self.assertRaises(ValueError):self.build(rubric)
                synth=Mock(side_effect=AssertionError('No model may be loaded'))
                with self.assertRaises(ValueError):
                    render.render(self.f.paths,self.f.root/'absent-checkpoint-map.json',
                        self.f.root/'absent-operation-policies.json',strict_rubric=rubric,synth_factory=synth)
                synth.assert_not_called()

    def test_renderer_real_job_validation_accepts_explicit_strict_rubric(self):
        # Stop at the next independent operation-policy gate; do not load a
        # checkpoint or synthesize audio to prove strict policy propagation.
        policy_path=self.f.root/'operation-policies.json';fixtures.write_json(policy_path,{})
        class ReachedOperationPolicy(Exception):pass
        with patch.object(render,'validate_operation_policies',side_effect=ReachedOperationPolicy) as gate:
            with self.assertRaises(ReachedOperationPolicy):
                render.checked_context(self.f.paths,self.f.root/'absent-checkpoint-map.json',policy_path,
                    strict_rubric=self.rubric)
        gate.assert_called_once()

    def test_strict_unit_receipts_and_renderer_cache_use_current_rubric(self):
        from tests.test_render_formal_target_language_speech import FakeSynth
        f=self.f
        context={name:package.read_object(path) for name,path in f.paths.items()}
        context.update(strict_rubric=self.rubric,checkpoint=f.root/'no-model-checkpoint',
            checkpointMapFileSha256='a'*64,operationPoliciesFileSha256='b'*64)
        for index,unit in enumerate(f.job['units']):
            (f.asset_root/unit['outputRelativePath']).unlink()
            (f.asset_root/f'receipts/unit-{index:04d}.json').unlink()
        FakeSynth.calls=[]
        rows=render.render_units(context,f.paths,f.asset_root,f.root/'checkpoint-map.json',synth_factory=FakeSynth)
        self.assertEqual(len(FakeSynth.calls),len(f.job['units']))
        FakeSynth.calls=[]
        self.assertEqual(render.render_units(context,f.paths,f.asset_root,f.root/'checkpoint-map.json',
            synth_factory=FakeSynth),rows)
        self.assertEqual(FakeSynth.calls,[])
        audio=f.asset_root/f.job['units'][0]['outputRelativePath']
        receipt=package.read_object(f.asset_root/'receipts/unit-0000.json')
        integrity.validate_receipt(f.paths['job'],0,audio,receipt,strict_rubric=self.rubric)
        changed=copy.deepcopy(self.rubric);changed['rubricVersion']='changed'
        for rubric in (None,changed):
            with patch.object(integrity,'probe_full_decode',side_effect=AssertionError('must validate first')) as decode:
                with self.assertRaises(ValueError):integrity.build_receipt(f.paths['job'],0,audio,strict_rubric=rubric)
                with self.assertRaises(ValueError):integrity.validate_receipt(f.paths['job'],0,audio,receipt,strict_rubric=rubric)
                decode.assert_not_called()

    def test_strict_mode_keeps_independent_human_and_voice_gates(self):
        original=copy.deepcopy(self.f.human_receipt)
        self.f.human_receipt['candidateJsonSha256']='0'*64
        fixtures.write_json(self.f.paths['human_receipt'],self.f.human_receipt)
        with self.assertRaisesRegex(ValueError,'Human review receipt'):self.build(self.rubric)
        fixtures.write_json(self.f.paths['human_receipt'],original)
        self.f.clip_auth['targetLocale']='es'
        fixtures.write_json(self.f.paths['clip_voice_authorization'],self.f.clip_auth)
        with self.assertRaisesRegex(ValueError,'Clip voice authorization'):self.build(self.rubric)


if __name__=='__main__':unittest.main()

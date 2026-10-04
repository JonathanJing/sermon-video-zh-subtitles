import json
import unittest
from unittest.mock import patch
from tests import test_render_formal_target_language_speech as fixture
from scripts import sermon_unified_audio as audio
from scripts import target_audio_capacity_experiment as capacity


class UnifiedAudioTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.FormalRenderTests('test_two_units_full_decode_and_resume_without_synthesis')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        root = self.f.root
        (root/'checkpoint-map.json').write_text('{}'); (root/'operations.json').write_text('{}')
        self.config = root/'audio-adapter.json'
        self.value = {'schemaVersion': audio.SCHEMA, 'paths': {k:str(v) for k,v in self.f.paths.items()},
                      'checkpointMap':'checkpoint-map.json', 'audioOperationPolicies':'operations.json'}
        self.config.write_text(json.dumps(self.value))
        self.checked = patch.object(audio.renderer, 'checked_context', return_value=self.f.context)
        self.checked.start(); self.addCleanup(self.checked.stop)
        draft = self.config
        self.config = self.f.root/'audio-adapter-frozen.json'
        audio.freeze(draft, self.config)
        self.value = json.loads(self.config.read_text())

    def test_assembly_adapter_rejects_missing_without_dispatch(self):
        plan = audio.inspect(self.config)
        self.assertEqual(plan['maxEndLagSeconds'], 8.0)
        with patch.object(audio.renderer, 'render_accounted') as run:
            with self.assertRaisesRegex(ValueError, 'complete committed cache'):
                audio.execute(self.config, self.f.root/'result.json', expected_plan_hash=plan['planHash'])
            run.assert_not_called()

    def test_closed_fields_reject_command_injection(self):
        self.value['command'] = ['echo', 'unsafe']
        self.config.write_text(json.dumps(self.value))
        with self.assertRaisesRegex(ValueError, 'Unknown audio adapter'):
            audio.inspect(self.config)

    def test_plan_change_cannot_dispatch(self):
        plan = audio.inspect(self.config)
        self.value['settings'] = {'seed':43}
        self.config.write_text(json.dumps(self.value))
        with self.assertRaisesRegex(ValueError, 'plan identity changed'):
            audio.execute(self.config, self.f.root/'result.json', expected_plan_hash=plan['planHash'])

    def test_full_cache_dispatches_fixed_renderer_and_retains_pending_review(self):
        rows = self.f.render_units()
        plan = audio.inspect(self.config)
        def run(*args, **kwargs):
            self.assertTrue(kwargs['assembly_only'])
            self.assertEqual(kwargs['policy']['maxEndLagSeconds'], 8.0)
            return audio.renderer.assemble(self.f.context, self.f.paths, self.f.root, rows)
        with patch.object(audio.renderer, 'render_accounted', side_effect=run):
            result = audio.execute(self.config, self.f.root/'result.json', expected_plan_hash=plan['planHash'])
        self.assertEqual(result['review'], 'human_pending')
        self.assertFalse(result['productionEligible'])
        verified = audio.verify_result(self.config, result)
        self.assertEqual(verified['fullDecode'], 'pass')
        manifest = json.loads((self.f.root/'render-manifest.json').read_text())
        (self.f.root/manifest['track']['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            audio.verify_result(self.config, result)

    def test_capacity_matrix_has_separate_cold_warm_and_cache(self):
        plan = capacity.plan(speech_job_sha256='a'*64, sound_identity_sha256='b'*64,
                             unit_indices=list(range(8)), max_generated_units=32, max_wall_seconds=3600)
        self.assertEqual(len(plan['cases']), 8)
        self.assertEqual(plan['quality']['reserveGiB'], 24)
        result = capacity.compare(plan, [])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['missingCases']), 8)
        with self.assertRaisesRegex(ValueError, 'synthesis budget'):
            capacity.plan(speech_job_sha256='a'*64, sound_identity_sha256='b'*64,
                          unit_indices=list(range(8)), max_generated_units=8, max_wall_seconds=3600)

    def test_capacity_reported_pass_requires_real_bound_evidence(self):
        plan = capacity.plan(speech_job_sha256='a'*64, sound_identity_sha256='b'*64,
                             unit_indices=[0], max_generated_units=4, max_wall_seconds=100, replicas=(1,), batch_size=1)
        row = {'caseId':plan['cases'][0]['caseId'], 'planHash':plan['planHash'],
               'speechJobSha256':'a'*64, 'soundIdentitySha256':'b'*64, 'unitIndices':[0],
               'fullDecode':'pass', 'maxEndLagSeconds':8, 'humanListeningReview':'approved',
               'humanReviewReceiptSha256':'c'*64, 'timeStretch':False, 'wallSeconds':1,
               'generatedUnits':1}
        with self.assertRaisesRegex(ValueError, 'requires bound job'):
            capacity.compare(plan, [row])

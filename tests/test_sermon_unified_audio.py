import copy
import json
import unittest
from unittest.mock import patch
from tests import test_render_formal_target_language_speech as fixture
from scripts import sermon_unified_audio as audio
from scripts import ko_spoken_numerals
from scripts import target_audio_capacity_experiment as capacity


class UnifiedAudioTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.FormalRenderTests('test_two_units_full_decode_and_resume_without_synthesis')
        def complete_source(source):
            source['source'].update(sourceId='fixture-source', sourceUrlHash='d' * 64)
            return source
        with patch.object(fixture.fixture_module.AudioPackageTests, 'complete_source_fixture',
                          side_effect=complete_source):
            self.f.setUp()
        self.addCleanup(self.f.doCleanups)
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

    def test_adapter_hash_keeps_legacy_file_keys_and_hashes_package_bytes(self):
        plan = audio.inspect(self.config)
        code = audio.audio_backend.current().code
        names = ('sermon_unified_audio.py', 'render_formal_target_language_speech.py',
                 'validate_target_language_audio_unit.py')
        expected = audio.identity.json_sha256({
            name: audio.identity.sha256(code.implementation_path('scripts/' + name))
            for name in names})
        self.assertEqual(plan['adapterCodeSha256'], expected)
        self.assertEqual(code.implementation_path('scripts/sermon_unified_audio.py'),
                         audio.Path(audio.__file__).resolve())

    def test_registered_korean_plan_refuses_changed_spoken_form_dependency(self):
        self.f.context['job']['adapter']['normalizationPolicySha256'] = audio.identity.json_sha256(
            audio.renderer.SPOKEN_FORMS_NORMALIZATION_POLICY)
        plan = audio.inspect(self.config)
        original = audio.identity.sha256
        root = audio.audio_backend.current().code.implementation_path('scripts/ko_spoken_numerals.py').parent
        for name in ('ko_spoken_numerals.py', 'language_review_plugins/auto_qc_text_common.py',
                     'language_review_plugins/common.py'):
            target = root / name
            with self.subTest(dependency=name), patch.object(audio.identity, 'sha256',
                    side_effect=lambda path: '0' * 64 if audio.Path(path) == target else original(path)), \
                    patch.object(audio.renderer, 'render_accounted') as dispatch:
                with self.assertRaisesRegex(ValueError, 'plan identity changed'):
                    audio.execute(self.config, self.f.root/'result.json', expected_plan_hash=plan['planHash'])
                dispatch.assert_not_called()

    def test_explicit_v2_korean_instruction_plan_binds_rule_dependency(self):
        job = self.f.context['job']
        job['adapter']['normalizationPolicySha256'] = audio.identity.json_sha256(
            audio.renderer.SPOKEN_FORMS_NORMALIZATION_POLICY)
        job['units'][0]['text'] = '하박국 2장을 보십시오.'
        document = ko_spoken_numerals.build(job)
        path = self.f.root/'instructions.json'
        path.write_text(json.dumps(document))
        config = dict(self.value, unitInstructions=str(path))
        config.pop('inputSnapshotSha256', None)
        draft = self.f.root/'explicit-draft.json'
        draft.write_text(json.dumps(config))
        config_path = self.f.root/'explicit-frozen.json'
        audio.freeze(draft, config_path)
        plan = audio.inspect(config_path)
        original = audio.identity.sha256
        target = audio.audio_backend.current().code.implementation_path('scripts/ko_spoken_numerals.py')
        with patch.object(audio.identity, 'sha256', side_effect=lambda path: '0' * 64
                          if audio.Path(path) == target else original(path)), \
                patch.object(audio.renderer, 'render_accounted') as dispatch:
            with self.assertRaisesRegex(ValueError, 'plan identity changed'):
                audio.execute(config_path, self.f.root/'result.json', expected_plan_hash=plan['planHash'])
            dispatch.assert_not_called()

    def test_legacy_korean_spoken_override_cannot_freeze_a_plan(self):
        job = self.f.context['job']
        job['units'][0]['text'] = '시편 101편을 읽습니다.'
        document = ko_spoken_numerals.build(job)
        path = self.f.root/'legacy-instructions.json'
        path.write_text(json.dumps(document))
        config = dict(self.value, unitInstructions=str(path))
        config.pop('inputSnapshotSha256', None)
        draft = self.f.root/'legacy-explicit-draft.json'
        draft.write_text(json.dumps(config))
        with patch.object(audio.renderer, 'render_accounted') as dispatch:
            with self.assertRaisesRegex(ValueError, 'new job frozen with normalization-v2'):
                audio.freeze(draft, self.f.root/'legacy-explicit-frozen.json')
            dispatch.assert_not_called()

    def test_exact_text_plan_does_not_add_registered_rule_dependency(self):
        plan = audio.inspect(self.config)
        original = audio.identity.sha256
        target = audio.audio_backend.current().code.implementation_path('scripts/ko_spoken_numerals.py')
        with patch.object(audio.identity, 'sha256', side_effect=lambda path: '0' * 64
                          if audio.Path(path) == target else original(path)):
            self.assertEqual(audio.inspect(self.config)['planHash'], plan['planHash'])

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
        for key in ('sourceIdentity', 'sourcePackage', 'configurationSha256'):
            changed = dict(result, **{key: None})
            with self.subTest(resultField=key), self.assertRaisesRegex(ValueError, 'source/configuration'):
                audio.verify_result(self.config, changed)
        other_config = self.f.root / 'another-valid-config.json'
        other_config.write_text(json.dumps(dict(self.value, pageId='another-page')))
        self.assertTrue(audio.inspect(other_config)['snapshotBound'])
        with self.assertRaisesRegex(ValueError, 'input/plan'):
            audio.verify_result(other_config, result)
        old = dict(result, schemaVersion='sermon-unified-audio-result-v1')
        with self.assertRaisesRegex(ValueError, 'input/plan'):
            audio.verify_result(self.config, old)
        manifest = json.loads((self.f.root/'render-manifest.json').read_text())
        (self.f.root/manifest['track']['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            audio.verify_result(self.config, result)

    def test_full_source_identity_rejects_another_run_on_same_media(self):
        plan = audio.inspect(self.config)
        manifest = {'source': copy.deepcopy(plan['sourceIdentity']),
                    'policies': [{'locale': plan['targetLocale'], 'policySha256': plan['policySha256']}],
                    'content': {'pageId': 'page-a'}}
        self.assertTrue(audio.validate_manifest_binding(plan, manifest, plan['targetLocale']))
        # Both source windows/identifiers are structurally valid. Sharing media
        # and policy cannot authorize the independently admitted audio for B.
        changes = [('sourceId', 'another-source'), ('sourceUrlHash', 'f' * 64),
                   ('durationSeconds', 30), ('window.startSeconds', 0.1),
                   ('window.endSeconds', 0.6), ('window.approvalReceiptSha256', 'e' * 64)]
        for key, value in changes:
            with self.subTest(field=key):
                other = copy.deepcopy(manifest)
                target = other['source']
                parts = key.split('.')
                if len(parts) == 2: target = target[parts[0]]
                target[parts[-1]] = value
                with self.assertRaisesRegex(ValueError, 'source identity'):
                    audio.validate_manifest_binding(plan, other, plan['targetLocale'])
        other_plan = dict(plan, pageId='page-b')
        with self.assertRaisesRegex(ValueError, 'page differs'):
            audio.validate_manifest_binding(other_plan, manifest, plan['targetLocale'])

    def test_legacy_configuration_migrates_without_changing_sound_settings(self):
        legacy = self.f.root / 'legacy.json'
        value = dict(self.value, schemaVersion=audio.LEGACY_SCHEMA)
        legacy.write_text(json.dumps(value))
        before = audio.inspect(legacy)
        migrated = self.f.root / 'migrated.json'
        after = audio.freeze(legacy, migrated)
        self.assertEqual(json.loads(migrated.read_text())['schemaVersion'], audio.SCHEMA)
        for key in ('settings', 'sourceIdentity', 'sourcePackage', 'inputsSha256'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after['schemaVersion'], 'sermon-unified-audio-plan-v2')
        self.assertNotEqual(before['configurationSha256'], after['configurationSha256'])

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

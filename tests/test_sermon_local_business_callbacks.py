"""Real business validators/producers, synthetic approvals and injected PCM only."""
from contextlib import chdir
from dataclasses import replace
import copy
import hashlib
import os
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from scripts import sermon_local_business_callbacks as subject
from scripts import sermon_log_profile as profile
from scripts import sermon_review_contracts as c
from tests import test_sermon_strict_layer3_preparation as speech_fixtures
from tests import test_sermon_delivery_intent_binding as delivery_fixtures
from tests import test_render_formal_target_language_speech as render_fixtures
from tests import test_prepare_target_language_speech_job as voice_fixtures


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        subject.initialize_scope(self.root, 'synthetic-local-business')
        self.scope = dict(offline=True, fixture_id='synthetic-local-business', fixture_root=self.root)
        # All nested existing fixture temp directories belong to this explicit scope.
        self.enterContext(patch.object(tempfile, 'tempdir', str(self.root)))

    def context(self):
        return profile.session(self.root / 'accounting', 'offline-local-callback-tests',
                               work_kind='engineering', evidence_mode='synthetic')

    def test_scope_profile_identity_and_path_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'requires_synthetic_profile'):
            with subject._scope(**self.scope): pass
        with self.context():
            with self.assertRaisesRegex(ValueError, 'identity_changed'):
                with subject._scope(**dict(self.scope, fixture_id='other')): pass
            with self.assertRaisesRegex(ValueError, 'outside_scope'):
                subject._path(self.root, self.root.parent / 'real-run')
            with subject._scope(**self.scope):
                with self.assertRaisesRegex(ValueError, 'forbidden'):
                    socket.create_connection(('example.invalid', 443))
                with self.assertRaisesRegex(ValueError, 'forbidden'):
                    subject.renderer.QwenSynthesizer(self.root)
                with self.assertRaisesRegex(ValueError, 'forbidden'):
                    __import__('qwen_tts')

    def test_effective_accounting_destination_must_be_scoped_before_emission(self):
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside:
            directory = Path(outside) / 'accounting'
            with profile.context(workKind='engineering', evidenceMode='synthetic'), patch.dict(
                    os.environ, {'SERMON_ACCOUNTING_DIR': str(directory), 'SERMON_ACCOUNTING_RUN_ID': 'outside-run'}):
                with self.assertRaisesRegex(ValueError, 'outside_scope'):
                    with subject._scope(**self.scope): pass
            self.assertFalse(directory.exists())

    def test_missing_default_synth_rejects_before_job_or_checkpoint_load(self):
        for factory in (None, subject.renderer.QwenSynthesizer):
            with self.assertRaisesRegex(ValueError, 'trusted_synth_fixture_required'):
                subject.render_speech({}, self.root / 'absent', self.root / 'absent',
                                      synth_factory=factory, **self.scope)


class SpeechTests(ScopeTests):
    def setUp(self):
        super().setUp()
        self.f = speech_fixtures.PreparationTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def prepare(self):
        return subject.prepare_speech(self.f.f.boundary, self.f.intent,
            adapter_path=self.f.adapter_path, registry_path=self.f.registry_path,
            out=self.f.out, **self.scope)

    def test_real_preparation_replay_preserves_receipt_and_voice_barrier(self):
        with self.context():
            first = self.prepare()
            original = (self.f.out / 'job.json').read_bytes()
            replay = self.prepare()
        self.assertEqual(first['result'], replay['result'])
        self.assertEqual(original, (self.f.out / 'job.json').read_bytes())
        self.assertFalse(first['result']['synthesisEligible'])
        self.assertFalse(first['productionEligible'])
        self.assertEqual(first['executionAuthority'], 'none')
        self.assertIn(str(self.f.f.boundary.config.human_receipt), [r['path'] for r in first['artifacts']])

    def test_changed_original_approval_blocks_preparation(self):
        with self.context():
            self.prepare()
            self.f.f.approve(evidence='Synthetic changed receipt')
            with self.assertRaisesRegex(ValueError, 'admission_evidence_changed'):
                self.prepare()

    def test_relative_admission_job_root_cannot_write_into_external_cwd(self):
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside, chdir(outside):
            sentinel = Path(outside) / 'sentinel'
            sentinel.write_bytes(b'unchanged')
            boundary = subject.admission.AdmissionBoundary(
                replace(self.f.f.boundary.config, job_root=Path('jobs')), self.f.f.boundary.store)
            with self.context(), self.assertRaisesRegex(ValueError, 'boundary_paths_must_be_absolute'):
                subject.prepare_speech(boundary, self.f.intent, adapter_path=self.f.adapter_path,
                    registry_path=self.f.registry_path, out=self.f.out, **self.scope)
            self.assertEqual(list(Path(outside).iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b'unchanged')
            self.assertFalse(self.f.out.exists())

    def test_all_immutable_boundary_paths_reject_relative_or_external_values(self):
        original = self.f.f.boundary
        for field in ('source', 'anchor', 'policy', 'rubric', 'public_candidate',
                      'human_receipt', 'plugin', 'job_root', 'revision_root', 'revision_roots', 'store'):
            for value in (Path('relative'), self.root.parent / 'external'):
                with self.subTest(field=field, value=value):
                    boundary = copy.copy(original)
                    if field == 'store':
                        boundary.store = copy.copy(original.store)
                        boundary.store.root = value
                    else:
                        replacement = (value,) if field == 'revision_roots' else value
                        boundary.config = replace(original.config, **{field: replacement})
                    with self.assertRaisesRegex(ValueError, 'must_be_absolute|outside_scope'):
                        subject._boundary_paths(self.root, boundary)


class PreflightTests(ScopeTests):
    def setUp(self):
        super().setUp()
        self.f = delivery_fixtures.StrictDeliveryBindingTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def preflight(self, **kwargs):
        return subject.delivery_preflight(self.f.manifest, self.f.plan,
            root=kwargs.pop('root', self.f.root), configuration=self.f.config,
            strict_admissions=self.f.strict_admissions, **self.scope, **kwargs)

    def test_real_binding_rechecks_original_receipts_without_publication(self):
        with self.context():
            first = self.preflight()
            with tempfile.TemporaryDirectory(dir=self.root.parent) as outside, chdir(outside):
                replay = self.preflight(binding=first['binding'], root=self.f.root.relative_to(self.root))
            self.assertEqual(first['result'], replay['result'])
            self.assertFalse(first['result']['publicationAuthorized'])
            path = Path(self.f.config['locales']['zh-Hans']['humanReview'])
            path = path if path.is_absolute() else self.f.root / path
            value = json.loads(path.read_text()); value['candidateJsonSha256'] = 'e' * 64
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                self.preflight(binding=first['binding'])


class RenderTests(ScopeTests):
    def setUp(self):
        super().setUp()
        # The normal fixture uses a real registry's hash. Supply inert checkpoint
        # bytes and matching fixture identities before it builds voice receipts.
        weights = b'synthetic checkpoint bytes; never loaded by a model'
        digest = hashlib.sha256(weights).hexdigest()
        policies = {'normalization': {'policy': 'exact_human_approved_target_text_no_rewrite'},
                    'asrScreening': {'policy': 'synthetic'}, 'subtitle': {'policy': 'synthetic'}}
        original = voice_fixtures.TargetLanguageSpeechJobTests.setUp
        def fixture_setup(fixture):
            original(fixture)
            fixture.registry['speakers'][0]['checkpoint']['checkpointSha256'] = digest
            fixture.adapter['conditioningSha256'] = digest
            fixture.adapter['registryJsonSha256'] = c.canonical_sha256(fixture.registry)
            for key, field in [('normalization', 'normalizationPolicySha256'),
                               ('asrScreening', 'asrScreeningPolicySha256'), ('subtitle', 'subtitlePolicySha256')]:
                fixture.adapter[field] = c.canonical_sha256(policies[key])
            fixture.registry_path.write_text(json.dumps(fixture.registry))
            fixture.adapter_path.write_text(json.dumps(fixture.adapter))
        with patch.object(voice_fixtures.TargetLanguageSpeechJobTests, 'setUp', fixture_setup):
            self.f = render_fixtures.FormalRenderTests()
            self.f.setUp(); self.addCleanup(self.f.doCleanups)
        checkpoint = self.f.root / 'fixture-model'
        (checkpoint / 'model.safetensors').write_bytes(weights)
        adapter = self.f.context['adapter']
        (checkpoint / 'config.json').write_text(json.dumps({'talker_config': {'spk_id': {adapter['speakerKey']: 0}}}))
        self.checkpoint_map = self.f.root / 'checkpoint-map.json'
        self.checkpoint_map.write_text(json.dumps({'schemaVersion': 'sermon-speaker-checkpoint-map-v1',
            'checkpoints': [{'speakerId': adapter['speakerId'], 'checkpointRef': adapter['conditioningRef'],
                             'path': str(checkpoint)}]}))
        self.policies = self.f.root / 'audio-operation-policies.json'
        self.policies.write_text(json.dumps(policies))

    def render(self, factory=render_fixtures.FakeSynth, **kwargs):
        return subject.render_speech(self.f.paths, self.checkpoint_map, self.policies,
            synth_factory=factory, device='cpu', **self.scope, **kwargs)

    def test_actual_renderer_and_full_decode_replay_without_new_synth(self):
        with self.context():
            first = self.render()
            calls = len(render_fixtures.FakeSynth.calls)
            receipt = self.f.root / 'receipts/unit-0000.render.json'
            original = receipt.read_bytes()
            replay = self.render()
        self.assertEqual(calls, 2)
        self.assertEqual(len(render_fixtures.FakeSynth.calls), calls)
        self.assertEqual(first['result'], replay['result'])
        self.assertEqual(original, receipt.read_bytes())
        self.assertEqual(first['result']['machineScreening']['status'], 'not_run')
        events, damaged = subject.accounting.read_events(self.root / 'accounting')
        self.assertFalse(damaged)
        for result in (first, replay):
            self.assertTrue(any(row['event'] == 'stage_finished' and row['spanId'] == result['spanId']
                                for row in events))

    def test_changed_render_receipt_blocks_replay_without_new_synth(self):
        with self.context():
            self.render()
            calls = len(render_fixtures.FakeSynth.calls)
            path = self.f.root / 'receipts/unit-0000.render.json'
            value = json.loads(path.read_text()); value['identity']['seed'] = -1
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): self.render()
        self.assertEqual(len(render_fixtures.FakeSynth.calls), calls)

    def test_relative_instruction_path_reads_only_scoped_file_outside_cwd(self):
        instructions = self.root / 'instructions.json'
        job = self.f.context['job']
        instructions.write_text(json.dumps({
            'schemaVersion': 'sermon-unit-delivery-instructions-v1',
            'targetLocale': job['targetLocale'], 'speechJobJsonSha256': c.canonical_sha256(job),
            'units': [{'translationGroupId': unit['translationGroupId'],
                       'approvedTextSha256': hashlib.sha256(unit['text'].encode()).hexdigest(),
                       'instruction': 'Synthetic fixture instruction', 'operatorEvidence': 'Synthetic only'}
                      for unit in job['units']]}))
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside, chdir(outside):
            Path('instructions.json').write_text('invalid outside JSON')
            with self.context():
                result = self.render(unit_instructions_path=Path('instructions.json'))
                self.assertIn(str(instructions), [row['path'] for row in result['artifacts']])
                calls = len(render_fixtures.FakeSynth.calls)
                instructions.unlink()
                with self.assertRaises(FileNotFoundError):
                    self.render(unit_instructions_path=Path('instructions.json'))
                self.assertEqual(len(render_fixtures.FakeSynth.calls), calls)

    def test_instruction_embedded_path_outside_scope_rejects_before_render(self):
        instructions = self.root / 'instructions.txt'
        instructions.write_text(json.dumps({'evidence': {'path': str(self.root.parent / 'outside.json')}}))
        with self.context(), self.assertRaisesRegex(ValueError, 'outside_scope'):
            self.render(unit_instructions_path=Path('instructions.txt'))
        instructions.write_text(json.dumps({'evidence': {'path': 'relative-outside.json'}}))
        with self.context(), self.assertRaisesRegex(ValueError, 'must_be_absolute'):
            self.render(unit_instructions_path=Path('instructions.txt'))
        self.assertEqual(render_fixtures.FakeSynth.calls, [])

    def test_inherited_progress_ledger_outside_scope_is_not_read_or_changed(self):
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside:
            ledger = Path(outside) / 'progress.json'
            ledger.write_text('outside sentinel, invalid JSON')
            with self.context(), patch.dict(os.environ, {'SERMON_FOUR_LAYER_LEDGER': str(ledger)}):
                with self.assertRaisesRegex(ValueError, 'outside_scope'):
                    self.render()
            self.assertEqual(ledger.read_text(), 'outside sentinel, invalid JSON')
            self.assertEqual(list(Path(outside).iterdir()), [ledger])
        self.assertEqual(render_fixtures.FakeSynth.calls, [])

    def test_inherited_progress_accounting_symlink_cannot_write_outside(self):
        progress_root = self.root / 'progress-fixture'
        progress_root.mkdir()
        ledger = progress_root / 'progress.json'
        ledger.write_text('{}')
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside:
            sentinel = Path(outside) / 'sentinel'
            sentinel.write_bytes(b'unchanged progress accounting')
            (progress_root / 'accounting').symlink_to(outside, target_is_directory=True)
            with self.context(), patch.dict(os.environ, {'SERMON_FOUR_LAYER_LEDGER': str(ledger)}):
                with self.assertRaisesRegex(ValueError, 'outside_scope|symlink_forbidden'):
                    self.render()
            self.assertEqual(list(Path(outside).iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b'unchanged progress accounting')
            self.assertEqual(ledger.read_text(), '{}')
        self.assertEqual(render_fixtures.FakeSynth.calls, [])

    def test_changed_voice_receipt_blocks_before_synth(self):
        path = self.f.paths['clip_voice_authorization']
        value = json.loads(path.read_text()); value['englishSourcePackageJsonSha256'] = '0' * 64
        path.write_text(json.dumps(value))
        with self.context(), self.assertRaises(ValueError): self.render()
        self.assertEqual(render_fixtures.FakeSynth.calls, [])

    def test_derived_output_symlinks_reject_before_intent_write_or_synth(self):
        locale = self.f.context['job']['targetLocale']
        directories = ['receipts', 'languages', f'languages/{locale}/audio',
                       f'languages/{locale}/synchronization']
        files = [f'languages/{locale}/audio/unit-0000.wav',
                 f'languages/{locale}/audio/unit-0000.partial.wav',
                 f'languages/{locale}/audio/track.wav',
                 f'languages/{locale}/synchronization/captions.json',
                 f'languages/{locale}/synchronization/schedule.json',
                 'receipts/unit-0000.intent.json', 'render-manifest.json']
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside:
            outside = Path(outside)
            sentinel = outside / 'sentinel'
            sentinel.write_bytes(b'unchanged external output')
            constructors = []
            def factory(*args, **kwargs):
                constructors.append(True)
                return render_fixtures.FakeSynth(*args, **kwargs)
            for index, relative in enumerate(directories + files):
                with self.subTest(path=relative):
                    path = self.f.root / relative
                    saved = self.root / f'saved-output-{index}'
                    existed = path.exists()
                    if existed:
                        path.rename(saved)
                    target = outside if relative in directories else sentinel
                    path.symlink_to(target, target_is_directory=target.is_dir())
                    before = {str(p.relative_to(self.f.root)): p.read_bytes()
                              for p in self.f.root.rglob('*') if p.is_file() and not p.is_symlink()}
                    try:
                        with self.context(), self.assertRaisesRegex(ValueError, 'outside_scope|symlink_forbidden'):
                            self.render(factory=factory)
                        self.assertEqual(list(outside.iterdir()), [sentinel])
                        self.assertEqual(sentinel.read_bytes(), b'unchanged external output')
                        self.assertEqual(render_fixtures.FakeSynth.calls, [])
                        self.assertEqual(constructors, [])
                        after = {str(p.relative_to(self.f.root)): p.read_bytes()
                                 for p in self.f.root.rglob('*') if p.is_file() and not p.is_symlink()}
                        self.assertEqual(after, before)
                    finally:
                        path.unlink()
                        if existed:
                            saved.rename(path)


class LocalDeliveryTests(ScopeTests):
    def setUp(self):
        super().setUp()
        self.f = delivery_fixtures.FormalStrictDeliveryTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def prepare(self, **kwargs):
        return subject.prepare_delivery(self.f.manifest, root=self.f.formal.root,
            configuration=self.f.config, stage_args=self.f.args,
            preparation_receipt_path=kwargs.pop('preparation_receipt_path', self.f.preparation_receipt_path),
            strict_admissions=self.f.admissions, **self.scope, **kwargs)

    def test_relative_preparation_receipt_is_scoped_from_external_cwd(self):
        relative = self.f.preparation_receipt_path.relative_to(self.root)
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside, chdir(outside):
            impostor = Path(outside) / relative
            impostor.parent.mkdir(parents=True)
            impostor.write_text('invalid outside receipt')
            with self.context():
                result = self.prepare(preparation_receipt_path=relative)
            self.assertEqual(result['result']['status'], 'local_prepared_not_deployed')
            self.assertIn(str(self.f.preparation_receipt_path), [row['path'] for row in result['artifacts']])
            self.assertEqual(impostor.read_text(), 'invalid outside receipt')

    def test_actual_local_stage_and_existing_output_requires_reconciliation(self):
        with self.context():
            first = self.prepare()
            self.assertEqual(first['result']['status'], 'local_prepared_not_deployed')
            self.assertFalse(first['result']['publicationAuthorized'])
            receipt = Path(self.f.args.out) / 'stage-receipt.json'
            original = receipt.read_bytes()
            with self.assertRaisesRegex(ValueError, 'requires_reconciliation'): self.prepare()
            self.assertEqual(receipt.read_bytes(), original)


if __name__ == '__main__': unittest.main()

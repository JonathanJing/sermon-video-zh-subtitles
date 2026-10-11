import fcntl
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator
from scripts import production_recovery_plan as subject
from scripts import sermon_sentence_interpretation as identity
from tests import test_render_formal_target_language_speech as fixtures


class RecoveryPlanTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.FormalRenderTests('test_two_units_full_decode_and_resume_without_synthesis')
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.f = f
        self.root = f.root.resolve()
        self.job_path = f.paths['job'].resolve()
        f.render_units()
        self.expected_path = self.root.parent / 'recovery-expected.json'
        self.state_path = self.root.parent / 'recovery-owner.json'
        self.intents = [json.loads((self.root / f'receipts/unit-{i:04d}.intent.json').read_text())
                        for i in range(2)]
        self.envelopes()

    def envelopes(self, owner='terminal'):
        job = json.loads(self.job_path.read_text())
        binding = {'jobJsonSha256': identity.json_sha256(job), 'jobFileSha256': identity.sha256(self.job_path)}
        self.expected_path.write_text(json.dumps(dict(binding,
            schemaVersion='sermon-l3-recovery-intent-snapshot-v1', intents=self.intents)))
        self.state_path.write_text(json.dumps(dict(binding,
            schemaVersion='sermon-l3-recovery-execution-snapshot-v1', status=owner, renderRoot=str(self.root))))

    def plan(self, **kwargs):
        return subject.plan_layer3(self.job_path, render_root=self.root,
            expected_intents_path=self.expected_path, execution_state_path=self.state_path, **kwargs)

    def delete_unit(self, index):
        (self.root / self.f.context['job']['units'][index]['outputRelativePath']).unlink()
        for suffix in ('', '.render'):
            (self.root / f'receipts/unit-{index:04d}{suffix}.json').unlink()

    def assert_schema(self, result):
        schema = json.loads((Path(__file__).parents[1] / 'schemas/sermon-production-recovery-plan-v1.schema.json').read_text())
        Draft202012Validator(schema).validate(result)

    def test_exact_cache_reuse_and_readonly_schema(self):
        before = {p: identity.sha256(p) for p in self.root.rglob('*') if p.is_file()}
        calls = len(fixtures.FakeSynth.calls)
        result = self.plan()
        self.assertEqual(result['counts'], {'reuse': 2, 'revalidate': 0, 'recompute': 0, 'unknown': 0})
        self.assertEqual(result['modelCalls'], 0)
        self.assertFalse(result['dispatchAuthorized'])
        self.assertFalse(result['formalAdmissionValidated'])
        self.assertEqual(calls, len(fixtures.FakeSynth.calls))
        self.assertEqual(before, {p: identity.sha256(p) for p in self.root.rglob('*') if p.is_file()})
        self.assert_schema(result)

    def test_missing_same_job_only_proposes_missing_unit(self):
        self.delete_unit(1)
        result = self.plan()
        self.assertEqual(result['counts']['reuse'], 1)
        self.assertEqual(result['counts']['recompute'], 1)
        self.assertEqual(result['plannedModelUnitEvaluations'], 1)
        self.assertEqual(result['plannedMissingUnitCommits'], 1)
        self.assertEqual(result['batchReplay'][0]['submitMissingUnitIndices'], [1])

    def test_started_missing_result_remains_unknown(self):
        self.delete_unit(1)
        (self.root / 'receipts/unit-0001.started.json').write_text('{}')
        result = self.plan()
        self.assertEqual(result['units'][1]['classification'], 'unknown')
        self.assertEqual(result['plannedMissingUnitCommits'], 0)
        self.assertFalse(result['resourceReleaseAuthorized'])

    def test_missing_owner_snapshot_is_blocked_proposed_recompute(self):
        self.delete_unit(1)
        result = subject.plan_layer3(self.job_path, render_root=self.root, expected_intents_path=self.expected_path)
        self.assertEqual(result['units'][1]['classification'], 'recompute')
        self.assertTrue(result['units'][1]['blocked'])
        self.assertIn('owner_not_verified_proposed_recompute_only', result['units'][1]['reasons'])

    def test_missing_expected_identity_never_claims_exact_reuse(self):
        result = subject.plan_layer3(self.job_path, render_root=self.root, execution_state_path=self.state_path)
        self.assertEqual(result['counts']['revalidate'], 2)
        self.assertTrue(all(r['blocked'] for r in result['units']))

    def test_missing_receipt_revalidates_without_new_model(self):
        (self.root / 'receipts/unit-0001.json').unlink()
        result = self.plan()
        self.assertEqual(result['units'][1]['classification'], 'revalidate')
        self.assertFalse(result['units'][1]['modelRecomputeRequired'])
        self.assertEqual(result['plannedModelUnitEvaluations'], 0)

    def test_committed_partial_revalidation_does_not_rename(self):
        wav = self.root / self.f.context['job']['units'][1]['outputRelativePath']
        partial = wav.with_suffix('.partial.wav')
        wav.rename(partial)
        result = self.plan()
        self.assertEqual(result['units'][1]['classification'], 'revalidate')
        self.assertTrue(partial.exists())
        self.assertFalse(wav.exists())

    def test_corrupt_commit_and_audio_cannot_be_recomputed_blindly(self):
        wav = self.root / self.f.context['job']['units'][1]['outputRelativePath']
        wav.write_bytes(b'corrupt')
        result = self.plan()
        self.assertEqual(result['units'][1]['classification'], 'unknown')
        self.assertTrue(result['units'][1]['blocked'])

    def test_package_hash_change_is_not_model_recompute(self):
        # Desired candidate/job packaging changed, per-unit text and sound did not.
        job = json.loads(self.job_path.read_text())
        job['inputs']['targetLanguageCandidate']['jsonSha256'] = 'e' * 64
        self.job_path.write_text(json.dumps(job))
        for intent in self.intents:
            intent['jobJsonSha256'] = identity.json_sha256(job)
            intent['jobFileSha256'] = identity.sha256(self.job_path)
            intent['candidateJsonSha256'] = 'e' * 64
        self.envelopes()
        result = self.plan()
        self.assertEqual(result['counts']['revalidate'], 2)
        self.assertTrue(all(not r['modelRequestChanged'] for r in result['units']))
        self.assertTrue(all(r['modelRecomputeRequired'] is None for r in result['units']))
        self.assertEqual(result['plannedModelUnitEvaluations'], 0)

    def test_changed_text_reports_actual_model_input_without_overwrite_permission(self):
        job = json.loads(self.job_path.read_text())
        job['units'][1]['text'] += ' changed'
        self.job_path.write_text(json.dumps(job))
        for i, intent in enumerate(self.intents):
            intent.update(subject._job_binding(job, identity.sha256(self.job_path), job['units'][i], i))
        self.envelopes()
        result = self.plan()
        self.assertFalse(result['units'][0]['modelRequestChanged'])
        self.assertTrue(result['units'][1]['modelRequestChanged'])
        changes = {c['field'] for c in result['units'][1]['changes']}
        self.assertIn('textSha256', changes)
        self.assertTrue(result['units'][1]['blocked'])

    def test_batch_replays_full_window_preserves_successful_neighbor(self):
        # Rebuild synthetic canonical batch evidence with actual valid WAV/receipts.
        for i, intent in enumerate(self.intents):
            intent.update(batchSize=2, batchWindowStart=0, batchWindowUnitIndices=[0, 1],
                          batchWindowInputsSha256='d' * 64)
            intent_path = self.root / f'receipts/unit-{i:04d}.intent.json'
            intent_path.write_text(json.dumps(intent))
            commit_path = self.root / f'receipts/unit-{i:04d}.render.json'
            commit = json.loads(commit_path.read_text())
            commit.update(identity=intent, generationBatch={'unitIndices': [0, 1], 'seed': intent['seed']})
            commit_path.write_text(json.dumps(commit))
        self.envelopes()
        self.delete_unit(1)
        result = self.plan()
        self.assertEqual(result['plannedModelUnitEvaluations'], 2)
        self.assertEqual(result['plannedMissingUnitCommits'], 1)
        self.assertEqual(result['batchReplay'][0]['preserveCommittedUnitIndices'], [0])
        self.assertEqual(result['batchReplay'][0]['submitMissingUnitIndices'], [1])

    def test_active_owner_and_busy_formal_lock_block_dispatch(self):
        self.envelopes(owner='unknown')
        self.assertTrue(self.plan()['blockedScope']['wholeLayerDispatchBlocked'])
        self.envelopes()
        with (self.root / '.formal-render.lock').open('rb') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.plan()
        self.assertEqual(result['formalRenderLockObservation'], 'busy')
        self.assertEqual(result['ownerObservation'], 'active')
        self.assertTrue(result['blockedScope']['wholeLayerDispatchBlocked'])

    def test_owner_snapshot_wrong_root_is_rejected(self):
        state = json.loads(self.state_path.read_text()); state['renderRoot'] += '-other'
        self.state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'render_root_changed'):
            self.plan()

    def test_symlink_root_and_output_are_rejected(self):
        alias = self.root.parent / 'recovery-alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'regular_render_root'):
            subject.plan_layer3(self.job_path, render_root=alias)
        wav = self.root / self.f.context['job']['units'][1]['outputRelativePath']
        original = wav.read_bytes(); wav.unlink()
        target = self.root.parent / 'external.wav'; target.write_bytes(original); wav.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'escapes_root|symlink'):
            self.plan()

    def test_toctou_dependency_change_is_rejected(self):
        original = subject.Snapshot.check
        def change_then_check(snapshot):
            self.job_path.write_bytes(self.job_path.read_bytes() + b' ')
            original(snapshot)
        with patch.object(subject.Snapshot, 'check', change_then_check):
            with self.assertRaisesRegex(ValueError, 'changed_during_planning'):
                self.plan()

    def test_context_hash_alone_does_not_claim_all_model_inputs_changed(self):
        job = json.loads(self.job_path.read_text())
        job['inputs']['anchorManifest']['jsonSha256'] = 'b' * 64
        self.job_path.write_text(json.dumps(job))
        for i, intent in enumerate(self.intents):
            intent.update(subject._job_binding(job, identity.sha256(self.job_path), job['units'][i], i))
        self.envelopes()
        result = self.plan()
        self.assertTrue(all(r['modelRequestChanged'] is None for r in result['units']))
        self.assertEqual(result['plannedModelUnitEvaluations'], 0)
        self.assertTrue(result['namedJobDependencyProblems'])

    def test_named_upstream_input_change_blocks_without_fabricating_recompute(self):
        candidate = self.f.paths['candidate']
        candidate.write_bytes(candidate.read_bytes() + b' ')
        result = self.plan()
        self.assertTrue(result['namedJobDependencyProblems'])
        self.assertEqual(result['counts']['recompute'], 0)
        self.assertTrue(result['blockedScope']['wholeLayerDispatchBlocked'])

    def test_dependency_changed_during_planning_is_rejected(self):
        original = subject.Snapshot.check
        def change_then_check(snapshot):
            path = self.f.paths['candidate']
            path.write_bytes(path.read_bytes() + b' ')
            original(snapshot)
        with patch.object(subject.Snapshot, 'check', change_then_check):
            with self.assertRaisesRegex(ValueError, 'changed_during_planning'):
                self.plan()

    def test_formal_lock_replaced_during_planning_is_rejected(self):
        original = subject._plan_layer3
        def replace_lock(*args, **kwargs):
            result = original(*args, **kwargs)
            lock = self.root / '.formal-render.lock'
            lock.rename(lock.with_suffix('.saved'))
            lock.write_text('')
            return result
        with patch.object(subject, '_plan_layer3', replace_lock):
            with self.assertRaisesRegex(ValueError, 'formal_render_lock_changed'):
                self.plan()

    def test_incomplete_expected_snapshot_is_rejected(self):
        data = json.loads(self.expected_path.read_text())
        data['intents'][0].pop('checkpointSha256')
        self.expected_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'expected_intent_incomplete'):
            self.plan()

    def test_cli_stdout_only_no_models_and_schema(self):
        before = {p: identity.sha256(p) for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, '-m', 'scripts.production_recovery_plan',
            '--job', str(self.job_path), '--render-root', str(self.root),
            '--expected-intents', str(self.expected_path), '--execution-state', str(self.state_path)],
            capture_output=True, text=True, check=True)
        self.assert_schema(json.loads(result.stdout))
        self.assertEqual(before, {p: identity.sha256(p) for p in self.root.rglob('*') if p.is_file()})


if __name__ == '__main__':
    unittest.main()

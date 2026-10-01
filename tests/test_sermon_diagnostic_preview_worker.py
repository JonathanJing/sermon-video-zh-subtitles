"""Actual fixed child and speculative renderer; synthetic input/PCM only."""
import copy
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch

from scripts import sermon_diagnostic_preview_worker as subject
from scripts import sermon_diagnostic_provider as provider
from scripts import sermon_log_profile as profile
from scripts import sermon_review_budget as budget
from scripts import sermon_review_contracts as c
from tests import test_render_speculative_target_language_speech as fixtures
from tests import test_sermon_diagnostic_provider as provider_fixtures


class PreviewWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.DiagnosticPreviewTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.diag.f.f.root.resolve()
        self.context = copy.deepcopy(self.f.context)
        self.store = self.f.diag.f.store
        config = provider_fixtures.config(runId=self.context['runId'],
            approvalSha256=self.store.authority['approvalSha256'], targetMicrousd=5000,
            hardLimitMicrousd=10000, maxRequests=10, totalWallSeconds=60)
        self.subject = provider.DiagnosticProvider(self.store, config, domain=lambda: '7' * 64)
        self.context['runConfigSha256'] = c.canonical_sha256(config)
        with self.subject._locked(): pass  # Existing synthetic run, established before adapter invocation.
        self.state_path = self.store.root / budget.STORE_ID / 'provider-run/state.json'
        self.ledger_path = self.store.root / budget.STORE_ID / 'state.json'
        self.spec = dict(paths={key: str(path.resolve()) for key, path in self.f.preview.paths.items()},
            checkpoint_map_path=str(self.f.preview.checkpoint_map.resolve()),
            operation_policies_path=str(self.f.preview.policies.resolve()),
            strict_rubric_path=str(self.root / 'preview-rubric.json'),
            out=str(self.root / 'preview-output'), execute=False, device='cpu')
        Path(self.spec['strict_rubric_path']).write_text(json.dumps(self.f.rubric))
        checkpoint = self.f.f.root / 'checkpoint'
        raw = b'inert synthetic checkpoint; never a real model'
        (checkpoint / 'model.safetensors').write_bytes(raw)
        adapter_path = Path(self.spec['paths']['adapter'])
        registry_path = Path(self.spec['paths']['registry'])
        adapter = json.loads(adapter_path.read_text()); registry = json.loads(registry_path.read_text())
        digest = c.bytes_sha256(raw)
        registry['speakers'][0]['checkpoint']['checkpointSha256'] = digest
        adapter['conditioningSha256'] = digest
        adapter['registryJsonSha256'] = c.canonical_sha256(registry)
        adapter_path.write_text(json.dumps(adapter)); registry_path.write_text(json.dumps(registry))
        (checkpoint / 'config.json').write_text(json.dumps({'talker_config': {'spk_id': {adapter['speakerKey']: 0}}}))
        self.out = Path(self.spec['out'])

    def session(self):
        return profile.session(self.root / 'preview-accounting', 'preview-worker-test',
                               work_kind='engineering', evidence_mode='synthetic')

    def launch(self, **changes):
        return subject.launch_preview(self.root, self.subject, self.context,
                                      dict(self.spec, **changes), offline_fixture=True)

    def test_actual_subprocess_render_and_readonly_replay_keep_pending_and_original_ledgers(self):
        state, ledger = self.state_path.read_bytes(), self.ledger_path.read_bytes()
        before = {key: Path(path).read_bytes() for key, path in self.spec['paths'].items()}
        with self.session(), patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-secret-never-forward'}):
            receipt = self.launch()
            calls = (self.out / 'fixture-synth-calls.jsonl').read_bytes()
            with patch.object(subject.harness, 'bounded_process', side_effect=AssertionError('must not respawn')):
                self.assertEqual(self.launch(), receipt)
            self.assertEqual(subject.validate_preview_receipt(self.root, self.subject, self.context, receipt), receipt)
        self.assertEqual(len(calls.splitlines()), 2)
        self.assertEqual((self.out / 'fixture-synth-calls.jsonl').read_bytes(), calls)
        self.assertEqual(self.state_path.read_bytes(), state); self.assertEqual(self.ledger_path.read_bytes(), ledger)
        self.assertEqual({key: Path(path).read_bytes() for key, path in self.spec['paths'].items()}, before)
        self.assertFalse(receipt['productionEligible']); self.assertEqual(receipt['humanAcceptance'], 'pending')
        self.assertEqual(receipt['deadlineMonotonic'], json.loads(state)['startedMonotonic'] + 60)
        self.assertNotIn('synthetic-secret-never-forward', json.dumps(receipt))
        self.assertFalse((self.out / 'job.json').exists())
        events, errors = subject.accounting.read_events(self.root / 'preview-accounting')
        self.assertFalse(errors)
        self.assertTrue(any((row.get('stage') or '').endswith('.synthesis') for row in events))

    def test_scrubbed_environment_has_no_credentials_or_proxy(self):
        with self.session(), patch.dict(os.environ, {'OPENAI_API_KEY': 'secret', 'HTTPS_PROXY': 'secret'}):
            env = subject._environment(self.root, self.out, True)
        self.assertNotIn('OPENAI_API_KEY', env); self.assertNotIn('HTTPS_PROXY', env)
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')
        self.assertEqual(env['TRANSFORMERS_OFFLINE'], '1')

    def test_later_settled_provider_work_does_not_invalidate_original_receipt(self):
        with self.session(): receipt = self.launch()
        state = json.loads(self.state_path.read_text())
        state['requests']['later-fixture-request'] = dict(requestSha256='a'*64,
            bounds=dict(requests=1, wallTimeMs=1, costMicrousd=1), model='gpt-transcribe',
            state='returned', receiptSha256='b'*64, operationId='later.fixture')
        subject.jobs._persist(self.state_path, state)
        with self.session(), patch.object(subject.harness, 'bounded_process', side_effect=AssertionError('must not respawn')):
            self.assertEqual(self.launch(), receipt)

    def test_hung_child_is_killed_at_original_deadline_and_never_restarted(self):
        state = json.loads(self.state_path.read_text())
        state['startedMonotonic'] = time.monotonic() - 57  # Three seconds remain in this synthetic original run.
        subject.jobs._persist(self.state_path, state)
        original = self.state_path.read_bytes()
        began = time.monotonic()
        with self.session(), self.assertRaises(subprocess.TimeoutExpired):
            self.launch(fixture_behavior='hang')
        self.assertLess(time.monotonic() - began, 9)
        self.assertTrue((self.out / 'worker-attempt.json').is_file())
        self.assertFalse((self.out / 'worker-receipt.json').exists())
        self.assertEqual(self.state_path.read_bytes(), original)
        with self.session(), patch.object(subject.harness, 'bounded_process', side_effect=AssertionError('must not respawn')):
            with self.assertRaisesRegex(ValueError, 'deadline|reconciliation'):
                self.launch(fixture_behavior='hang')

    def test_failed_child_after_render_requires_reconciliation_without_new_synth(self):
        with self.session(), self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
            self.launch(fixture_behavior='fail_after_render')
        calls = (self.out / 'fixture-synth-calls.jsonl').read_bytes()
        with self.session(), patch.object(subject.harness, 'bounded_process', side_effect=AssertionError('must not respawn')):
            with self.assertRaisesRegex(ValueError, 'requires_reconciliation'):
                self.launch(fixture_behavior='fail_after_render')
        self.assertEqual((self.out / 'fixture-synth-calls.jsonl').read_bytes(), calls)

    def test_missing_provider_does_not_initialize_clock_or_store(self):
        self.state_path.unlink()
        with self.session(), self.assertRaisesRegex(ValueError, 'existing_provider_required'):
            self.launch()
        self.assertFalse(self.state_path.exists()); self.assertFalse(self.out.exists())

    def test_unknown_provider_request_blocks_before_dispatch(self):
        state = json.loads(self.state_path.read_text())
        state['requests']['unknown-fixture-request'] = dict(requestSha256='a'*64,
            bounds=dict(requests=1, wallTimeMs=1, costMicrousd=1), model='gpt-transcribe',
            state='outcome_unknown', receiptSha256='b'*64, operationId='unknown.fixture')
        subject.jobs._persist(self.state_path, state)
        before = self.state_path.read_bytes()
        with self.session(), patch.object(subject.harness, 'bounded_process', side_effect=AssertionError('must not dispatch')):
            with self.assertRaisesRegex(ValueError, 'outcome_requires_reconciliation'):
                self.launch()
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse(self.out.exists())

    def test_wrong_context_or_checkpoint_and_revoked_voice_reject_before_worker(self):
        self.context['runConfigSha256'] = 'f'*64
        with self.session(), self.assertRaisesRegex(ValueError, 'config_changed'): self.launch()
        self.context['runConfigSha256'] = c.canonical_sha256(self.subject.config)
        registry_path = Path(self.spec['paths']['registry']); registry = json.loads(registry_path.read_text())
        registry['speakers'][0]['authorization']['status'] = 'revoked'
        registry_path.write_text(json.dumps(registry))
        adapter_path = Path(self.spec['paths']['adapter']); adapter = json.loads(adapter_path.read_text())
        adapter['registryJsonSha256'] = c.canonical_sha256(registry); adapter_path.write_text(json.dumps(adapter))
        with self.session(), self.assertRaises(ValueError): self.launch()
        self.assertFalse(self.out.exists())

    def test_original_embedded_source_bytes_are_rechecked_before_worker(self):
        source = json.loads(Path(self.spec['paths']['source']).read_text())
        transcript = Path(source['transcript']['artifact']['path'])
        transcript.write_text('[]')
        with self.session(), patch.object(subject.harness, 'bounded_process', side_effect=AssertionError('must not dispatch')):
            with self.assertRaisesRegex(ValueError, 'embedded_artifact_changed'):
                self.launch()
        self.assertFalse(self.out.exists())

    def test_derived_symlink_rejects_before_worker_or_external_write(self):
        self.out.mkdir()
        outside = self.root.parent / (self.root.name + '-preview-sentinel')
        outside.mkdir(); self.addCleanup(outside.rmdir)
        sentinel = outside / 'sentinel'; sentinel.write_bytes(b'unchanged'); self.addCleanup(sentinel.unlink)
        (self.out / 'receipts').symlink_to(outside, target_is_directory=True)
        with self.session(), patch.object(subject.harness, 'bounded_process', side_effect=AssertionError('must not dispatch')):
            with self.assertRaisesRegex(ValueError, 'Symlink'): self.launch()
        self.assertEqual(list(outside.iterdir()), [sentinel]); self.assertEqual(sentinel.read_bytes(), b'unchanged')

    def test_changed_unit_receipt_or_attempt_rejects_completed_replay(self):
        with self.session(): receipt = self.launch()
        attempt_path = self.out / 'worker-attempt.json'
        attempt = json.loads(attempt_path.read_text()); attempt['requestSha256'] = 'f'*64
        attempt_path.write_text(json.dumps(attempt))
        with self.assertRaisesRegex(ValueError, 'artifact_changed'):
            subject.validate_preview_receipt(self.root, self.subject, self.context, receipt)

    def test_real_execution_requires_explicit_flag_before_model_load(self):
        with self.session(), self.assertRaisesRegex(ValueError, 'execute_required'):
            subject.launch_preview(self.root, self.subject, self.context, self.spec)
        self.assertFalse(self.out.exists())


if __name__ == '__main__': unittest.main()

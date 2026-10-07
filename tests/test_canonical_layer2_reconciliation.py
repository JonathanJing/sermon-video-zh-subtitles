"""Artifact recovery uses actual L2 producer/validator fixtures, never paid calls."""
from contextlib import contextmanager
import copy
import os
import subprocess
import sys
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_reconciliation as subject
from scripts import canonical_layer2_controller as layer2
from scripts import canonical_durable_jobs as durable
from scripts import sermon_workflow_jobs as jobs
from scripts.sermon_execution_harness import work_lock, WorkAlreadyRunning
from tests import test_canonical_layer2_controller as fixtures


class CanonicalLayer2ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CanonicalLayer2ControllerTests('test_real_producer_and_plugin_create_only_human_pending_candidate')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.path
        with self.fixture.active() as (config, code, key, folder):
            self.fixture.execute(config, code, key)
        self.config, self.key, self.folder = config, key, folder
        self.original = {name: (folder / name).read_bytes() for name in ('request.json', 'state.json')}

    def view(self):
        return layer2.snapshot(layer2.load_configuration(self.path))

    def reconcile(self, revision=None):
        return subject.reconcile(self.path, 'zh-Hans', revision or self.view()['stateRevision'])

    def receipt_path(self):
        return self.folder / durable.RECONCILIATION_FILE

    def test_abandoned_successful_artifact_settles_without_rewriting_command_outcome(self):
        before = self.view()
        self.assertEqual(before['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        calls = len(self.fixture.calls)
        with patch.object(jobs, 'start_job') as start, patch.object(layer2.models, 'run_accounted') as run:
            result = self.reconcile()
            self.assertEqual(result['status'], 'artifact_reconciled')
            after = self.view()
            tick = layer2.Controller(self.path, mode='deterministic_execute').tick()
        start.assert_not_called(); run.assert_not_called()
        self.assertEqual(len(self.fixture.calls), calls)
        self.assertFalse(tick['dispatched'])
        self.assertEqual(after['nodes']['text.zh-Hans']['status'], 'validated')
        self.assertEqual(after['nodes']['audio.zh-Hans']['status'], 'human_gate')
        self.assertEqual(after['durableJobInspection']['jobs'][0]['status'], 'artifact_reconciled')
        self.assertEqual(after['durableJobInspection']['jobs'][0]['originalJobStatus'], 'uncertain')
        self.assertEqual(jobs.peek_job(self.config.job_root, self.key)['status'], 'uncertain')
        for name, data in self.original.items():
            self.assertEqual((self.folder / name).read_bytes(), data)
        self.assertFalse(result['humanApprovalCreated'])
        self.assertNotIn(str(self.fixture.root), json.dumps(result))

    def test_failed_command_with_valid_candidate_retains_its_actual_failure(self):
        jobs._write_state(self.folder, self.key, 'failed', returnCode=2, reason='command_completed')
        original = (self.folder / 'state.json').read_bytes()
        self.assertEqual(self.reconcile()['originalJobStatus'], 'failed')
        self.assertEqual((self.folder / 'state.json').read_bytes(), original)
        self.assertEqual(self.view()['nodes']['text.zh-Hans']['status'], 'validated')

    def test_default_controller_does_not_reconcile_implicitly(self):
        layer2.Controller(self.path, mode='deterministic_execute').tick()
        self.assertFalse(self.receipt_path().exists())
        self.assertEqual((self.folder / 'state.json').read_bytes(), self.original['state.json'])

    def test_stale_snapshot_and_config_changes_are_rejected(self):
        old = self.view()['stateRevision']
        jobs._write_state(self.folder, self.key, 'failed', reason='new_outcome')
        with self.assertRaisesRegex(ValueError, 'stale_reconciliation_revision'):
            self.reconcile(old)
        self.assertFalse(self.receipt_path().exists())
        request = jobs._read(self.folder / 'request.json')
        request['command'][-3] = 'f'*64
        request['commandSha256'] = jobs._digest(request['command'])
        jobs._persist(self.folder / 'request.json', request)
        jobs._write_state(self.folder, self.key, 'failed', requestSha256=jobs._digest(request))
        with self.assertRaisesRegex(ValueError, 'original_execution_binding_changed'):
            self.reconcile()
        self.assertFalse(self.receipt_path().exists())

    def test_live_owner_or_output_writer_cannot_be_reconciled(self):
        with jobs._lock(self.config.job_root, self.key):
            with self.assertRaisesRegex(ValueError, 'job_owner_still_active'):
                self.reconcile()
        with work_lock(self.fixture.output):
            with self.assertRaises(WorkAlreadyRunning):
                self.reconcile()
        self.assertFalse(self.receipt_path().exists())

    def test_missing_or_invalid_candidate_never_creates_receipt(self):
        path = self.fixture.output / 'candidate.json'
        original = path.read_bytes()
        for value in (None, b'{}'):
            if value is None:
                path.unlink()
            else:
                path.write_bytes(value)
            with self.assertRaisesRegex(ValueError, 'validated_candidate_required'):
                self.reconcile()
            self.assertFalse(self.receipt_path().exists())
        path.write_bytes(original)

    def test_receipt_is_idempotent_and_old_revision_cannot_repeat_mutation(self):
        old = self.view()['stateRevision']
        first = self.reconcile(old)
        path = self.receipt_path()
        evidence = path.read_bytes(), path.stat().st_mtime_ns
        with self.assertRaisesRegex(ValueError, 'stale_reconciliation_revision'):
            self.reconcile(old)
        self.assertEqual(self.reconcile(), first)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), evidence)

    def test_read_side_revalidates_candidate_and_keeps_unknown_outcome_after_loss(self):
        self.reconcile()
        (self.fixture.output / 'candidate.json').unlink()
        with patch.object(jobs, 'start_job') as start:
            view = self.view()
            tick = layer2.Controller(self.path, mode='deterministic_execute').tick()
        start.assert_not_called()
        self.assertFalse(tick['dispatched'])
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')

    def test_modified_receipt_or_job_state_fails_closed(self):
        self.reconcile()
        original = self.receipt_path().read_bytes()
        receipt = json.loads(original)
        for name, value in [('validatedOutputSha256', 'f'*64), ('identity', {}), ('stateSha256', 'f'*64)]:
            changed = copy.deepcopy(receipt); changed[name] = value
            self.receipt_path().write_text(json.dumps(changed))
            self.assertEqual(self.view()['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        self.receipt_path().write_bytes(original)
        jobs._write_state(self.folder, self.key, 'failed', reason='changed_after_reconciliation')
        self.assertTrue(self.view()['durableJobInspection']['diagnostics'])

    def test_atomic_receipt_failure_retains_original_unknown_evidence(self):
        with patch.object(jobs, '_persist', side_effect=OSError('injected publication failure')):
            with self.assertRaises(OSError):
                self.reconcile()
        self.assertFalse(self.receipt_path().exists())
        self.assertEqual((self.folder / 'state.json').read_bytes(), self.original['state.json'])
        self.assertEqual(self.view()['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        self.reconcile()
        self.assertEqual(self.view()['nodes']['text.zh-Hans']['status'], 'validated')

    def test_post_publication_sync_failure_is_resumed_without_overwriting_receipt(self):
        with patch.object(jobs, '_sync_directory_ancestry', side_effect=OSError('injected metadata failure')):
            with self.assertRaises(OSError):
                self.reconcile()
        original = self.receipt_path().read_bytes()
        result = self.reconcile()
        self.assertEqual(result['status'], 'artifact_reconciled')
        self.assertEqual(self.receipt_path().read_bytes(), original)
        self.assertEqual((self.folder / 'state.json').read_bytes(), self.original['state.json'])

    def test_state_change_in_job_lock_window_is_rejected_even_with_same_status(self):
        original_lock = jobs._lock
        @contextmanager
        def altered(root, key, *args, **kwargs):
            with original_lock(root, key, *args, **kwargs) as result:
                if key == self.key:
                    state = jobs._read(self.folder / 'state.json')
                    state['reason'] = 'changed_under_admission'
                    jobs._persist(self.folder / 'state.json', state)
                yield result
        with patch.object(jobs, '_lock', side_effect=altered):
            with self.assertRaisesRegex(ValueError, 'original_execution_binding_changed'):
                self.reconcile()
        self.assertFalse(self.receipt_path().exists())

    def test_two_cli_processes_publish_one_receipt_without_model_credentials(self):
        revision = self.view()['stateRevision']
        command = [sys.executable, str(Path(subject.__file__).resolve()), '--config', str(self.path),
                   '--locale', 'zh-Hans', '--expected-state-revision', revision]
        env = {**os.environ, 'OPENAI_API_KEY': '', 'CODEX_HOME': '/nonexistent/tongxing-test-no-auth'}
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                    for _ in range(2)]
        outputs = [child.communicate(timeout=20) for child in children]
        self.assertEqual(sum(child.returncode == 0 for child in children), 1, outputs)
        self.assertEqual(self.view()['nodes']['text.zh-Hans']['status'], 'validated')
        self.assertEqual((self.folder / 'state.json').read_bytes(), self.original['state.json'])
        self.assertEqual(len(list(self.folder.glob(durable.RECONCILIATION_FILE))), 1)

    def test_reconciled_shadow_preserves_all_files_and_metadata(self):
        self.reconcile()
        before = self.fixture.files()
        layer2.Controller(self.path).tick()
        self.assertEqual(self.fixture.files(), before)

    def test_symlink_reconciliation_cannot_redirect_a_write(self):
        outside = self.fixture.root / 'unrelated.json'
        outside.write_text('preserve me')
        self.receipt_path().symlink_to(outside)
        with self.assertRaises(ValueError):
            self.reconcile()
        self.assertEqual(outside.read_text(), 'preserve me')


if __name__ == '__main__':
    unittest.main()

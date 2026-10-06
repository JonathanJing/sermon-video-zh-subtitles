"""Complete returned responses can recover locally; missing responses never retry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_cache_recovery as subject
from scripts import canonical_layer2_reconciliation as reconciliation
from scripts import canonical_layer2_controller as layer2
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_accounting as accounting
from scripts import weekly_pipeline_report as weekly
from tests import test_canonical_layer2_controller as fixtures


class CanonicalLayer2CacheRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CanonicalLayer2ControllerTests('test_real_producer_and_plugin_create_only_human_pending_candidate')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path, self.output = self.fixture.path, self.fixture.output
        with self.fixture.active() as (config, code, key, folder):
            self.fixture.execute(config, code, key)
        self.config, self.key, self.folder = config, key, folder
        self.original_candidate = (self.output / 'candidate.json').read_bytes()
        (self.output / 'candidate.json').unlink()
        self.original_job = {name: (folder / name).read_bytes() for name in ('request.json', 'state.json')}

    def revision(self):
        return layer2.snapshot(layer2.load_configuration(self.path))['stateRevision']

    def recover(self, revision=None):
        return subject.recover(self.path, 'zh-Hans', revision or self.revision())

    def assert_job_unchanged(self):
        for name, data in self.original_job.items():
            self.assertEqual((self.folder / name).read_bytes(), data)

    def test_rebuilds_missing_evidence_and_candidate_without_any_model_or_secret_access(self):
        original_cache = {p.name: p.read_bytes() for p in self.output.glob('group-*.json')}
        (self.output / 'evidence.json').unlink()
        (self.output / 'language-review.json').unlink()
        before, _ = accounting.read_events(self.output / 'accounting')
        environ_get = os.environ.get
        def public_configuration_only(key, *args):
            if key == 'OPENAI_API_KEY':
                self.fail('credential access')
            return environ_get(key, *args)
        with patch.object(layer2.os.environ, 'get', side_effect=public_configuration_only), \
             patch.object(jobs, 'start_job') as start:
            result = self.recover()
        start.assert_not_called()
        self.assertEqual(result['status'], 'candidate_recovered_reconciliation_required')
        self.assertEqual(result['modelCalls'], 0)
        self.assertEqual((self.output / 'candidate.json').read_bytes(), self.original_candidate)
        self.assertEqual({p.name: p.read_bytes() for p in self.output.glob('group-*.json')}, original_cache)
        self.assertEqual(len(self.fixture.calls), 4)
        self.assert_job_unchanged()
        view = layer2.snapshot(self.config)
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        reconciliation.reconcile(self.path, 'zh-Hans', view['stateRevision'])
        self.assertEqual(layer2.snapshot(self.config)['nodes']['audio.zh-Hans']['status'], 'human_gate')
        events, damaged = accounting.read_events(self.output / 'accounting')
        self.assertFalse(damaged)
        prior = {e['eventId'] for e in before}
        new = [e for e in events if e['eventId'] not in prior and e['event'] == 'stage_started']
        self.assertTrue(new)
        self.assertTrue(all(e['executorType'] == 'deterministic_program' for e in new))
        recovery_runs = {e['runId'] for e in new}
        self.assertEqual(len(recovery_runs), 1)
        starts = {e['stage']: e for e in new}
        chain = ['evidence_assembly', 'cache_binding', 'cache_candidate', 'cache_final_validation']
        for parent, child in zip(chain, chain[1:]):
            self.assertEqual(starts['layer2.' + child + '.zh-Hans']['dependsOn'],
                             [starts['layer2.' + parent + '.zh-Hans']['spanId']])
        self.assertEqual(starts['layer2.source_admission.zh-Hans']['dependsOn'],
                         [starts['layer2.cache_admission.zh-Hans']['spanId']])
        for run_id in recovery_runs:
            report = weekly.project_run(run_id, [e for e in events if e['runId'] == run_id])
            self.assertEqual(report['status'], 'projected')
            self.assertEqual(report['leafElapsedByExecutor']['production_model'], 0)

    def test_complete_raw_responses_can_rebuild_parsed_caches_without_transport(self):
        for p in self.output.glob('group-*.json'):
            if not p.name.endswith('.raw.json'):
                p.unlink()
        self.recover()
        self.assertEqual((self.output / 'candidate.json').read_bytes(), self.original_candidate)
        self.assertEqual(len(list(self.output.glob('group-*-astra.json'))), 2)
        self.assert_job_unchanged()

    def test_unknown_started_request_without_returned_response_remains_blocked(self):
        parsed = self.output / 'group-0002-sol.json'
        parsed.unlink(); parsed.with_suffix('.raw.json').unlink()
        marker = parsed.with_suffix('.started.json'); marker.write_text('{"status":"started_response_unconfirmed"}')
        before = marker.read_bytes()
        with patch.object(layer2.models, 'run_accounted') as run:
            with self.assertRaisesRegex(ValueError, 'complete_returned_model_cache_required'):
                self.recover()
        run.assert_not_called()
        self.assertEqual(marker.read_bytes(), before)
        self.assertFalse((self.output / 'candidate.json').exists())
        self.assert_job_unchanged()

    def test_cache_only_transport_guard_precedes_new_paid_intent(self):
        output = self.output / 'missing-response.json'
        policy = self.fixture.fixture.fixture.policy
        with patch.object(layer2.models, 'save_new') as save:
            with self.assertRaisesRegex(ValueError, 'Cache-only recovery has no returned'):
                layer2.models._model_call('translator', {'instruction': 'synthetic', 'input': {}}, policy,
                    output, '', lambda *_: self.fail('transport called'), cache_only=True)
        save.assert_not_called()
        self.assertFalse(output.with_suffix('.started.json').exists())

    def test_changed_payload_identity_cannot_be_recovered(self):
        path = self.output / 'group-0001-astra.json'
        saved = jobs._read(path);saved['payloadSha256'] = 'f'*64;path.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, 'Cached translator response belongs to different inputs'):
            self.recover()
        self.assertFalse((self.output / 'candidate.json').exists())
        self.assert_job_unchanged()

    def test_incomplete_raw_response_and_failed_semantic_evidence_cannot_pass(self):
        path = self.output / 'group-0001-sol.json'
        saved = jobs._read(path);saved['result']['semanticReview']['status'] = 'fail'
        path.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, 'Sol flagged'):
            self.recover()
        path.unlink()
        raw_path = path.with_suffix('.raw.json'); raw = jobs._read(raw_path)
        raw['response']['choices'][0]['finish_reason'] = 'length';raw_path.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, 'response is incomplete'):
            self.recover()
        self.assertFalse((self.output / 'candidate.json').exists())
        self.assert_job_unchanged()

    def test_invalid_candidate_or_conflicting_language_receipt_is_not_overwritten(self):
        candidate = self.output / 'candidate.json';candidate.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'upstream_or_candidate_not_ready'):
            self.recover()
        self.assertEqual(candidate.read_text(), '{}');candidate.unlink()
        receipt = self.output / 'language-review.json';receipt.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'existing_recovery_artifact_conflict'):
            self.recover()
        self.assertEqual(receipt.read_text(), '{}')
        self.assertFalse(candidate.exists())

    def test_redirected_and_oversized_cache_is_rejected_before_model_runner(self):
        path = self.output / 'group-0001-astra.json'
        saved = path.read_bytes()
        external = self.output.parent / 'external-cache.json'; external.write_bytes(saved)
        path.unlink(); path.symlink_to(external)
        with patch.object(layer2.models, 'run_accounted') as run:
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                self.recover()
            run.assert_not_called()
        path.unlink(); path.write_bytes(saved)
        with path.open('ab') as stream:
            stream.truncate(layer2.packages.MAX_JSON_BYTES + 1)
        with patch.object(layer2.models, 'run_accounted') as run:
            with self.assertRaisesRegex(ValueError, 'oversized_recovery_cache'):
                self.recover()
            run.assert_not_called()
        self.assertFalse((self.output / 'candidate.json').exists())
        self.assert_job_unchanged()

    def test_live_owner_and_stale_revision_cannot_recover(self):
        with jobs._lock(self.config.job_root, self.key):
            with self.assertRaisesRegex(ValueError, 'job_owner_still_active'):
                self.recover()
        old = self.revision()
        jobs._write_state(self.folder, self.key, 'failed', reason='new_outcome')
        with self.assertRaisesRegex(ValueError, 'stale_recovery_revision'):
            self.recover(old)
        self.assertFalse((self.output / 'candidate.json').exists())

    def test_config_drift_after_cache_validation_preserves_paid_results_without_candidate(self):
        original = layer2.models.run_accounted
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            config = jobs._read(self.path);config['productionRunId'] = 'e'*64
            self.path.write_text(json.dumps(config))
            return result
        with patch.object(layer2.models, 'run_accounted', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'configuration_or_code_changed'):
                self.recover()
        self.assertFalse((self.output / 'candidate.json').exists())
        self.assertTrue((self.output / 'evidence.json').exists())
        self.assertEqual(len(self.fixture.calls), 4)

    def test_candidate_commit_failure_can_resume_without_new_calls(self):
        candidate = self.output / 'candidate.json'
        original = layer2.models.save_new
        def failed(path, value):
            if path.resolve() == candidate.resolve():
                raise OSError('candidate commit interrupted')
            return original(path, value)
        with patch.object(layer2.models, 'save_new', side_effect=failed):
            with self.assertRaises(OSError):
                self.recover()
        self.assertFalse(candidate.exists())
        self.recover()
        self.assertEqual(candidate.read_bytes(), self.original_candidate)
        self.assertEqual(len(self.fixture.calls), 4)

    def test_existing_valid_candidate_is_read_only_and_does_not_approve_the_job(self):
        self.recover()
        before = self.fixture.files()
        self.assertEqual(self.recover()['status'], 'validated_candidate_already_present')
        self.assertEqual(self.fixture.files(), before)
        self.assertEqual(layer2.snapshot(self.config)['nodes']['text.zh-Hans']['status'], 'reconciliation_required')

    def test_cli_with_empty_key_restores_candidate_without_dispatch(self):
        command = [sys.executable, str(Path(subject.__file__).resolve()), '--config', str(self.path),
                   '--locale', 'zh-Hans', '--expected-state-revision', self.revision()]
        result = subprocess.run(command, env={**os.environ, 'OPENAI_API_KEY': '', 'CODEX_HOME': '/nonexistent/tongxing-test-no-auth'}, capture_output=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['modelCalls'], 0)
        self.assertEqual((self.output / 'candidate.json').read_bytes(), self.original_candidate)
        self.assert_job_unchanged()


if __name__ == '__main__':
    unittest.main()

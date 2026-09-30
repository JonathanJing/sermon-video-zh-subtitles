"""Fixed L2 orchestration over actual validators/producers; all model replies are synthetic."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_controller as subject
from scripts import canonical_durable_jobs as durable
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_execution_harness as harness
from tests import test_inspect_canonical_packages as fixtures


class CanonicalLayer2ControllerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PackageInspectionTests('test_real_source_candidate_validators_inspect_without_approval_or_writes')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.fixture.config['locales']['zh-Hans'].pop('candidate')
        self.fixture.write('inspection.json', self.fixture.config)
        self.path = self.root / 'execution.json'
        self.output = self.root / 'outputs' / 'zh-Hans'
        self.config_data = {'schemaVersion': subject.SCHEMA, 'productionRunId': 'a'*64,
                            'inspectionConfig': 'inspection.json', 'jobRoot': 'jobs',
                            'locales': {'zh-Hans': {'outputDirectory': 'outputs/zh-Hans',
                                                   'plugin': str(self.fixture.fixture.plugin_path)}}}
        self.save_config()
        self.calls = []

    def save_config(self):
        self.path.write_text(json.dumps(self.config_data))

    def files(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def fake_call(self, key, payload):
        self.assertEqual(key, 'fixture-key')
        self.calls.append(payload)
        index = (len(self.calls) - 1) // 2
        input_group = json.loads(payload['messages'][1]['content'])
        group = self.fixture.fixture.evidence['groups'][index]
        fields = ['translationGroupId', 'sourceUnitIds', 'targetUtterances', 'coverage']
        if payload['model'] == 'gpt-6-sol':
            fields += ['semanticReview']
        answer = {k: copy.deepcopy(group[k]) for k in fields}
        answer['translationGroupId'] = input_group['translationGroupId']
        return {'id': 'fixture-response-' + str(len(self.calls)), 'model': payload['model'],
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]}

    @contextmanager
    def active(self, *, status='running'):
        config = subject.load_configuration(self.path)
        view = subject.package_view(config)
        ident = durable.identity(view, config.run_id, 'text.zh-Hans')
        key, code = jobs._digest(ident), subject.code_identity()
        command = subject._worker_command(config, 'zh-Hans', key, code)
        request = {'schemaVersion': jobs.SCHEMA, 'jobId': key, 'identity': ident,
                   'command': command, 'commandSha256': jobs._digest(command), 'timeoutSeconds': 21600.0}
        with jobs._lock(config.job_root, key) as (folder, _, held):
            self.assertTrue(held)
            folder.mkdir()
            jobs._persist(folder / 'request.json', request)
            jobs._persist(folder / 'state.json', {'schemaVersion': jobs.SCHEMA, 'jobId': key,
                          'status': status, 'requestSha256': jobs._digest(request)})
            yield config, code, key, folder

    def execute(self, config, code, key, *, caller=None):
        return subject.execute(self.path, 'zh-Hans', config.sha256, code, key,
                               caller=caller or self.fake_call, api_key='fixture-key')

    def test_default_shadow_is_read_only_and_never_loads_credentials_or_dispatches(self):
        before = self.files()
        with patch.object(subject.os.environ, 'get', side_effect=AssertionError('secret access')), \
             patch.object(jobs, 'start_job') as start:
            result = subject.Controller(self.path).tick()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['proposedWorkUnit'], 'text.zh-Hans')
        self.assertFalse(result['dispatched'])
        self.assertEqual(self.files(), before)
        self.assertFalse((self.root / 'jobs').exists())
        self.assertNotIn(str(self.root), json.dumps(result))
        start.assert_not_called()

    def test_fixed_admission_rechecks_state_under_lock_and_uses_no_shell(self):
        controller = subject.Controller(self.path, mode='deterministic_execute')
        original = subject.snapshot
        calls = 0
        def changed(config):
            nonlocal calls
            calls += 1
            result = original(config)
            if calls == 2:
                result['stateRevision'] = 'f'*64
            return result
        with patch.object(subject, 'snapshot', side_effect=changed), patch.object(jobs, 'start_job') as start:
            result = controller.tick()
        start.assert_not_called()
        self.assertEqual(result['status'], 'blocked')
        def admitted(root, ident, command, *, timeout_seconds):
            with jobs._lock(root, subject.ADMISSION_LOCK) as (_, _, held):
                self.assertFalse(held)
            self.assertEqual(command[:3], [sys.executable, str(Path(subject.__file__).resolve()), 'worker'])
            self.assertEqual(timeout_seconds, 21600)
            self.assertEqual(ident['workUnitId'], 'text.zh-Hans')
            self.assertNotIn('fixture-key', str(command))
            return {'jobId': jobs._digest(ident), 'status': 'queued'}
        with patch.object(jobs, 'start_job', side_effect=admitted) as start:
            self.assertTrue(controller.tick()['dispatched'])
        start.assert_called_once()

    def test_real_producer_and_plugin_create_only_human_pending_candidate(self):
        with self.active() as (config, code, key, folder):
            def no_credentials(name, default=None):
                self.assertNotEqual(name, 'OPENAI_API_KEY')
                return default
            with patch.object(subject.os.environ, 'get', side_effect=no_credentials):
                result = self.execute(config, code, key)
            candidate = json.loads((self.output / 'candidate.json').read_text())
            self.assertEqual(candidate['status'], 'machine_review_pass_human_review_pending')
            self.assertFalse(candidate['releaseEligible'])
            self.assertEqual(candidate['humanReview']['translation'], 'pending')
            self.assertEqual(result['candidateJsonSha256'], jobs._digest(candidate))
            self.assertEqual([c['model'] for c in self.calls], ['gpt-6-astra', 'gpt-6-sol']*2)
            self.assertTrue((self.output / 'language-review.json').is_file())
            jobs._write_state(folder, key, 'succeeded')
        controller = subject.Controller(self.path, mode='deterministic_execute')
        with patch.object(jobs, 'start_job') as start:
            result = controller.tick()
        start.assert_not_called()
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'validated')
        self.assertEqual(result['nodes']['audio.zh-Hans']['status'], 'human_gate')
        self.assertFalse(result['dispatched'])
        self.assertFalse(any(p.suffix in ('.wav','.mp3','.html') for p in self.output.rglob('*')))

    def test_abandoned_queued_job_cannot_be_restarted_even_with_ready_source(self):
        with self.active(status='queued'):
            pass
        before = self.files()
        with patch.object(jobs, 'start_job') as start:
            view = subject.Controller(self.path).tick()
        self.assertEqual(view['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        self.assertEqual(before, self.files())
        start.assert_not_called()

    def test_direct_worker_requires_active_bound_job_and_canonical_output_lock(self):
        config = subject.load_configuration(self.path)
        key = jobs._digest(durable.identity(subject.package_view(config), config.run_id, 'text.zh-Hans'))
        with self.assertRaises(ValueError):
            self.execute(config, subject.code_identity(), key)
        self.assertEqual(self.calls, [])
        with self.active() as (config, code, key, _), harness.work_lock(self.output):
            with self.assertRaises(harness.WorkAlreadyRunning):
                self.execute(config, code, key)
        self.assertEqual(self.calls, [])

    def test_configuration_code_and_source_drift_stop_before_model(self):
        with self.active() as (config, code, key, _):
            with self.assertRaises(ValueError):
                self.execute(config, 'f'*64, key)
            self.config_data['productionRunId'] = 'b'*64; self.save_config()
            with self.assertRaises(ValueError):
                self.execute(config, code, key)
            self.config_data['productionRunId'] = 'a'*64; self.save_config()
            source = copy.deepcopy(self.fixture.fixture.source)
            source['review']['humanApproval'] = False
            self.fixture.write('source.json', source)
            with self.assertRaises(ValueError):
                self.execute(config, code, key)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.output / 'candidate.json').exists())

    def test_source_review_change_during_response_blocks_next_call_and_preserves_paid_receipt(self):
        def changed(key, payload):
            answer = self.fake_call(key, payload)
            source = copy.deepcopy(self.fixture.fixture.source)
            source['review']['humanApproval'] = False
            self.fixture.write('source.json', source)
            return answer
        with self.active() as (config, code, key, _):
            with self.assertRaises(ValueError):
                self.execute(config, code, key, caller=changed)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(any(self.output.glob('*astra*.json')))
        self.assertFalse((self.output / 'candidate.json').exists())

    def test_drift_after_last_response_blocks_candidate_without_discarding_models(self):
        def changed(key, payload):
            answer = self.fake_call(key, payload)
            if len(self.calls) == 4:
                self.config_data['productionRunId'] = 'b'*64; self.save_config()
            return answer
        with self.active() as (config, code, key, _):
            with self.assertRaises(ValueError):
                self.execute(config, code, key, caller=changed)
        self.assertEqual(len(self.calls), 4)
        self.assertTrue((self.output / 'evidence.json').is_file())
        self.assertFalse((self.output / 'candidate.json').exists())

    def test_invalid_existing_candidate_and_wrong_plugin_are_never_proposed_for_overwrite(self):
        self.output.mkdir(parents=True)
        candidate = self.output / 'candidate.json'; candidate.write_text('{}')
        result = subject.Controller(self.path).tick()
        self.assertIsNone(result['proposedWorkUnit'])
        self.assertEqual(candidate.read_text(), '{}')
        candidate.unlink()
        self.fixture.fixture.plugin_path.write_text('PLUGIN_ID = "changed"')
        result = subject.Controller(self.path).tick()
        self.assertEqual(result['nodes']['text.zh-Hans']['status'], 'blocked')
        self.assertIsNone(result['proposedWorkUnit'])

    def test_unknown_fields_and_overlapping_outputs_are_rejected(self):
        base = copy.deepcopy(self.config_data)
        for key, value in [('command', ['sh','-c','anything']), ('apiKey','must-not-be-stored'), ('mode','execute')]:
            self.config_data = {**base, key: value}; self.save_config()
            with self.assertRaises(ValueError): subject.load_configuration(self.path)
        self.config_data = copy.deepcopy(base)
        self.config_data['locales']['zh-Hans']['outputDirectory'] = '.'; self.save_config()
        with self.assertRaises(ValueError): subject.load_configuration(self.path)

    def test_running_job_applies_one_locale_capacity_without_new_dispatch(self):
        with self.active() as (config, _, _, _):
            controller = subject.Controller(self.path, mode='deterministic_execute')
            with patch.object(jobs, 'start_job') as start:
                result = controller.tick()
            self.assertFalse(result['dispatched'])
            start.assert_not_called()
            view = subject.snapshot(config)
            # Even a separate ready lane cannot exceed this adapter's initial
            # per-production-run locale capacity.
            view['nodes']['text.ko'] = {'status': 'ready'}
            controller.config.lanes['ko'] = {}
            self.assertIsNone(controller._choose(view))

    def test_actual_worker_cli_without_key_stops_before_any_model_cache(self):
        with self.active() as (config, code, key, _):
            result = subprocess.run(subject._worker_command(config, 'zh-Hans', key, code),
                cwd=subject.ROOT, env={'OPENAI_API_KEY': ''}, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OPENAI_API_KEY_is_not_configured', result.stderr)
        self.assertFalse(self.output.exists())

    def test_two_real_controllers_launch_one_durable_attempt_and_preserve_failure(self):
        command = [sys.executable, str(Path(subject.__file__).resolve()), 'tick', '--config', str(self.path),
                   '--mode', 'deterministic_execute']
        children = [subprocess.Popen(command, cwd=subject.ROOT, env={'OPENAI_API_KEY': ''},
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        outputs = []
        try:
            for child in children:
                outputs.append((child, *child.communicate(timeout=10)))
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
        self.assertTrue(all(child.returncode == 0 for child, _, _ in outputs), outputs)
        results = [json.loads(stdout) for _, stdout, _ in outputs]
        self.assertEqual(sum(result['dispatched'] is True for result in results), 1)
        config = subject.load_configuration(self.path)
        key = jobs._digest(durable.identity(subject.package_view(config), config.run_id, 'text.zh-Hans'))
        until = time.monotonic() + 8
        while jobs.peek_job(config.job_root, key)['status'] in jobs.ACTIVE and time.monotonic() < until:
            time.sleep(.025)
        self.assertEqual(jobs.peek_job(config.job_root, key)['status'], 'failed')
        self.assertEqual([p.name for p in config.job_root.iterdir() if p.name != '.locks'], [key])
        with patch.object(jobs, 'start_job') as start:
            retry = subject.Controller(self.path, mode='deterministic_execute').tick()
        start.assert_not_called()
        self.assertFalse(retry['dispatched'])
        self.assertFalse(self.output.exists())

    def test_controller_crash_after_durable_intent_does_not_repeat_dispatch(self):
        controller = subject.Controller(self.path, mode='deterministic_execute')
        with patch.object(jobs.subprocess, 'Popen', side_effect=KeyboardInterrupt('simulated controller death')):
            with self.assertRaises(KeyboardInterrupt):
                controller.tick()
        with patch.object(jobs, 'start_job') as start:
            retry = subject.Controller(self.path, mode='deterministic_execute').tick()
        start.assert_not_called()
        self.assertEqual(retry['nodes']['text.zh-Hans']['status'], 'reconciliation_required')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()

"""Fixed L2 orchestration over actual validators/producers; all model replies are synthetic."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from scripts import canonical_layer2_controller as subject
from scripts import canonical_durable_jobs as durable
from scripts import sermon_accounting as accounting
from scripts import weekly_pipeline_report as weekly
from scripts import sermon_workflow_jobs as jobs
from scripts import sermon_execution_harness as harness
from scripts import target_language_policy as policies
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
        (self.root / "invalid-auth").mkdir()
        (self.root / "invalid-auth" / "auth.json").write_text(json.dumps({"auth_mode": "api"}))
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
        if payload['reasoning_effort'] == 'medium':
            fields += ['semanticReview']
        answer = {k: copy.deepcopy(group[k]) for k in fields}
        answer['translationGroupId'] = input_group['translationGroupId']
        return {'id': 'fixture-' + input_group['targetLocale'] + '-response-' + str(len(self.calls)), 'model': payload['model'],
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]}

    @contextmanager
    def active(self, *, status='running', locale='zh-Hans'):
        config = subject.load_configuration(self.path)
        view = subject.package_view(config)
        ident = durable.identity(view, config.run_id, 'text.' + locale)
        key, code = jobs._digest(ident), subject.code_identity()
        command = subject._worker_command(config, locale, key, code)
        request = {'schemaVersion': jobs.SCHEMA, 'jobId': key, 'identity': ident,
                   'command': command, 'commandSha256': jobs._digest(command), 'timeoutSeconds': 21600.0, 'livenessPolicy': subject.LIVENESS_POLICY}
        with jobs._lock(config.job_root, key) as (folder, _, held):
            self.assertTrue(held)
            folder.mkdir()
            jobs._persist(folder / 'request.json', request)
            jobs._persist(folder / 'state.json', {'schemaVersion': jobs.SCHEMA, 'jobId': key,
                          'status': status, 'requestSha256': jobs._digest(request)})
            yield config, code, key, folder

    def execute(self, config, code, key, *, caller=None, locale='zh-Hans'):
        return subject.execute(self.path, locale, config.sha256, code, key,
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
        def admitted(root, ident, command, *, timeout_seconds, liveness_policy):
            with jobs._lock(root, subject.ADMISSION_LOCK) as (_, _, held):
                self.assertFalse(held)
            self.assertEqual(command[:3], [sys.executable, str(Path(subject.__file__).resolve()), 'worker'])
            self.assertEqual(timeout_seconds, 21600)
            self.assertEqual(liveness_policy, subject.LIVENESS_POLICY)
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
            self.assertEqual([c['model'] for c in self.calls], ['gpt-6.1-sol', 'gpt-6.1-sol']*2)
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

    def test_real_worker_links_models_candidate_and_final_validation_in_one_run(self):
        original_plugin = subject.producer.run_language_plugin
        def measured_plugin(*args, **kwargs):
            time.sleep(.02)
            return original_plugin(*args, **kwargs)
        with self.active() as (config, code, key, _), patch.object(
                subject.producer, 'run_language_plugin', side_effect=measured_plugin):
            self.execute(config, code, key)
        events, damaged = accounting.read_events(self.output / 'accounting')
        self.assertFalse(damaged)
        self.assertEqual(len({e['runId'] for e in events}), 1)
        report = weekly.project(self.output / 'accounting')['runs'][0]
        self.assertEqual(report['status'], 'projected', report['diagnostics'])
        starts = {e['stage']: e for e in events if e['event'] == 'stage_started'}
        chain = ['worker_admission', 'source_admission', 'run_admission']
        for parent, child in zip(chain, chain[1:]):
            self.assertEqual(starts['layer2.' + child + '.zh-Hans']['dependsOn'],
                             [starts['layer2.' + parent + '.zh-Hans']['spanId']])
        chain = ['evidence_assembly', 'post_model_binding', 'language_and_candidate', 'final_package_validation']
        for parent, child in zip(chain, chain[1:]):
            self.assertEqual(starts['layer2.' + child + '.zh-Hans']['dependsOn'],
                             [starts['layer2.' + parent + '.zh-Hans']['spanId']])
        leaves = {x['stage']: x for x in report['workUnits']}
        self.assertGreaterEqual(leaves['layer2.language_and_candidate.zh-Hans']['elapsedSeconds'], .02)
        self.assertIn('layer2.final_package_validation.zh-Hans', leaves)
        self.assertNotIn('canonical_layer2_worker', leaves)
        self.assertNotIn('layer2_models', leaves)
        self.assertIsNotNone(report['criticalPath'])
        self.assertEqual(len(self.calls), 4)
        candidate = json.loads((self.output / 'candidate.json').read_text())
        self.assertNotIn('spanId', json.dumps(candidate))
        self.assertFalse(candidate['releaseEligible'])

    def test_state_wrapper_preserves_cli_decoder_and_identity_without_api_envelope(self):
        decoded = []
        owner = self
        class CliCaller:
            execution_identity = {'backend': 'codex_cli', 'testIdentity': 'mock-only'}
            billing = 'local'
            def __call__(self, key, payload):
                api = owner.fake_call(key, payload)
                return {'id': api['id'], 'cliContent': api['choices'][0]['message']['content']}
            def completed_content(self, response, model, role):
                decoded.append((model, role))
                return response['cliContent']
        with self.active() as (config, code, key, _):
            result = subject.execute(config.path, 'zh-Hans', config.sha256, code, key,
                                     caller=CliCaller(), api_key='fixture-key')
        self.assertFalse(result['releaseEligible'])
        self.assertEqual(decoded, [('gpt-6.1-sol', 'translator'), ('gpt-6.1-sol', 'reviewer')]*2)
        cached_hashes = {json.loads(path.read_text())["payloadSha256"] for path in self.output.glob("*-astra.json")}
        expected_hashes = {subject.models.policy_tools.canonical_sha256({
            "payload": payload, "modelTransportIdentity": CliCaller.execution_identity})
            for payload in self.calls if payload["reasoning_effort"] == "high"}
        self.assertEqual(cached_hashes, expected_hashes)

    def test_plugin_failure_keeps_model_evidence_and_records_failed_dependency_leaf(self):
        with self.active() as (config, code, key, _), patch.object(
                subject.producer, 'run_language_plugin', side_effect=ValueError('fixture_plugin_failure')):
            with self.assertRaisesRegex(ValueError, 'fixture_plugin_failure'):
                self.execute(config, code, key)
        events, damaged = accounting.read_events(self.output / 'accounting')
        self.assertFalse(damaged)
        self.assertEqual(len({e['runId'] for e in events}), 1)
        candidate = next(e for e in events if e['event'] == 'stage_finished'
                         and e['stage'] == 'layer2.language_and_candidate.zh-Hans')
        self.assertEqual(candidate['status'], 'failed')
        self.assertTrue(candidate['dependsOn'])
        self.assertFalse(any(e.get('stage') == 'layer2.final_package_validation.zh-Hans' for e in events))
        self.assertTrue((self.output / 'evidence.json').exists())
        self.assertFalse((self.output / 'candidate.json').exists())
        self.assertEqual(len(self.calls), 4)

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
            # A running locale reserves the single controller slot.
            view['nodes']['text.ko'] = {'status': 'ready'}
            controller.config.lanes['ko'] = {}
            self.assertIsNone(controller._choose(view))

    def test_binding_is_rechecked_after_waiting_for_api_slot(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        errors = []

        @contextmanager
        def held_slot(_job_root):
            entered.set()
            if not release.wait(timeout=10):
                raise TimeoutError('test did not release API slot')
            yield

        def caller(key, payload):
            calls.append(payload)
            return self.fake_call(key, payload)

        with self.active() as (config, code, key, _):
            with patch.object(subject.api_concurrency, 'request_slot', held_slot):
                def execute():
                    try:
                        self.execute(config, code, key, caller=caller)
                    except BaseException as exc:
                        errors.append(exc)

                worker = threading.Thread(target=execute)
                worker.start()
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    self.config_data['productionRunId'] = 'b' * 64
                    self.save_config()
                finally:
                    release.set()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
        self.assertEqual(calls, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('worker_configuration_or_code_changed_during_models', str(errors[0]))

    def test_actual_worker_cli_without_key_stops_before_any_model_cache(self):
        with self.active() as (config, code, key, _):
            result = subprocess.run(subject._worker_command(config, 'zh-Hans', key, code),
                cwd=subject.ROOT, env={'OPENAI_API_KEY': '', 'CODEX_HOME': str(self.root / 'invalid-auth')}, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('codex_language_requires_chatgpt_auth', result.stderr)
        self.assertEqual({p.name for p in self.output.iterdir()}, {'accounting'})
        events, damaged = accounting.read_events(self.output / 'accounting')
        self.assertFalse(damaged)
        self.assertFalse(any(e['event'] == 'api_attempt' for e in events))
        self.assertTrue(any(e['event'] == 'run_finished' and e['status'] == 'failed' for e in events))

    def test_two_real_controllers_launch_one_durable_attempt_and_preserve_failure(self):
        command = [sys.executable, str(Path(subject.__file__).resolve()), 'tick', '--config', str(self.path),
                   '--mode', 'deterministic_execute']
        children = [subprocess.Popen(command, cwd=subject.ROOT, env={'OPENAI_API_KEY': '', 'CODEX_HOME': str(self.root / 'invalid-auth')},
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
        self.assertEqual({p.name for p in self.output.iterdir()}, {'accounting'})
        events, damaged = accounting.read_events(self.output / 'accounting')
        self.assertFalse(damaged)
        self.assertFalse(any(e['event'] == 'api_attempt' for e in events))
        self.assertTrue(any(e['event'] == 'run_finished' and e['status'] == 'failed' for e in events))

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

    def test_unknown_owner_retains_capacity_until_reconciliation(self):
        with self.active(status='queued'):
            pass
        controller = subject.Controller(self.path)
        view = subject.snapshot(controller.config)
        # An uncertain owner conservatively retains the single locale slot.
        self.assertTrue(controller._capacity_full(view))
        self.assertIsNone(controller._choose(view))

    def test_three_synthetic_locales_use_the_same_fixed_producer_gates_and_capacity(self):
        original_groups = copy.deepcopy(self.fixture.fixture.evidence['groups'])
        samples = {'ko': ['처음 사랑을 기억하세요.', '돌아가세요.'],
                   'es': ['Recuerda tu primer amor.', 'Vuelve a él.']}
        for locale in samples:
            plugin = self.root / (locale + '-synthetic-plugin.py')
            plugin.write_text(self.fixture.fixture.plugin_path.read_text().replace('zh-Hans-sermon-v1', locale + '-sermon-v1'))
            policy = copy.deepcopy(self.fixture.fixture.policy); policy.pop('componentSha256')
            policy['targetLocale'] = locale
            policy['scripture']['quoteCheckPolicy'] = 'references_only'
            policy['languageReview'].update(pluginId=locale + '-sermon-v1',
                pluginImplementationSha256=subject.producer.plugin_implementation_sha256(plugin))
            self.fixture.write(locale + '-policy.json', policies.freeze_policy(policy))
            self.fixture.config['locales'][locale] = {'policy': locale + '-policy.json'}
            self.config_data['locales'][locale] = {'outputDirectory': 'outputs/' + locale, 'plugin': str(plugin)}
        self.fixture.write('inspection.json', self.fixture.config); self.save_config()
        counts = {}
        for locale in ('es', 'ko', 'zh-Hans'):
            self.calls.clear()
            self.fixture.fixture.evidence['groups'] = copy.deepcopy(original_groups)
            if locale in samples:
                for group, text in zip(self.fixture.fixture.evidence['groups'], samples[locale]):
                    group['targetUtterances'] = [text]
                    for row in group['coverage']:
                        row['targetText'] = text
            self.assertEqual(subject.Controller(self.path).tick()['proposedWorkUnit'], 'text.' + locale)
            with self.active(locale=locale) as (config, code, key, folder):
                held = subject.Controller(self.path).tick()
                self.assertEqual(held['reasonCode'], 'layer2_capacity_reached')
                self.execute(config, code, key, locale=locale)
                jobs._write_state(folder, key, 'succeeded')
            candidate = json.loads((self.root / 'outputs' / locale / 'candidate.json').read_text())
            self.assertEqual(candidate['targetLocale'], locale)
            self.assertEqual(candidate['humanReview']['translation'], 'pending')
            self.assertFalse(candidate['releaseEligible'])
            counts[locale] = len(self.calls)
        self.assertEqual(counts, {'es': 4, 'ko': 4, 'zh-Hans': 4})
        done = subject.Controller(self.path).tick()
        self.assertIsNone(done['proposedWorkUnit'])
        self.assertTrue(all(done['nodes']['text.' + locale]['status'] == 'validated' for locale in counts))
        self.assertTrue(all(done['nodes']['audio.' + locale]['status'] == 'human_gate' for locale in counts))


if __name__ == '__main__':
    unittest.main()
